import subprocess
import sys
import textwrap
import time

import pytest

from launcher.rc.cli import RcCli
from launcher.rc.errors import RcError
from launcher.rc.proc import CmdResult, SubprocessRunner

from conftest import STEAM_ROOT
from launcher.rc.paths import TOOLS_EXE

ID = "0123456789abcdef0123456789abcdef"


class Scripted:
    def __init__(self, result):
        self.result, self.argv = result, None

    def run(self, argv, *, timeout, cwd=None, cancelled=None):
        self.argv = argv
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


def cli_for(tmp_path, result):
    exe = tmp_path / TOOLS_EXE
    exe.write_bytes(b"x")
    runner = Scripted(result)
    return RcCli(lambda: exe, tmp_path / "state", runner), runner


def test_missing_exe_is_tools_missing(tmp_path):
    cli = RcCli(lambda: None, tmp_path, Scripted(CmdResult(0, "[]")))
    with pytest.raises(RcError) as e:
        cli.list()
    assert e.value.code == "tools_missing"


def test_success_json_and_state_dir_flag(tmp_path):
    cli, runner = cli_for(tmp_path, CmdResult(0, '[{"id":"x"}]'))
    assert cli.list() == [{"id": "x"}]
    assert runner.argv[1:] == ["list", "--state-dir", str(tmp_path / "state")]


def test_discover_does_not_pass_state_dir(tmp_path):
    cli, runner = cli_for(tmp_path, CmdResult(0, "[]"))
    cli.discover()
    assert "--state-dir" not in runner.argv


def test_exit_2_verify_is_an_answer_not_an_error(tmp_path):
    cli, _ = cli_for(tmp_path, CmdResult(2, '{"isValid": false, "issues": []}'))
    assert cli.verify(ID)["isValid"] is False


def test_exit_3_plan_is_an_answer(tmp_path):
    cli, _ = cli_for(tmp_path, CmdResult(3, '{"canExecuteOnCurrentPlatform": false}'))
    assert cli.plan(ID)["canExecuteOnCurrentPlatform"] is False


def test_rc_error_object_on_stderr_maps_to_plain_codes(tmp_path):
    cli, _ = cli_for(tmp_path, CmdResult(1, "", '{"error":"installation_not_found","message":"No installation with that ID is in this catalog."}'))
    with pytest.raises(RcError) as e:
        cli.verify(ID)
    assert e.value.code == "installation_not_found" and "installation_not_found" in e.value.detail


def test_garbage_output_is_bad_output_with_detail(tmp_path):
    cli, _ = cli_for(tmp_path, CmdResult(0, "<html>"))
    with pytest.raises(RcError) as e:
        cli.list()
    assert e.value.code == "tools_bad_output"


def test_timeout_and_unrunnable_exe(tmp_path):
    cli, _ = cli_for(tmp_path, CmdResult(-1, "", "", timed_out=True))
    with pytest.raises(RcError) as e:
        cli.list()
    assert e.value.code == "tools_timeout"
    cli, _ = cli_for(tmp_path, OSError("%1 is not a valid Win32 application"))
    with pytest.raises(RcError) as e:
        cli.list()
    assert e.value.code == "tools_corrupt"


@pytest.mark.parametrize("bad", ["", "nope", "../etc", ID.upper() + "0", ID[:-1], None, 5])
def test_installation_ids_are_checked_before_anything_runs(tmp_path, bad):
    cli, runner = cli_for(tmp_path, CmdResult(0, "{}"))
    with pytest.raises(RcError) as e:
        cli.verify(bad)
    assert e.value.code == "bad_request" and runner.argv is None


@pytest.mark.parametrize("mode,target", [("fly", "client"), ("screen", "shell"), ("", "client")])
def test_launch_intents_are_checked(tmp_path, mode, target):
    cli, runner = cli_for(tmp_path, CmdResult(0, "{}"))
    with pytest.raises(RcError):
        cli.launch(ID, mode=mode, target=target)
    assert runner.argv is None


def test_launch_args_never_go_through_a_shell_string(tmp_path):
    cli, runner = cli_for(tmp_path, CmdResult(0, '{"processId": 1}'))
    cli.launch(ID, mode="vr", target="external", approved_launcher=r"C:\Games\My Launcher.exe")
    assert runner.argv[1:] == ["launch", ID, "--mode", "vr", "--target", "external", "--approved-launcher",
                               r"C:\Games\My Launcher.exe", "--state-dir", str(tmp_path / "state")]


def test_import_flags(tmp_path):
    cli, runner = cli_for(tmp_path, CmdResult(0, '{"id":"x"}'))
    cli.import_(STEAM_ROOT, "Rec Room", launcher=r"C:\x.exe", replace=True)
    assert runner.argv[1:8] == ["import", STEAM_ROOT, "--name", "Rec Room", "--launcher", r"C:\x.exe", "--replace"]


# -- the real subprocess runner ---------------------------------------------------------------------------------------
def script(tmp_path, body):
    p = tmp_path / "s.py"
    p.write_text(textwrap.dedent(body), encoding="utf-8")
    return [sys.executable, str(p)]


def test_runner_captures_utf8_and_exit_code(tmp_path):
    argv = script(tmp_path, """
        import sys
        sys.stdout.buffer.write('caf\\u00e9 \\u00b7 ok'.encode('utf-8'))
        sys.stderr.write('warn')
        sys.exit(2)
    """)
    r = SubprocessRunner(str(tmp_path / "tmp")).run(argv, timeout=20)
    assert (r.code, r.stdout, r.stderr, r.timed_out) == (2, "caf\u00e9 \u00b7 ok", "warn", False)


def test_runner_kills_on_timeout(tmp_path):
    argv = script(tmp_path, "import time; time.sleep(60)")
    t = time.monotonic()
    r = SubprocessRunner(str(tmp_path / "tmp")).run(argv, timeout=0.6)
    assert r.timed_out and r.code == -1 and time.monotonic() - t < 15


def test_runner_cancel(tmp_path):
    argv = script(tmp_path, "import time; time.sleep(60)")
    t = time.monotonic()
    r = SubprocessRunner(str(tmp_path / "tmp")).run(argv, timeout=60, cancelled=lambda: time.monotonic() - t > 0.5)
    assert r.code == -1 and not r.timed_out and time.monotonic() - t < 15


def test_runner_returns_when_the_tool_exits_even_if_a_child_it_started_keeps_running(tmp_path):
    """`launch` starts the game and exits; the game must not hold our wait open (pipe handles would)."""
    argv = script(tmp_path, f"""
        import subprocess, sys
        subprocess.Popen([sys.executable, "-c", "import time; time.sleep(8)"])
        print('{{"processId": 1}}')
    """)
    t = time.monotonic()
    r = SubprocessRunner(str(tmp_path / "tmp")).run(argv, timeout=30)
    assert r.code == 0 and '"processId"' in r.stdout
    assert time.monotonic() - t < 6, "waited for the grandchild"
