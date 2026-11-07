"""Fake-file checks for Metallic's verdict adapter; no grader, evaluation, queue or model runs."""
from __future__ import annotations

import json
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "metallic"))
from metallic import checks  # noqa: E402
from metallic.config import Config  # noqa: E402

count = 0
MALFORMED = "malformed paired verdict: allowed must be boolean and exit_code must be integer"


def check(condition, label):
    global count
    assert condition, label
    count += 1


def main():
    with TemporaryDirectory(prefix="metallic-verdict-types-") as temporary:
        root = Path(temporary)
        path = root / "synthetic-verdict.json"
        cfg = Config(eval_paths=["pkg/prompts.py"], eval_blocking=True)
        ctx = checks.Context(root, cfg, "fake-base", "fake-tree", {}, ["pkg/prompts.py"], "synthetic-only")

        def route(payload, *, explicit=True):
            destination = path if explicit else root / "eval" / "fake-tree.json"
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_text(json.dumps(payload), encoding="utf-8")
            with patch("metallic.checks.subprocess.run", side_effect=AssertionError("no subprocess permitted")):
                return checks.check_eval(ctx, str(destination) if explicit else None, root)

        for allowed in (False, True):
            for code in (0, 1, 2, 3, 4, -1, 99):
                result = route({"allowed": allowed, "exit_code": code})
                expected = checks.PASS if allowed is True and code == 0 else checks.FAIL
                check(result.status == expected and result.blocking is True,
                      f"canonical bool/int routing retained for {allowed}/{code}")

        malformed = [None, False, True, 0, 0.0, "object required", [],
                     [{"allowed": True, "exit_code": 0}], {}, {"allowed": True}, {"exit_code": 0}]
        malformed += [{"allowed": value, "exit_code": 0}
                      for value in ("false", "true", 0, 1, -1, 1.0, None, [], {})]
        malformed += [{"allowed": True, "exit_code": value}
                      for value in (False, True, "0", "false", 0.0, 0.8, -0.8, None, [], {})]
        for index, payload in enumerate(malformed):
            result = route(payload)
            check(result.status == checks.FAIL and result.blocking is True and result.summary == MALFORMED,
                  f"malformed case {index} fails statically rather than coercing or throwing")

        private_marker = "synthetic diagnostic must never appear in the returned summary"
        result = route({"allowed": private_marker, "exit_code": {"detail": private_marker}})
        check(private_marker not in json.dumps(result.to_dict()) and result.summary == MALFORMED,
              "malformed field contents are not reflected in diagnostics")
        result = route({"allowed": True, "exit_code": 0, "baseline_pass": 42,
                        "problems": [], "provenance": "synthetic-only, not an actual grade"})
        check(result.status == checks.PASS, "extra producer fields preserve the established adapter contract")
        result = route({"allowed": True, "exit_code": 0}, explicit=False)
        check(result.status == checks.PASS, "default state-file lookup retains canonical behavior")

        for blocking in (False, True):
            cfg.eval_blocking = blocking
            result = route({"allowed": "false", "exit_code": False})
            check(result.status == checks.FAIL and result.blocking is True,
                  "present malformed verdict remains blocking in either configured mode")
            result = route({"allowed": False, "exit_code": 4})
            check(result.status == checks.FAIL and result.blocking is True,
                  "present canonical denial preserves existing blocking behavior")
            result = checks.check_eval(ctx, str(root / "not-present.json"), root)
            expected = checks.FAIL if blocking else checks.WARN
            check(result.status == expected and result.blocking is blocking,
                  "missing-file behavior preserves configured report-only/blocking mode")
            path.write_text("{invalid JSON", encoding="utf-8")
            result = checks.check_eval(ctx, str(path), root)
            check(result.status == expected and result.blocking is blocking,
                  "JSON decode failure retains existing missing-verdict policy")

        for blocking in (False, True):
            cfg.eval_blocking = blocking
            cfg.eval_paths = []
            with patch.object(Path, "read_text", side_effect=AssertionError("unconfigured route must not read a verdict")):
                result = checks.check_eval(ctx, str(path), root)
            check(result.status == checks.SKIP and result.blocking is blocking,
                  "unconfigured adapter remains skipped without a file read")
            cfg.eval_paths = ["pkg/prompts.py"]
            ctx.changed = ["README.md"]
            with patch.object(Path, "read_text", side_effect=AssertionError("unaffected route must not read a verdict")):
                result = checks.check_eval(ctx, str(path), root)
            check(result.status == checks.PASS and result.blocking is blocking,
                  "unaffected paths preserve existing pass without file access")

        ctx.changed = ["pkg/prompts.py"]
        path.write_text(json.dumps({"allowed": "false", "exit_code": 0}), encoding="utf-8")
        with patch("metallic.checks.subprocess.run", side_effect=AssertionError("no subprocess permitted")):
            results = checks.run_builtin(ctx, ["eval-gate"], verdict_file=str(path), state=root, private_names=[])
        check(len(results) == 1 and results[0].status == checks.FAIL and results[0].blocking,
              "built-in dispatcher retains malformed failure rather than manufacturing a pass")
    print(f"{count} Metallic verdict-type checks passed; fake files only, no evaluation or promotion run.")


if __name__ == "__main__":
    main()
