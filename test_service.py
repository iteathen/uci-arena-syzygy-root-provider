import threading
import unittest
from service import RootService, TransportError
from test_root_contract import request


class ServiceTests(unittest.TestCase):
    def test_two_ticket_admission_cancellation_and_late_exact_discard(self):
        entered, release = threading.Event(), threading.Event()
        events = []
        class Provider:
            generation = "b" * 32
            identity = {"fixture": "transport"}
            def events(self, raw, cancelled):
                entered.set()
                release.wait(2)
                yield {"request_id": raw["request_id"], "root_fence": raw["root_fence"], "status": "exact"}
        service = RootService(Provider(), events.append)
        try:
            first = request(); first["request_id"] = "first"
            second = request(); second["request_id"] = "second"
            third = request(); third["request_id"] = "third"
            service.handle({"operation": "probe", "request": first})
            self.assertTrue(entered.wait(1))
            service.handle({"operation": "probe", "request": second})
            service.handle({"operation": "probe", "request": third})
            self.assertEqual(events[-1]["reason"], "ticket_capacity")
            service.handle({"operation": "cancel", "request_id": "first", "root_fence": "a" * 32})
            release.set()
            service.drain(2)
            self.assertFalse(any(e.get("status") == "exact" and e.get("request_id") == "first" for e in events))
            self.assertTrue(any(e.get("request_id") == "second" for e in events))
        finally:
            release.set()
            self.assertTrue(service.close(2))
    def test_duplicate_or_mismatched_cancel_cannot_replace_an_owned_fence(self):
        held = threading.Event()
        class Provider:
            generation = "c" * 32
            identity = {}
            def events(self, raw, cancelled):
                held.wait(2)
                yield {"status": "safety_only"}
        service = RootService(Provider(), lambda event: None)
        try:
            service.handle({"operation": "probe", "request": request()})
            with self.assertRaises(TransportError):
                service.handle({"operation": "probe", "request": request()})
            with self.assertRaises(TransportError):
                service.handle({"operation": "cancel", "request_id": "fixture", "root_fence": "d" * 32})
        finally:
            held.set()
            self.assertTrue(service.close(2))
    def test_blocked_output_cannot_hold_the_cancellation_lock(self):
        writing, release, cancelled = threading.Event(), threading.Event(), threading.Event()
        class Provider:
            generation = "f" * 32
            identity = {}
            def events(self, raw, cancelled):
                yield {"status": "safety_only"}
        def emit(event):
            writing.set()
            release.wait(2)
        service = RootService(Provider(), emit)
        service.handle({"operation": "probe", "request": request()})
        self.assertTrue(writing.wait(1))
        def cancel():
            service.handle({"operation": "cancel", "request_id": "fixture", "root_fence": "a" * 32})
            cancelled.set()
        reader = threading.Thread(target=cancel)
        reader.start()
        try:
            self.assertTrue(cancelled.wait(0.2), "pipe backpressure must not block cancel")
        finally:
            release.set()
            reader.join(2)
            self.assertTrue(service.close(2))

    def test_cancel_after_completion_is_idempotent_without_reopening_a_ticket(self):
        class Provider:
            generation = "e" * 32
            identity = {}
            def events(self, raw, cancelled):
                yield {"status": "safety_only"}
        service = RootService(Provider(), lambda event: None)
        try:
            service.handle({"operation": "probe", "request": request()})
            self.assertTrue(service.drain(1))
            service.handle({"operation": "cancel", "request_id": "fixture", "root_fence": "a" * 32})
            self.assertTrue(service.drain(0.01))
        finally:
            self.assertTrue(service.close(1))

    def test_failed_output_quarantines_readiness_and_future_ingress(self):
        class Provider:
            generation = "e" * 32
            identity = {}
            def events(self, raw, cancelled):
                yield {"status": "safety_only"}
        def failed_emit(event):
            raise TransportError("owned output unavailable")
        service = RootService(Provider(), failed_emit)
        try:
            service.handle({"operation": "probe", "request": request()})
            self.assertTrue(service.drain(1))
            self.assertEqual(service.describe()["status"], "quarantined")
            with self.assertRaises(TransportError):
                service.handle({"operation": "probe", "request": request()})
        finally:
            self.assertFalse(service.close(1))
            self.assertEqual(service.close_disposition, {"drained": True, "failed": True, "status": "quarantined"})

    def test_unknown_operation_or_path_injection_never_dispatches(self):
        class Provider:
            generation = "e" * 32
            identity = {}
            def events(self, raw, cancelled):
                raise AssertionError("must not dispatch")
        service = RootService(Provider(), lambda event: None)
        try:
            for raw in [{"operation": "eval", "code": "bad"}, {"operation": "probe", "request": request(), "path": "E:/other"}]:
                with self.assertRaises(TransportError):
                    service.handle(raw)
        finally:
            self.assertTrue(service.close(2))


if __name__ == "__main__":
    unittest.main()
