import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from dataset import admit_dataset, DatasetError


class DatasetTests(unittest.TestCase):
    def setUp(self):
        base = Path("E:/uci-arena-task-builds/syzygy-root-provider-tools-20261008/unit-data")
        base.mkdir(exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=base)
        self.root = Path(self.temp.name)
        self.bytes = b"owned hash fixture only, not a Syzygy table"
        (self.root / "KQvK.rtbw").write_bytes(self.bytes)
        self.row = {"name": "KQvK.rtbw", "bytes": len(self.bytes), "sha256": hashlib.sha256(self.bytes).hexdigest()}
        self.write([self.row])
    def tearDown(self):
        self.temp.cleanup()
    def write(self, rows):
        data = json.dumps({"schema": "uci_arena_syzygy_manifest_v1", "cardinality": 6, "files": rows}).encode()
        (self.root / "syzygy_manifest_v1.json").write_bytes(data)
        self.manifest_sha = hashlib.sha256(data).hexdigest()
    def test_admission_binds_actual_subset_not_top_level_cardinality(self):
        result = admit_dataset(self.root, ["KQvK.rtbw"], self.manifest_sha)
        self.assertEqual(result.identity["admitted_cardinality"], 3)
        self.assertEqual(result.identity["manifest_cardinality"], 6)
        self.assertEqual(result.identity["files"][0]["sha256"], self.row["sha256"])
        self.assertEqual(result.identity["manifest_sha256"], self.manifest_sha)
    def test_corruption_digest_drift_duplicate_or_escaping_member_rejected(self):
        for mode in ["bytes", "manifest", "duplicate", "path"]:
            self.write([self.row])
            (self.root / "KQvK.rtbw").write_bytes(self.bytes)
            if mode == "bytes":
                (self.root / "KQvK.rtbw").write_bytes(b"wrong")
            if mode == "duplicate":
                self.write([self.row, self.row])
            with self.assertRaises(DatasetError):
                admit_dataset(self.root, ["../KQvK.rtbw"] if mode == "path" else ["KQvK.rtbw"], "0" * 64 if mode == "manifest" else self.manifest_sha)
    def test_readiness_never_loads_uninventoried_directory_neighbors(self):
        (self.root / "KRvK.rtbw").write_bytes(b"not admitted")
        result = admit_dataset(self.root, ["KQvK.rtbw"], self.manifest_sha)
        class PublicTablebase:
            def __init__(self):
                self.files = []
                self.closed = False
            def add_file(self, path):
                self.files.append(Path(path).name)
                return 1
            def close(self):
                self.closed = True
        table = PublicTablebase()
        result.open(lambda: table)
        self.assertEqual(table.files, ["KQvK.rtbw"])
        result.close()
        self.assertTrue(table.closed)
    def test_failed_native_close_retains_owner_and_never_retries(self):
        result = admit_dataset(self.root, ["KQvK.rtbw"], self.manifest_sha)
        class FailingTable:
            calls = 0
            def add_file(self, path):
                return 1
            def close(self):
                self.calls += 1
                raise OSError("fixture close failure")
        table = FailingTable()
        result.open(lambda: table)
        with self.assertRaises(OSError):
            result.close()
        with self.assertRaises(DatasetError):
            result.close()
        self.assertIs(result.tablebase, table)
        self.assertEqual(table.calls, 1)

    def test_failed_open_cleanup_retains_failed_close_owner(self):
        result = admit_dataset(self.root, ["KQvK.rtbw"], self.manifest_sha)
        class FailingTable:
            def add_file(self, path):
                raise OSError("fixture add failure")
            def close(self):
                raise OSError("fixture close failure")
        table = FailingTable()
        with self.assertRaises(OSError):
            result.open(lambda: table)
        self.assertIs(result.tablebase, table)
        self.assertEqual(result.state, "quarantined")

    def test_dataset_substitution_is_detected_without_relabeling_prior_identity(self):
        result = admit_dataset(self.root, ["KQvK.rtbw"], self.manifest_sha)
        (self.root / "KQvK.rtbw").write_bytes(b"different")
        with self.assertRaises(DatasetError):
            result.check_unchanged()


if __name__ == "__main__":
    unittest.main()
