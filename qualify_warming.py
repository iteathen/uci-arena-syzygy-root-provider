"""Literal public CLI warming cancellation; no engine/GPU/search qualification."""
import argparse
import hashlib
import json
from pathlib import Path
import queue
import subprocess
import threading
import time
from root_contract import canonical_json
from test_root_contract import request


def main():
    parser = argparse.ArgumentParser()
    for name in ('package', 'config', 'output'):
        parser.add_argument('--' + name, required=True)
    options = parser.parse_args()
    root, output = Path(options.package), Path(options.output)
    if not root.is_absolute() or not output.is_absolute() or output.exists():
        raise ValueError('explicit package and fresh receipt required')
    manifest_sha = hashlib.sha256((root / 'package-manifest.json').read_bytes()).hexdigest()
    args = [str(root / 'python/python.exe'), '-I', '-B', 'app/run_provider.py', '--config', options.config,
            '--inventory', 'package-manifest.json', '--expected-manifest-sha256', manifest_sha]
    observations = []
    for disposition in ('close', 'eof'):
        process = subprocess.Popen(args, cwd=root, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        frames = queue.Queue(maxsize=8)
        def read():
            try:
                for line in iter(process.stdout.readline, b''):
                    if len(line) > 1048576:
                        raise ValueError('output capacity')
                    frames.put(json.loads(line), timeout=2)
            except Exception as error:
                frames.put(error, timeout=2)
        reader = threading.Thread(target=read, daemon=True)
        reader.start()
        def send(value):
            process.stdin.write((canonical_json(value) + '\n').encode())
            process.stdin.flush()
        def receive():
            result = frames.get(timeout=5)
            if isinstance(result, Exception):
                raise result
            return result
        try:
            started = time.monotonic()
            send({'operation': 'describe'})
            description = receive()
            describe_ms = (time.monotonic() - started) * 1000
            if description['status'] != 'warming' or 'dataset' in description['provider_identity'] or description['readiness']['dataset'] != 'not-admitted':
                raise AssertionError('full selected dataset must still be warming without readiness')
            if description['provider_identity']['package']['manifest_sha256'] != manifest_sha:
                raise AssertionError('actual package mismatch')
            raw = request()
            send({'operation': 'probe', 'request': raw})
            deferred = receive()
            if deferred.get('reason') != 'provider_warming' or deferred.get('status') != 'deferred' or deferred.get('root_fence') != raw['root_fence'] or 'safe_moves' in deferred:
                raise AssertionError('warming probe acquired false authority')
            stop = time.monotonic()
            terminal = None
            if disposition == 'close':
                send({'operation': 'close'})
                terminal = receive()
                if terminal['status'] != 'closed' or not terminal['drained'] or terminal['failed']:
                    raise AssertionError('warming owner not joined')
            else:
                process.stdin.close()
            code = process.wait(timeout=5)
            close_ms = (time.monotonic() - stop) * 1000
            reader.join(1)
            if code != 0 or reader.is_alive():
                raise AssertionError('process/output not closed normally')
            observations.append({'disposition': disposition, 'description': description, 'deferred': deferred,
                                 'terminal': terminal, 'process_exit_code': code, 'stdout_eof': True,
                                 'forced': False, 'describe_milliseconds': describe_ms, 'close_milliseconds': close_ms})
        finally:
            if process.poll() is None:
                process.kill()
                process.wait(3)
            if not process.stdin.closed:
                process.stdin.close()
            process.stdout.close()
            process.stderr.close()
    record = {'schema': 'uci_arena_root_provider_warming_observation_v1', 'status': 'pass',
              'package_manifest_sha256': manifest_sha, 'launch': {'arguments': args, 'working_directory': str(root)},
              'config_file_sha256': hashlib.sha256(Path(options.config).read_bytes()).hexdigest(),
              'observations': observations, 'scope': 'full-selection-cold-cancel-and-eof-only',
              'dataset_ready_qualification': False, 'vector_consumer_qualification': False,
              'source_files': {name: hashlib.sha256(Path(__file__).with_name(name).read_bytes()).hexdigest()
                               for name in ('qualify_warming.py', 'run_provider.py', 'dataset.py', 'warming.py')}}
    output.write_text(json.dumps(record, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({'status': 'pass', 'receipt_sha256': hashlib.sha256(output.read_bytes()).hexdigest(),
                      'measurements': [{k: row[k] for k in ('describe_milliseconds', 'close_milliseconds')} for row in observations]}))


if __name__ == '__main__':
    main()
