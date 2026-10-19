"""Owner-captured local/LAN targets for bulk work; credentials stay in the OS.

Profiles are immutable snapshots of the *current* desktop Settings. The page
cannot supply a new address, workspace root or secret. Each LAN credential is
copied to a separate OS-keyring entry bound to that captured endpoint, so a
later change to STAR's current server key cannot redirect an older profile.
"""
from __future__ import annotations

from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path
import re
import threading
import uuid

from .atomic_io import atomic_write_text
from .providers import connection_for, provider_kind, validate_lan_endpoint

MAX_TARGETS = 32
PROFILE_FIELDS = (
    "provider", "endpoint", "model", "project", "workspace", "server_endpoint",
    "allow_cgnat", "server_timeout", "server_parallel", "server_context_tokens",
)
_ID = re.compile(r"^target_[0-9a-f]{32}$")


def fingerprint(value: dict) -> str:
    return sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                             ensure_ascii=True, allow_nan=False).encode()).hexdigest()


class OSProfileSecrets:
    """No plaintext fallback, including when an optional keyring plugin is installed."""

    service = "STAR Bulk Targets"

    @staticmethod
    def _backend():
        import keyring
        backend = keyring.get_keyring()
        module = type(backend).__module__
        if not module.startswith(("keyring.backends.Windows", "keyring.backends.macOS",
                                  "keyring.backends.SecretService", "keyring.backends.kwallet")):
            raise RuntimeError("Secure OS credential storage is unavailable for saved brain targets")
        return backend

    def put(self, account: str, secret: str) -> None:
        try:
            self._backend().set_password(self.service, account, secret)
        except Exception:
            raise RuntimeError("Could not save the brain credential in secure OS storage") from None

    def get(self, account: str) -> str | None:
        try:
            value = self._backend().get_password(self.service, account)
            return value if isinstance(value, str) and value else None
        except Exception:
            return None

    def delete(self, account: str) -> None:
        try:
            backend = self._backend()
            if backend.get_password(self.service, account):
                backend.delete_password(self.service, account)
        except Exception:
            raise RuntimeError("Could not remove the saved brain credential from secure OS storage") from None


def profile_settings(profile: dict):
    from .desktop_core import Settings
    raw = profile["settings"]
    if set(raw) != set(PROFILE_FIELDS):
        raise ValueError("Saved bulk target has an unsupported settings format")
    settings = Settings(**deepcopy(raw))
    settings.validate()
    if provider_kind(settings) not in {"local", "lan"}:
        raise PermissionError("Bulk targets support configured local and LAN brains only")
    return settings


def endpoint_for(settings) -> str:
    if provider_kind(settings) == "lan":
        return validate_lan_endpoint(settings.server_endpoint, allow_cgnat=settings.allow_cgnat)
    return settings.endpoint.rstrip("/")


class BulkProfiles:
    """Small local metadata store; the service's engine lock owns its lifecycle."""

    def __init__(self, path: Path, *, secrets=None):
        self.path = Path(path)
        self.secrets = secrets if secrets is not None else OSProfileSecrets()
        self._lock = threading.RLock()
        self._data = {"version": 1, "enabled": False, "targets": []}
        if self.path.exists():
            if self.path.is_symlink() or self.path.stat().st_size > 131072:
                raise ValueError("Bulk target settings file is invalid")
            try:
                data = json.loads(self.path.read_text(encoding="utf-8"))
                if (not isinstance(data, dict) or set(data) != {"version", "enabled", "targets"}
                        or data["version"] != 1 or type(data["enabled"]) is not bool
                        or not isinstance(data["targets"], list) or len(data["targets"]) > MAX_TARGETS):
                    raise ValueError
                seen = set()
                for profile in data["targets"]:
                    if (not isinstance(profile, dict)
                            or set(profile) != {"id", "name", "settings", "allow_edit", "credential_ref"}
                            or not isinstance(profile["id"], str) or not _ID.fullmatch(profile["id"])
                            or profile["id"] in seen or type(profile["allow_edit"]) is not bool
                            or not isinstance(profile["name"], str) or not 1 <= len(profile["name"]) <= 80
                            or not isinstance(profile["settings"], dict)
                            or set(profile["settings"]) != set(PROFILE_FIELDS)):
                        raise ValueError
                    seen.add(profile["id"])
                    # Endpoint and workspace availability are checked when used;
                    # an offline/moved workspace must not hide all saved history.
                    if profile["credential_ref"] != self._account(profile):
                        raise ValueError
                self._data = data
            except (ValueError, TypeError, KeyError):
                raise ValueError("Bulk target settings are damaged; no targets were enabled") from None

    @staticmethod
    def _account(profile: dict) -> str | None:
        raw = profile["settings"]
        if raw.get("provider") == "local":
            return None
        endpoint = validate_lan_endpoint(raw.get("server_endpoint"), allow_cgnat=raw.get("allow_cgnat") is True)
        return profile["id"] + ":" + sha256(endpoint.encode()).hexdigest()

    def _save(self, data: dict) -> None:
        encoded = json.dumps(data, indent=2, ensure_ascii=True)
        if len(encoded.encode("utf-8")) > 131072:
            raise ValueError("Saved target metadata is too large; remove unused targets or use shorter workspace paths")
        atomic_write_text(self.path, encoded)
        self._data = data

    @property
    def enabled(self) -> bool:
        with self._lock:
            return self._data["enabled"]

    def set_enabled(self, enabled: bool) -> None:
        if type(enabled) is not bool:
            raise ValueError("Choose on or off for bulk tasks")
        with self._lock:
            self._save({**self._data, "enabled": enabled})

    def ids(self) -> tuple[str, ...]:
        with self._lock:
            return tuple(profile["id"] for profile in self._data["targets"])

    def get(self, target_id: str) -> dict:
        with self._lock:
            for profile in self._data["targets"]:
                if profile["id"] == target_id:
                    return deepcopy(profile)
        raise ValueError("The selected bulk target no longer exists")

    def capture(self, settings, *, name: str, allow_edit: bool = False) -> dict:
        if not isinstance(name, str) or not 1 <= len(name.strip()) <= 80 or any(ord(c) < 32 for c in name):
            raise ValueError("Give this target a name of 1–80 characters")
        if type(allow_edit) is not bool:
            raise ValueError("Workspace edit permission must be explicit")
        settings.validate()
        kind = provider_kind(settings)
        if kind not in {"local", "lan"}:
            raise PermissionError("Select a local or LAN brain in Settings before capturing a bulk target")
        if allow_edit and (settings.workspace_edit is not True or not settings.workspace):
            raise PermissionError("Enable workspace editing in Settings before granting edits to this target")
        raw = {key: deepcopy(getattr(settings, key)) for key in PROFILE_FIELDS}
        raw["workspace"] = str(Path(settings.workspace).expanduser().resolve(strict=True)) if settings.workspace else ""
        # Only the selected connection is relevant; discard a different saved server address.
        raw["server_endpoint"] = endpoint_for(settings) if kind == "lan" else ""
        raw["endpoint"] = endpoint_for(settings) if kind == "local" else "http://127.0.0.1:8080/v1"
        profile = {"id": "target_" + uuid.uuid4().hex, "name": name.strip(),
                   "settings": raw, "allow_edit": allow_edit, "credential_ref": None}
        profile["credential_ref"] = self._account(profile)
        with self._lock:
            if not self.enabled:
                raise PermissionError("Bulk tasks are off")
            if len(self._data["targets"]) >= MAX_TARGETS:
                raise ValueError("Bulk tasks allow at most 32 saved targets")
            if any(p["settings"] == raw and p["allow_edit"] == allow_edit for p in self._data["targets"]):
                raise ValueError("This workspace and brain configuration is already captured")
            if kind == "lan":
                endpoint, secret = connection_for(settings)
                if endpoint != raw["server_endpoint"]:
                    raise ValueError("The current brain endpoint changed during capture")
                self.secrets.put(profile["credential_ref"], secret)
            try:
                self._save({**self._data, "targets": [*self._data["targets"], profile]})
            except Exception:
                if kind == "lan":
                    self.secrets.delete(profile["credential_ref"])
                raise
        return deepcopy(profile)

    def remove(self, target_id: str) -> None:
        with self._lock:
            profile = self.get(target_id)
            if profile["credential_ref"]:
                self.secrets.delete(profile["credential_ref"])
            self._save({**self._data, "targets": [p for p in self._data["targets"] if p["id"] != target_id]})

    def credential(self, profile: dict) -> str:
        settings = profile_settings(profile)
        if provider_kind(settings) == "local":
            return "local-only"
        if profile["credential_ref"] != self._account(profile):
            raise PermissionError("The saved credential does not match this brain")
        value = self.secrets.get(profile["credential_ref"])
        if not value:
            raise PermissionError("The saved brain credential is unavailable; remove and recapture this target")
        return value

    def catalog(self, *, workspace_edit: bool = False) -> dict:
        with self._lock:
            result = []
            for profile in self._data["targets"]:
                raw = profile["settings"]
                ready = profile["credential_ref"] is None or bool(self.secrets.get(profile["credential_ref"]))
                valid = True
                try:
                    profile_settings(profile)
                except (ValueError, TypeError, PermissionError):
                    valid = False
                result.append({"id": profile["id"], "name": profile["name"],
                               "project": raw["project"], "workspace": raw["workspace"],
                               "provider": raw["provider"], "model": raw["model"],
                               "endpoint": raw["server_endpoint"] or raw["endpoint"],
                               "can_prompt": valid and ready and bool(raw["model"]),
                               "can_edit": valid and profile["allow_edit"] and workspace_edit is True and bool(raw["workspace"]),
                               "credential_ready": ready})
            return {"enabled": self.enabled, "targets": result, "max_targets": MAX_TARGETS}
