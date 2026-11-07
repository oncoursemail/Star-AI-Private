"""STAR plays games: a two-tier loop (fast local perception-action, slow planner/persona) with human-like input.

humanlike.py   reaction times, Fitts-law curved pointer paths, overshoot, misses; Actuator plays timed events
winput.py      the real Windows input sink (SendInput scan codes, only into the game window)
capture.py     screen frames (dxcam / mss / GDI) and fake frames
percept.py     Detection / ChatLine / Percept;  perception.py: colour blobs, YOLO ONNX decoding, chat OCR
planner.py     the slow layer's model call: situation -> goal + optional spoken line
loop.py        FastLoop (10-30 Hz), SlowLoop (~1 Hz, wakes on game moments), GameSession, latency stats
roblox.py      obby controller (screen + keys);  minecraft/: skill library, Voyager-style learner, reflexes
session.py     builds a GameSession for each game;  bench.py: latency on fake frames (python -m star.play.bench)
learn/         per-game policies cloned from recorded play + filtered self-improvement + per-game eval
Research, design and limits: docs/research/game-play-20261026.md.
"""
