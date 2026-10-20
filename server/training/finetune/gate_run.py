"""Run one arm of the fine-tune gate: STAR's real answer pipeline against a temporary llama-server, scored by the suite.

    python gate_run.py --arm base  --model q3-4b-base   --server http://127.0.0.1:8098/v1 --ssh U@H \
        --suite evals/roblox/golden-tasks-v2.json --out work/ft20/gate/base-v2.json
    python gate_run.py --arm bank  --model q3-4b-base   --bank work/ft20/data/bank.jsonl ...   (exemplar-bank control)
    python gate_run.py --arm sft   --model apprentice-v3 ...                                   (LoRA server)

- The answer path is star.eval_runner's (desktop_core.run_task, mode auto, packs off, docs search, Luau check and
  repair, temperature 0); only the model behind --server changes. The temporary server never replaces a live model.
- --bank switches on the app's own worked-example retrieval (star/worked_examples.py, setting worked_examples_enabled)
  with the bank imported into each task's throw-away APPDATA project. Eval-only variant: the per-turn block budget
  MAX_PROMPT_CHARS 2400 -> --bank-chars (8000), because no real verified example fits in 2400 characters
  (docs/agents/worked-examples-eval.md); the live default is unchanged.
- The knowledge service and the Luau VM sandbox are brain 1's (STAR_EVAL_KNOWLEDGE, --ssh): a local --server address
  would otherwise point the docs search at this PC.
Compare arms with `python -m star.evals gate --paired-session --allow-model-change ...` or gate_report.py.
"""
from __future__ import annotations

import argparse
import dataclasses
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def patch_run_task(knowledge: str, bank: Path | None, bank_chars: int) -> None:
    """Wrap desktop_core.run_task (eval_runner imports it at call time) so every task sees the knowledge address and,
    for the bank arm, the imported exemplar bank."""
    from star import desktop_core, worked_examples
    original = desktop_core.run_task
    if bank is not None:
        worked_examples.MAX_PROMPT_CHARS = bank_chars

    def run_task(settings, prompt, **kwargs):
        changes = {"knowledge_endpoint": knowledge} if knowledge else {}
        if bank is not None:
            worked_examples.import_file(bank, home=desktop_core.app_data(), project=settings.project)
            changes["worked_examples_enabled"] = True
        return original(dataclasses.replace(settings, **changes), prompt, **kwargs)

    desktop_core.run_task = run_task


def patch_luau_client(knowledge: str) -> None:
    """eval_runner.build_real's own Luau-check client also has to use brain 1's knowledge service."""
    if not knowledge:
        return
    from star import doc_knowledge
    original = doc_knowledge.client_for

    def client_for(settings, **kwargs):
        return original(dataclasses.replace(settings, knowledge_endpoint=knowledge), **kwargs)

    doc_knowledge.client_for = client_for


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--arm", required=True)
    ap.add_argument("--model", required=True, help="name recorded for this arm (the temporary server serves one model)")
    ap.add_argument("--server", required=True, help="the temporary llama-server, e.g. http://127.0.0.1:8098/v1")
    ap.add_argument("--ssh", default=os.environ.get("STAR_EVAL_SSH", ""), help="brain 1 LXD host (sandbox, quiet lock)")
    ap.add_argument("--knowledge", default=os.environ.get("STAR_EVAL_KNOWLEDGE", ""),
                    help="STAR Knowledge address (brain 1 container, port 8091)")
    ap.add_argument("--suite", required=True, type=Path)
    ap.add_argument("--out", required=True, type=Path)
    ap.add_argument("--tasks", default="")
    ap.add_argument("--bank", type=Path, default=None)
    ap.add_argument("--bank-chars", type=int, default=8000)
    ap.add_argument("--retry-errors", action="store_true", help="run tasks that ended in an error again")
    args = ap.parse_args(argv)
    if not args.knowledge:
        raise SystemExit("give --knowledge or STAR_EVAL_KNOWLEDGE (the docs search and Luau check run there)")
    patch_luau_client(args.knowledge)
    patch_run_task(args.knowledge, args.bank, args.bank_chars)
    from star import eval_runner
    run = ["run", "--suite", str(args.suite), "--server", args.server, "--model", args.model, "--pin-model",
           "--mode", "auto", "--packs", "off", "--out", str(args.out)]
    if args.ssh:
        run += ["--ssh", args.ssh]
    if args.tasks:
        run += ["--tasks", args.tasks]
    if args.retry_errors:
        run.append("--retry-errors")
    return eval_runner.main(run)


if __name__ == "__main__":
    raise SystemExit(main())
