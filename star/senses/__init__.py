"""STAR's senses on her own PC: hearing all audio (games, music, calls), a virtual microphone for her voice, and the
instant, glitch-free voice path. Everything here is behind small interfaces and tested with fake devices; the real
Windows devices (WASAPI loopback, virtual audio cable) live in capture.py and routes.py and need their packages.

hearing.py     SensesHub: loopback + microphone, rolling buffer, streaming speech-to-text, non-speech classifier
reference.py   what STAR herself played, and the canceller that removes it from what she hears
classify.py    "what is this audio?": silence / speech / music / game sounds / noise
output.py      PlaybackBuffer: jitter buffer, click-free starts and stops, stop within one device block
routes.py      finds the virtual cable by name; a speaker that plays only into it (Discord / game voice chat)
instant.py     keep-warm, the settings preset for her PC, session builder
fastpath.py    which turns the small GPU model answers and which go to the big brain; VRAM budget; downloads
bench.py       end-to-end latency on fake engines (python -m star.senses.bench)
"""
