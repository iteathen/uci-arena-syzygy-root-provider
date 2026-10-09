"""Public isolated root-only process entrypoint; operator configuration is cold."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import secrets
import sys
from dataset import admit_dataset, regular, stamp, cancellation_point
from root_contract import canonical_json
from root_provider import RootKnowledgeProvider
from runtime_manifest import admit_runtime
from service import RootService, TRANSPORT_SCHEMA, TransportError
from transport import BoundedOutput, read_frame
from warming import WarmingService


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
    return serve_service(service, provider.generation, source, output)


def serve_warming(identity, generation, load, source, sink):
    output = BoundedOutput(sink)
    service = WarmingService(identity, generation, load, output.write)
    return serve_service(service, generation, source, output)


def serve_service(service, generation, source, output):
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
                          "reason": "invalid_transport", "provider_generation": generation})
        except TransportError:
            pass
    finally:
        service.close(1)
        output.close(1)
        worker, writer = service.close_disposition, output.close_disposition
        if not worker["drained"] or not writer["drained"]:
            code = 3  # Incomplete drain: preserve owner, contain process.
        elif worker["failed"] or writer["failed"]:
            code = 4  # Drained failure is quarantine, never successful close.
    return code


class OwnedRootProvider(RootKnowledgeProvider):
    def __init__(self, dataset, identity, generation):
        super().__init__(dataset, identity, maximum_pieces=dataset.identity['admitted_cardinality'], generation=generation)
        self.dataset = dataset

    def close(self):
        self.dataset.close()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", required=True)
    parser.add_argument("--inventory", required=True)
    parser.add_argument("--expected-manifest-sha256", required=True)
    options = parser.parse_args()
    try:
        inventory = Path(options.inventory).absolute()
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
        config_state = stamp(path)
        configuration = admit_config(json.loads(path.read_bytes()))
        if stamp(path) != config_state:
            raise ConfigurationError('configuration changed during admission')
        identity["configuration_sha256"] = hashlib.sha256(canonical_json(configuration).encode()).hexdigest()
        generation = secrets.token_hex(16)
        def load(cancelled):
            dataset = None
            try:
                if stamp(path) != config_state:
                    raise ConfigurationError('configuration changed before dataset admission')
                dataset = admit_dataset(configuration['dataset_root'], configuration['selected_files'], configuration['manifest_sha256'], cancelled=cancelled)
                dataset.open(cancelled=cancelled)
                cancellation_point(cancelled)
                # Readiness binds the same runtime/configuration before and after
                # the long cold phase, as well as every admitted dataset member.
                current = admit_runtime(inventory)
                if current != {key: value for key, value in identity.items() if key != 'configuration_sha256'} or stamp(path) != config_state:
                    raise ConfigurationError('cold selection changed before readiness')
                dataset.check_unchanged()
                cancellation_point(cancelled)
                ready_identity = dict(identity, dataset=dataset.identity)
                return OwnedRootProvider(dataset, ready_identity, generation)
            except Exception:
                if dataset is not None:
                    dataset.close()  # A failed close propagates quarantine.
                raise
        return serve_warming(identity, generation, load, sys.stdin.buffer, sys.stdout.buffer)
    except Exception:
        print("root provider unavailable: cold admission failed", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
