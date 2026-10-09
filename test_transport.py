import io
import threading
import unittest
from transport import BoundedOutput, read_frame, TransportError


class TransportTests(unittest.TestCase):
    def test_frame_is_closed_utf8_json_with_a_finite_byte_budget(self):
        self.assertEqual(read_frame(io.BytesIO(b'{"operation":"describe"}\n')), {"operation": "describe"})
        self.assertIsNone(read_frame(io.BytesIO()))
        for data in [b'{"a":1,"a":2}\n', b'{"a":NaN}\n', b'\xff\n', b' ' * 262209]:
            with self.assertRaises(TransportError):
                read_frame(io.BytesIO(data))

    def test_blocked_writer_has_bounded_queue_and_does_not_block_ingress(self):
        entered, release = threading.Event(), threading.Event()
        class Pipe:
            def write(self, value):
                entered.set()
                release.wait(2)
            def flush(self):
                pass
        output = BoundedOutput(Pipe(), capacity=2)
        try:
            output.write({"sequence": 0})
            self.assertTrue(entered.wait(1))
            output.write({"sequence": 1})
            output.write({"sequence": 2})
            with self.assertRaises(TransportError):
                output.write({"sequence": 3})
            self.assertFalse(output.close(0.01))
        finally:
            release.set()
            self.assertTrue(output.close(2))

    def test_ordered_output_owns_a_copy_and_write_failure_is_quarantined(self):
        pipe = io.BytesIO()
        output = BoundedOutput(pipe)
        event = {"sequence": 1}
        output.write(event)
        event["sequence"] = 8
        self.assertTrue(output.close(2))
        self.assertEqual(pipe.getvalue(), b'{"sequence":1}\n')
        with self.assertRaises(TransportError):
            output.write(event)
        failed = threading.Event()
        class FailedPipe:
            def write(self, value):
                failed.set()
                raise OSError("fixture output failure")
        output = BoundedOutput(FailedPipe())
        output.write({"sequence": 0})
        self.assertTrue(failed.wait(1))
        self.assertFalse(output.close(2))
        self.assertEqual(output.close_disposition, {"drained": True, "failed": True, "status": "quarantined"})
        with self.assertRaises(TransportError):
            output.write({"sequence": 1})


if __name__ == "__main__":
    unittest.main()
