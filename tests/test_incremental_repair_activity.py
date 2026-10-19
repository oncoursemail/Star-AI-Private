"""Incremental repair events reveal only bounded facts and limited check claims."""
import pytest

from star.react_shell import sanitize_event


@pytest.mark.parametrize('checker,label', [
    ('python.compile', 'Python syntax check'),
    ('json.loads', 'JSON syntax check'),
    ('tomllib.loads', 'TOML syntax check'),
    ('luau.lint', 'Luau advisory check'),
])
def test_repair_check_passed_names_only_the_observed_check(checker, label):
    out = sanitize_event({'event': 'repair_check_passed', 'checker': checker,
                          'kind': 'advisory' if checker == 'luau.lint' else 'syntax',
                          'count': 0, 'attempt': 1})
    assert out['phase'] == label + ' passed'
    assert out['activity']['result'] == 'check_passed'
    assert out['activity']['state'] == 'done'
    assert 'fixed' not in str(out).lower()


def test_repair_finding_and_pause_are_closed_non_success_facts():
    detected = sanitize_event({'event': 'repair_detected', 'checker': 'json.loads',
                               'kind': 'syntax', 'count': 1, 'attempt': 0})
    assert detected['activity'] == {
        'type': 'repair', 'result': 'detected', 'state': 'failed',
        'checker': 'json.loads', 'kind': 'syntax', 'count': 1, 'attempt': 0,
    }
    blocked = sanitize_event({'event': 'repair_blocked', 'checker': 'json.loads',
                              'kind': 'budget', 'attempt': 2})
    assert blocked['activity']['state'] == 'blocked'
    assert blocked['phase'] == 'Focused repair limit reached'


def test_queued_batch_deferral_does_not_claim_retry_exhaustion():
    out = sanitize_event({'event': 'repair_blocked', 'checker': 'none',
                          'kind': 'budget', 'attempt': 0})
    assert out['phase'] == 'Work paused for a repair'
    assert out['activity']['state'] == 'blocked'
    assert 'limit' not in out['phase']


def test_luau_advisory_records_a_completed_observation_not_a_proven_failure():
    out = sanitize_event({'event': 'repair_detected', 'checker': 'luau.lint',
                          'kind': 'advisory', 'count': 2, 'attempt': 0})
    assert out['phase'] == 'Luau advisory check reported possible issues'
    assert out['activity']['result'] == 'detected'
    assert out['activity']['state'] == 'done'
    assert 'passed' not in out['phase'] and 'problem' not in out['phase']


def test_repair_sanitizer_strips_sensitive_fields_and_rejects_forged_enums():
    secret = 'secret-file-and-token'
    out = sanitize_event({'event': 'repair_detected', 'checker': [secret], 'kind': secret,
                          'count': True, 'attempt': 3, 'path': secret, 'output': secret,
                          'arguments': {'path': secret}, 'message': secret, 'tool': secret})
    assert secret not in str(out)
    assert out['activity'] == {'type': 'repair', 'result': 'detected', 'state': 'failed',
                               'checker': 'none', 'kind': 'unknown_outcome'}


@pytest.mark.parametrize('checker,kind', [
    ('none', 'syntax'), ('invented.check', 'syntax'),
    ('python.compile', 'unknown_outcome'), ('tool.result', 'budget'),
])
def test_unknown_evidence_cannot_announce_a_pass(checker, kind):
    out = sanitize_event({'event': 'repair_check_passed', 'checker': checker, 'kind': kind})
    assert out['activity']['result'] == 'blocked'
    assert out['activity']['state'] == 'blocked'
    assert 'passed' not in out['phase']


def test_tool_recovery_does_not_claim_code_validation():
    out = sanitize_event({'event': 'repair_check_passed', 'checker': 'tool.result',
                          'kind': 'tool_error', 'attempt': 1})
    assert out['phase'] == 'Tool call returned successfully'
    assert 'code' not in out['phase'] and 'fixed' not in out['phase']


@pytest.mark.parametrize('count,attempt', [(-1, -1), (101, 3), ('1', '1'), (True, False)])
def test_invalid_numeric_fields_are_not_forwarded(count, attempt):
    out = sanitize_event({'event': 'repair_detected', 'checker': 'luau.lint',
                          'kind': 'advisory', 'count': count, 'attempt': attempt})
    assert 'count' not in out['activity'] and 'attempt' not in out['activity']
