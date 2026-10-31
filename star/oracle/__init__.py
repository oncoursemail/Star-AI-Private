"""Star Oracle: predict whether a change to Star helps or hurts quality in minutes instead of a day-long A/B
(docs/agents/IDEA-star-oracle-20261021.md; notes docs/agents/oracle-20261021.md).

    python -m star.oracle probe --eval-results <passing eval result files> --out probe.jsonl
    python -m star.oracle compare --base base.json --cand cand.json --probe probe.jsonl --workdir out/ [--max-layer N]
    python -m star.oracle calibrate --registry registry.json --out data/oracle/calibration.json
    python -m star.oracle replay --registry registry.json --out replay.json

Layers (cheapest first; config.py says which layer can see which kind of change):
  L0 equiv.py    greedy token-for-token equivalence of two configs (perf-only changes)
  L1 score.py    KL divergence and top-1 agreement against the base config over verified answers
  L2 score.py    log-probability margin of verified GOOD answers over planted BAD twins (probe.py), calibrated
                 against past A/Bs (calibrate.py) into a pass-rate delta with an interval
  L3 irt.py      adaptive paired eval: item-response task order + sequential stopping, on star.evals
Prefill scoring runs server/oracle/llama_score.cpp (a small tool on the llama.cpp C API; no generation).
Nothing here switches anything on: the oracle predicts, star.evals gate still decides promotions.
"""
