"""Signed update channel for the Metallic Launcher and its add-ons (Litha, later RC/MC/RB tools).

See docs/agents/metallic-px-updater-site-20261026.md. Client: `Updater`; owner tools: `publish`, `keys`, `cli`.
"""
from .client import IntegrityError, UpdateError, Updater, verify_dir  # noqa: F401
from .keys import SigningKeyError, TrustStore  # noqa: F401
from .manifest import ManifestError  # noqa: F401
