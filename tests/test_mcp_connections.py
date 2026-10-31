"""Offline STAR MCP tests: protocol negotiation, security, tool grants and UI-facing status.

All remote calls use in-process httpx.MockTransport. Passing these tests does
NOT certify a real Obsidian/Graphify installation or Windows GPU runtime.
"""
from __future__ import annotations

import asyncio
from pathlib import Path
import json
from types import SimpleNamespace

import httpx
import pytest
from jsonschema.exceptions import ValidationError

from star.agent import execute
from star.desktop_core import Settings
from star.mcp_connections import (
    LEGACY, MODERN, MCPGateway, Server, StreamableHTTP, TOOLS, check_destination,
    decode_reply, extra_headers, header_value, presets, valid_schema,
)


def reply(ident: str, result: dict, headers=None):
    return httpx.Response(200, headers={"Content-Type": "application/json", **(headers or {})},
                          json={"jsonrpc": "2.0", "id": ident, "result": result})


def docs_handler(request: httpx.Request) -> httpx.Response:
    body = json.loads(request.content)
    assert request.url == "https://graphify.com/api/mcp"
    assert request.headers["mcp-protocol-version"] == MODERN
    assert request.headers["mcp-method"] == body["method"]
    assert request.headers["accept"] == "application/json, text/event-stream"
    assert body["params"]["_meta"]["io.modelcontextprotocol/protocolVersion"] == MODERN
    assert "authorization" not in request.headers
    if body["method"] == "tools/list":
        return reply(body["id"], {
            "resultType": "complete",
            "tools": [
                {"name": "search_graphify_docs", "description": "Search indexed Graphify docs",
                 "inputSchema": {"type": "object", "properties": {
                     "query": {"type": "string"}}, "required": ["query"], "additionalProperties": False}},
                {"name": "delete_everything", "description": "Dangerous write",
                 "inputSchema": {"type": "object", "properties": {}}},
            ],
        })
    assert body["method"] == "tools/call"
    assert request.headers["mcp-name"] == "search_graphify_docs"
    assert body["params"]["arguments"]["query"] == "graphify"
    return reply(body["id"], {"resultType": "complete", "isError": False,
                              "content": [{"type": "text", "text": "Graphify docs reference found"}]})


def factory(handler):
    return lambda server: StreamableHTTP(server, transport=httpx.MockTransport(handler))


def task_settings(**kw):
    return SimpleNamespace(mcp_graphify_docs=kw.get("mcp_graphify_docs", True),
                           mcp_graphify_local=kw.get("mcp_graphify_local", False),
                           mcp_graphify_port=kw.get("mcp_graphify_port", 8931),
                           mcp_obsidian_live=kw.get("mcp_obsidian_live", False))


def test_modern_mcp_live_discovery_and_task_scoped_calls():
    async def run():
        gateway = MCPGateway(task_settings(), factory=factory(docs_handler))
        assert not gateway.definitions("Good morning")
        assert {s["name"] for s in gateway.definitions("Use my MCP connection to search docs")} == {
            "star_mcp_search", "star_mcp_call"}
        state = gateway.status()
        assert state["servers"][0]["state"] == "configured_not_tested"
        assert state["servers"][0]["read_only"] is True
        result = await gateway.search("graphify docs", limit=2)
        assert [x["tool"] for x in result["tools"]] == ["search_graphify_docs"]
        assert "delete_everything" not in repr(result)
        assert result["tools"][0]["source"] == "https://graphify.com/api/mcp"
        got = await gateway.call("star_mcp_call", {
            "server": "graphify_docs", "tool": "search_graphify_docs",
            "arguments": {"query": "graphify"},
        })
        assert "Graphify docs reference" in got["result"]["output"]
        assert got["result"]["untrusted"] is True
    asyncio.run(run())


def test_no_remote_call_without_discovery_and_invalid_args_blocked():
    async def run():
        gateway = MCPGateway(task_settings(), factory=factory(docs_handler))
        with pytest.raises(PermissionError):
            await gateway.call("star_mcp_call", {
                "server": "graphify_docs", "tool": "search_graphify_docs",
                "arguments": {"query": "graphify"},
            })
        await gateway.search("graphify")
        with pytest.raises(ValidationError):
            await gateway.call("star_mcp_call", {
                "server": "graphify_docs", "tool": "search_graphify_docs",
                "arguments": {"bad": "key"},
            })
        with pytest.raises(PermissionError):
            await gateway.call("star_mcp_call", {
                "server": "graphify_docs", "tool": "delete_everything",
                "arguments": {},
            })
    asyncio.run(run())


def test_mcp_graphify_legacy_handshake_session_and_sse():
    sequence: list[str] = []
    def handler(request: httpx.Request):
        body = json.loads(request.content)
        method = body["method"]
        sequence.append(method)
        assert request.url == "http://127.0.0.1:8931/mcp"
        assert request.headers["mcp-protocol-version"] == LEGACY
        if method == "initialize":
            assert request.headers.get("mcp-session-id") is None
            return reply(body["id"], {"protocolVersion": LEGACY,
                                       "capabilities": {"tools": {}},
                                       "serverInfo": {"name": "graphify", "version": "1"}},
                         {"Mcp-Session-Id": "test-session"})
        assert request.headers["mcp-session-id"] == "test-session"
        assert method in {"notifications/initialized", "tools/list", "tools/call"}
        assert "Mcp-Method" not in request.headers
        if method == "notifications/initialized":
            assert "id" not in body
            return httpx.Response(202)
        if method == "tools/list":
            data = {"jsonrpc": "2.0", "id": body["id"], "result": {
                "tools": [{"name": "query_graph", "description": "Find nodes",
                           "inputSchema": {"type": "object",
                                           "properties": {"query": {"type": "string"}},
                                           "required": ["query"]}},
                          {"name": "delete_graph", "inputSchema": {"type": "object"}}]}}
            return httpx.Response(200, headers={"Content-Type": "text/event-stream"},
                                  text="event: message\ndata: " + json.dumps(data) + "\n\n")
        return reply(body["id"], {"content": [{"type": "text", "text": "graph paths"}]})
    async def run():
        gateway = MCPGateway(task_settings(mcp_graphify_docs=False, mcp_graphify_local=True),
                             factory=factory(handler))
        found = await gateway.search("query graph")
        assert [x["tool"] for x in found["tools"]] == ["query_graph"]
        answer = await gateway.call("star_mcp_call", {
            "server": "graphify_local", "tool": "query_graph",
            "arguments": {"query": "main"},
        })
        assert "graph paths" in answer["result"]["output"]
        assert sequence == [
            "initialize", "notifications/initialized", "tools/list",
            "initialize", "notifications/initialized", "tools/call"]
    asyncio.run(run())


def test_modern_headers_include_primitive_tool_params_and_sanitize_unicode():
    schema = {"type": "object", "properties": {
        "query": {"type": "string", "x-mcp-header": "Search-Term"},
        "limit": {"type": "integer", "x-mcp-header": "Max-Items"},
        "active": {"type": "boolean", "x-mcp-header": "Verbose"}}}
    observed = {}
    def handler(request: httpx.Request):
        body = json.loads(request.content)
        if body["method"] == "tools/list":
            return reply(body["id"], {"tools": [{
                "name": "search_graphify_docs", "description": "Search docs",
                "inputSchema": schema}]})
        observed.update(dict(request.headers))
        return reply(body["id"], {"content": [{"type": "text", "text": "ok"}]})
    async def run():
        gateway = MCPGateway(task_settings(), factory=factory(handler))
        await gateway.search("graphify docs")
        await gateway.call("star_mcp_call", {
            "server": "graphify_docs", "tool": "search_graphify_docs",
            "arguments": {"query": "über", "limit": 4, "active": True}})
    asyncio.run(run())
    assert observed["mcp-param-search-term"].startswith("=?base64?")
    assert observed["mcp-param-max-items"] == "4"
    assert observed["mcp-param-verbose"] == "true"
    assert header_value("ASCII") == "ASCII"


def test_security_malformed_remote_schema_and_header_are_rejected():
    assert valid_schema({"type": "object", "properties": {
        "x": {"$ref": "http://dangerous"}}}) is None
    assert valid_schema({"type": "array"}) is None
    assert valid_schema({"type": "object", "properties": {
        "a": {"type": "string", "x-mcp-header": "bad\nHeader"}}}) is None
    with pytest.raises(ValueError):
        extra_headers({"type": "object", "properties": {
            "a": {"type": "string", "x-mcp-header": "A"},
            "b": {"type": "string", "x-mcp-header": "a"}}}, {})
    # Modern MCP supports exact nested property paths; nested values are
    # mirrored only when present and preserve their declared primitive type.
    annotated = {"type": "object", "properties": {
        "a": {"type": "object", "properties": {
            "b": {"type": "string", "x-mcp-header": "B"}}}}}
    assert extra_headers(annotated, {"a": {"b": "nested"}}) == {
        "Mcp-Param-B": "nested"}
    assert valid_schema({"type": "object", "properties": {
        "a": {"type": "string", "x-mcp-header": "Safe-Name"}}}) is not None


def test_destinations_lock_host_path_protocol_and_port():
    for server in [
        Server("graphify_docs", "wrong", "http://evil.example/mcp", MODERN, frozenset()),
        Server("graphify_docs", "wrong", "https://graphify.com.evil/mcp", MODERN, frozenset()),
        Server("graphify_local", "wrong", "http://127.0.0.1:22/mcp", LEGACY, frozenset()),
        Server("obsidian_live", "wrong", "https://localhost:27124/mcp/", MODERN, frozenset()),
        Server("anything", "wrong", "https://graphify.com/api/mcp", MODERN, frozenset()),
    ]:
        with pytest.raises(PermissionError):
            check_destination(server)
    with pytest.raises(ValueError):
        presets(task_settings(mcp_graphify_local=True, mcp_graphify_port=True))


def test_unauthorized_credentials_are_not_returned(monkeypatch):
    monkeypatch.delenv("STAR_OBSIDIAN_MCP_TOKEN", raising=False)
    server = presets(task_settings(mcp_graphify_docs=False, mcp_obsidian_live=True))[0]
    with pytest.raises(PermissionError):
        StreamableHTTP(server)._options()
    monkeypatch.setenv("STAR_OBSIDIAN_MCP_TOKEN", "super-private-token")
    gateway = MCPGateway(task_settings(mcp_graphify_docs=False, mcp_obsidian_live=True))
    state = gateway.status()
    assert next(item for item in state["servers"] if item["name"] == "obsidian_live")["credential_ready"] is True
    assert "super-private-token" not in repr(state)
    monkeypatch.setenv("STAR_OBSIDIAN_MCP_CA_BUNDLE", "/no/such/certificate.crt")
    with pytest.raises(ValueError):
        StreamableHTTP(server)._options()


def test_redirect_and_auth_failures_have_no_response_body_leakage():
    def handler(request):
        return httpx.Response(307, headers={"Location": "https://evil.example/steal"},
                              text="SECRET RESPONSE BODY")
    async def run():
        gateway = MCPGateway(task_settings(), factory=factory(handler))
        outcome = await gateway.search("graphify docs")
        assert outcome["tools"] == []
        assert "graphify_docs" in outcome["connector_errors"]
        assert "SECRET" not in repr(outcome)
    asyncio.run(run())


def test_bad_rpc_ids_content_types_and_sse_are_rejected():
    with pytest.raises(ValueError):
        decode_reply(b'{"jsonrpc":"2.0","id":"wrong","result":{}}',
                     "application/json", "correct")
    with pytest.raises(ValueError):
        decode_reply(b"unsafe", "text/html", "id")
    valid = b'event: message\ndata: {"jsonrpc":"2.0","id":"yes","result":{"tools":[]}}\n\n'
    assert decode_reply(valid, "text/event-stream", "yes")["result"] == {"tools":[]}
    with pytest.raises(ValueError):
        decode_reply(valid, "text/event-stream", "no")


def test_disabled_mcp_does_not_use_network_or_affect_plain_streaming():
    gateway = MCPGateway(task_settings(mcp_graphify_docs=False))
    assert gateway.definitions("use MCP connector") == []
    assert not gateway.status()["servers"][0]["enabled"]
    assert gateway.status()["servers"][0]["state"] == "disabled"


def test_mcp_settings_persist_and_validate(tmp_path: Path):
    file = tmp_path / "settings.json"
    settings = Settings()
    assert not settings.mcp_graphify_docs
    assert not settings.mcp_obsidian_live
    assert settings.mcp_graphify_port == 8931
    settings.mcp_graphify_local = True
    settings.mcp_graphify_port = 8935
    settings.save(file)
    back = Settings.load(file)
    assert back.mcp_graphify_local and back.mcp_graphify_port == 8935
    back.mcp_graphify_port = 21
    with pytest.raises(ValueError):
        back.validate()
    back.mcp_graphify_port = 8931
    back.mcp_obsidian_live = "true"
    with pytest.raises(ValueError):
        back.validate()


def test_real_agent_loop_discovers_then_calls_mock_mcp():
    class Model:
        def __init__(self):
            self.seen = []
        async def create(self, **kwargs):
            self.seen.append(kwargs)
            n = len(self.seen)
            if n == 1:
                name, arguments = "star_mcp_search", {"query": "graphify docs"}
            elif n == 2:
                name, arguments = "star_mcp_call", {
                    "server": "graphify_docs", "tool": "search_graphify_docs",
                    "arguments": {"query": "graphify"}}
            else:
                return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(
                    content="The verified docs mention Graphify.", tool_calls=None))])
            call = SimpleNamespace(id=str(n), function=SimpleNamespace(
                name=name, arguments=json.dumps(arguments)))
            return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(
                content="", tool_calls=[call]))])
    async def run():
        model = Model()
        client = SimpleNamespace(chat=SimpleNamespace(completions=model))
        gateway = MCPGateway(task_settings(), factory=factory(docs_handler))
        answer, conversation, _ = await execute(
            client=client, model="local", prompt="Please use MCP to search Graphify docs",
            image_paths=[], mcp_gateway=gateway)
        assert "verified docs" in answer
        assert [m["role"] for m in conversation].count("system") == 1
        assert [m["role"] for m in conversation].count("tool") == 2
        assert "star_mcp_search" in [x["function"]["name"] for x in model.seen[0]["tools"]]
    asyncio.run(run())


def test_remote_tool_errors_are_nonfatal_to_model():
    def handler(request):
        body = json.loads(request.content)
        if body["method"] == "tools/list":
            return reply(body["id"], {"tools": [{
                "name": "search_graphify_docs", "description": "Docs",
                "inputSchema": {"type": "object", "properties": {}}}]})
        return httpx.Response(401, text="private-token-leak-not-visible")
    async def run():
        gateway = MCPGateway(task_settings(), factory=factory(handler))
        await gateway.search("graphify")
        with pytest.raises(PermissionError):
            await gateway.call("star_mcp_call", {
                "server": "graphify_docs", "tool": "search_graphify_docs",
                "arguments": {},
            })
    asyncio.run(run())


def test_readonly_hint_contradiction_blocks_even_a_known_tool_name():
    def handler(request: httpx.Request):
        body = json.loads(request.content)
        return reply(body["id"], {"tools": [{
            "name": "search_graphify_docs",
            "annotations": {"readOnlyHint": False},
            "description": "Pretends to be safe but writes state",
            "inputSchema": {"type": "object", "properties": {}}}]})
    async def run():
        gateway = MCPGateway(task_settings(), factory=factory(handler))
        result = await gateway.search("graphify docs")
        assert result["tools"] == []
        with pytest.raises(PermissionError):
            await gateway.call("star_mcp_call", {
                "server": "graphify_docs", "tool": "search_graphify_docs",
                "arguments": {},
            })
    asyncio.run(run())


def test_re_discovery_revokes_stale_mcp_tool_grants():
    observations = {"catalog_calls": 0}
    def handler(request: httpx.Request):
        body = json.loads(request.content)
        observations["catalog_calls"] += 1
        tools = [{
            "name": "search_graphify_docs",
            "description": "Graphify docs",
            "inputSchema": {"type": "object", "properties": {}},
        }] if observations["catalog_calls"] == 1 else []
        return reply(body["id"], {"tools": tools})
    async def run():
        gateway = MCPGateway(task_settings(), factory=factory(handler))
        initial = await gateway.search("graphify docs")
        assert len(initial["tools"]) == 1
        second = await gateway.search("graphify docs")
        assert second["tools"] == []
        with pytest.raises(PermissionError):
            await gateway.call("star_mcp_call", {
                "server": "graphify_docs", "tool": "search_graphify_docs",
                "arguments": {},
            })
    asyncio.run(run())
