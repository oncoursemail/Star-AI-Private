"""STAR learns to play one game at a time from recorded play (behaviour cloning) and improves on her own successes.

actions.py    GameSpec (keys, buttons, mouse bins, success/failure moments) and InputState -> per-step labels
recorder.py   consented, visible recording of the game window + game keys/mouse into compact shards
              (RawInputSource for the owner's play, SinkTap/TeeSource for STAR's own play)
dataset.py    shards -> frame stacks + labels, session-level train/val split, idle thinning, episode masks
policy.py     IMPALA-CNN policy (~1.3 M params), mixed-precision training, checkpoints (needs PyTorch)
adapter.py    the policy as the fast loop's reflex controller with human limits; reflex_session(...)
improve.py    filtered behaviour cloning on successful episodes + automatic eval gate + promotion/rollback
evaluate.py   success rate over N attempts with a Wilson interval, written to her history
synthetic.py  a fake game with a known answer (tests, GPU smoke runs on synthetic data)
CLI: python -m star.play.learn {record,train,synth,bench,heavy-ok} -h.  Research: docs/research/play-learn-20261026.md.
"""
