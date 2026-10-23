"""React source/host checks without requiring Qt imports on Linux."""
from pathlib import Path
from star.react_shell import ALLOWED_ACTIONS, PERMITTED_SETTINGS, react_index

ROOT=Path(__file__).resolve().parents[1]

def test_react_native_bridge_commands_are_explicit():
    assert 'sendMessage' in ALLOWED_ACTIONS
    assert 'installBrain' in ALLOWED_ACTIONS
    assert 'discoverStudio' in ALLOWED_ACTIONS
    assert 'run_arbitrary_shell' not in ALLOWED_ACTIONS

def test_strata_settings_are_permitted_but_no_secret_or_remote_host_is_added():
    expected = {
        'strata_enabled','strata_endpoint','strata_model','strata_reasoning',
        'strata_context_tokens','strata_timeout','strata_vision_enabled',
    }
    assert expected <= PERMITTED_SETTINGS
    assert 'strata_api_key' not in PERMITTED_SETTINGS


def test_react_web_sources_exist():
    assert (ROOT/'frontend/src/App.tsx').is_file()
    assert (ROOT/'frontend/src/Desktop.tsx').is_file()
    assert (ROOT/'frontend/src/bridge.ts').is_file()
    assert (ROOT/'frontend/src/styles.css').is_file()

def test_windows_workflow_builds_react_assets():
    workflow=(ROOT/'.github/workflows/windows-desktop.yml').read_text()
    assert 'frontend/dist' in workflow
    assert 'npm run build' in workflow
    assert '--add-data' in workflow
