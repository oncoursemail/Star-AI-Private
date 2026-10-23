"""Turn-local, evidence-driven recovery at authorized tool boundaries.

This controller never executes tools, expands permissions, changes model
weights, or certifies a task. It steers the existing bounded agent loop using
observed failures and narrowly scoped, fresh checks of workspace writes.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import re
from typing import Any, Callable


MAX_REPAIR_ATTEMPTS = 2
_SHA256 = re.compile(r'^[0-9a-f]{64}$')
_PARSERS = frozenset({'python.compile', 'json.loads', 'tomllib.loads'})

# Recovery instructions are attached only to observed issues below. Adding an
# unconditional rule block would consume healthy-turn context and can cause
# unnecessary compaction calls or reject an otherwise fitting request.


@dataclass
class _Issue:
    kind: str
    checker: str
    resource: str = ''
    attempts: int = 0
    digest: str = ''
    blocked: bool = False


class RepairDeferred(Exception):
    """A request was not executed; feedback may be returned as a tool result."""

    def __init__(self, feedback: dict[str, Any]):
        super().__init__(feedback['instruction'])
        self.feedback = feedback


def _call_key(name: str, args: dict[str, Any]) -> tuple[str, str]:
    # Keep bounded fingerprints, not copies of potentially sensitive arguments.
    encoded = json.dumps(args, sort_keys=True, ensure_ascii=False, separators=(',', ':')).encode('utf-8')
    return name, hashlib.sha256(encoded).hexdigest()


def _outcome_key(name: str, args: dict[str, Any], group: str, resource: str,
                 mutation: bool) -> tuple[str, str]:
    # A corrected edit request for this exact local file can recover a failed
    # edit match even though its old/new strings changed. Unrelated file writes
    # and successful reads never clear it. Other tools require the exact call.
    if mutation and group == 'workspace' and resource:
        return 'workspace_mutation', resource
    return _call_key(name, args)


class RepairController:
    """At most two corrective calls per unresolved file/call in one user turn.

    The enclosing agent still owns authorization, cancellation, and overall
    model/tool budgets. Call ``before_call`` only after existing authorization.
    Only pass ``workspace_result`` from the local workspace dispatcher: an
    external tool's nested JSON must never become trusted validation evidence.
    """

    def __init__(self, event: Callable[[dict], None]):
        self._event = event
        self._files: dict[str, _Issue] = {}
        self._tools: dict[tuple[str, str], _Issue] = {}
        self._ambiguous_groups: set[str] = set()
        self._advisories: dict[str, str] = {}
        self._completion_prompts = 0
        self._rejected_requests = 0

    def _emit(self, event: str, issue: _Issue, count: int = 1) -> None:
        # User-visible callbacks carry host enums/counts only, never paths,
        # diagnostics, code, arguments, model text, or private reasoning.
        self._event({'event': event, 'kind': issue.kind, 'checker': issue.checker,
                     'count': min(100, max(0, count)), 'attempt': issue.attempts})

    @staticmethod
    def _feedback(issue: _Issue, status: str, instruction: str) -> dict[str, Any]:
        return {'status': status, 'kind': issue.kind, 'checker': issue.checker,
                'attempt': issue.attempts, 'max_attempts': MAX_REPAIR_ATTEMPTS,
                'instruction': instruction}

    def _defer(self, issue: _Issue, instruction: str) -> None:
        self._emit('repair_blocked', issue)
        raise RepairDeferred(self._feedback(issue, 'not_executed', instruction))

    def _unavailable(self, resource: str, checker: str = 'none', digest: str = '') -> tuple[dict, bool]:
        issue = self._files.get(resource) or _Issue('syntax', checker, resource)
        issue.blocked = True
        if digest:
            issue.digest = digest
        self._files[resource] = issue
        self._emit('repair_blocked', issue)
        return self._feedback(issue, 'unverified',
                              'The file was saved, but its syntax checker could not provide a valid result. '
                              'This is unavailable evidence, not a proven code defect or a passing check. '
                              'Do not keep changing the file merely to satisfy an unavailable checker.'), True

    def rejected(self) -> None:
        """Record a known non-execution without inviting a permission workaround."""
        self._rejected_requests += 1
        self._emit('repair_blocked', _Issue('tool_error', 'tool.result', blocked=True))

    def before_call(self, name: str, args: dict[str, Any], *, mutation: bool,
                    group: str, resource: str = '', batch_paused: bool = False) -> None:
        """Defer queued writes and refuse repeated or uncertain mutations."""
        if mutation and group in self._ambiguous_groups:
            self._defer(_Issue('unknown_outcome', 'tool.result'),
                        'An earlier mutation in this tool group has an unknown outcome. '
                        'This action was not executed. Inspect state with read-only tools and report '
                        'the uncertainty; do not replay or switch write tools to work around it in this turn.')
        if mutation and batch_paused:
            self._defer(_Issue('budget', 'none'),
                        'This queued write was not executed because an earlier action in the batch '
                        'needs attention. Inspect its result, repair the affected part if possible, '
                        'and replan the remaining work in the next model turn.')
        if mutation and group == 'workspace':
            issue = self._files.get(resource)
            active = [value for value in self._files.values() if not value.blocked]
            if active and issue is None:
                self._defer(_Issue('syntax', active[0].checker),
                            'This write was not executed while a different workspace file has an '
                            'unresolved syntax check. Address that recorded diagnostic before adding '
                            'more workspace changes; read-only inspection remains available.')
            if issue is not None:
                if issue.blocked or issue.attempts >= MAX_REPAIR_ATTEMPTS:
                    self._defer(issue, 'The focused repair limit was reached or its checker is unavailable. '
                                'This write was not executed. Preserve the current work, inspect if useful, '
                                'and report the unresolved check; do not bypass this limit with another write tool.')
                if name == 'workspace_write' and isinstance(args.get('content'), str):
                    digest = hashlib.sha256(args['content'].encode('utf-8')).hexdigest()
                    if digest == issue.digest:
                        self._defer(issue, 'This write would repeat the same content that failed the check, '
                                    'so it was not executed. Inspect the diagnostic and make a different, focused edit.')
                issue.attempts += 1
        issue = self._tools.get(_outcome_key(name, args, group, resource, mutation))
        if issue is not None:
            if issue.blocked or issue.attempts >= MAX_REPAIR_ATTEMPTS:
                self._defer(issue, 'This unsuccessful call has reached its retry limit or has an unknown outcome. '
                            'It was not executed again. Use new read-only evidence or report it unresolved.')
            issue.attempts += 1

    def observe(self, name: str, args: dict[str, Any], *, is_error: bool,
                mutation: bool, group: str, resource: str = '',
                uncertain: bool = False, workspace_result: dict | None = None) -> tuple[dict | None, bool]:
        """Return concise model feedback and whether later queued writes pause.

        Successful unrelated calls never erase failures. A previous tool error
        recovers only when the same call succeeds. Syntax recovery requires the
        same local checker and a different valid content digest, not a model claim.
        """
        key = _outcome_key(name, args, group, resource, mutation)
        if is_error:
            issue = self._tools.get(key)
            if issue is None:
                issue = _Issue('unknown_outcome' if uncertain else 'tool_error', 'tool.result')
                self._tools[key] = issue
            if mutation and uncertain:
                issue.kind, issue.blocked = 'unknown_outcome', True
                self._ambiguous_groups.add(group)
            self._emit('repair_detected', issue)
            if issue.blocked:
                instruction = ('The tool failed after a mutation may have started; its outcome is unknown. '
                               'Do not repeat it. Inspect current state with authorized read-only tools '
                               'and report what is and is not known.')
            else:
                instruction = ('The tool reported an observed failure. Inspect the diagnostic, correct the '
                               'smallest relevant cause or use a more suitable authorized read-only query, '
                               'then check the result. Do not claim the task is fixed from a successful write alone.')
            return self._feedback(issue, 'unresolved', instruction), True

        issue = self._tools.get(key)
        feedback = None
        if issue is not None and not issue.blocked:
            del self._tools[key]
            self._emit('repair_check_passed', issue)
            feedback = self._feedback(issue, 'call_succeeded',
                                      'The previously unsuccessful call now succeeded. This verifies that '
                                      'call only, not the entire task or the behavior of edited code.')
        if workspace_result is None:
            if mutation and group == 'workspace':
                return self._unavailable(resource)
            return feedback, False
        if not isinstance(workspace_result, dict):
            return self._unavailable(resource)

        validation = workspace_result.get('validation')
        expected_parser = resource.lower().endswith(('.py', '.pyw', '.pyi', '.json', '.toml'))
        if not isinstance(validation, dict) or validation.get('scope') != 'file_syntax':
            if expected_parser or resource in self._files:
                return self._unavailable(resource)
        if isinstance(validation, dict) and validation.get('scope') == 'file_syntax':
            raw_checker, raw_digest = validation.get('checker'), validation.get('content_sha256')
            checker = raw_checker if isinstance(raw_checker, str) else ''
            digest = raw_digest if isinstance(raw_digest, str) else ''
            status = validation.get('status')
            diagnostics = validation.get('diagnostics')
            known_checker = checker in _PARSERS
            valid_digest = bool(_SHA256.fullmatch(digest))
            # Even the local validator may fail or return a malformed report.
            # A fallback/unavailable report must not vanish into a successful write.
            if status == 'unavailable':
                return self._unavailable(resource, checker if known_checker else 'none',
                                         digest if valid_digest else '')
            if known_checker and (not valid_digest or validation.get('runtime_verified') is not False
                                  or not isinstance(diagnostics, list)
                                  or any(not isinstance(item, dict) for item in diagnostics)
                                  or not isinstance(status, str)
                                  or status not in {'passed', 'failed'}
                                  or (status == 'passed' and bool(diagnostics))
                                  or (status == 'failed' and not diagnostics)):
                return self._unavailable(resource, checker, digest if valid_digest else '')
            if expected_parser and not known_checker:
                return self._unavailable(resource)
            if isinstance(checker, str) and checker in _PARSERS and isinstance(digest, str) and _SHA256.fullmatch(digest):
                old = self._files.get(resource)
                if status == 'failed':
                    issue = old or _Issue('syntax', checker, resource)
                    issue.checker, issue.digest = checker, digest
                    self._files[resource] = issue
                    count = len(validation.get('diagnostics', [])) if isinstance(validation.get('diagnostics'), list) else 1
                    self._emit('repair_detected', issue, count)
                    return self._feedback(issue, 'needs_focused_edit',
                                          'The file was saved, but the local syntax check failed on these exact '
                                          'bytes. Use the diagnostic and a small workspace_edit, then inspect '
                                          'the new validation. Keep unrelated edits paused. A baseline comparison '
                                          'is an observation, not proof that this action caused the problem.'), True
                if status == 'passed' and old is not None:
                    if checker == old.checker and digest != old.digest:
                        del self._files[resource]
                        self._emit('repair_check_passed', old)
                        return self._feedback(old, 'check_passed',
                                              'The revised file passed the same local syntax check. Code was '
                                              'not executed; imports, schema constraints, behavior, visual '
                                              'quality and the original task still need relevant verification.'), False
                    return self._feedback(old, 'unresolved',
                                          'This result does not establish a fresh passing check for the recorded '
                                          'failure. Inspect the current file and relevant check before claiming recovery.'), True

        # Preserve the existing Luau checker as advisory evidence. No automatic
        # forced repair or definite-error state is created from heuristic lint.
        if resource.lower().endswith(('.lua', '.luau')):
            findings = workspace_result.get('lint', [])
            if isinstance(findings, list) and findings:
                signature = hashlib.sha256(json.dumps(findings, sort_keys=True).encode('utf-8')).hexdigest()
                if self._advisories.get(resource) != signature:
                    self._advisories[resource] = signature
                    self._emit('repair_detected', _Issue('advisory', 'luau.lint'), len(findings))
                return {'status': 'advisory', 'kind': 'advisory', 'checker': 'luau.lint',
                        'instruction': 'Luau lint reported possible issues. Inspect their applicability; '
                                       'heuristics alone do not prove a defect. Preserve correct code and '
                                       'use a relevant runtime or engine check when available.'}, False
        return feedback, False

    @property
    def unresolved(self) -> bool:
        return bool(self._files or self._tools or self._rejected_requests)

    def completion_prompt(self) -> str:
        """One extra opportunity within the existing model budget, only for syntax.

        A failed external query may have a valid alternative. Do not force an
        unrelated retry or interpret an unavailable service as broken source.
        """
        candidates = [issue for issue in self._files.values()
                      if not issue.blocked and issue.attempts < MAX_REPAIR_ATTEMPTS]
        if not candidates or self._completion_prompts >= 1:
            return ''
        self._completion_prompts += 1
        return ('A local workspace syntax check is still unresolved in the recorded tool results. '
                'Before completing the original task, inspect that diagnostic and make a small authorized '
                'repair if possible, then use its fresh validation. Do not rewrite unrelated files or '
                'claim runtime correctness from syntax alone. If repair cannot be completed, explicitly '
                'report the unresolved check and preserve the existing work.')

    def final_note(self) -> str:
        if not self.unresolved:
            return ''
        count = len(self._files) + len(self._tools)
        parts = []
        if count:
            parts.append(f'{count} check or tool outcome(s) remain unresolved in this turn. '
                         'A successful later write or unrelated call does not verify those outcomes. '
                         'The overall task is not confirmed complete.')
        if self._rejected_requests:
            parts.append(f'{self._rejected_requests} requested action(s) were rejected before execution. '
                         'Those requests did not run; a later separately authorized request has its own result.')
        return '\n\n**Recorded verification status:** ' + ' '.join(parts)


class RepairsOff:
    """Settings > incremental_repair off: no call is deferred, no note is added, streaming is unchanged."""

    unresolved = False

    def rejected(self) -> None:
        pass

    def before_call(self, name: str, args: dict[str, Any], **_: Any) -> None:
        pass

    def observe(self, name: str, args: dict[str, Any], **_: Any) -> tuple[dict | None, bool]:
        return None, False

    def completion_prompt(self) -> str:
        return ''

    def final_note(self) -> str:
        return ''
