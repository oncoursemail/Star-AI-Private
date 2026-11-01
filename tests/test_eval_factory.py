"""Bug-injection factory: seed parsing, mutation operators, F2P screening, judge output parsing, leakage index."""
from star import eval_factory as F
from star.eval_checks import judge_outcome, judge_source
from star.eval_sandbox import SandboxResult

SEED = """=== id: clampy | domain: math | difficulty: 2
--- spec
a ModuleScript `C` with `C.clamp(x: number, lo: number, hi: number): number`.
--- module
--!strict
local C = {}
-- a comment with < and + that must never be mutated
function C.clamp(x: number, lo: number, hi: number): number
	if x < lo then
		return lo
	end
	local s = "a < b"
	return if x > hi then hi else x - 0
end
return C
--- test
local C = load_answer()
check("below", C.clamp(-1, 0, 5) == 0)
check("above", C.clamp(9, 0, 5) == 5)
check("inside", C.clamp(3, 0, 5) == 3)
"""


def test_parse_seeds_reads_meta_and_sections():
    (seed,) = F.parse_seeds(SEED, "luau")
    assert (seed.id, seed.domain, seed.difficulty) == ("clampy", "math", 2)
    assert seed.spec.startswith("a ModuleScript") and "return C" in seed.module and "check(" in seed.test


def test_mutants_skip_comments_strings_and_unary_minus():
    (seed,) = F.parse_seeds(SEED, "luau")
    muts = F.mutants(seed.module, "luau")
    changed = {(m.op, m.before, m.after) for m in muts}
    assert ("rel", "<", "<=") in changed and ("rel", ">", ">=") in changed
    assert ("arith", "-", "+") in changed                        # binary `x - 0`
    for m in muts:
        assert "-- a comment with < and +" in m.code             # comments untouched
        assert '"a < b"' in m.code                               # strings untouched
    assert all("(-1" not in m.code for m in muts)
    assert not any(m.code == seed.module for m in muts)
    assert len({m.code for m in muts}) == len(muts)


def test_mutants_never_touch_luau_function_type_arrows():
    code = "local f: (number) -> boolean = function(n: number): boolean return n > 1 end\n"
    assert all("->" in m.code for m in F.mutants(code, "luau"))


def test_python_deletion_keeps_blocks_valid():
    code = "def f(x):\n    if x:\n        y = 1\n    z = 2\n    return z\n"
    deleted = [m for m in F.mutants(code, "python") if m.op == "delete"]
    assert [m.before for m in deleted] == ["z = 2"]             # `y = 1` is the only statement of its block


class FakeLuau:
    """Pretends to run the test: the reference passes all three checks, `return {}` fails to load a function."""

    def run(self, sources):
        out = []
        for src in sources:
            if "x <= lo" in src:
                out.append(("@@T\tpass\tbelow\n@@T\tpass\tabove\n@@T\tpass\tinside\n@@DONE\n", 0))
            elif "if x < lo" in src and "x > hi" in src and "x - 0" in src:
                out.append(("@@T\tpass\tbelow\n@@T\tpass\tabove\n@@T\tpass\tinside\n@@DONE\n", 0))
            elif "return {}" in src:
                out.append(("@@ERR\tattempt to call nil\n@@DONE\n", 0))
            else:
                out.append(("@@T\tfail\tbelow\n@@T\tpass\tabove\n@@T\tpass\tinside\n@@DONE\n", 0))
        return out


def test_screen_keeps_only_fail_to_pass_mutants_with_distinct_signatures():
    (seed,) = F.parse_seeds(SEED, "luau")
    report = F.screen_seed(seed, "", luau=FakeLuau(), max_bugs=5)
    assert report.reference_ok and report.trivial_fails and report.assertions == 3
    assert report.f2p >= 1 and len(report.kept) == 1             # every failing mutant has the same signature
    assert report.kept_failing == [["below"]]
    tasks = F.make_tasks(seed, report, set_id="t", number=iter(["A", "B"]).__next__, rng=__import__("random").Random(1))
    assert [t["kind"] for t in tasks] == ["spec", "bugfix"] and tasks[1]["_bad"] == report.kept[0].code
    assert tasks[1]["_bad"] in tasks[1]["prompt"] and tasks[0]["prompt"].startswith("Write a Luau ModuleScript")


def test_judge_outcome_rejects_forged_or_unfinished_output():
    assert judge_outcome("@@PASS a\n@@PASS b\n@@DONE 2/2\n") == (["a", "b"], [], True)
    forged = "@@PASS fake\n@@PASS fake\n@@PASS a\n@@FAIL b\n@@DONE 1/2\n"     # answer printed its own PASS lines
    assert judge_outcome(forged)[2] is False
    assert judge_outcome("@@PASS a\n")[2] is False                              # exited before the harness finished
    src = judge_source("python", "def f():\n    return 1\n", 'check("one", lambda: f() == 1)')
    assert src.index("def f") < src.index("def check") < src.index('check("one"') < src.index("@@DONE")


def test_factory_judge_outcome_uses_sandbox_results():
    out = F.judge_outcome(SandboxResult(stdout="@@PASS a\n@@DONE 1/1\n").stdout)
    assert out.all_pass and out.loaded


def test_leak_index_flags_copied_text_and_code_but_not_type_signatures():
    index = F.LeakIndex()
    index.add_text("visible.md", "Players earn coins when they finish a round of the obstacle course quickly.\n"
                   "```lua\nlocal function award(p, n)\n\tp.coins = p.coins + n * 2\n\treturn p.coins\nend\n```\n")
    index.add_text("types.json", "`get(scores: { [string]: number }): { [string]: number }`", code=False)
    assert index.reasons("Players earn coins when they finish a round of the obstacle course quickly, says the spec.")
    assert index.reasons("unrelated", code="local function award(p, n)\n\tp.coins = p.coins + n * 2\n\treturn p.coins\nend")
    assert not index.reasons("A module with `top(scores: { [string]: number }): { [string]: number }` sorted by name.")
    assert not index.reasons("A fresh sentence about a cooldown tracker for abilities that nobody wrote before.")
