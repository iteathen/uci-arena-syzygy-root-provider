"""Cold exact local file-set admission and public tablebase lifetime owner."""
import hashlib
import json
from pathlib import Path
import re
import stat
import chess.syzygy


class DatasetError(ValueError):
    pass


def regular(path, *, directory=False):
    info = path.lstat()
    if path.is_symlink() or path.is_junction() or getattr(info, "st_file_attributes", 0) & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 1024):
        raise DatasetError("reparse resource is unsupported")
    if not (stat.S_ISDIR(info.st_mode) if directory else stat.S_ISREG(info.st_mode)):
        raise DatasetError("regular resource required")
    return info


def stamp(path):
    info = regular(path)
    return info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns


def digest(path):
    with path.open("rb") as source:
        return hashlib.file_digest(source, "sha256").hexdigest()


class DatasetAdmission:
    def __init__(self, root, identity, states):
        self.root, self.identity, self.states = root, identity, states
        self.tablebase = None
        self._close_failed = False
        self.state = "admitted"

    def check_unchanged(self):
        if self.state in ("closed", "quarantined"):
            raise DatasetError("dataset is not available")
        for path, expected in self.states.items():
            if stamp(path) != expected:
                self.state = "quarantined"
                raise DatasetError("admitted immutable file set changed")

    def open(self, factory=lambda: chess.syzygy.Tablebase(max_fds=4)):
        self.check_unchanged()
        if self.tablebase is not None:
            raise DatasetError("tablebase already opened")
        tablebase = factory()
        self.tablebase = tablebase  # Retain ownership even if admission/cleanup fails.
        try:
            for row in self.identity["files"]:
                # Public pinned add_file avoids scanning/loading unadmitted peers.
                loaded = tablebase.add_file(str(self.root / row["name"]))
                if type(loaded) is not int or loaded != 1:
                    raise DatasetError("public tablebase did not admit declared member")
        except BaseException:
            self.close()
            raise
        self.tablebase, self.state = tablebase, "open"
        return self

    def probe_wdl(self, board):
        self.check_unchanged()
        if self.tablebase is None:
            raise DatasetError("tablebase not opened")
        return self.tablebase.probe_wdl(board)

    def probe_dtz(self, board):
        self.check_unchanged()
        if self.tablebase is None:
            raise DatasetError("tablebase not opened")
        return self.tablebase.probe_dtz(board)

    def close(self):
        if self._close_failed:
            raise DatasetError("failed close is quarantined; restart provider process")
        if self.state == "closed":
            return
        if self.tablebase is not None:
            try:
                self.tablebase.close()
            except BaseException:
                self._close_failed = True
                self.state = "quarantined"
                raise
            self.tablebase = None
        self.state = "closed"


def admit_dataset(root, selected, expected_manifest_sha256):
    root = Path(root)
    if not root.is_absolute():
        raise DatasetError("explicit absolute dataset root required")
    for directory in (root, *root.parents):
        regular(directory, directory=True)
    manifest_path = root / "syzygy_manifest_v1.json"
    manifest_stat = regular(manifest_path)
    if manifest_stat.st_size > 1048576:
        raise DatasetError("manifest byte capacity")
    data = manifest_path.read_bytes()
    manifest_sha = hashlib.sha256(data).hexdigest()
    if not isinstance(expected_manifest_sha256, str) or not re.fullmatch(r"[0-9a-f]{64}", expected_manifest_sha256) or expected_manifest_sha256 != manifest_sha:
        raise DatasetError("manifest identity mismatch")
    document = json.loads(data)
    rows = document.get("files")
    if document.get("schema") != "uci_arena_syzygy_manifest_v1" or type(rows) is not list or not 1 <= len(rows) <= 2048:
        raise DatasetError("bounded resource inventory required")
    if selected is None:
        selected = [row.get("name") for row in rows if type(row) is dict]
    if type(selected) is not list or not 1 <= len(selected) <= 2048 or any(not isinstance(name, str) for name in selected) or len(set(selected)) != len(selected):
        raise DatasetError("bounded unique explicit members required")
    files, states, cardinality, total = [], {manifest_path: stamp(manifest_path)}, 0, 0
    for name in selected:
        match = re.fullmatch(r"(K[QRBNP]*vK[QRBNP]*)\.(rtbw|rtbz)", name)
        if not match:
            raise DatasetError("unsafe or nonstandard member name")
        pieces = len(match[1]) - 1
        if not 3 <= pieces <= 6:
            raise DatasetError("member exceeds root-only cardinality profile")
        matches = [row for row in rows if type(row) is dict and row.get("name") == name]
        if len(matches) != 1:
            raise DatasetError("unique declared member required")
        row, path = matches[0], root / name
        before = regular(path)
        if type(row.get("bytes")) is not int or not 1 <= row["bytes"] <= 68719476736 or before.st_size != row["bytes"] or not isinstance(row.get("sha256"), str) or not re.fullmatch(r"[0-9a-f]{64}", row["sha256"]):
            raise DatasetError("member size or identity fields invalid")
        total += before.st_size
        if total > 1099511627776:
            raise DatasetError("dataset byte capacity")
        state = stamp(path)
        actual = digest(path)
        if actual != row["sha256"] or stamp(path) != state:
            raise DatasetError("member content identity mismatch")
        states[path] = state
        files.append({"name": name, "bytes": before.st_size, "sha256": actual, "pieces": pieces})
        cardinality = max(cardinality, pieces)
    if stamp(manifest_path) != states[manifest_path]:
        raise DatasetError("manifest changed during admission")
    return DatasetAdmission(root, {"schema": "uci_arena_syzygy_root_dataset_identity_v1", "manifest_sha256": manifest_sha,
                                  "manifest_cardinality": document.get("cardinality"), "admitted_cardinality": cardinality,
                                  "files": files, "file_count": len(files), "total_bytes": total, "scope": "exact_selected_file_set"}, states)
