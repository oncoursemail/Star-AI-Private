"""Fully synthetic, offline gameplay-skill evidence rehearsal.

Run from repository root:
    PYTHONPATH=. python3 examples/gameplay_skill_bank_rehearsal.py

No games, controllers, streams, real player data, keys or models are accessed.
The signing keys below are TEST FIXTURES, not appropriate for any real host.
"""
from __future__ import annotations

from dataclasses import replace
import hashlib
import hmac
import time

from star.gameplay_skill_bank import GameTrial, GameplaySkillBank

PRACTICE = hashlib.sha256(b"public demo signer practice NOT A SECRET").digest()
VALIDATION = hashlib.sha256(b"public demo signer validation NOT A SECRET").digest()
EVIDENCE = hashlib.sha256(b"synthetic fixture; not real observations").hexdigest()


def sign_fixture(trial: GameTrial) -> str:
    secret = PRACTICE if trial.split == "practice" else VALIDATION
    return hmac.new(secret, trial.canonical_bytes(), hashlib.sha256).hexdigest()


def main() -> None:
    now = int(time.time())
    with GameplaySkillBank(practice_key=PRACTICE, validation_key=VALIDATION) as bank:
        for index in range(5):
            trial = GameTrial(f"p{index}", "sample_obby", "build1", "reach_goal",
                              "normal_course", "jump_then_pause", f"training{index}",
                              "practice", "success", EVIDENCE, now)
            bank.ingest(trial, sign_fixture(trial), now_unix_s=now)
        trial = replace(trial, trial_id="unsigned", run_id="unauthorized", split="validation")
        try:
            bank.ingest(trial, sign_fixture(replace(trial, split="practice")),
                        now_unix_s=now)
        except PermissionError:
            print("Synthetic signer isolation: PASS (practice cannot forge validation)")
        practice = bank.suggest("sample_obby", "build1", "reach_goal", "normal_course",
                                now_unix_s=now)
        print(f"Practice evidence: {practice.status}; controls enabled: {practice.authorized_to_play}")
        for index in range(8):
            trial = GameTrial(f"v{index}", "sample_obby", "build1", "reach_goal",
                              "normal_course", "jump_then_pause", f"holdout{index}",
                              "validation", "success", EVIDENCE, now)
            bank.ingest(trial, sign_fixture(trial), now_unix_s=now)
        result = bank.suggest("sample_obby", "build1", "reach_goal",
                              "normal_course", now_unix_s=now)
        print(f"Independent synthetic holdout: {result.status}; "
              f"lower_bound={result.validation_lower_bound:.4f}; "
              f"controls enabled: {result.authorized_to_play}")
        print("RESULTS ARE SYNTHETIC; no game played, no skill deployed, no broadcast started.")


if __name__ == "__main__":
    main()
