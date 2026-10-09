"""Finite UTF-8 JSON-lines framing and independent bounded output drain."""
from collections import deque
import json
import threading
from root_contract import canonical_json, MAX_REQUEST_BYTES
from service import TransportError, MAX_OUTPUT_BYTES

MAX_FRAME_BYTES = MAX_REQUEST_BYTES + 64


def _object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise TransportError("duplicate_json_field")
        result[key] = value
    return result


def read_frame(source):
    data = source.readline(MAX_FRAME_BYTES + 1)
    if not data:
        return None
    if len(data) > MAX_FRAME_BYTES:
        raise TransportError("transport_frame_capacity")
    try:
        return json.loads(data.decode("utf-8"), object_pairs_hook=_object,
                          parse_constant=lambda value: (_ for _ in ()).throw(TransportError("nonfinite_json")))
    except (UnicodeError, ValueError, RecursionError) as error:
        raise TransportError("invalid_json_frame") from error


class BoundedOutput:
    def __init__(self, sink, *, capacity=8):
        if type(capacity) is not int or not 1 <= capacity <= 8:
            raise TransportError("output_ticket_capacity")
        self.sink, self.capacity = sink, capacity
        self._condition, self._queue = threading.Condition(), deque()
        self._bytes, self._closed, self._failed = 0, False, False
        self._worker = threading.Thread(target=self._run, name="root-output-writer", daemon=True)
        self._worker.start()

    def write(self, value):
        data = (canonical_json(value) + "\n").encode("utf-8")
        if len(data) > MAX_OUTPUT_BYTES:
            raise TransportError("output_byte_capacity")
        with self._condition:
            if self._closed or self._failed:
                raise TransportError("output_unavailable")
            if len(self._queue) >= self.capacity or self._bytes + len(data) > 2 * MAX_OUTPUT_BYTES:
                raise TransportError("output_backpressure")
            self._queue.append(data)
            self._bytes += len(data)
            self._condition.notify_all()

    def _run(self):
        while True:
            with self._condition:
                while not self._queue and not self._closed:
                    self._condition.wait()
                if not self._queue:
                    return
                data = self._queue.popleft()
                self._bytes -= len(data)
            try:
                self.sink.write(data)
                self.sink.flush()
            except Exception:
                with self._condition:
                    self._failed = True
                    self._queue.clear()
                    self._bytes = 0
                return

    def close(self, seconds=1):
        with self._condition:
            self._closed = True
            self._condition.notify_all()
        self._worker.join(seconds)
        outcome = self.close_disposition
        return outcome["drained"] and not outcome["failed"]

    @property
    def close_disposition(self):
        with self._condition:
            drained, failed = not self._worker.is_alive(), self._failed
            return {"drained": drained, "failed": failed,
                    "status": "quarantined" if failed else "closed" if drained else "draining"}
