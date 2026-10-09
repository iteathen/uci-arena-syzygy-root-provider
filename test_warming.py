import threading
import unittest
from warming import WarmingService
from dataset import AdmissionCancelled
from test_root_contract import request


class ColdOwner:
    def __init__(self):
        self.entered, self.release = threading.Event(), threading.Event()
        self.closed = 0
        self.generation = '1' * 32
        self.identity = {'package': {'manifest_sha256': 'a' * 64},
                         'runtime': {'version': '3.13.16'}, 'configuration_sha256': 'b' * 64}
    def load(self, cancelled):
        self.entered.set()
        while not self.release.wait(.001):
            if cancelled():
                raise AdmissionCancelled('cancelled')
        return self
    def events(self, raw, cancelled):
        return iter(())
    def close(self):
        self.closed += 1


class WarmingTests(unittest.TestCase):
    def start(self, owner=None):
        owner = owner or ColdOwner()
        events = []
        service = WarmingService(owner.identity, owner.generation, owner.load, events.append)
        self.addCleanup(service.close, 1)
        self.assertTrue(owner.entered.wait(1))
        return owner, service, events
    def test_describe_is_responsive_without_dataset_readiness_claim(self):
        owner, service, events = self.start()
        service.handle({'operation': 'describe'})
        self.assertEqual(events[-1]['status'], 'warming')
        self.assertNotIn('dataset', events[-1]['provider_identity'])
        self.assertEqual(events[-1]['readiness']['dataset'], 'not-admitted')
        self.assertTrue(events[-1]['profile']['cold_lifecycle']['cancel_during_warming'])
        self.assertFalse(owner.release.is_set())
    def test_warming_probe_defers_with_identity_and_no_safety_or_miss(self):
        owner, service, events = self.start()
        raw = request()
        service.handle({'operation': 'probe', 'request': raw})
        event = events[-1]
        self.assertEqual((event['status'], event['reason']), ('deferred', 'provider_warming'))
        self.assertEqual(event['root_fence'], raw['root_fence'])
        self.assertEqual(event['request_id'], raw['request_id'])
        self.assertNotIn('safe_moves', event)
        self.assertNotIn('dataset', event)
    def test_close_cancels_and_joins_warm_worker_without_open_owner(self):
        owner, service, events = self.start()
        service.handle({'operation': 'close'})
        self.assertEqual(events[-1]['status'], 'closed')
        self.assertTrue(events[-1]['drained'])
        self.assertFalse(events[-1]['failed'])
        self.assertEqual(owner.closed, 0)
        self.assertFalse(service.worker_alive)
    def test_ready_identity_published_only_after_complete_loader(self):
        owner, service, events = self.start()
        owner.identity = dict(owner.identity, dataset={'file_count': 2})
        owner.release.set()
        self.assertTrue(service.wait_ready(1))
        service.handle({'operation': 'describe'})
        self.assertEqual(events[-1]['status'], 'ready')
        self.assertEqual(events[-1]['provider_identity']['dataset']['file_count'], 2)
        self.assertTrue(service.close(1))
        self.assertEqual(owner.closed, 1)
        self.assertTrue(service.close(1))
        self.assertEqual(owner.closed, 1)
    def test_late_loader_owner_is_closed_before_cancelled_close_returns(self):
        owner = ColdOwner()
        def load(cancelled):
            owner.entered.set()
            while not cancelled():
                owner.release.wait(.001)
            return owner
        owner.load = load
        owner, service, events = self.start(owner)
        self.assertTrue(service.close(1))
        self.assertEqual(owner.closed, 1)
        self.assertFalse(service.wait_ready(0))
    def test_failed_admission_is_quarantined_not_ready_or_clean_close(self):
        owner = ColdOwner()
        def load(cancelled):
            owner.entered.set()
            raise ValueError('hash mismatch')
        owner.load = load
        owner, service, events = self.start(owner)
        self.assertFalse(service.wait_ready(1))
        service.handle({'operation': 'describe'})
        self.assertEqual(events[-1]['status'], 'quarantined')
        self.assertNotIn('dataset', events[-1]['provider_identity'])
        self.assertFalse(service.close(1))
        self.assertTrue(service.close_disposition['failed'])
    def test_undrained_warm_worker_cannot_claim_closed(self):
        owner = ColdOwner()
        def load(cancelled):
            owner.entered.set()
            owner.release.wait(1)
            return owner
        owner.load = load
        owner, service, events = self.start(owner)
        self.assertFalse(service.close(.001))
        self.assertEqual(service.close_disposition['status'], 'draining')
        self.assertEqual(service.describe()['status'], 'draining')
        owner.release.set()
        self.assertTrue(service.close(1))
        self.assertEqual(owner.closed, 1)
    def test_ready_owner_failed_close_is_quarantined_and_never_retried(self):
        owner = ColdOwner()
        def failed_close():
            owner.closed += 1
            raise OSError('close failed')
        owner.close = failed_close
        owner, service, events = self.start(owner)
        owner.release.set()
        self.assertTrue(service.wait_ready(1))
        self.assertFalse(service.close(1))
        self.assertEqual(service.close_disposition['status'], 'quarantined')
        self.assertFalse(service.close(1))
        self.assertEqual(owner.closed, 1)
    def test_cancelled_late_owner_close_failure_is_not_retried(self):
        owner = ColdOwner()
        def load(cancelled):
            owner.entered.set()
            while not cancelled():
                owner.release.wait(.001)
            return owner
        def fail():
            owner.closed += 1
            raise OSError('failed late owner close')
        owner.load, owner.close = load, fail
        owner, service, events = self.start(owner)
        self.assertFalse(service.close(1))
        self.assertEqual(owner.closed, 1)
        self.assertFalse(service.close(1))
        self.assertEqual(owner.closed, 1)


if __name__ == '__main__':
    unittest.main()
