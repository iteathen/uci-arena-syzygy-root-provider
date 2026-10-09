"""Provider-owned package inventory, never dependency-issued schema authority."""
import hashlib
import json
from pathlib import Path
import re
import sys
import chess
from dataset import regular, stamp, digest


class PackageError(ValueError):
    pass


def verify_package(path):
    path = Path(path)
    if not path.is_absolute() or path.name != "package-manifest.json":
        raise PackageError("explicit package manifest required")
    root = path.parent
    try:
        for directory in (root, *root.parents):
            regular(directory, directory=True)
        if regular(path).st_size > 1048576:
            raise PackageError("package manifest capacity")
        data = path.read_bytes()
        document = json.loads(data)
        rows = document.get("files")
        if document.get("schema") != "uci_arena_root_provider_package_v1" or type(rows) is not list or not 1 <= len(rows) <= 512:
            raise PackageError("bounded package inventory required")
        seen, total = set(), 0
        for row in rows:
            if type(row) is not dict or set(row) != {"path", "bytes", "sha256"}:
                raise PackageError("closed package row required")
            name = row["path"]
            if not isinstance(name, str) or not re.fullmatch(r"[A-Za-z0-9_.-]+(?:/[A-Za-z0-9_.-]+)*", name) or any(p in (".", "..") for p in name.split("/")) or name.casefold() in seen:
                raise PackageError("unique safe package path required")
            seen.add(name.casefold())
            if type(row["bytes"]) is not int or not 0 <= row["bytes"] <= 134217728 or not isinstance(row["sha256"], str) or not re.fullmatch(r"[0-9a-f]{64}", row["sha256"]):
                raise PackageError("bounded package member identity required")
            total += row["bytes"]
            if total > 536870912:
                raise PackageError("package total capacity")
        for row in rows:
            member = root / row["path"]
            for directory in member.parents:
                if directory == root:
                    break
                regular(directory, directory=True)
            before = stamp(member)
            if before[2] != row["bytes"] or digest(member) != row["sha256"] or stamp(member) != before:
                raise PackageError("package content substitution")
        # Import closure is exact: no unlisted Python modules/native neighbors.
        actual = set()
        pending = [root]
        while pending:
            directory = pending.pop()
            for member in directory.iterdir():
                if member == path:
                    continue
                if member.is_dir():
                    regular(member, directory=True)
                    pending.append(member)
                else:
                    regular(member)
                    actual.add(member.relative_to(root).as_posix().casefold())
                if len(actual) + len(pending) > 1024:
                    raise PackageError("package closure capacity")
        if actual != seen:
            raise PackageError("uninventoried package member")
    except (OSError, ValueError, TypeError, AttributeError) as error:
        if isinstance(error, PackageError):
            raise
        raise PackageError("package admission failed") from error
    return {"schema": "uci_arena_root_provider_package_identity_v1",
            "manifest_sha256": hashlib.sha256(data).hexdigest(), "file_count": len(rows),
            "total_bytes": total, "provenance": document.get("provenance"), "files": rows}


def admit_runtime(manifest_path):
    identity = verify_package(manifest_path)
    root = Path(manifest_path).parent
    if sys.implementation.name != "cpython" or sys.version_info[:3] != (3, 13, 16) or chess.__version__ != "1.11.2":
        raise PackageError("pinned runtime/dependency mismatch")
    if Path(sys.executable).resolve() != (root / "python/python.exe").resolve() or Path(chess.__file__).resolve() != (root / "deps/chess/__init__.py").resolve():
        raise PackageError("runtime/dependency placement mismatch")
    required = {"python/python.exe", "python/python313._pth", "deps/chess/__init__.py", "deps/chess/syzygy.py", "app/run_provider.py"}
    if not required.issubset({row["path"] for row in identity["files"]}):
        raise PackageError("runtime closure missing")
    return {"package": identity, "runtime": {"implementation": "CPython", "version": "3.13.16", "chess_version": "1.11.2"}}
