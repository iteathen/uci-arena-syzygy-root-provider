"""Public cold-lifecycle owner; dataset readiness follows exact admission only."""
import copy
import json
import re
import threading
from dataset import AdmissionCancelled
from root_contract import canonical_json, MAX_REQUEST_BYTES, REQUEST_SCHEMA
from service import RootService, TRANSPORT_SCHEMA, TransportError

COLD_LIFECYCLE = {'schema': 'uci_arena_root_provider_cold_lifecycle_v1',
                  'cancel_during_warming': True, 'warming_probe': 'deferred',
                  'ready_notification': False, 'hash_chunk_bytes': 65536}


class WarmingService:
    def __init__(self, identity, generation, load, emit):
        self.generation = generation
        self.identity = copy.deepcopy(identity)
        self._load, self.emit = load, emit
        self._lock, self._cancel = threading.Lock(), threading.Event()
        self._finished = threading.Event()
        self._service = self._owner = None
        self._closed = self._failed = self._owner_closed = False
        self._worker = threading.Thread(target=self._run, name='root-cold-admission', daemon=True)
        self._worker.start()

    def _run(self):
        owner = None
        try:
            owner = self._load(self._cancel.is_set)
            with self._lock:
                self._owner = owner
                discard = self._closed
                if not discard:
                    self._service = RootService(owner, self.emit)
            if discard:
                try:
                    owner.close()
                finally:
                    with self._lock:
                        self._owner_closed = True
        except AdmissionCancelled:
            if not self._cancel.is_set():
                with self._lock:
                    self._failed = True
        except Exception:
            with self._lock:
                self._failed = True
        finally:
            self._finished.set()

    @property
    def worker_alive(self):
        return self._worker.is_alive()

    def wait_ready(self, seconds):
        self._finished.wait(seconds)
        with self._lock:
            return self._service is not None and not self._closed and not self._failed

    def describe(self):
        with self._lock:
            service = self._service
            failed, closed = self._failed, self._closed
        if service is not None and not failed and not closed:
            result = service.describe()
            result['readiness'] = {'dataset': 'admitted'}
        else:
            result = {'schema': TRANSPORT_SCHEMA, 'operation': 'describe',
                      'status': self.close_disposition['status'] if closed else 'quarantined' if failed else 'warming',
                      'provider_generation': self.generation,
                      'provider_identity': copy.deepcopy(self.identity),
                      'readiness': {'dataset': 'not-admitted'},
                      'profile': {'root_only': True, 'worker_count': 1, 'ticket_capacity': 0,
                                  'request_schema': REQUEST_SCHEMA, 'active_gpu_callback': False}}
        result['profile']['cold_lifecycle'] = copy.deepcopy(COLD_LIFECYCLE)
        return result

    def handle(self, message):
        expected = {'describe': {'operation'}, 'probe': {'operation', 'request'},
                    'cancel': {'operation', 'request_id', 'root_fence'}, 'close': {'operation'}}
        if type(message) is not dict or message.get('operation') not in expected or set(message) != expected[message['operation']]:
            raise TransportError('closed_transport_fields')
        operation = message['operation']
        if operation == 'describe':
            self.emit(self.describe())
            return
        if operation == 'close':
            self.close(1)
            self.emit({'schema': TRANSPORT_SCHEMA, 'operation': 'close',
                       **self.close_disposition, 'provider_generation': self.generation})
            return
        with self._lock:
            service, failed, closed = self._service, self._failed, self._closed
        if service is not None and not failed and not closed:
            service.handle(message)
            return
        raw = message if operation == 'cancel' else message['request']
        try:
            text = canonical_json(raw)
            if len(text.encode('utf-8')) > MAX_REQUEST_BYTES:
                raise TransportError('request_byte_capacity')
            raw = json.loads(text)
        except (TypeError, ValueError) as error:
            raise TransportError('bounded_json_required') from error
        if type(raw) is not dict or not isinstance(raw.get('request_id'), str) or not re.fullmatch(r'[A-Za-z0-9_.-]{1,128}', raw['request_id']) or not isinstance(raw.get('root_fence'), str) or not re.fullmatch(r'[0-9a-f]{32}', raw['root_fence']) or (operation == 'probe' and raw.get('schema') != REQUEST_SCHEMA):
            raise TransportError('invalid_request_identity')
        if operation == 'cancel':
            return  # Warming deferrals create no request ticket.
        self.emit({'schema': TRANSPORT_SCHEMA, 'operation': 'probe', 'status': 'deferred',
                   'reason': 'provider_unavailable' if failed or closed else 'provider_warming',
                   'request_id': raw['request_id'], 'root_fence': raw['root_fence'],
                   'provider_generation': self.generation})

    def close(self, seconds=1):
        with self._lock:
            self._closed = True
            self._cancel.set()
        self._worker.join(seconds)
        if self._worker.is_alive():
            return False
        with self._lock:
            service, owner = self._service, self._owner
        if service is not None:
            service.close(seconds)
            if not service.close_disposition['drained']:
                return False
            if service.close_disposition['failed']:
                with self._lock:
                    self._failed = True
        if owner is not None and not self._owner_closed:
            # Single ingress owner calls close; never close underneath live work.
            try:
                owner.close()
            except Exception:
                with self._lock:
                    self._failed = True
            finally:
                self._owner_closed = True
        outcome = self.close_disposition
        return outcome['drained'] and not outcome['failed']

    @property
    def close_disposition(self):
        with self._lock:
            service, failed = self._service, self._failed
            drained = not self._worker.is_alive()
        if service is not None:
            facts = service.close_disposition
            drained = drained and facts['drained']
            failed = failed or facts['failed']
        return {'drained': drained, 'failed': failed,
                'status': 'quarantined' if failed else 'closed' if drained else 'draining'}
