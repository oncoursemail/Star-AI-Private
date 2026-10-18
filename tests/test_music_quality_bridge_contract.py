"""Source contracts for explicitly owner-triggered STAR desktop integrations.

They do not simulate a live Qt window or claim an actual catalog song match.
"""
from pathlib import Path

from star.react_shell import ALLOWED_ACTIONS
from star.desktop_music_quality import OWNER_ACTIONS

ROOT = Path(__file__).resolve().parents[1]


def test_owner_actions_are_exposed_but_not_model_shell_tools():
    assert OWNER_ACTIONS <= ALLOWED_ACTIONS
    for action in (
        "musicStatus", "musicChooseWav", "musicChooseFpcalc", "musicClear", "musicIdentify",
        "qualityChooseFile", "qualityPreview", "qualityClear",
    ):
        assert action in ALLOWED_ACTIONS
    for action in ("musicWatchSystemAudio", "musicAutoListen", "musicUploadAnywhere",
                   "qualityMarkPassed", "qualityApproveOnBehalfOfOwner", "runShell"):
        assert action not in ALLOWED_ACTIONS


def test_only_native_dialog_supplies_audio_and_quality_paths():
    src = (ROOT / "star" / "react_shell.py").read_text(encoding="utf-8")
    assert "QFileDialog.getOpenFileName(" in src
    assert "self.music_quality.select_wav(Path(chosen))" in src
    assert "self.music_quality.select_quality_file(Path(chosen))" in src
    assert "self.music_quality.identify(" in src
    assert "self.active_task or self._in_voice_call()" in src
    assert "self._run(rid, action" in src
    # No direct unapproved route to the audio service from an agent tool.
    assert "music_recognition.recognize_audd" not in src
    assert "music_recognition.capture_microphone" not in src


def test_chat_composer_has_live_music_trigger_and_a_separate_review_ui():
    composer = (ROOT / "frontend" / "src" / "Composer.tsx").read_text(encoding="utf-8")
    desktop = (ROOT / "frontend" / "src" / "Desktop.tsx").read_text(encoding="utf-8")
    assert "<MusicRecognitionButton disabled={busy} />" in composer
    assert "<QualityChecklistPanel disabled={inactive||busy}/>" in desktop
    music = (ROOT / "frontend" / "src" / "MusicRecognition.tsx").read_text(encoding="utf-8")
    assert "uploadConsent:consent.upload" in music
    assert "billingConsent:consent.billing" in music
    assert "noncommercialConsent:consent.noncommercial" in music
    assert "onBackendEvent" in music
