"""Rust edition/diagnostic regressions and real compile-only fixture checks.

No generated answer is executed. Tests with rustc use metadata emission on the
trusted fixture below; without a toolchain only those two cases are skipped.
"""
from __future__ import annotations

import contextlib
import concurrent.futures
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import threading

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "server"))
from mesh.polyglot import client as pg_client  # noqa: E402
from mesh.polyglot import note, runner, rust_edition  # noqa: E402
from mesh.verify import core  # noqa: E402
from mesh.verify.apidump import ApiIndex  # noqa: E402
sys.path.remove(str(ROOT / "server"))

LET_CHAIN = """fn main() {
    let value = Some(7);
    if let Some(number) = value && number > 2 {
        println!("{number}");
    }
}
"""


def fake_compile(monkeypatch, *, stderr="", rc=0, timed_out=False):
    calls = []

    def run(cmd, cwd, **kwargs):
        calls.append(list(cmd))
        return {"cmd": cmd, "rc": rc, "timed_out": timed_out, "stderr": stderr, "stdout": "", "seconds": 0.0}

    monkeypatch.setattr(runner, "Workdir", lambda *a, **k: contextlib.nullcontext("."))
    monkeypatch.setattr(runner, "run_limited", run)
    return calls


def diagnostic(code, message, *, line=3):
    return json.dumps({"level": "error", "code": {"code": code}, "message": message,
                       "spans": [{"is_primary": True, "line_start": line}], "children": []})


@pytest.mark.parametrize("edition", ["2015", "2018", "2021", "2024"])
def test_explicit_supported_editions_reach_rustc(monkeypatch, edition):
    calls = fake_compile(monkeypatch)
    out = runner.check("rust", "fn main() {}", f"Write a Rust {edition} program")
    assert out["checked"] and out["compiled"] and out["edition"] == edition
    assert calls[0][calls[0].index("--edition") + 1] == edition
    assert "--emit=metadata" in calls[0]
    assert out["tool"] == "rustc"  # never claim an unobserved version


def test_default_edition_stays_compatible_and_prompt_honors_target():
    assert rust_edition.resolve() == "2021"
    assert "Rust 2021 edition" in note.note("rust")
    req = {"messages": [{"role": "system", "content": "prefix"},
                        {"role": "user", "content": "Write a Rust 2024 program with let chains"}]}
    assert note.apply(req) == {"X-Mesh-Polyglot": "rust"}
    assert "Rust 2024 edition" in req["messages"][-1]["content"]
    assert "Rust 2021 edition" not in req["messages"][-1]["content"]
    assert req["messages"][0]["content"] == "prefix"


def test_code_string_cannot_change_edition_and_cargo_manifest_can():
    assert rust_edition.resolve('```rust\nfn main(){ println!("Rust 2024"); }\n```') == "2021"
    assert rust_edition.resolve('Cargo.toml:\n```toml\n[package]\nedition = "2024"\n```') == "2024"
    assert rust_edition.resolve("Use edition: '2018'") == "2018"


@pytest.mark.parametrize("opening, closing", [("```rust", "```"), ("```rust", ""),
                                               ("~~~rust", "~~~"), ("~~~rust", ""),
                                               ("````rust", "````")])
def test_all_supported_source_fences_exclude_literal_editions(opening, closing):
    source = 'fn main() { let gen = 1; println!("Rust 2024 {gen}"); }'
    assert rust_edition.resolve(f"Rust 2021\n{opening}\n{source}\n{closing}") == "2021"


@pytest.mark.parametrize("context", ["Rust 2099", "Rust edition 2027", "Rust 2021 and Rust 2024"])
def test_unsupported_or_ambiguous_target_is_unchecked(monkeypatch, context):
    calls = fake_compile(monkeypatch)
    out = runner.check("rust", "fn main() {}", context)
    assert not out["checked"] and not out["compiled"] and out["problems"] == []
    assert out["error"] and not calls


@pytest.mark.parametrize("edition", ["2024 --cfg anything", "2027", 2024, ["2024"], ""])
def test_explicit_field_rejects_unsupported_values_before_compiling(monkeypatch, edition):
    calls = fake_compile(monkeypatch)
    out = runner.check("rust", "fn main() {}", edition=edition)
    assert not out["checked"] and not calls


def test_structured_edition_has_priority(monkeypatch):
    calls = fake_compile(monkeypatch)
    out = runner.check("rust", "fn main() {}", "Rust 2021", edition="2024")
    assert out["edition"] == "2024" and "2024" in calls[0]


@pytest.mark.parametrize("stderr", ["compiler crashed", "", "[]\nnull\n", "error: unsupported edition"])
def test_failed_compiler_never_appears_clean(monkeypatch, stderr):
    fake_compile(monkeypatch, stderr=stderr, rc=1)
    out = runner.check("rust", "fn main() {}")
    assert not out["checked"] and not out["compiled"] and out["problems"] == []


def test_missing_external_dependency_does_not_prove_success(monkeypatch):
    fake_compile(monkeypatch, stderr=diagnostic("E0432", "unresolved import `tokio`"), rc=1)
    out = runner.check("rust", "use tokio::runtime::Runtime;\nfn main() {}")
    assert not out["checked"] and not out["compiled"] and out["problems"] == []


def test_real_borrow_error_still_drives_repair(monkeypatch):
    fake_compile(monkeypatch, stderr=diagnostic("E0382", "borrow of moved value: `s`"), rc=1)
    out = runner.check("rust", 'fn main() {\nlet s = String::new();\ndrop(s);\nprintln!("{s}");\n}')
    assert out["checked"] and not out["compiled"]
    assert out["problems"][0]["kind"] == "borrow"
    assert "E0382" in out["problems"][0]["message"]


def test_timeout_is_unchecked(monkeypatch):
    fake_compile(monkeypatch, rc=137, timed_out=True)
    out = runner.check("rust", "fn main() {}", "Rust 2024")
    assert not out["checked"] and out["error"] == "timeout" and out["edition"] == "2024"


def test_run_edition_does_not_mutate_later_jobs(monkeypatch):
    calls = fake_compile(monkeypatch)
    first = runner.run_job({"language": "rust", "edition": "2024", "files": {"main.rs": "fn main() {}"}})
    second = runner.run_job({"language": "rust", "files": {"main.rs": "fn main() {}"}})
    assert first["ok"] and first["edition"] == "2024" and "2024" in calls[0]
    assert second["ok"] and second["edition"] == "2021" and "2021" in calls[2]
    assert runner.RUN_RECIPES["rust"]["compile"][0][2] == "2021"


def test_run_rejects_unsupported_edition_without_starting_job(monkeypatch):
    calls = fake_compile(monkeypatch)
    out = runner.run_job({"language": "rust", "edition": "2099", "files": {"main.rs": "fn main() {}"}})
    assert not out["ok"] and "unsupported" in out["error"] and not calls


class CompilerClient:
    def __init__(self):
        self.contexts = []

    def check(self, language, code, context=""):
        self.contexts.append((language, context))
        if language != "rust":
            return {"checked": True, "problems": []}
        out = runner.check(language, code, context)
        return out if out["checked"] else None

    def check_many(self, items, context=""):
        return {item: self.check(*item, context) for item in items}


@pytest.mark.parametrize("style", ["raw", "open", "tildes", "four-backticks"])
@pytest.mark.parametrize("question", [None, "Write a Rust 2021 program"])
def test_verifier_never_reads_source_literals_as_editions(monkeypatch, style, question):
    calls = fake_compile(monkeypatch)
    source = 'fn main() { let gen = 1; println!("Rust 2024 {gen}"); }'
    answers = {"raw": source, "open": "```rust\n" + source,
               "tildes": "~~~rust\n" + source + "\n~~~",
               "four-backticks": "````rust\n" + source + "\n````"}
    verifier = core.Verifier(ApiIndex({"meta": {}, "classes": {}, "enums": {}}), None,
                             polyglot=CompilerClient())
    out = verifier.verify(answers[style], language="rust" if style == "raw" else None, question=question)
    assert out["blocks"][0]["checked"]
    assert calls[0][calls[0].index("--edition") + 1] == "2021"


def test_direct_checker_raw_context_cannot_choose_edition(monkeypatch):
    calls = fake_compile(monkeypatch)
    code = 'fn main() { println!("Rust 2024"); }'
    assert runner.check("rust", code, code)["edition"] == "2021"
    assert "2021" in calls[0]


@pytest.mark.parametrize("answer", ["```rust\nfn main() {}\n```",
                                    "```rust\nfn main() {}\n```\n```python\nprint(1)\n```"])
def test_verifier_preserves_requested_rust_edition(monkeypatch, answer):
    calls = fake_compile(monkeypatch)
    client = CompilerClient()
    verifier = core.Verifier(ApiIndex({"meta": {}, "classes": {}, "enums": {}}), None, polyglot=client)
    result = verifier.verify(answer, question="Write a Rust 2024 program")
    assert result["blocks"][0]["checked"] and "2024" in calls[0]
    for language, context in client.contexts:
        assert ("Write a Rust 2024 program" in context) == (language == "rust")


def test_unverified_rust_repair_is_rejected(monkeypatch):
    fake_compile(monkeypatch)
    client = CompilerClient()

    def check(language, code, context=""):
        if "drop(s)" in code:
            return {"checked": True, "problems": [{"kind": "borrow", "severity": "error", "name": "s",
                    "message": "Rust E0382: borrow of moved value", "suggestion": None, "line": 1}]}
        return None  # absent dependency, timeout, unsupported edition or compiler failure

    client.check = check
    verifier = core.Verifier(ApiIndex({"meta": {}, "classes": {}, "enums": {}}), None, polyglot=client)
    original = '```rust\nfn main() { let s = String::new(); drop(s); println!("{s}"); }\n```'
    out = verifier.fix(original, lambda messages: '```rust\nfn main() { unavailable::run(); }\n```')
    assert out["answer"] == original
    assert any("could not verify" in change.get("rejected", "") for change in out["changes"])


def test_mixed_language_checks_keep_one_parallel_batch(monkeypatch):
    client = pg_client.Polyglot("http://127.0.0.1:9", "unused")
    barrier = threading.Barrier(2)
    contexts = {}

    def compile_block(language, code, context=""):
        contexts[language] = context
        barrier.wait(timeout=5)  # fails if the Rust/Python groups are serialized
        return {"checked": True, "problems": []}

    monkeypatch.setattr(client, "check", compile_block)
    verifier = core.Verifier(ApiIndex({"meta": {}, "classes": {}, "enums": {}}), None, polyglot=client)
    answer = "```rust\nfn main() {}\n```\n```python\nprint(1)\n```"
    try:
        out = verifier.verify(answer, question="Write a Rust 2024 program and its Python counterpart")
        assert all(block["checked"] for block in out["blocks"])
        assert "Rust 2024" in contexts["rust"]
        assert contexts["python"] == answer
    finally:
        client.pool.shutdown(wait=True)


def test_conflicting_duplicate_contexts_start_no_compilers(monkeypatch):
    client = pg_client.Polyglot("http://127.0.0.1:9", "unused")
    calls = []
    monkeypatch.setattr(client, "check", lambda *args: calls.append(args))
    try:
        with pytest.raises(ValueError, match="Conflicting"):
            client.check_many_contexts([("rust", "fn main() {}", "Rust 2021"),
                                        ("rust", "fn main() {}", "Rust 2024")])
        assert not calls
    finally:
        client.pool.shutdown(wait=True)


def test_shared_verifier_requests_do_not_share_edition_results():
    first_ready = threading.Event()
    second_ready = threading.Event()

    class EditionCompiler(CompilerClient):
        def check(self, language, code, context=""):
            problems = []
            if language == "rust" and rust_edition.resolve(context) == "2024":
                problems = [{"kind": "syntax", "severity": "error", "name": None, "suggestion": None,
                             "message": "expected identifier, found reserved keyword `gen`", "line": 1}]
            return {"checked": True, "problems": problems}

    class RacingVerifier(core.Verifier):
        def prefetch(self, blocks, prose, question=None):
            super().prefetch(blocks, prose, question)
            if question == "Rust 2024":
                first_ready.set()
                assert second_ready.wait(timeout=5)
            else:
                second_ready.set()

    verifier = RacingVerifier(ApiIndex({"meta": {}, "classes": {}, "enums": {}}), None,
                              polyglot=EditionCompiler())
    answer = "```rust\nfn main(){ let gen=1; }\n```\n```python\nprint(1)\n```"
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(verifier.verify, answer, question="Rust 2024")
        assert first_ready.wait(timeout=5)
        second = pool.submit(verifier.verify, answer, question="Rust 2021")
        old, new = second.result(timeout=5), first.result(timeout=5)
    assert old["ok"] and old["blocks"][0]["checked"]
    assert not new["ok"] and new["blocks"][0]["checked"] and new["blocks"][0]["problems"]


def test_isolated_runner_import_finds_adjacent_edition_helper():
    script = "import runpy, sys; d=runpy.run_path(sys.argv[1]); print(d['rust_edition']('Rust 2024'))"
    out = subprocess.run([sys.executable, "-I", "-c", script, str(ROOT / "server/mesh/polyglot/runner.py")],
                         capture_output=True, text=True, timeout=15)
    assert out.returncode == 0, out.stderr
    assert out.stdout.rstrip().endswith("2024")


@pytest.mark.parametrize("edition, compiled", [("2024", True), ("2021", False)])
def test_real_rustc_let_chain_fixture(monkeypatch, edition, compiled):
    rustc = shutil.which("rustc")
    if not rustc:
        pytest.skip("rustc not installed; offline mocked checks still run")

    @contextlib.contextmanager
    def workdir(*, files, **kwargs):
        with tempfile.TemporaryDirectory(prefix="litha-rust-compile-") as folder:
            for name, content in files.items():
                (Path(folder) / name).write_text(content, encoding="utf-8")
            yield folder

    def compile_only(cmd, cwd, **kwargs):
        assert "--emit=metadata" in cmd
        done = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=15)
        return {"rc": done.returncode, "stdout": done.stdout, "stderr": done.stderr, "timed_out": False}

    monkeypatch.setattr(runner, "RUSTC", rustc)
    monkeypatch.setattr(runner, "Workdir", workdir)
    monkeypatch.setattr(runner, "run_limited", compile_only)
    result = runner.check("rust", LET_CHAIN, f"Rust {edition}")
    assert result["compiled"] is compiled
    assert result["checked"]
    assert bool(result["problems"]) is not compiled
