"""Litha's face: a small local web app where the owner sees and steers her (python -m litha.face).

Reads her state files under ~/.star read-only (tails, cached by mtime; never calls gh), writes only her own control
files (pause, autonomy APPLY, Claude day cap; every change logged), and lets the owner ask her a question.
Binds 127.0.0.1 unless --lan; LAN clients need the token in ~/.star/litha-face.token."""
