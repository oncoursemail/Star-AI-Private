from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import asyncio
import json
import pytest
from PIL import Image

from star.media import image_part
from star.memory import Memory
from star.policy import allowed_registry, enforce
from star.github_app import valid_upload_path, GitHubApp
from star.agent import execute, text_size


def schema_tool(name):
    return {"name":name, "description":"fake", "inputSchema":{"type":"object","properties":{"studio_id":{"type":"string"},"datamodel_type":{"type":"string"}},"required":["studio_id"]}}


def test_image_local_bytes():
    with TemporaryDirectory() as d:
        p=Path(d)/"pic.png"
        Image.new("RGB",(10,8),"red").save(p)
        part=image_part(p)
        assert part["image_url"]["url"].startswith("data:image/png;base64,")
        assert text_size([part]) < 1000


def test_reject_large_image():
    with TemporaryDirectory() as d:
        p=Path(d)/"pic.txt";p.write_text("foo")
        with pytest.raises((OSError,ValueError)):
            image_part(p)


def test_scope():
    tools=[schema_tool("script_read"),schema_tool("execute_luau"),schema_tool("not_allowed")]
    reg=allowed_registry(tools,False)
    assert list(reg)==["script_read"]
    enforce("script_read",{"studio_id":"abc"},reg,"abc",False)
    with pytest.raises(ValueError):
        enforce("script_read",{"studio_id":"wrong"},reg,"abc",False)
    with pytest.raises(ValueError):
        enforce("execute_luau",{"studio_id":"abc"},reg,"abc",False)


def test_edit_mode_scoped():
    reg=allowed_registry([schema_tool("execute_luau")],True,allow_luau=True)
    with pytest.raises(ValueError):
        enforce("execute_luau",{"studio_id":"abc","datamodel_type":"Play"},reg,"abc",True,allow_luau=True)
    enforce("execute_luau",{"studio_id":"abc","datamodel_type":"Edit"},reg,"abc",True,allow_luau=True)


def test_memory_scope_and_persistence():
    with TemporaryDirectory() as d:
        db=Path(d)/"memory.sqlite3"
        m=Memory(db);m.put("VALEN","use green trees");m.put("BOOBOUND","use ghosts");m.close()
        m=Memory(db)
        assert m.get("VALEN")=="use green trees"
        assert m.get("BOOBOUND")=="use ghosts"
        assert m.get("unknown")==""
        m.close()


def test_github_paths():
    for p in ("star/skills/tween_helpers.py","docs/skills/tween_helpers.md"):
        assert valid_upload_path(p)
    for p in ("star/agent.py","docs/readme.md","tests/test_star.py","README.md",
              ".env", "runs/secret.txt", "star/../../secrets.py", ".github/workflows/tests.yml", "private.pem", "star/script.exe", "star/secret.key"):
        assert not valid_upload_path(p)


def test_github_app_parameters_fail_closed():
    with pytest.raises(ValueError):
        GitHubApp("abc","1",Path("missing.pem"),"person/repo")


class FakeModels:
    def __init__(self, responses):
        self.responses=responses;self.requests=[]
    async def create(self, **kwargs):
        self.requests.append(kwargs)
        if not self.responses:
            raise AssertionError("No more model responses")
        return self.responses.pop(0)


def reply(content=None, calls=None):
    m=SimpleNamespace(content=content,tool_calls=calls)
    return SimpleNamespace(choices=[SimpleNamespace(message=m)])


def call(name, arguments):
    return SimpleNamespace(id="id1", function=SimpleNamespace(name=name,arguments=json.dumps(arguments)))


class FakeStudio:
    def __init__(self):
        self.calls=[]
    async def call_tool(self, name, arguments):
        self.calls.append((name,arguments))
        return SimpleNamespace(model_dump=lambda **kwargs: {"content":[{"type":"text","text":"observed object"}],"isError":False})


def test_local_agent_answer():
    async def run():
        fake=SimpleNamespace(chat=SimpleNamespace(completions=FakeModels([reply("STAR ready")])) )
        answer, transcript, _=await execute(client=fake,model="local",prompt="hello",image_paths=[])
        assert answer == "STAR ready"
        assert transcript[1]["role"]=="user"
        assert [i for i,m in enumerate(transcript) if m["role"]=="system"] == [0]
    asyncio.run(run())


def test_agent_automatic_tool_without_permission_prompt():
    async def run():
        fake_studio=FakeStudio()
        fake=SimpleNamespace(chat=SimpleNamespace(completions=FakeModels([
            reply(calls=[call("script_read",{"studio_id":"sandbox"})]), reply("I inspected the script")])) )
        answer, _, _ = await execute(client=fake, model="local",prompt="inspect",image_paths=[],
            studio=fake_studio,studio_id="sandbox",discovered=[schema_tool("script_read")])
        assert answer=="I inspected the script"
        assert len(fake_studio.calls)==1
    asyncio.run(run())


def test_agent_blocks_wrong_studio_even_in_auto_mode():
    async def run():
        fake_studio=FakeStudio()
        fake=SimpleNamespace(chat=SimpleNamespace(completions=FakeModels([
            reply(calls=[call("execute_luau",{"studio_id":"other","datamodel_type":"Edit"})]), reply("blocked")])) )
        answer, _, _ = await execute(client=fake,model="local",prompt="change",image_paths=[],
            studio=fake_studio,studio_id="sandbox",may_edit=True,discovered=[schema_tool("execute_luau")])
        assert answer == (
            "blocked\n\n**Recorded verification status:** "
            "1 requested action(s) were rejected before execution. "
            "Those requests did not run; a later separately authorized request has its own result."
        )
        assert not fake_studio.calls
    asyncio.run(run())


def test_qwen_chat_template_has_one_first_system_message():
    """Regression: Qwen3.5 Jinja returns HTTP 500 for a later system role."""
    async def run():
        responder=FakeModels([reply("It works")])
        client=SimpleNamespace(chat=SimpleNamespace(completions=responder))
        answer, _, _=await execute(client=client,model="qwen-local",prompt="hello",
            image_paths=[],project_memory="old project notes")
        assert answer=="It works"
        messages=responder.requests[0]["messages"]
        assert [i for i,m in enumerate(messages) if m["role"]=="system"]==[0]
        assert "old project notes" in messages[0]["content"]
        assert messages[1]["role"]=="user"
    asyncio.run(run())


def test_qwen_compaction_never_adds_second_system(monkeypatch):
    import star.agent as agent
    updates=[]
    async def pretend_compact(client,model,project,prior,history):
        assert history and all(msg["role"]!="system" for msg in history)
        return "Verified task checkpoint after inspecting a Studio script"
    monkeypatch.setattr(agent,"compact",pretend_compact)
    async def run():
        class LongScriptStudio(FakeStudio):
            async def call_tool(self, name, arguments):
                return SimpleNamespace(model_dump=lambda **kwargs: {
                    "content": [{"type": "text", "text": "observed script\n" * 800}], "isError": False})
        model=FakeModels([
            reply(calls=[call("script_read",{"studio_id":"sandbox"})]),
            reply("Finished inspection"),
        ])
        client=SimpleNamespace(chat=SimpleNamespace(completions=model))
        answer,messages,archive=await execute(client=client,model="qwen-local",
            prompt="inspect script",image_paths=[],studio=LongScriptStudio(),
            studio_id="sandbox",discovered=[schema_tool("script_read")],
            context_chars=6000,checkpoint=lambda summary:updates.append(summary))
        assert answer=="Finished inspection"
        assert updates and archive
        for request in model.requests:
            assert [i for i,m in enumerate(request["messages"]) if m["role"]=="system"]==[0]
        # The checkpoint travels in a later user turn; the one system message is not
        # rewritten, so the server's cached start of the request survives compaction.
        before,after=(request["messages"] for request in model.requests)
        assert after[0]==before[0] and after[1]==before[1]
        assert "Verified task checkpoint" not in after[0]["content"]
        assert after[-1]["role"]=="user" and "Verified task checkpoint" in after[-1]["content"]
        assert messages[0]==before[0]
    asyncio.run(run())


def test_model_roles_validate_locally():
    from star.agent import validate_model_roles
    with pytest.raises(ValueError,match="one system message"):
        validate_model_roles([{"role":"system"},{"role":"system"},{"role":"user"}])
    with pytest.raises(ValueError,match="one system message"):
        validate_model_roles([{"role":"user"},{"role":"system"}])



def test_plain_chat_streams_visible_deltas_without_exposing_reasoning():
    async def streaming_reply():
        for item in ['STAR ', 'is ', 'working.']:
            yield SimpleNamespace(choices=[SimpleNamespace(delta=SimpleNamespace(
                content=item, reasoning_content='private reasoning not for display'))])
    async def run():
        calls=[]
        class StreamingModels:
            async def create(self, **kwargs):
                calls.append(kwargs)
                return streaming_reply()
        events=[]
        fake=SimpleNamespace(chat=SimpleNamespace(completions=StreamingModels()))
        answer, messages, _=await execute(client=fake, model='local', prompt='say hi',
            image_paths=[], stream_tokens=True, on_event=events.append)
        assert answer=='STAR is working.'
        assert calls[0]['stream'] is True
        streamed=''.join(e['text'] for e in events if e.get('event')=='assistant_delta')
        assert streamed==answer
        assert 'private reasoning' not in streamed
        assert messages[-1]['role']=='assistant'
    asyncio.run(run())


def test_stream_rejection_falls_back_to_nonstream_response():
    class UnsupportedStream(Exception):
        status_code=400
    async def run():
        calls=[]
        class ConditionalModels:
            async def create(self, **kwargs):
                calls.append(kwargs)
                if kwargs.get('stream'):
                    raise UnsupportedStream('stream unsupported')
                return reply('Fallback response')
        fake=SimpleNamespace(chat=SimpleNamespace(completions=ConditionalModels()))
        answer, messages, _=await execute(client=fake,model='local',prompt='hello',
            image_paths=[],stream_tokens=True)
        assert answer=='Fallback response'
        assert len(calls)==2
        assert calls[0]['stream'] is True and not calls[1].get('stream')
    asyncio.run(run())


from star.selfbuild import skill_path, read_source, write_source


def test_self_build_scope():
    for p in ("star/skills/luau_quality.py", "docs/skills/animation_notes.md"):
        assert skill_path(p)
    for p in ("star/policy.py", "star/agent.py", "star/skills/../../policy.py", ".env", "tests/test_star.py", "docs/secret.pem", "star/skills/../agent.py"):
        assert not skill_path(p)


def test_self_build_code_syntax_only():
    with TemporaryDirectory() as d:
        root=Path(d)
        assert "syntax check" in write_source(root, "star/skills/example.py", "def good():\n    return 1\n")
        assert "return 1" in read_source(root,"star/skills/example.py")
        with pytest.raises(SyntaxError):
            write_source(root,"star/skills/bad.py","def missing(: pass")
        assert not (root/"star/skills/bad.py").exists()


def test_self_build_symlink_escape():
    with TemporaryDirectory() as d, TemporaryDirectory() as outside:
        root=Path(d)
        (root/"star").mkdir()
        try:
            (root/"star"/"skills").symlink_to(Path(outside), target_is_directory=True)
        except (OSError, NotImplementedError):
            pytest.skip("OS does not allow symlink")
        with pytest.raises(ValueError):
            write_source(root,"star/skills/leak.py","pass")

from star.selfbuild import develop, run_git


def test_self_build_end_to_end_offline_git_branch():
    async def scenario(root: Path):
        skill=Path(root)/"star"/"skills"
        docs=Path(root)/"docs"
        skill.mkdir(parents=True)
        docs.mkdir()
        (skill/"__init__.py").write_text("",encoding="utf8")
        (root/"README.md").write_text("# empty test repo",encoding="utf8")
        run_git("init",cwd=root)
        run_git("add",".",cwd=root)
        run_git("-c","user.name=Test","-c","user.email=test@example.com","commit","-m","base",cwd=root)
        fake=SimpleNamespace(chat=SimpleNamespace(completions=FakeModels([
            reply(calls=[call("write_skill_file",{"path":"star/skills/new_skill.py","content":"def help_luau():\n    return 'Luau'\n"})]),
            reply("Created initial skill")
        ])))
        result=await develop(client=fake,model="local",repository=root,task="Add a tiny skill")
        assert "star/skills/new_skill.py" in result["files"]
        assert result["branch"].startswith("star/skill-")
        assert "NOT been executed" in result["verification"]
        assert not (root/"star/skills/new_skill.py").exists()  # changes isolated in branch
        assert run_git("branch", "--list", result["branch"], cwd=root).strip()
    with TemporaryDirectory() as d:
        asyncio.run(scenario(Path(d)))


def test_unrestricted_luau_not_exposed_in_default_edit_mode():
    assert not allowed_registry([schema_tool("execute_luau")], True)
    with pytest.raises(ValueError):
        allowed_registry([schema_tool("execute_luau")], False, allow_luau=True)
