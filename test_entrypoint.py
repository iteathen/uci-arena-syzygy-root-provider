import io
import json
import unittest
from run_provider import admit_config, serve, ConfigurationError
from test_root_contract import request


class EntrypointTests(unittest.TestCase):
    def test_real_sink_failure_cannot_report_successful_process_disposition(self):
        class Provider:
            generation = "3" * 32
            identity = {}
            def events(self, raw, cancelled):
                raise AssertionError("describe must not probe")
        class BrokenSink:
            def write(self, data):
                raise BrokenPipeError("real write path failure")
            def flush(self):
                raise AssertionError("write already failed")
        self.assertEqual(serve(Provider(), io.BytesIO(b'{"operation":"describe"}\n'), BrokenSink()), 4)

    def test_configuration_cannot_carry_code_or_unbounded_selection(self):
        valid = {"schema": "uci_arena_syzygy_root_configuration_v1", "dataset_root": "E:/syzygy/standard/6",
                 "manifest_sha256": "a" * 64, "selected_files": ["KQvK.rtbw", "KQvK.rtbz"]}
        self.assertEqual(admit_config(valid), valid)
        for changed in [dict(valid, callback="eval"), dict(valid, selected_files=[]), dict(valid, manifest_sha256="fake")]:
            with self.assertRaises(ConfigurationError):
                admit_config(changed)

    def test_describe_and_eof_close_drains_before_owned_dataset_close(self):
        class Provider:
            generation = "1" * 32
            identity = {"fixture": "process protocol"}
            def events(self, raw, cancelled):
                raise AssertionError("describe does not probe")
        output = io.BytesIO()
        self.assertEqual(serve(Provider(), io.BytesIO(b'{"operation":"describe"}\n'), output), 0)
        event = json.loads(output.getvalue())
        self.assertEqual(event["provider_generation"], "1" * 32)
        self.assertTrue(event["profile"]["root_only"])

    def test_malformed_or_over_capacity_framing_closes_without_dispatch(self):
        class Provider:
            generation = "2" * 32
            identity = {}
            def events(self, raw, cancelled):
                raise AssertionError("must not probe")
        output = io.BytesIO()
        self.assertEqual(serve(Provider(), io.BytesIO(b'{"operation":"probe","operation":"eval"}\n'), output), 2)
        self.assertEqual(json.loads(output.getvalue())["reason"], "invalid_transport")


if __name__ == "__main__":
    unittest.main()
