"""Captured target boundaries with real Settings and a disposable secret store."""
from copy import deepcopy
import json

import pytest

from star.bulk_profiles import BulkProfiles, PROFILE_FIELDS, fingerprint, profile_settings
from star.desktop_core import Settings


class FakeSecrets:
    """Only the operating-system credential boundary is substituted."""

    def __init__(self):
        self.values = {}
        self.deleted = []

    def put(self, account, secret):
        self.values[account] = secret

    def get(self, account):
        return self.values.get(account)

    def delete(self, account):
        self.deleted.append(account)
        self.values.pop(account, None)


@pytest.fixture
def store(tmp_path):
    return BulkProfiles(tmp_path / "targets.json", secrets=FakeSecrets())


def test_new_catalog_is_off_and_capture_requires_explicit_enable(store):
    assert store.catalog() == {"enabled": False, "targets": [], "max_targets": 32}
    with pytest.raises(PermissionError, match="off"):
        store.capture(Settings(model="local-test"), name="Local brain")
    assert store.ids() == ()
    assert store.secrets.values == {}
    store.set_enabled(True)
    profile = store.capture(Settings(model="local-test"), name="Local brain")
    assert store.ids() == (profile["id"],)
    assert store.credential(profile) == "local-only"
    assert profile["credential_ref"] is None
    assert store.secrets.values == {}


def test_oversized_metadata_cannot_replace_the_last_readable_registry(store):
    store.set_enabled(True)
    original = store.capture(Settings(model="local-test"), name="Keep this target")
    before = store.path.read_bytes()
    oversized = {"version": 1, "enabled": True, "targets": [deepcopy(original)]}
    oversized["targets"][0]["settings"]["workspace"] = "/" + "界" * 24000
    with pytest.raises(ValueError, match="metadata is too large"):
        store._save(oversized)
    assert store.path.read_bytes() == before
    reopened = BulkProfiles(store.path, secrets=store.secrets)
    assert reopened.get(original["id"]) == original


def test_capture_copies_only_current_supported_settings_and_no_edit_grants(store, tmp_path):
    workspace = tmp_path / "project"
    workspace.mkdir()
    settings = Settings(model="local-test", workspace=str(workspace), workspace_edit=True,
                        studio_luau=True, server_endpoint="http://192.168.1.99:8080/v1")  # star:allow test address
    store.set_enabled(True)
    profile = store.capture(settings, name="  Project brain  ")
    assert profile["name"] == "Project brain"
    assert set(profile["settings"]) == set(PROFILE_FIELDS)
    assert profile["settings"]["server_endpoint"] == ""
    assert profile["settings"]["workspace"] == str(workspace.resolve())
    assert not profile["allow_edit"]
    rebuilt = profile_settings(profile)
    assert rebuilt.workspace_edit is False and rebuilt.studio_luau is False
    original_hash = fingerprint(profile)
    settings.model = "different-model"
    profile["settings"]["model"] = "caller-mutated-model"
    assert store.get(profile["id"])["settings"]["model"] == "local-test"
    assert fingerprint(store.get(profile["id"])) == original_hash
    assert not store.catalog(workspace_edit=True)["targets"][0]["can_edit"]


@pytest.mark.parametrize("provider", ["groq", "openrouter", "gemini", "cerebras"])
def test_cloud_targets_cannot_be_captured(store, provider):
    store.set_enabled(True)
    with pytest.raises(PermissionError, match="local or LAN"):
        store.capture(Settings(provider=provider, model="hosted-model"), name="Hosted")
    assert store.ids() == ()
    assert store.secrets.values == {}


def test_lan_credentials_remain_bound_after_current_key_and_endpoint_change(store, monkeypatch):
    first_key, next_key = "synthetic-first-token", "synthetic-next-token"
    monkeypatch.setenv("STAR_SERVER_API_KEY", first_key)
    settings = Settings(provider="star_server", model="brain-a", server_endpoint="http://192.168.1.10:8080/v1/")  # star:allow test address
    store.set_enabled(True)
    first = store.capture(settings, name="First brain")
    assert first["settings"]["server_endpoint"] == "http://192.168.1.10:8080/v1"  # star:allow test address
    monkeypatch.setenv("STAR_SERVER_API_KEY", next_key)
    settings.server_endpoint = "http://192.168.1.11:8080/v1"  # star:allow test address
    second = store.capture(settings, name="Second brain")
    assert first["credential_ref"] != second["credential_ref"]
    assert store.credential(first) == first_key
    assert store.credential(second) == next_key
    assert store.get(first["id"])["settings"]["server_endpoint"] == "http://192.168.1.10:8080/v1"  # star:allow test address
    serialized = store.path.read_text(encoding="utf-8") + json.dumps(store.catalog())
    assert first_key not in serialized and next_key not in serialized
    assert "credential_ref" not in store.catalog()["targets"][0]
    forged = deepcopy(first)
    forged["settings"]["server_endpoint"] = second["settings"]["server_endpoint"]
    with pytest.raises(PermissionError, match="does not match"):
        store.credential(forged)


def test_missing_captured_credential_fails_without_falling_back_to_current_key(store, monkeypatch):
    monkeypatch.setenv("STAR_SERVER_API_KEY", "synthetic-captured-token")
    store.set_enabled(True)
    profile = store.capture(Settings(provider="star_server", model="brain-a",
                                     server_endpoint="http://192.168.1.10:8080/v1"), name="LAN")  # star:allow test address
    store.secrets.values.clear()
    monkeypatch.setenv("STAR_SERVER_API_KEY", "synthetic-current-different-token")
    with pytest.raises(PermissionError, match="unavailable"):
        store.credential(profile)
    target = store.catalog()["targets"][0]
    assert target["credential_ready"] is False and target["can_prompt"] is False


def test_secure_store_failure_does_not_save_a_plaintext_fallback(store, monkeypatch):
    monkeypatch.setenv("STAR_SERVER_API_KEY", "synthetic-must-not-persist")
    store.set_enabled(True)

    class UnavailableSecrets(FakeSecrets):
        def put(self, account, secret):
            raise RuntimeError("Synthetic secure-store outage")

    store.secrets = UnavailableSecrets()
    with pytest.raises(RuntimeError, match="secure-store"):
        store.capture(Settings(provider="star_server", model="brain-a",
                               server_endpoint="http://192.168.1.10:8080/v1"), name="LAN")  # star:allow test address
    assert store.ids() == ()
    assert "synthetic-must-not-persist" not in store.path.read_text(encoding="utf-8")


def test_enabled_state_and_profiles_survive_restart_and_removal_deletes_only_their_secret(store, monkeypatch):
    monkeypatch.setenv("STAR_SERVER_API_KEY", "synthetic-captured-token")
    store.set_enabled(True)
    profile = store.capture(Settings(provider="star_server", model="brain-a",
                                     server_endpoint="http://192.168.1.10:8080/v1"), name="LAN")  # star:allow test address
    store.set_enabled(False)
    reopened = BulkProfiles(store.path, secrets=store.secrets)
    assert reopened.enabled is False
    assert reopened.get(profile["id"]) == profile
    reopened.remove(profile["id"])
    assert reopened.ids() == ()
    assert store.secrets.deleted == [profile["credential_ref"]]
    assert BulkProfiles(store.path, secrets=store.secrets).ids() == ()


def test_edit_grant_requires_a_real_workspace_and_current_edit_permission(store, tmp_path):
    store.set_enabled(True)
    with pytest.raises(PermissionError):
        store.capture(Settings(model="test"), name="No workspace", allow_edit=True)
    with pytest.raises(PermissionError):
        store.capture(Settings(model="test", workspace=str(tmp_path)), name="No permission", allow_edit=True)
    settings = Settings(model="test", workspace=str(tmp_path), workspace_edit=True)
    profile = store.capture(settings, name="Approved", allow_edit=True)
    assert profile["allow_edit"] is True
    assert store.catalog(workspace_edit=False)["targets"][0]["can_edit"] is False
    assert store.catalog(workspace_edit=True)["targets"][0]["can_edit"] is True


def test_offline_workspace_keeps_metadata_available_but_is_not_runnable(store, tmp_path):
    workspace = tmp_path / "project"
    workspace.mkdir()
    store.set_enabled(True)
    profile = store.capture(Settings(model="test", workspace=str(workspace), workspace_edit=True),
                            name="Moved workspace", allow_edit=True)
    workspace.rename(tmp_path / "moved")
    reopened = BulkProfiles(store.path, secrets=store.secrets)
    assert reopened.get(profile["id"]) == profile
    target = reopened.catalog(workspace_edit=True)["targets"][0]
    assert target["can_prompt"] is False and target["can_edit"] is False


def test_duplicate_capture_cannot_silently_multiply_the_same_configuration(store):
    store.set_enabled(True)
    first = store.capture(Settings(model="test"), name="First name")
    with pytest.raises(ValueError, match="already captured"):
        store.capture(Settings(model="test"), name="Different name")
    assert store.ids() == (first["id"],)


@pytest.mark.parametrize("field,value", [("enabled", 1), ("allow_edit", 1)])
def test_permission_fields_require_booleans(store, field, value):
    with pytest.raises(ValueError):
        if field == "enabled":
            store.set_enabled(value)
        else:
            store.set_enabled(True)
            store.capture(Settings(model="test"), name="Invalid grant", allow_edit=value)


def test_endpoint_tampering_in_saved_metadata_cannot_rebind_an_existing_secret(store, monkeypatch):
    monkeypatch.setenv("STAR_SERVER_API_KEY", "synthetic-captured-token")
    store.set_enabled(True)
    store.capture(Settings(provider="star_server", model="test",
                           server_endpoint="http://192.168.1.10:8080/v1"), name="LAN")  # star:allow test address
    data = json.loads(store.path.read_text(encoding="utf-8"))
    data["targets"][0]["settings"]["server_endpoint"] = "http://192.168.1.11:8080/v1"  # star:allow test address
    store.path.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(ValueError, match="damaged"):
        BulkProfiles(store.path, secrets=store.secrets)
