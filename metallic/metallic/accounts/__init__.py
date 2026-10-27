"""Metallic accounts + social: one self-hosted account system for the launcher, Star 2.0 and Metallic-RC.

Modules: crypto (argon2id, TOTP, ES256 tokens, sealed secrets), store (SQLite), service (rules), server (HTTPS API),
client (stdlib client used by the launcher and tests). Needs argon2-cffi and cryptography (apt: python3-argon2,
python3-cryptography); everything else is the standard library.
"""
