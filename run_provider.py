"""Public isolated root-only process entrypoint; operator configuration is cold."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import secrets
import sys
from dataset import admit_dataset, regular
from root_contract import canonical_json
from root_provider import RootKnowledgeProvider
from runtime_manifest import admit_runtime
from service import RootService, TRANSPORT_SCHEMA, TransportError
from transport import BoundedOutput, read_frame


class ConfigurationError(ValueError):
    pass


def admit_config(value):
    if type(value) is not dict or set(value) != {"schema", "dataset_root", "manifest_sha256", "selected_files"} or value["schema"] != "uci_arena_syzygy_root_configuration_v1":
        raise ConfigurationError("closed configuration required")
    if not isinstance(value["dataset_root"], str) or not Path(value["dataset_root"]).is_absolute():
        raise ConfigurationError("explicit dataset root required")
    if not isinstance(value["manifest_sha256"], str) or not re.fullmatch(r"[0-9a-f]{64}", value["manifest_sha256"]):
        raise ConfigurationError("exact manifest identity required")
    selected = value["selected_files"]
    if type(selected) is not list or not 1 <= len(selected) <= 2048 or any(not isinstance(name, str) for name in selected) or len(set(selected)) != len(selected):
        raise ConfigurationError("explicit bounded dataset selection required")
    return json.loads(canonical_json(value))


def serve(provider, source, sink):
    output = BoundedOutput(sink)
    service = RootService(provider, output.write)
    code = 0
    try:
        while True:
            message = read_frame(source)
            if message is None:
                break
            service.handle(message)
            if message.get("operation") == "close":
                break
    except (TransportError, ValueError, TypeError, RecursionError):
        code = 2
        try:
            output.write({"schema": TRANSPORT_SCHEMA, "operation": "transport", "status": "error",
                          "reason": "invalid_transport", "provider_generation": provider.generation})
        except TransportError:
            pass
    finally:
        if not service.close(1):
            code = 3  # Native/file call drain not complete; caller must contain process.
        if not output.close(1):
            code = 3
    return code


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", required=True)
    parser.add_argument("--inventory", required=True)
    parser.add_argument("--expected-manifest-sha256", required=True)
    options = parser.parse_args()
    dataset = None
    try:
        inventory = Path(options.inventory)
        if not re.fullmatch(r"[0-9a-f]{64}", options.expected_manifest_sha256) or regular(inventory).st_size > 1048576 or hashlib.sha256(inventory.read_bytes()).hexdigest() != options.expected_manifest_sha256:
            raise ConfigurationError("package identity mismatch")
        identity = admit_runtime(inventory)
        if identity["package"]["manifest_sha256"] != options.expected_manifest_sha256:
            raise ConfigurationError("package changed during admission")
        if not sys.flags.isolated or not sys.dont_write_bytecode:
            raise ConfigurationError("isolated no-bytecode launch required")
        path = Path(options.config)
        if not path.is_absolute() or regular(path).st_size > 65536:
            raise ConfigurationError("bounded regular cold configuration required")
        configuration = admit_config(json.loads(path.read_bytes()))
        dataset = admit_dataset(configuration["dataset_root"], configuration["selected_files"], configuration["manifest_sha256"])
        dataset.open()
        identity["dataset"] = dataset.identity
        identity["configuration_sha256"] = hashlib.sha256(canonical_json(configuration).encode()).hexdigest()
        provider = RootKnowledgeProvider(dataset, identity, maximum_pieces=dataset.identity["admitted_cardinality"], generation=secrets.token_hex(16))
        code = serve(provider, sys.stdin.buffer, sys.stdout.buffer)
        if code != 3:
            dataset.close()  # Never close tablebase before outstanding worker drain.
        return code
    except Exception:
        if dataset is not None:
            try:
                dataset.close()
            except Exception:
                pass  # Failed cleanup stays process-contained; no retry/qualification.
        print("root provider unavailable: cold admission failed", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
