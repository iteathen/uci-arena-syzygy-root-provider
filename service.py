"""One serialized offline knowledge worker behind bounded cancellable JSON."""
from collections import deque
import copy
import json
import re
import threading
import time
from root_contract import canonical_json, MAX_REQUEST_BYTES, REQUEST_SCHEMA

TRANSPORT_SCHEMA = "uci_arena_syzygy_root_transport_v1"
MAX_OUTPUT_BYTES = 1048576


class TransportError(ValueError):
    pass


class RootService:
    def __init__(self, provider, emit):
        self.provider, self.emit = provider, emit
        self._condition, self._emit_lock = threading.Condition(), threading.Lock()
        self._queue, self._tickets = deque(), {}
        self._closed = False
        self._failed = False
        self._worker = threading.Thread(target=self._run, name="root-knowledge-worker", daemon=True)
        self._worker.start()

    def _send(self, value):
        text = canonical_json(value)
        if len(text.encode("utf-8")) > MAX_OUTPUT_BYTES:
            raise TransportError("output_byte_capacity")
        with self._emit_lock:
            self.emit(json.loads(text))

    def describe(self):
        with self._condition:
            status = "quarantined" if self._failed else "closed" if self._closed else "ready"
        return {"schema": TRANSPORT_SCHEMA, "operation": "describe", "status": status,
                "provider_generation": self.provider.generation, "provider_identity": copy.deepcopy(self.provider.identity),
                "profile": {"root_only": True, "worker_count": 1, "ticket_capacity": 2,
                            "maximum_request_bytes": MAX_REQUEST_BYTES, "maximum_output_bytes": MAX_OUTPUT_BYTES,
                            "request_schema": REQUEST_SCHEMA, "active_gpu_callback": False,
                            "claim_policies": {"adjudicated-claims-as-draw": {"rule50": [True, False]},
                                               "orthodoxy-live-claims-v1": {"rule50": [True], "automatic_repetition": 5, "automatic_halfmoves": 150, "virtual_claim_move": False}}}}

    def handle(self, message):
        if type(message) is not dict:
            raise TransportError("closed_transport_fields")
        operation = message.get("operation")
        expected = {"describe": {"operation"}, "probe": {"operation", "request"},
                    "cancel": {"operation", "request_id", "root_fence"}, "close": {"operation"}}.get(operation)
        if expected is None or set(message) != expected:
            raise TransportError("closed_transport_fields")
        if operation == "describe":
            self._send(self.describe())
            return
        if operation == "close":
            complete = self.close(1)
            self._send({"schema": TRANSPORT_SCHEMA, "operation": "close", "status": "closed" if complete else "draining", "provider_generation": self.provider.generation})
            return
        if operation == "cancel":
            if not isinstance(message["request_id"], str) or not re.fullmatch(r"[A-Za-z0-9_.-]{1,128}", message["request_id"]) or not isinstance(message["root_fence"], str) or not re.fullmatch(r"[0-9a-f]{32}", message["root_fence"]):
                raise TransportError("invalid_cancel_identity")
            with self._condition:
                ticket = self._tickets.get(message["request_id"])
                if ticket is None:
                    return  # Completion may race consumer abandonment.
                if ticket["request"]["root_fence"] != message["root_fence"]:
                    raise TransportError("stale_cancel_fence")
                ticket["cancelled"].set()
                self._condition.notify_all()
            return
        try:
            text = canonical_json(message["request"])
            if len(text.encode("utf-8")) > MAX_REQUEST_BYTES:
                raise TransportError("request_byte_capacity")
            raw = json.loads(text)
        except (ValueError, TypeError) as error:
            raise TransportError("bounded_json_required") from error
        # Cheap identity gating keeps the reader responsive; legal replay and
        # tablebase admission occur only inside the cancellable worker.
        if type(raw) is not dict or raw.get("schema") != REQUEST_SCHEMA or not isinstance(raw.get("request_id"), str) or not re.fullmatch(r"[A-Za-z0-9_.-]{1,128}", raw["request_id"]) or not isinstance(raw.get("root_fence"), str) or not re.fullmatch(r"[0-9a-f]{32}", raw["root_fence"]):
            raise TransportError("invalid_request_identity")
        request_id = raw["request_id"]
        with self._condition:
            if self._closed:
                raise TransportError("service_closed")
            if request_id in self._tickets:
                raise TransportError("duplicate_request")
            if len(self._tickets) >= 2:
                capacity = True
            else:
                capacity = False
                ticket = {"request": raw, "cancelled": threading.Event()}
                self._tickets[request_id] = ticket
                self._queue.append(ticket)
                self._condition.notify_all()
        if capacity:
            self._send({"schema": TRANSPORT_SCHEMA, "operation": "probe", "status": "deferred", "reason": "ticket_capacity",
                        "request_id": request_id, "root_fence": raw["root_fence"], "provider_generation": self.provider.generation})

    def _run(self):
        while True:
            with self._condition:
                while not self._queue and not self._closed:
                    self._condition.wait()
                if not self._queue and self._closed:
                    return
                ticket = self._queue.popleft()
            raw, cancelled = ticket["request"], ticket["cancelled"]
            try:
                if not cancelled.is_set():
                    for event in self.provider.events(raw, cancelled=cancelled.is_set):
                        # A cancelled/stale worker cannot publish a late exact.
                        with self._condition:
                            current = self._tickets.get(raw["request_id"])
                            if current is not ticket or cancelled.is_set() or self._closed:
                                break
                        # Never hold ingress/cancel ownership across transport I/O.
                        # Consumers still fence already-in-flight output on abandon.
                        self._send(event)
            except Exception:
                if not cancelled.is_set() and not self._closed:
                    try:
                        self._send({"schema": TRANSPORT_SCHEMA, "operation": "probe", "status": "error", "reason": "provider_request_failed",
                                    "request_id": raw["request_id"], "root_fence": raw["root_fence"], "provider_generation": self.provider.generation})
                    except Exception:
                        with self._condition:
                            self._failed = self._closed = True
                            for owned in self._tickets.values():
                                owned["cancelled"].set()
                            self._condition.notify_all()
            finally:
                with self._condition:
                    self._tickets.pop(raw["request_id"], None)
                    self._condition.notify_all()

    def drain(self, seconds):
        deadline = time.monotonic() + seconds
        with self._condition:
            while self._tickets:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return False
                self._condition.wait(remaining)
        return True

    def close(self, seconds=1):
        with self._condition:
            self._closed = True
            for ticket in self._tickets.values():
                ticket["cancelled"].set()
            self._condition.notify_all()
        self._worker.join(seconds)
        return not self._worker.is_alive()
