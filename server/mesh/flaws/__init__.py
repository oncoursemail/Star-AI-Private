"""Flaw loop: STAR/Litha finds her own weak spots in live router logs, turns them into regression items, and ships
cheap fixes (routing rules, notes) only when they measurably win. See docs/agents/flaw-loop-20261030.md.

hook.py   router side (litha only): per-turn flaw signals for the log + the shipped fixes
mine.py   journal + flaw samples -> clusters by cause -> self-model report
items.py  clusters -> regression items with checkable graders (evals/flaws/*.jsonl)
gate.py   A/B of a fix through the router (X-Mesh-Fixes), ship/reject, rollback watch
"""
