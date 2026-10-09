import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from runtime_manifest import verify_package, PackageError


class PackageTests(unittest.TestCase):
    def test_exact_regular_inventory_and_substitution_fence(self):
        base = Path("E:/uci-arena-task-builds/syzygy-root-provider-tools-20261008/unit-data")
        with tempfile.TemporaryDirectory(dir=base) as name:
            root = Path(name)
            (root / "app").mkdir()
            source = root / "app/source.py"
            source.write_bytes(b"source fixture")
            manifest = {"schema": "uci_arena_root_provider_package_v1", "files": [
                {"path": "app/source.py", "bytes": source.stat().st_size, "sha256": hashlib.sha256(source.read_bytes()).hexdigest()}]}
            path = root / "package-manifest.json"
            path.write_text(json.dumps(manifest), encoding="utf-8")
            identity = verify_package(path)
            self.assertEqual(identity["manifest_sha256"], hashlib.sha256(path.read_bytes()).hexdigest())
            extra = root / "app/uninventoried.py"
            extra.write_bytes(b"not admitted")
            with self.assertRaises(PackageError):
                verify_package(path)
            extra.unlink()
            source.write_bytes(b"changed fixture")
            with self.assertRaises(PackageError):
                verify_package(path)

    def test_escaping_duplicate_and_unbounded_inventory_fail_before_file_read(self):
        base = Path("E:/uci-arena-task-builds/syzygy-root-provider-tools-20261008/unit-data")
        with tempfile.TemporaryDirectory(dir=base) as name:
            root = Path(name)
            path = root / "package-manifest.json"
            row = {"path": "../outside.py", "bytes": 1, "sha256": "a" * 64}
            for rows in [[row], [row, row], [row] * 513]:
                path.write_text(json.dumps({"schema": "uci_arena_root_provider_package_v1", "files": rows}), encoding="utf-8")
                with self.assertRaises(PackageError):
                    verify_package(path)


if __name__ == "__main__":
    unittest.main()
