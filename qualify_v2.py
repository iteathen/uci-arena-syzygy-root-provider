"""Finite external-process proof over an explicitly inventoried existing KQvK subset."""
import argparse
import hashlib
import json
from pathlib import Path
import queue
import subprocess
import threading
import time
import chess
from root_contract import canonical_json


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--package", required=True)
    parser.add_argument("--config", required=True)
    parser.add_argument("--output", required=True)
    options = parser.parse_args()
    package, output = Path(options.package), Path(options.output)
    if not package.is_absolute() or not output.is_absolute() or output.exists():
        raise ValueError("explicit package and fresh output required")
    manifest = package / "package-manifest.json"
    manifest_sha = hashlib.sha256(manifest.read_bytes()).hexdigest()
    process = subprocess.Popen([str(package / "python/python.exe"), "-I", "-B", str(package / "app/run_provider.py"),
                                "--config", options.config, "--inventory", str(manifest), "--expected-manifest-sha256", manifest_sha],
                               stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    events = queue.Queue(maxsize=8)
    def read():
        try:
            while True:
                line = process.stdout.readline(1048577)
                if not line:
                    return
                if len(line) > 1048576:
                    raise ValueError("output capacity")
                events.put(json.loads(line), timeout=2)
        except Exception as error:
            events.put(error, timeout=2)
    reader = threading.Thread(target=read, daemon=True)
    reader.start()
    def send(value):
        process.stdin.write((canonical_json(value) + "\n").encode())
        process.stdin.flush()
    def receive():
        event = events.get(timeout=5)
        if isinstance(event, Exception):
            raise event
        return event
    observations = []
    try:
        send({"operation": "describe"})
        description = receive()
        if description["status"] != "ready" or description["provider_identity"]["package"]["manifest_sha256"] != manifest_sha:
            raise AssertionError("actual package readiness mismatch")
        cases = [
            ("raw-zero-cap", "8/8/8/8/8/2k5/8/KQ6 w - - 0 1", [], None, "safety_only", "node_capacity"),
            ("unknown-prefix", "8/8/8/8/8/2k5/8/KQ6 w - - 99 1", [], None, "safety_only", "history_unavailable"),
            ("third-occurrence", "8/8/8/8/8/2k5/8/KQ6 w - - 0 1", ["b1b2", "c3c4", "b2b1", "c4c3", "b1b2", "c3c4", "b2b1"], ["c4c3"], "exact", None),
            ("mate-boundary", "7k/8/5KQ1/8/8/8/8/8 w - - 0 1", [], ["g6g7"], "exact", None),
            ("live-third-not-forced", "8/8/8/8/8/2k5/8/KQ6 w - - 0 1", ["b1b2", "c3c4", "b2b1", "c4c3", "b1b2", "c3c4", "b2b1"], ["c4c3"], "safety_only", "node_capacity"),
            ("live-mate-boundary", "7k/8/5KQ1/8/8/8/8/8 w - - 0 1", [], ["g6g7"], "exact", None),
        ]
        for index, (name, fen, moves, allowed, status, reason) in enumerate(cases):
            board = chess.Board(fen)
            for move in moves:
                board.push_uci(move)
            request = {"schema": "uci_arena_syzygy_root_request_v2", "request_id": name, "root_fence": f"{index + 1:032x}",
                       "position": {"origin_fen": fen, "moves": moves}, "legal_moves": [m.uci() for m in board.legal_moves],
                       "searchmoves": allowed, "rules": {"rule50": True, "repetition": "threefold-as-draw", "claim_policy": "orthodoxy-live-claims-v1" if name.startswith("live-") else "adjudicated-claims-as-draw"},
                       "history_mode": "replay-from-origin", "limits": {"max_nodes": 32, "max_depth": 128, "max_milliseconds": 1000}}
            start = time.monotonic()
            send({"operation": "probe", "request": request})
            first, final = receive(), receive()
            expected_sha = hashlib.sha256(canonical_json(request).encode()).hexdigest()
            for event in (first, final):
                if event["request_sha256"] != expected_sha or event["root_fence"] != request["root_fence"] or event["provider_generation"] != description["provider_generation"]:
                    raise AssertionError("request/root/provider fence mismatch")
            if first["status"] != "safety_only" or first["authority"]["exact_move"] or final["status"] != status or final["refinement"]["reason"] != reason or final["safe_moves"] != first["safe_moves"]:
                raise AssertionError(f"bounded case failed: {name}")
            if status == "exact":
                if not final["authority"]["history_adjusted"] or final["move"] != allowed[0] or final["result_class"] != (0 if name == "third-occurrence" else 1):
                    raise AssertionError("independent repetition/mate fact mismatch")
            observations.append({"name": name, "request": request, "events": [first, final], "elapsed_milliseconds": (time.monotonic() - start) * 1000})
        send({"operation": "close"})
        terminal = receive()
        if terminal["status"] != "closed" or process.wait(timeout=3) != 0:
            raise AssertionError("owned provider did not drain and close")
        # Real OS pipe failure is a separate owned process, never a successful
        # close merely because its output thread has stopped.
        broken = subprocess.Popen([str(package / "python/python.exe"), "-I", "-B", str(package / "app/run_provider.py"),
                                   "--config", options.config, "--inventory", str(manifest), "--expected-manifest-sha256", manifest_sha],
                                  stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        try:
            broken.stdout.close()
            broken.stdin.write(b'{"operation":"describe"}\n')
            broken.stdin.flush()
            broken.stdin.close()
            failure_code = broken.wait(timeout=5)
            stderr = broken.stderr.read(8193)
            if failure_code == 0 or len(stderr) > 8192:
                raise AssertionError("broken output was incorrectly reported successful")
            output_failure = {"observed_exit_code": failure_code, "forced_shutdown": False,
                              "consumer_closed_stdout": True, "stderr_bytes": len(stderr),
                              "successful_close": False, "individual_dataset_close_observed": False}
        finally:
            if broken.poll() is None:
                broken.kill(); broken.wait(timeout=3)
            if not broken.stdin.closed:
                broken.stdin.close()
            broken.stderr.close()
        record = {"schema": "uci_arena_syzygy_root_process_observation_v2", "description": description,
                  "observations": observations, "process_exit": 0, "owned_worker_and_dataset_closed": True,
                  "broken_output_process": output_failure,
                  "scope": "closed-KQvK-three-piece-subset", "suite_acceptance": False, "vector_consumer_qualification": False,
                  "source_files": {name: hashlib.sha256(Path(__file__).with_name(name).read_bytes()).hexdigest()
                                   for name in ["qualify_v2.py", "root_contract.py", "root_provider.py", "dataset.py", "service.py", "transport.py", "runtime_manifest.py", "run_provider.py"]}}
        output.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
        print(json.dumps({"passed": len(observations), "manifest_sha256": manifest_sha,
                          "receipt_sha256": hashlib.sha256(output.read_bytes()).hexdigest(), "suite_acceptance": False}))
    finally:
        if process.poll() is None:
            process.kill()
            process.wait(timeout=3)
        process.stdin.close(); process.stdout.close(); process.stderr.close()


if __name__ == "__main__":
    main()
