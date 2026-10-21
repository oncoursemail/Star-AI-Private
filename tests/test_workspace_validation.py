"""Evidence after a saved write, without executing written code or widening scope."""
import hashlib
import json

import pytest

from star import workspace_validation as validation
from star.workspace import MAX_LINT_FINDINGS, Workspace


def _write(workspace, path, content):
    return workspace.call('workspace_write', {'path': path, 'content': content}, allow_write=True)


def _edit(workspace, path, old, new):
    return workspace.call('workspace_edit', {'path': path, 'old_string': old, 'new_string': new},
                          allow_write=True)


@pytest.mark.parametrize('path, invalid, old, new, checker', [
    ('main.py', 'def answer()\n    return 42\n', 'def answer()', 'def answer():', 'python.compile'),
    ('data.json', '{"answer": 42,}', '42,', '42', 'json.loads'),
    ('config.toml', 'answer =\n', 'answer =', 'answer = 42', 'tomllib.loads'),
])
def test_failed_write_can_be_repaired_with_one_focused_edit(tmp_path, path, invalid, old, new, checker):
    workspace = Workspace(tmp_path, validate=True)
    failed = _write(workspace, path, invalid)
    evidence = failed['validation']
    assert failed['bytes_written'] == len(invalid.encode('utf-8'))
    assert (tmp_path / path).read_bytes() == invalid.encode('utf-8')
    assert evidence['checker'] == checker
    assert evidence['status'] == 'failed'
    assert evidence['scope'] == 'file_syntax'
    assert evidence['runtime_verified'] is False
    assert evidence['diagnostics'][0]['severity'] == 'error'
    assert evidence['content_sha256'] == hashlib.sha256((tmp_path / path).read_bytes()).hexdigest()

    fixed = _edit(workspace, path, old, new)
    after = fixed['validation']
    assert fixed['replacements'] == 1 and fixed['match'] == 'exact'
    assert after['status'] == 'passed' and after['diagnostics'] == []
    assert after['baseline']['status'] == 'failed'
    assert after['baseline']['content_sha256'] == evidence['content_sha256']
    assert after['content_sha256'] == hashlib.sha256((tmp_path / path).read_bytes()).hexdigest()
    assert after['content_sha256'] != evidence['content_sha256']
    assert after['comparison'] == 'changed'
    assert after['runtime_verified'] is False


def test_python_checks_statement_context_without_executing_or_resolving_imports(tmp_path):
    workspace = Workspace(tmp_path, validate=True)
    bad = _write(workspace, 'outside.py', 'return 1\n')['validation']
    assert bad['status'] == 'failed'
    assert bad['diagnostics'][0]['code'] == 'SyntaxError'
    assert bad['diagnostics'][0]['line'] == 1
    assert 'outside function' in bad['diagnostics'][0]['message']

    marker = tmp_path / 'must-not-be-created.txt'
    source = (f'from pathlib import Path\nPath({str(marker)!r}).write_text("executed")\n'
              'import module_that_does_not_exist_for_star_validation\n'
              'raise RuntimeError("error")\n')
    good = _write(workspace, 'unexecuted.py', source)['validation']
    assert good['status'] == 'passed'
    assert good['checker'] == 'python.compile' and good['checker_version']
    assert good['scope'] == 'file_syntax' and good['runtime_verified'] is False
    assert 'not executed' in good['summary']
    assert not marker.exists()


@pytest.mark.parametrize('path, text', [
    ('main.PY', 'message = "error"\n'),
    ('data.json', '{"error": "an error string is data", "literal": "NaN"}'),
    ('config.toml', 'error = "an error string is data"\n'),
])
def test_valid_content_containing_error_is_not_misclassified(tmp_path, path, text):
    evidence = _write(Workspace(tmp_path, validate=True), path, text)['validation']
    assert evidence['status'] == 'passed'
    assert evidence['diagnostics'] == []


@pytest.mark.parametrize('constant', ['NaN', 'Infinity', '-Infinity'])
def test_strict_json_rejects_nonstandard_constants(tmp_path, constant):
    evidence = _write(Workspace(tmp_path, validate=True), 'data.json', '{"value": ' + constant + '}')['validation']
    assert evidence['status'] == 'failed'
    assert evidence['diagnostics'][0]['code'] == 'NonStandardJSONConstant'


def test_fingerprint_preserves_exact_unicode_and_crlf_bytes(tmp_path):
    original = 'def answer():\r\n    return "caf\u00e9 \U0001f31f"\r\n'
    workspace = Workspace(tmp_path, validate=True)
    before = _write(workspace, 'unicode.py', original)['validation']
    after = _edit(workspace, 'unicode.py', '"caf\u00e9 \U0001f31f"', '"caf\u00e9 \U0001f319"')['validation']
    assert before['content_sha256'] == hashlib.sha256(original.encode('utf-8')).hexdigest()
    assert after['baseline']['content_sha256'] == before['content_sha256']
    written = (tmp_path / 'unicode.py').read_bytes()
    assert after['content_sha256'] == hashlib.sha256(written).hexdigest()
    assert written == original.replace('\U0001f31f', '\U0001f319').encode('utf-8')
    assert after['status'] == 'passed'


def test_baseline_distinguishes_preexisting_from_newly_detected_error(tmp_path):
    workspace = Workspace(tmp_path, validate=True)
    original = 'def broken()\n    return 1\n# old note\n'
    _write(workspace, 'main.py', original)
    unchanged_failure = _edit(workspace, 'main.py', '# old note', '# updated note')['validation']
    assert unchanged_failure['status'] == 'failed'
    assert unchanged_failure['baseline']['status'] == 'failed'
    assert unchanged_failure['comparison'] == 'preexisting'

    fixed = _edit(workspace, 'main.py', 'def broken()', 'def broken():')['validation']
    assert fixed['status'] == 'passed'
    new_failure = _edit(workspace, 'main.py', 'def broken():', 'def broken(')['validation']
    assert new_failure['status'] == 'failed'
    assert new_failure['baseline']['status'] == 'passed'
    assert new_failure['comparison'] == 'newly_detected'


def test_same_generic_error_at_different_source_is_not_labelled_preexisting():
    before = 'def old_name()\n    pass\n'
    after = 'def other_name()\n    pass\n'
    evidence = validation.validate_text('a.py', after, previous_text=before)
    assert evidence['status'] == 'failed' and evidence['baseline']['status'] == 'failed'
    assert evidence['comparison'] == 'changed'


def test_overwrite_baseline_is_best_effort_and_does_not_prevent_writing(tmp_path):
    workspace = Workspace(tmp_path, validate=True)
    path = tmp_path / 'data.json'
    path.write_bytes(b'\xff\xfe')
    evidence = _write(workspace, 'data.json', '{"valid": true}')['validation']
    assert evidence['status'] == 'passed'
    assert evidence['comparison'] == 'unknown' and 'baseline' not in evidence
    assert path.read_bytes() == b'{"valid": true}'


def test_luau_findings_keep_original_advisory_shape_and_are_not_parser_failures(tmp_path, monkeypatch):
    from star import luau_lint
    from star.luau_lint import Finding

    findings = [Finding('example-rule', i + 1, f'Advisory {i}', 'Review this.', 'error')
                for i in range(MAX_LINT_FINDINGS + 2)]
    monkeypatch.setattr(luau_lint, 'lint', lambda text: findings)
    result = _write(Workspace(tmp_path, validate=True), 'main.luau', 'return 1\n')
    assert result['validation']['status'] == 'not_applicable'
    assert result['validation']['checker'] == 'none'
    assert result['validation']['runtime_verified'] is False
    assert result['validation']['diagnostics'] == []
    assert len(result['lint']) == MAX_LINT_FINDINGS and result['lint_more'] == 2
    assert result['lint'][0] == {
        'line': 1, 'rule': 'example-rule', 'severity': 'error',
        'message': 'Advisory 0', 'fix': 'Review this.',
    }


def test_unsupported_file_type_is_explicitly_not_applicable(tmp_path):
    result = _write(Workspace(tmp_path, validate=True), 'notes.md', 'error: ordinary text\n')
    assert result['validation']['status'] == 'not_applicable'
    assert result['validation']['diagnostics'] == [] and 'lint' not in result


def test_checker_exception_is_unavailable_evidence_and_preserves_successful_write(tmp_path, monkeypatch):
    def crash(text):
        raise RuntimeError('internal detail should not be exposed')

    monkeypatch.setattr(validation, '_check_python', crash)
    result = _write(Workspace(tmp_path, validate=True), 'main.py', 'value = 1\n')
    assert result['bytes_written'] == 10
    assert (tmp_path / 'main.py').read_bytes() == b'value = 1\n'
    assert result['validation']['status'] == 'unavailable'
    assert result['validation']['checker'] == 'python.compile'
    assert result['validation']['diagnostics'][0]['code'] == 'checker_unavailable'
    assert 'internal detail' not in json.dumps(result)


def test_dispatcher_exception_does_not_turn_saved_write_into_tool_error(tmp_path, monkeypatch):
    def crash(*args, **kwargs):
        raise RuntimeError('dispatcher bug')

    monkeypatch.setattr(validation, 'validate_text', crash)
    result = _write(Workspace(tmp_path, validate=True), 'main.py', 'value = 1\n')
    assert result['bytes_written'] == 10
    assert (tmp_path / 'main.py').read_bytes() == b'value = 1\n'
    assert result['validation']['status'] == 'unavailable'
    assert result['validation']['diagnostics'][0]['code'] == 'checker_unavailable'
    assert result['validation']['content_sha256'] == hashlib.sha256(b'value = 1\n').hexdigest()


def test_missing_tomllib_is_explicitly_unavailable(tmp_path, monkeypatch):
    monkeypatch.setattr(validation, 'tomllib', None)
    result = _write(Workspace(tmp_path, validate=True), 'config.toml', 'value = 1\n')
    assert result['validation']['status'] == 'unavailable'
    assert result['validation']['checker'] == 'tomllib.loads'
    assert result['bytes_written'] == 10


def test_validation_diagnostic_text_is_bounded(monkeypatch):
    def syntax_error(*args, **kwargs):
        raise SyntaxError('x' * (validation.MAX_DIAGNOSTIC_CHARS + 500))

    monkeypatch.setattr(validation, 'compile', syntax_error, raising=False)
    evidence = validation.validate_text('a.py', 'value = 1\n')
    assert evidence['status'] == 'failed'
    assert len(evidence['diagnostics']) <= validation.MAX_DIAGNOSTICS
    assert len(evidence['diagnostics'][0]['message']) == validation.MAX_DIAGNOSTIC_CHARS
    assert len(json.dumps(evidence)) < 2000


def test_oversized_direct_validation_is_unavailable_without_invoking_checker(monkeypatch):
    def forbidden(text):
        pytest.fail('A checker must not run on content above the bound')

    monkeypatch.setattr(validation, '_check_python', forbidden)
    evidence = validation.validate_text('a.py', '#' * (validation.MAX_VALIDATION_BYTES + 1))
    assert evidence['status'] == 'unavailable'
    assert evidence['diagnostics'][0]['code'] == 'validation_size_limit'


def test_validation_does_not_bypass_workspace_permissions(tmp_path):
    workspace = Workspace(tmp_path, validate=True)
    with pytest.raises(PermissionError):
        workspace.call('workspace_write', {'path': 'main.py', 'content': 'value = 1\n'})
    assert not (tmp_path / 'main.py').exists()
    with pytest.raises(PermissionError):
        _write(workspace, '../outside.py', 'value = 1\n')
    with pytest.raises(PermissionError):
        _write(workspace, '.env', 'value = 1\n')
