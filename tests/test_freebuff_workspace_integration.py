"""Optional batch discovery through the actual agent catalogue and dispatcher."""
from __future__ import annotations

import asyncio
import copy
import json
from types import SimpleNamespace

import pytest

from star.agent import execute
from star.workspace import BATCH_SEARCH_TOOL, TOOLS, Workspace, tool_definitions


@pytest.fixture(autouse=True)
def default_off(monkeypatch):
    monkeypatch.delenv('STAR_CODE_SEARCH_BATCH', raising=False)


class ScriptedClient:
    def __init__(self, *, ask_batch=False, revoke=None):
        self.requests = []
        self.chat = SimpleNamespace(completions=self)
        self.ask_batch, self.revoke = ask_batch, revoke

    async def create(self, **kwargs):
        self.requests.append(copy.deepcopy(kwargs))
        calls = []
        if self.ask_batch and len(self.requests) == 1:
            if self.revoke is not None:
                self.revoke()
            calls = [SimpleNamespace(id='search-1', function=SimpleNamespace(
                name='workspace_search_batch', arguments=json.dumps({'queries': [
                    {'query': 'inventory', 'mode': 'symbols'}, {'query': 'return'}]})))]
        return SimpleNamespace(choices=[SimpleNamespace(
            message=SimpleNamespace(content='' if calls else 'Finished.', tool_calls=calls),
            finish_reason='stop')])


def run(client, workspace=None):
    return asyncio.run(execute(
        client=client, model='offline-scripted', prompt='Find the inventory implementation.',
        image_paths=[], workspace=workspace, context_chars=100_000,
        complete_code_answers=False, now=''))


def offered(client):
    return {tool['function']['name'] for tool in client.requests[0].get('tools', [])}


def test_default_catalogue_and_existing_schema_are_unchanged(tmp_path):
    assert tool_definitions() == TOOLS
    client = ScriptedClient()
    run(client, Workspace(tmp_path))
    assert BATCH_SEARCH_TOOL['name'] not in offered(client)
    with pytest.raises(PermissionError, match='switched off'):
        Workspace(tmp_path).call('workspace_search_batch', {'queries': [{'query': 'x'}]})


def test_enabled_catalogue_requires_workspace_and_does_not_mutate_default(monkeypatch, tmp_path):
    original = copy.deepcopy(TOOLS)
    monkeypatch.setenv('STAR_CODE_SEARCH_BATCH', 'on')
    assert tool_definitions()[-1] == BATCH_SEARCH_TOOL
    assert TOOLS == original
    client = ScriptedClient()
    run(client)
    assert 'workspace_search_batch' not in offered(client)
    client = ScriptedClient()
    run(client, Workspace(tmp_path))
    assert 'workspace_search_batch' in offered(client)


def test_live_agent_dispatch_returns_both_searches_without_writes(monkeypatch, tmp_path):
    monkeypatch.setenv('STAR_CODE_SEARCH_BATCH', 'on')
    source = tmp_path / 'inventory.py'
    source.write_text('def inventory():\n    return 1\n', encoding='utf-8')
    before = source.read_bytes()
    client = ScriptedClient(ask_batch=True)
    run(client, Workspace(tmp_path))
    messages = [m for m in client.requests[1]['messages'] if m['role'] == 'tool']
    assert len(messages) == 1 and messages[0]['tool_call_id'] == 'search-1'
    receipt = json.loads(messages[0]['content'])
    assert receipt['isError'] is False
    output = json.loads(receipt['output'])
    assert len(output['results']) == 2
    assert output['results'][0]['matches'][0]['name'] == 'inventory'
    assert output['results'][1]['matches'][0]['line'] == 2
    assert source.read_bytes() == before
    assert 'workspace_write' not in offered(client)


def test_revocation_after_model_request_still_refuses_dispatch(monkeypatch, tmp_path):
    monkeypatch.setenv('STAR_CODE_SEARCH_BATCH', 'on')
    client = ScriptedClient(ask_batch=True, revoke=lambda: monkeypatch.delenv('STAR_CODE_SEARCH_BATCH'))
    run(client, Workspace(tmp_path))
    message = next(m for m in client.requests[1]['messages'] if m['role'] == 'tool')
    receipt = json.loads(message['content'])
    assert receipt['isError'] is True
    assert 'switched off' in receipt['output']


def test_revocation_during_schema_validation_refuses_before_scan(monkeypatch, tmp_path):
    import jsonschema
    monkeypatch.setenv('STAR_CODE_SEARCH_BATCH', 'on')
    original = jsonschema.validate

    def revoking(*args, **kwargs):
        original(*args, **kwargs)
        monkeypatch.delenv('STAR_CODE_SEARCH_BATCH')

    monkeypatch.setattr(jsonschema, 'validate', revoking)
    with pytest.raises(PermissionError, match='switched off'):
        Workspace(tmp_path).call('workspace_search_batch', {'queries': [{'query': 'inventory'}]})


@pytest.mark.parametrize('args', [
    {'queries': []}, {'queries': [{'query': 'x'}] * 9},
    {'queries': [{'query': 'x', 'mode': 'map'}]},
    {'queries': [{'query': 'x'}], 'allow_write': True},
    {'queries': [{'query': 'x', 'path': '..'}]},
])
def test_batch_schema_rejects_invalid_arguments(monkeypatch, tmp_path, args):
    monkeypatch.setenv('STAR_CODE_SEARCH_BATCH', 'on')
    with pytest.raises(ValueError):
        Workspace(tmp_path).call('workspace_search_batch', args)
