"""Reversible unsigned candidate assembly from exact official binary/source archives."""
import argparse
import hashlib
import io
import json
from pathlib import Path
import shutil
import tarfile
import zipfile

PYTHON_SHA256 = "97dae5274cc54867065e8d5a3226e48c35017ed332a0fdb0e27d5b5821961297"
CHESS_SHA256 = "a8b43e5678fdb3000695bdaa573117ad683761e5ca38e591c4826eba6d25bb39"
APPLICATION = ["root_contract.py", "root_provider.py", "dataset.py", "service.py", "transport.py", "runtime_manifest.py", "run_provider.py"]


def sha(path):
    with path.open("rb") as source:
        return hashlib.file_digest(source, "sha256").hexdigest()


def assemble(tools, output):
    tools, output = Path(tools), Path(output)
    if not output.is_absolute() or output.exists() or output.parent.resolve() != tools.resolve() or not output.name.startswith("package-candidate-"):
        raise ValueError("fresh package-candidate directory directly in owned tools required")
    python_archive, chess_archive = tools / "python-3.13.16-embed-amd64.zip", tools / "chess-1.11.2.tar.gz"
    if sha(python_archive) != PYTHON_SHA256 or sha(chess_archive) != CHESS_SHA256:
        raise ValueError("pinned archive content mismatch")
    output.mkdir()
    runtime, dependencies, app = output / "python", output / "deps", output / "app"
    runtime.mkdir(); dependencies.mkdir(); app.mkdir()
    with zipfile.ZipFile(python_archive) as archive:
        members = archive.infolist()
        if len(members) > 100 or sum(row.file_size for row in members) > 134217728:
            raise ValueError("binary archive capacity")
        for row in members:
            if row.is_dir() or Path(row.filename).name != row.filename:
                raise ValueError("unexpected binary archive member")
            (runtime / row.filename).write_bytes(archive.read(row))
    (runtime / "python313._pth").write_text("python313.zip\n.\n../deps\n../app\n", encoding="utf-8")
    with tarfile.open(chess_archive, "r:gz") as archive:
        members = archive.getmembers()
        if len(members) > 1000 or sum(row.size for row in members) > 104857600:
            raise ValueError("source archive capacity")
        for row in members:
            parts = Path(row.name).parts
            if not parts or parts[0] != "chess-1.11.2" or any(p in (".", "..") for p in parts) or not (row.isfile() or row.isdir()):
                raise ValueError("unsafe source member")
            if len(parts) >= 2 and parts[1] == "chess":
                member = dependencies.joinpath(*parts[1:])
                if row.isdir():
                    member.mkdir(parents=True, exist_ok=True)
                else:
                    member.parent.mkdir(parents=True, exist_ok=True)
                    member.write_bytes(archive.extractfile(row).read())
    source_root = Path(__file__).parent
    for name in APPLICATION:
        shutil.copyfile(source_root / name, app / name)
    contracts = output / "contracts"
    contracts.mkdir()
    shutil.copyfile(source_root / "docs/root-only-contract-v2.md", contracts / "root-only-contract-v2.md")
    shutil.copyfile(source_root / "contracts/offline-root-knowledge-v2.json", contracts / "offline-root-knowledge-v2.json")
    sources = output / "sources"
    sources.mkdir()
    shutil.copyfile(chess_archive, sources / chess_archive.name)  # Complete GPL source/license.
    rows = [{"path": path.relative_to(output).as_posix(), "bytes": path.stat().st_size, "sha256": sha(path)}
            for path in sorted(output.rglob("*")) if path.is_file()]
    manifest = {"schema": "uci_arena_root_provider_package_v1", "status": "unsigned-source-candidate", "files": rows,
                "provenance": {"python": {"version": "3.13.16", "archive_sha256": PYTHON_SHA256,
                                          "source": "https://www.python.org/ftp/python/3.13.16/python-3.13.16-embed-amd64.zip"},
                               "chess": {"version": "1.11.2", "archive_sha256": CHESS_SHA256,
                                         "source": "https://pypi.org/project/chess/1.11.2/", "license": "GPL-3.0-or-later"},
                               "runtime_overlay": "closed _pth app/deps paths; isolated -I -B launch", "suite_acceptance": False}}
    path = output / "package-manifest.json"
    path.write_text(json.dumps(manifest, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    return {"directory": str(output), "manifest_sha256": sha(path), "file_count": len(rows), "suite_acceptance": False}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--tools", required=True)
    parser.add_argument("--output", required=True)
    options = parser.parse_args()
    print(json.dumps(assemble(options.tools, options.output)))
