"""Hermetic storage inventory and retention checks; never contact GitHub or delete files."""
import copy
import io
import json
from pathlib import Path
import textwrap
import unittest
from unittest.mock import patch
import urllib.error

ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS = ROOT / '.github/workflows'


def load_inventory():
    text = (WORKFLOWS / 'artifact-inventory.yml').read_text(encoding='utf-8')
    scope = {'__name__': 'trusted_inventory_fixture'}
    exec(compile(textwrap.dedent(text.split('run: |\n', 1)[1]), 'inventory-fixture', 'exec'), scope)
    return text, scope


def artifact(identifier, name='preview', expired=False, size=10, **run_changes):
    run = {'id': 7, 'repository_id': 1412474221, 'head_sha': 'a' * 40, 'head_branch': 'fix/demo'}
    run.update(run_changes)
    return {'id': identifier, 'name': name, 'expired': expired, 'size_in_bytes': size, 'workflow_run': run}


def reader(pages, metadata=None):
    info = metadata if metadata is not None else {
        'id': 1412474221, 'full_name': 'oncoursemail/Star-AI-Private', 'private': True}
    def read(path):
        if path == '':
            return info
        page = int(path.rsplit('=', 1)[1])
        return pages[page - 1]
    return read


class InventoryTests(unittest.TestCase):
    def setUp(self):
        self.text, self.scope = load_inventory()

    def test_workflow_has_no_mutation_permissions_or_artifact_dependency(self):
        self.assertIn('actions: read', self.text)
        self.assertIn('contents: read', self.text)
        for forbidden in ('contents: write', 'actions: write', 'uses:', 'secrets.', 'continue-on-error'):
            self.assertNotIn(forbidden, self.text)

    def test_empty_repository_is_a_complete_zero_not_a_billing_estimate(self):
        rows, complete, total = self.scope['collect'](reader([{'artifacts': [], 'total_count': 0}]))
        report = self.scope['summarize'](rows, complete, total)
        self.assertTrue(complete)
        self.assertEqual(report['listed_retained_bytes'], 0)
        self.assertFalse(report['account_quota_known'])
        self.assertEqual(report['deletions_performed'], 0)

    def test_collects_multiple_pages_and_excludes_expired_bytes(self):
        pages = [{'artifacts': [artifact(i) for i in range(1, 101)], 'total_count': 101},
                 {'artifacts': [artifact(101, expired=True, size=999)], 'total_count': 101}]
        rows, complete, total = self.scope['collect'](reader(pages))
        self.assertTrue(complete)
        report = self.scope['summarize'](rows, complete, total)
        self.assertEqual(report['listed_retained_bytes'], 1000)
        self.assertEqual(report['retained_artifacts'], 100)

    def test_page_limit_reports_partial_not_complete(self):
        self.scope['MAX_PAGES'] = 1
        rows, complete, total = self.scope['collect'](reader([
            {'artifacts': [artifact(i) for i in range(1, 101)], 'total_count': 200}]))
        self.assertFalse(complete)
        self.assertEqual((len(rows), total), (100, 200))

    def test_duplicate_ids_are_not_double_counted_or_called_complete(self):
        rows, complete, total = self.scope['collect'](reader([
            {'artifacts': [artifact(1), artifact(1)], 'total_count': 2}]))
        self.assertEqual(len(rows), 1)
        self.assertFalse(complete)

    def test_changing_totals_do_not_claim_a_complete_snapshot(self):
        pages = [{'artifacts': [artifact(i) for i in range(1, 101)], 'total_count': 102},
                 {'artifacts': [artifact(101)], 'total_count': 101}]
        self.assertFalse(self.scope['collect'](reader(pages))[1])

    def test_identity_change_refuses_before_any_artifact_page(self):
        for change in ({'id': True}, {'id': 1424898960}, {'private': False}, {'private': 1}, {'full_name': 'other/repo'}):
            with self.subTest(change=change), self.assertRaises(ValueError):
                self.scope['collect'](reader([], {
                    'id': 1412474221, 'full_name': 'oncoursemail/Star-AI-Private', 'private': True, **change}))

    def test_invalid_artifact_fields_are_not_coerced(self):
        for change in ({'id': True}, {'size_in_bytes': -1}, {'size_in_bytes': True}, {'expired': 'false'}, {'name': None}):
            with self.subTest(change=change), self.assertRaises(ValueError):
                self.scope['collect'](reader([{'artifacts': [{**artifact(1), **change}], 'total_count': 1}]))

    def test_foreign_artifact_repository_is_refused(self):
        with self.assertRaises(ValueError):
            self.scope['collect'](reader([{'artifacts': [artifact(1, repository_id=999)], 'total_count': 1}]))

    def duplicate_group(self):
        return [artifact(1, 'STAR-Fast-Brain-Preview', size=100),
                artifact(2, 'STAR-Ultimate-Windows-Setup', size=40),
                artifact(3, 'STAR-Ultimate-Windows-Portable', size=60)]

    def test_matching_preview_group_is_only_a_review_candidate(self):
        report = self.scope['summarize'](self.duplicate_group(), True, 3)
        self.assertEqual(report['possible_duplicate_groups'][0]['split_ids'], [2, 3])
        self.assertIn('not verified', report['possible_duplicate_groups'][0]['status'])
        self.assertEqual(report['deletions_performed'], 0)

    def test_missing_expired_ambiguous_or_different_revision_copies_are_not_candidates(self):
        rows = self.duplicate_group()
        variants = [rows[:2], rows + [artifact(4, 'STAR-Ultimate-Windows-Setup')]]
        for change in ({'head_sha': 'b' * 40}, {'head_branch': 'other'}, {'head_sha': None}):
            variant = copy.deepcopy(rows)
            variant[1]['workflow_run'].update(change)
            variants.append(variant)
        expired = copy.deepcopy(rows)
        expired[1]['expired'] = True
        variants.append(expired)
        main = copy.deepcopy(rows)
        for item in main:
            item['workflow_run']['head_branch'] = 'main'
        variants.append(main)
        for variant in variants:
            with self.subTest(variant=variant):
                self.assertEqual(self.scope['summarize'](variant, True, len(variant))['possible_duplicate_groups'], [])

    def test_report_size_is_bounded(self):
        report = self.scope['summarize']([artifact(i, 'name-' + str(i)) for i in range(1, 30)], True, 29)
        self.assertEqual(len(report['largest_groups']), 12)
        self.assertEqual(report['listed_retained_bytes'], 290)

    def test_unapproved_endpoint_refuses_before_credentials_are_read(self):
        with self.assertRaises(ValueError):
            self.scope['get']('/actions/artifacts/123')

    def test_http_is_get_only_and_redirects_are_disabled(self):
        calls = []
        class FakeOpener:
            def open(self, request, timeout):
                calls.append((request.get_method(), request.full_url, timeout))
                return io.BytesIO(b'{}')
        with patch.dict('os.environ', {'GH_TOKEN': 'fixture-only'}), patch('urllib.request.build_opener', return_value=FakeOpener()):
            self.scope['get']('')
        self.assertEqual(calls, [('GET', 'https://api.github.com/repos/oncoursemail/Star-AI-Private', 15)])
        self.assertIsNone(self.scope['NoRedirect']().redirect_request(None))

    def test_provider_error_bodies_are_not_exposed(self):
        class Failure:
            def open(self, *args, **kwargs):
                raise urllib.error.HTTPError('https://api.github.com', 403, 'secret-fixture', {}, None)
        with patch.dict('os.environ', {'GH_TOKEN': 'fixture-only'}), patch('urllib.request.build_opener', return_value=Failure()):
            with self.assertRaisesRegex(RuntimeError, r'^GitHub inventory request failed: HTTP 403$'):
                self.scope['get']('')


class RetentionTests(unittest.TestCase):
    def setUp(self):
        self.text = (WORKFLOWS / 'windows-desktop.yml').read_text(encoding='utf-8')

    def step(self, name):
        return self.text.split('      - name: ' + name + '\n', 1)[1].split('      - ', 1)[0]

    def test_combined_and_split_binaries_are_mutually_exclusive(self):
        combined = self.step('Upload testable executables')
        self.assertIn("if: github.event_name != 'pull_request'", combined)
        self.assertIn('name: STAR-Windows-vNext', combined)
        self.assertIn('retention-days: 1', combined)
        for name in ('Upload Ultimate preview Windows installer', 'Upload Ultimate preview portable ZIP'):
            step = self.step(name)
            self.assertIn("if: github.event_name == 'pull_request'", step)
            self.assertIn('retention-days: 3', step)
            self.assertIn('STAR-PREVIEW-SHA256SUMS.txt', step)
        self.assertNotIn('STAR-Fast-Brain-Preview', self.text)

    def test_retention_changes_do_not_bypass_tests_or_publication_gates(self):
        self.assertNotIn('continue-on-error:', self.text)
        for required in ('npm run test', 'python -m pytest', '--doctor', '--ui-doctor', '--build-doctor',
                         'needs.windows-build.result ==', 'needs.windows-tests.result ==', 'sha256sum -c',
                         'repositories: Star-AI', 'permission-contents: write'):
            self.assertIn(required, self.text)


if __name__ == '__main__':
    unittest.main()
