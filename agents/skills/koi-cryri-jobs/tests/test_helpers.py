"""Offline checks: missing measurements, partial GPU use, and registry safety."""
from datetime import datetime, timedelta, timezone
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import subprocess


def load(name):
    path = Path(__file__).resolve().parents[1] / 'scripts' / (name + '.py')
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


gpu = load('gpu_telemetry')
registry = load('registry')
END = datetime(2026, 10, 29, 15, tzinfo=timezone.utc)


def history(values=(10, 90), count=300):
    return [{'timestamp': (END - timedelta(minutes=count - i)).isoformat(),
             'gpus': [{'uuid': 'GPU-' + str(n), 'utilization_pct': u,
                       'memory_used_mib': 70000, 'memory_total_mib': 81920}
                      for n, u in enumerate(values)]} for i in range(count)]


def receipt():
    return dict(job_id='lm-mpi-job-5072b578-f593-4b23-82d7-306f2625461f',
                name='volovikova-test', comment='volovikova test', project='test',
                card='card-test', purpose='Offline test', status='pending', gpu_count=2,
                submitted_at=END.isoformat(), checked_at=END.isoformat(),
                ownership_verified=True, ownership_evidence='isolated test receipt')


class MetricsTests(unittest.TestCase):
    def summarize(self, rows, expected=2):
        return gpu.summarize(rows, end=END, expected_gpus=expected)[0]

    def test_one_idle_gpu_is_not_hidden_by_busy_peer_or_high_memory(self):
        d = self.summarize(history())
        self.assertEqual(d['verdict'], 'poor')
        self.assertEqual([g['verdict'] for g in d['gpus']], ['poor', 'healthy'])
        self.assertGreater(d['gpus'][0]['mean_memory_gib'], 60)

    def test_short_missing_and_stale_data_are_not_idle(self):
        for rows in ([], history(count=20), history()[:200]):
            self.assertEqual(self.summarize(rows)['verdict'], 'insufficient_data')

    def test_missing_gpu_prevents_all_clear(self):
        for utilization in (10, 90):
            d = self.summarize(history(values=(utilization,)))
            self.assertTrue(d['gpu_count_mismatch'])
            self.assertEqual(d['verdict'], 'insufficient_data')

    def test_duplicates_do_not_inflate_coverage(self):
        d = self.summarize(history() + history())
        self.assertAlmostEqual(d['gpus'][0]['coverage'], 1)
        self.assertEqual(d['gpus'][0]['samples'], 300)

    def test_driver_failure_and_na_are_not_zero(self):
        with patch.object(gpu.subprocess, 'run', side_effect=FileNotFoundError):
            d = gpu.gpu_sample('volovikova-test')
            self.assertIn('error', d)
            self.assertEqual(d['gpus'], [])
        fake = subprocess.CompletedProcess([], 0, '0, GPU-a, 70000, 81920, [N/A]\n')
        with patch.object(gpu.subprocess, 'run', return_value=fake):
            d = gpu.gpu_sample('volovikova-test')
            self.assertIsNone(d['gpus'][0]['utilization_pct'])


class RegistryTests(unittest.TestCase):
    def test_upsert_keeps_one_id_and_metadata(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / 'jobs.json'
            registry.update(p, receipt())
            result = registry.update(p, {'job_id': receipt()['job_id'], 'status': 'running'})
            self.assertEqual(len(result['jobs']), 1)
            self.assertEqual(result['jobs'][0]['purpose'], 'Offline test')
            self.assertIn('running', p.with_suffix('.md').read_text())

    def test_unknown_owner_or_missing_marker_is_rejected(self):
        for change in ({'ownership_verified': False}, {'name': 'other-user'}, {'comment': 'unmarked'}):
            with self.assertRaises(ValueError):
                registry.validate(dict(receipt(), **change))

    def test_stale_active_status_cannot_undo_cancellation(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / 'jobs.json'
            registry.update(p, dict(receipt(), status='cancelled'))
            with self.assertRaises(ValueError):
                registry.update(p, {'job_id': receipt()['job_id'], 'status': 'running'})
            self.assertEqual(json.loads(p.read_text())['jobs'][0]['status'], 'cancelled')

    def test_cancellation_request_is_preserved_until_confirmed(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / 'jobs.json'
            registry.update(p, dict(receipt(), status='running'))
            result = registry.update(p, {'job_id': receipt()['job_id'], 'status': 'cancel_requested'})
            self.assertEqual(result['jobs'][0]['status'], 'cancel_requested')
            result = registry.update(p, {'job_id': receipt()['job_id'], 'status': 'cancelled'})
            self.assertEqual(result['jobs'][0]['status'], 'cancelled')


if __name__ == '__main__':
    unittest.main()
