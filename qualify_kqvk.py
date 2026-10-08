"""Bounded diagnostic of an explicitly admitted, closed three-piece subset.

This is not a production provider package, history refinement or suite adoption.
"""
import argparse
import hashlib
import json
from pathlib import Path
import chess
import chess.syzygy
from provider import RootProvider


def digest(path):
    with path.open("rb") as source:
        return hashlib.file_digest(source, "sha256").hexdigest()


def main():
    arguments = argparse.ArgumentParser()
    arguments.add_argument("--tablebase-root", required=True)
    arguments.add_argument("--output", required=True)
    options = arguments.parse_args()
    root = Path(options.tablebase_root)
    if not root.is_absolute() or not root.is_dir():
        raise ValueError("explicit absolute tablebase directory required")
    for directory in (root, *root.parents):
        if directory.is_symlink() or directory.is_junction():
            raise ValueError("linked tablebase root is unsupported")
    manifest_path = root / "syzygy_manifest_v1.json"
    if manifest_path.is_symlink() or not manifest_path.is_file() or manifest_path.stat().st_size > 1048576:
        raise ValueError("bounded regular manifest required")
    manifest = json.loads(manifest_path.read_bytes())
    if manifest.get("schema") != "uci_arena_syzygy_manifest_v1":
        raise ValueError("unsupported resource manifest")
    files = manifest.get("files")
    if not isinstance(files, list) or len(files) > 2048:
        raise ValueError("bounded resource inventory required")
    admitted = []
    for name in ("KQvK.rtbw", "KQvK.rtbz"):
        rows = [row for row in files if isinstance(row, dict) and row.get("name") == name]
        if len(rows) != 1:
            raise ValueError("unique closed-subset resource record required")
        path = root / name
        if path.is_symlink() or not path.is_file() or path.stat().st_size != rows[0]["bytes"]:
            raise ValueError("regular tablebase resource size mismatch")
        actual = digest(path)
        if actual != rows[0]["sha256"]:
            raise ValueError("tablebase content identity mismatch")
        admitted.append({"name": name, "bytes": path.stat().st_size, "sha256": actual})
    identity = {"schema": "syzygy_root_diagnostic_identity_v1", "manifest_sha256": digest(manifest_path),
                "scope": "closed_KQvK_three_piece_subset", "files": admitted,
                "library_version": chess.__version__, "provider_source_sha256": digest(Path(__file__).with_name("provider.py"))}
    observations = []
    with chess.syzygy.open_tablebase(str(root), max_fds=4) as tablebase:
        provider = RootProvider(tablebase, identity, maximum_pieces=3)
        for index, (fen, expected) in enumerate([
            ("8/8/8/8/8/2k5/8/KQ6 w - - 0 1", 2),
            ("8/8/8/8/8/2k5/8/KQ6 b - - 0 1", -2),
            ("8/8/8/8/8/2k5/8/KQ6 w - - 99 1", 2),
        ]):
            board = chess.Board(fen)
            request = {"schema": "uci_arena_syzygy_root_request_v1", "request_id": f"kqvk-{index}",
                       "root_fence": f"{index + 1:032x}", "fen": fen,
                       "legal_moves": [move.uci() for move in board.legal_moves], "searchmoves": None}
            result = provider.probe(request)
            if result["status"] != "safety_only" or result["raw_wdl"] != expected or not result["safe_moves"]:
                raise AssertionError("closed subset raw safety failed")
            if result["exact"] or result["authority"]["history_adjusted"] or result["move"] is not None:
                raise AssertionError("raw safety widened into exact authority")
            observations.append({"fen": fen, "result": result})
    record = {"schema": "syzygy_root_provider_diagnostic_v1", "identity": identity,
              "observations": observations, "owned_tablebase_closed": True,
              "production_runtime_qualification": False, "history_adjusted_exact": False, "suite_adoption": False}
    output = Path(options.output)
    if not output.is_absolute() or output.exists():
        raise ValueError("fresh explicit absolute output required")
    output.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"passed": len(observations), "receipt_sha256": digest(output), "exact": False, "suite_adoption": False}))


if __name__ == "__main__":
    main()
