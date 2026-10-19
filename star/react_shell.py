"""STAR React Desktop shell and narrowly exposed Qt WebChannel service.

React is bundled locally under frontend/dist, never loaded from a remote site.
Every privileged action stays behind this explicit Python command registry.
The existing persistent SQLite files, model install paths, and Roblox MCP
adapters are reused without migration or credential exposure to JavaScript.
"""
from __future__ import annotations
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass
from pathlib import Path
import hashlib
import json
import os
import re
import sqlite3
import sys
import tempfile
import threading
import time
import uuid

from .desktop_core import Settings, Conversations, app_data, run_task, query_models, check_studio
from .analytics import get_dashboard
from .brain_overview import brain_snapshot, planner_snapshot
from .brain_setup import BrainInstall, install_brain
from .local_runtime import Runtime
from .version import __version__
from .build_info import read_build_info
from .intelligence import for_settings
from .providers import credential_status, save_api_key, clear_api_key, provider_kind
from .model_health import (explain_model_failure, missing_model_message, note_server_result,
                           probe_server, server_status)
from .chat_images import chat_image, generate_chat_image, latest_generated_path
from .comfy import ComfyError
from .warmup import Warmer
from .prefill_warm import DraftWarmer
from .diagnostics import export_review_bundle
from .screen_capture import (require_consent as require_screen_consent, store_capture as store_screen_capture,
                             describe as describe_screen_capture, preview_url as screen_preview_url)
from .mcp_connections import MCPGateway
from .blender_bridge import status as blender_status
from .studio_connections import connection_status, validate_target, select_instance
from .studio_host import STUDIO_HOST_ACTIONS, handle as handle_studio_host
from .tool_workshop import ToolWorkshop
from .voice.bridge import VOICE_ACTIONS, VoiceBridge
from .discord_supervisor import DISCORD_ACTIONS, DiscordSupervisor, handle_action as handle_discord_action, start_if_opted_in
from .clips_obs import CLIP_ACTIONS, ClipService
from .clip_library import ClipLibrary
from .steelseries_moments import MomentsEvents
from .game_lab_catalog import catalog as game_lab_catalog
from .lessons import (LESSON_ACTIONS, handle_action as handle_lesson_action,
                      import_bundled_lessons, learning_status, write_export)
from .learned_week import LEARNED_ACTIONS, handle_action as handle_learned_action, import_bundled as import_learning_bundle
from .corrections import CORRECTION_ACTIONS, handle_action as handle_correction_action
from .lesson_digest import Digester, may_start_automatic
from . import image_gen
from .media_actions import (MEDIA_ACTIONS, SLOW_MEDIA_ACTIONS, ComfyLauncher, effective_comfy_home,
                            handle as handle_media_action)
from . import media_places
from . import gpu_helper
from .chat_media import prepare_turn
from .roblox_cloud import (ROBLOX_ACTIONS, ROBLOX_NETWORK_ACTIONS, RobloxCloud,
                           handle_action as handle_roblox_action)

ALLOWED_ACTIONS = frozenset({
    'bootstrap','brainSnapshot','plannerStatus','switchProject','pickFiles','sendMessage','saveSettings',
    'installBrain','startBrain','listModels','testModel','discoverStudio','selectStudio',
    'checkUpdates','installUpdate','transcribe','openDataFolder', 'copyText', 'openLegacy', 'selectFolder',
    'generateImage','saveProviderKey','clearProviderKey','cancelMessage','exportReviewBundle',
    'newChat','switchChat','testMcpConnection','runTeam','rememberDecision','listLearning',
    'researchStatus','researchCheck','researchEvidence','researchNominate',
    'listCustomTools','previewCustomTool','approveCustomTool','disableCustomTool',
    'startModelRouter','stopBrain','testModelTeam','testServer','warmUp','warmDraft','testBlender',
    'serverKeyFileStatus','importServerKeyFile',
    # Sidebar chat menu (rename, delete after the Undo window) and the composer's
    # "Look at my screen", which needs the owner's per-use consent (star/screen_capture.py).
    'renameChat','deleteChat','captureScreen',
    # Settings > Use my GPU (star/gpu_helper.py): its status line and the on/off switch.
    'gpuHelperStatus','gpuHelperSet',
})
# Voice calls keep their own action list (star/voice/bridge.py, docs/STAR_VOICE_CALLS.md).
ALLOWED_ACTIONS = ALLOWED_ACTIONS | VOICE_ACTIONS
# Voice actions that make sound must run where Settings → Where STAR generates says (star/media_places.py).
VOICE_PLACE_ACTIONS = frozenset({'voiceStartCall', 'voicePreviewVoice', 'voiceSpeak'})
# Learning: review of lessons and thumbs on answers (star/lessons.py), plus the optional
# background rewording of raw captures (star/lesson_digest.py).
ALLOWED_ACTIONS = ALLOWED_ACTIONS | LESSON_ACTIONS | {'digestLessons'}
# What STAR learned this week (undo / restore / keep) and owner corrections that may become regression tests
# (star/learned_week.py, star/corrections.py, docs/SELF_LEARNING_LOOP.md).
ALLOWED_ACTIONS = ALLOWED_ACTIONS | LEARNED_ACTIONS | CORRECTION_ACTIONS
# Media: where images, voice and video run, the image engine on this PC, and a project's
# visual references (star/media_actions.py, docs/STAR_MEDIA.md).
ALLOWED_ACTIONS = ALLOWED_ACTIONS | MEDIA_ACTIONS
# Roblox Open Cloud: the owner's key, its test, the test experience and the approval of each write
# the model asked for (star/roblox_cloud.py, docs/ROBLOX_ACCESS.md). Never a publish action itself.
ALLOWED_ACTIONS = ALLOWED_ACTIONS | ROBLOX_ACTIONS
# Settings > Roblox Studio: whether an operator-made STAR Studio server connection exists
# (star/studio_host.py). Read-only: the page cannot store one, and the command is never sent to it.
ALLOWED_ACTIONS = ALLOWED_ACTIONS | STUDIO_HOST_ACTIONS
# Settings > Discord: status, Start/Stop and the opt-in autostart for the Discord bot process
# (star/discord_supervisor.py). Never carries the token, the owner's IDs or any key.
ALLOWED_ACTIONS = ALLOWED_ACTIONS | DISCORD_ACTIONS
# STAR Clips only accepts explicit desktop UI clicks; never model tool calls.
ALLOWED_ACTIONS = ALLOWED_ACTIONS | CLIP_ACTIONS
# Optional read-only clip folders and developer-owned SteelSeries Moments events.
CLIP_INTEROP_ACTIONS = frozenset({
    'clipChooseFolder', 'clipListFolder', 'clipClearFolder', 'clipOpenFile',
    'clipMomentsStatus', 'clipMomentsRegister', 'clipMomentsTrigger',
})
ALLOWED_ACTIONS = ALLOWED_ACTIONS | CLIP_INTEROP_ACTIONS
# A static read-only source index; no arbitrary fetch/install/execute capability.
ALLOWED_ACTIONS = ALLOWED_ACTIONS | {'gameLabCatalog'}

# A background warm-up (server check + prompt-cache priming) gives way at once to
# anything that talks to the model server or changes what it would talk to.
WARM_UP_STOPPERS = frozenset({
    'sendMessage','runTeam','generateImage','testServer','testModel','testModelTeam','listModels',
    'startModelRouter','stopBrain','startBrain','installBrain','saveSettings','switchProject',
    'saveProviderKey','clearProviderKey','newChat','switchChat','testBlender','deleteChat',
})

# Settings the React interface may change. Never a credential: provider and
# server keys go straight to the OS keyring through saveProviderKey.
PERMITTED_SETTINGS = frozenset({
    'endpoint','model','fast_model','reasoning_model','roblox_model','vision_model',
    'router_models_dir','router_context','gpu_layers','roblox_research_enabled','asset_forge_enabled',
    'tool_workshop_enabled','specialists_enabled','specialist_parallelism','provider',
    'project','workspace','studio_target','studio_edit','studio_own_places','studio_luau','studio_tool_examples','workspace_edit','max_calls',
    'context_chars','reduced_motion','comfy_workflow','comfy_prompt_node','comfy_port',
    'obsidian_vault','obsidian_enabled','skills_enabled','graphify_enabled',
    'mcp_graphify_docs','mcp_graphify_local','mcp_graphify_port','mcp_obsidian_live',
    'blender_enabled','blender_edit','blender_executable','blender_brain2',
    'server_endpoint','server_timeout','server_parallel','server_context_tokens','allow_cgnat',
    'instant_route_enabled','web_auto_search',
    'knowledge_endpoint','luau_run_before_answer',
    'learning_auto_accept','learning_digest','learning_digest_cloud','practice_lessons_enabled','worked_examples_enabled','learning_auto_live','research_auto_check','skill_pack_embeddings','roblox_docs_live_enabled', 'project_rules_enabled', 'luau_retry_ladder', 'presolve_enabled',
    'media_images','media_voice','media_video','media_chat_auto','session_capabilities_prompt','media_use_references','comfy_home','ffmpeg_dir',
    'picture_max_side',
    'best_of_n','best_of_n_max',
    # Use my GPU: where its files are and when it unloads. The switch itself is `gpuHelperSet`, saved at once.
    'gpu_helper_server','gpu_helper_model','gpu_idle_minutes',
    'prefill_while_typing',   # star/prefill_warm.py: warm the prompt cache with the draft, off by default
})

# Settings > Media "session capabilities" line: put before the owner's words of every turn (and of a draft warm-up).
SESSION_CAPABILITIES = ('Session capabilities: Image creation is available through STAR chat when the local engine is configured. '
                        'Other features depend on the current setup.\n\n')


def prepare_desktop_update(bridge, request_id: str, home: Path) -> dict:
    """Stage an official verified Setup and record it before asking Qt to exit."""
    from .updates import ADMIN_PROMPT_NOTE, install_scope, stage_installer, get_latest, select_downloaded_installer
    result = get_latest()
    if not result.available:
        raise RuntimeError('No newer update is available')
    # Issue 121: an all-users copy is upgraded in administrative mode, so Windows will ask for
    # approval. That prompt is required; say so before it appears instead of surprising the owner.
    admin_prompt = install_scope() == 'all-users'
    note = (' ' + ADMIN_PROMPT_NOTE) if admin_prompt else ''
    bridge._emit(request_id, 'progress', {'phase': 'Downloading and verifying STAR Setup' + note,
                                           'downloaded': 0, 'total': 0})
    candidate = stage_installer(result, home, progress=lambda done, total:
        bridge._emit(request_id, 'progress', {'phase': 'Downloading verified update' + note,
                                               'downloaded': done, 'total': total}))
    if not candidate.checksum_verified or not candidate.expected_sha256:
        raise PermissionError('Automatic restart requires a checksum-verified installer')
    # Setup starts only after the window has closed, where a refusal can no longer
    # be shown. Run the file checks that launch_installer repeats now, while the
    # interface can still report a problem.
    select_downloaded_installer(candidate.path)
    bridge.pending_update = candidate
    bridge.shutdownRequested.emit()
    return {'status': 'pending_restart', 'version': candidate.version, 'administrator_prompt': admin_prompt}


def finish_desktop_update(shell, instance) -> None:
    """Close desktop resources and release the single-instance lock before Setup.

    The bridge worker only stages a verified candidate and requests Qt to quit.
    Launch must happen after the event loop has stopped, not on that worker.
    If closing fails, the lock is still released, Setup is not started and the
    error propagates.
    """
    candidate = shell.bridge.pending_update if shell is not None else None
    try:
        if shell is not None:
            shell.close()
    finally:
        if instance is not None:
            instance.close()
    if candidate is not None:
        from .updates import launch_installer
        launch_installer(candidate, unattended=True)


def run_desktop(app, make_shell, instance, adopt=lambda shell: None) -> int:
    """Show the window, run the Qt event loop, then clean up and run any staged Setup.

    `adopt(shell)` receives the window before it is shown so that a second launch
    can bring it to the front. Cleanup runs even if the window cannot be built.
    """
    shell = None
    try:
        shell = make_shell()
        adopt(shell)
        shell.show()
        return app.exec()
    finally:
        finish_desktop_update(shell, instance)


def apply_setting_changes(settings: Settings, changes: dict) -> Settings:
    """Copy only allowlisted fields from the interface onto saved settings."""
    if not isinstance(changes, dict):
        raise ValueError('Invalid settings')
    changed_target = 'studio_target' in changes and validate_target(changes['studio_target']) != settings.studio_target
    for key, value in changes.items():
        if key in PERMITTED_SETTINGS:
            setattr(settings, key, value)
    if changed_target:
        settings.studio_id = ''
        settings.studio_edit = False
        settings.studio_luau = False
    return settings


def server_settings_for(action: str, settings_file: Path) -> Settings | None:
    """Saved settings when `action` talks to the selected STAR Server, else None."""
    if action not in {'sendMessage','testModel','listModels','runTeam','testModelTeam'}:
        return None
    try:
        current = Settings.load(settings_file)
        return current if provider_kind(current) == 'lan' else None
    except Exception:
        return None


def media_failure(exc: Exception) -> str | None:
    """Media errors are written for the owner already (what happened and the next step): show them whole."""
    from .comfy import ComfyError
    from .video_understanding import VideoError
    if isinstance(exc, (ComfyError, media_places.PlaceUnavailable, VideoError)):
        return str(exc)[:900]
    return None


def describe_failure(action: str, exc: Exception, settings_file: Path) -> str:
    """One short, secret-free line for the interface when a worker fails."""
    media = media_failure(exc)
    if media is not None:
        return media
    model_error = (getattr(exc, 'status_code', None) is not None
                   or type(exc).__name__ in {'APIConnectionError', 'APITimeoutError'}
                   or 'System message must be at the beginning' in str(exc))
    server = server_settings_for(action, settings_file)
    if server is not None:
        import httpx
        if model_error or isinstance(exc, httpx.HTTPError):
            status = getattr(exc, 'status_code', None)
            if status is None or status in (401, 403, 503):
                # Unreachable, timed out, wrong key or still loading: the status
                # light should stop claiming the server is ready.
                note_server_result(server, False, 'request_failed')
            return explain_model_failure(exc, provider_kind='lan')
    elif action in {'sendMessage', 'startBrain', 'testModel'} and model_error:
        return explain_model_failure(exc)
    return f'{type(exc).__name__}: {str(exc)[:350]}'


def react_index(root: Path | None = None) -> Path:
    """Resolve the static SPA from either source checkout or PyInstaller bundle."""
    base = root or Path(getattr(sys, '_MEIPASS', Path(__file__).resolve().parents[1]))
    return Path(base) / 'frontend' / 'dist' / 'index.html'


_SPECIALIST_ROLES = frozenset({'planner','research','luau','ui','animation',
                               'environment','review','integration'})
_TEAM_STAGES = frozenset({'evidence','design','critic','synthesis'})
_ROUTE_PROFILES = frozenset({'fast','reasoning','roblox','vision','research','agent'})
_STEP_STATES = {'completed':'done','done':'done','failed':'failed','blocked':'blocked',
                'cancelled':'cancelled'}
_TOOL_NAME = re.compile(r'[A-Za-z][A-Za-z0-9_.-]{0,47}')
# A model id as a server or provider names it ("star-voice", "openai/gpt-oss-20b"). Shown as
# plain text in the status popover and the activity record; anything else is not forwarded.
_MODEL_NAME = re.compile(r'[A-Za-z0-9][A-Za-z0-9._:/+-]{0,79}')
_REPAIR_CHECKS = {
    'python.compile': 'Python syntax check',
    'json.loads': 'JSON syntax check',
    'tomllib.loads': 'TOML syntax check',
    'luau.lint': 'Luau advisory check',
    'tool.result': 'Tool result check',
    'none': 'Repair check',
}
_REPAIR_KINDS = frozenset({'syntax', 'advisory', 'tool_error', 'unknown_outcome', 'budget'})


def _model_name(value):
    return value if isinstance(value, str) and _MODEL_NAME.fullmatch(value) else None


def _opaque_id(value) -> str:
    """Stable row key for the activity view that never reveals a model-authored id."""
    return 't' + hashlib.sha256(str(value).encode('utf-8', 'replace')).hexdigest()[:10]


def _bounded_int(value, top: int):
    return value if type(value) is int and 0 <= value <= top else None


def sanitize_event(event: dict) -> dict:
    """Never forward raw tool results/secret tokens to an unrestricted webpage.

    `phase` stays a short human sentence. `activity` is the structured form the
    chat's activity timeline renders: only enumerated kinds, states and roles,
    bounded integers, an opaque step key, and the name of a tool that already
    passed authorization. Goals, arguments, outputs and model-authored task ids
    are never included.
    """
    kind = str(event.get('event', 'working'))[:36]
    if kind == 'team_planned':
        steps = []
        tasks = event.get('tasks')
        for item in (tasks if isinstance(tasks, list) else [])[:8]:
            if not isinstance(item, dict) or item.get('id') not in _TEAM_STAGES:
                continue
            needs = item.get('dependencies')
            steps.append({
                'id': item['id'],
                'role': item.get('role') if item.get('role') in _SPECIALIST_ROLES else 'research',
                'needs': [d for d in (needs if isinstance(needs, (list, tuple)) else ())[:8]
                          if d in _TEAM_STAGES],
            })
        return {'phase': 'STAR Teams: plan ready',
                'activity': {'type': 'plan', 'group': 'team', 'steps': steps}}
    if kind in {'agent_started','agent_finished','agent_blocked'}:
        role=str(event.get('role','agent'))[:24]
        if role not in _SPECIALIST_ROLES:
            role='agent'
        status=str(event.get('status','working'))[:18]
        task=event.get('task')
        state=('running' if kind == 'agent_started' else 'blocked' if kind == 'agent_blocked'
               else _STEP_STATES.get(status, 'failed'))
        activity={'type':'agent','group':'team',
                  'id':task if task in _TEAM_STAGES else _opaque_id(task),
                  'role':role if role != 'agent' else 'specialist','state':state}
        elapsed=_bounded_int(event.get('elapsed_ms'), 3_600_000)
        if kind == 'agent_finished' and elapsed is not None:
            activity['elapsed_ms']=elapsed
        return {'phase':f'STAR Teams: {role} — {state if kind != "agent_started" else "working"}',
                'activity':activity}
    if kind == 'assistant_delta':
        return {'phase':'Generating response', 'delta':str(event.get('text',''))[:2500]}
    if kind in {'subagent_started','subagent_finished'}:
        role=str(event.get('role','research'))[:30]
        if role not in _SPECIALIST_ROLES:
            role='research'
        status='working' if kind=='subagent_started' else str(event.get('status','done'))[:16]
        if kind == 'subagent_finished' and status not in _STEP_STATES:
            status='failed'
        state='running' if kind == 'subagent_started' else _STEP_STATES[status]
        return {'phase':f'STAR {role} specialist · {status}',
                'activity':{'type':'agent','group':'specialist',
                            'id':_opaque_id(event.get('task_id')),'role':role,'state':state}}
    if kind == 'route_selected':
        activity={'type':'route'}
        if event.get('profile') in _ROUTE_PROFILES:
            activity['profile']=event['profile']
        if _model_name(event.get('model')):
            activity['model']=event['model']       # the model this message is sent to
        return {'phase': 'STAR · ' + str(event.get('description', 'Selecting model'))[:90],
                'activity':activity}
    if kind == 'instant_selected':
        activity = {'type': 'instant'}
        if _model_name(event.get('model')):
            activity['model'] = event['model']
        return {'phase': 'Answering on this PC', 'activity': activity}
    if kind == 'instant_fallback':
        activity = {'type': 'instant_fallback'}
        if _model_name(event.get('model')):
            activity['model'] = event['model']
        return {'phase': 'On-device answer unavailable; using STAR Server', 'activity': activity}
    if kind == 'answer_stats':
        activity = {'type': 'answer_stats'}
        if event.get('brain') in {'pc', 'server', 'cloud'}:
            activity['brain'] = event['brain']
        if _model_name(event.get('model')):
            activity['model'] = event['model']
        first = _bounded_int(event.get('first_token_ms'), 3_600_000)
        if first is not None:
            activity['first_token_ms'] = first
        rate = event.get('tokens_per_second')
        if type(rate) in (int, float) and 0 <= rate <= 10000:
            activity['tokens_per_second'] = round(float(rate), 1)
        activity['estimated_tokens'] = event.get('estimated_tokens') is True
        return {'phase': 'Answer complete', 'activity': activity}
    if kind == 'route_fallback':
        # The model chosen for this job is missing or did not load; the configured one answers.
        activity={'type':'route','fallback':True}
        if _model_name(event.get('model')):
            activity['model']=event['model']
        return {'phase':'That model is not available. Using your main model','activity':activity}
    if kind == 'worked_example_used':
        count = _bounded_int(event.get('count'), 2)
        if count is not None and count > 0:
            return {'phase':f'Using {count} checked practice example' + ('s' if count != 1 else ''),
                    'activity':{'type':'example','count':count}}
        return {'phase':'Reviewing local reference data'}
    if kind == 'model_answered':
        # The model name the server itself reported on the answer.
        activity={'type':'model'}
        if _model_name(event.get('model')):
            activity['model']=event['model']
        return {'phase':'Finishing the answer','activity':activity}
    if kind in {'search_started','search_finished'}:
        started = kind == 'search_started'
        return {'phase':'Searching the web' if started else 'Web search finished',
                'activity':{'type':'search','state':'running' if started else 'done'}}
    if kind in {'knowledge_started','knowledge_finished'}:
        # Official documentation lookup on STAR Server. Only a state and two bounded numbers
        # leave the host; the query and the passages never do.
        state=str(event.get('state',''))
        activity={'type':'docs','state':'running' if kind == 'knowledge_started'
                  else 'done' if state in {'ok','empty'} else 'failed'}
        for key,top in (('passages',10),('elapsed_ms',600_000)):
            count=_bounded_int(event.get(key), top)
            if kind == 'knowledge_finished' and count is not None:
                activity[key]=count
        return {'phase':'Reading the official documentation' if kind == 'knowledge_started'
                else 'Documentation ready' if activity['state'] == 'done' else 'Documentation unavailable',
                'activity':activity}
    if kind in {'repair_detected', 'repair_check_passed', 'repair_blocked'}:
        # Adapter-owned facts only. Diagnostics, file paths, model text and opaque
        # output never cross into the page, even when an event carries extra fields.
        checker = event.get('checker')
        checker = checker if isinstance(checker, str) and checker in _REPAIR_CHECKS else 'none'
        repair_kind = event.get('kind')
        repair_kind = (repair_kind if isinstance(repair_kind, str) and repair_kind in _REPAIR_KINDS
                       else 'unknown_outcome')
        result = {'repair_detected': 'detected', 'repair_check_passed': 'check_passed',
                  'repair_blocked': 'blocked'}[kind]
        # An unknown checker or outcome cannot be promoted into a passed check.
        if result == 'check_passed' and (checker == 'none' or repair_kind in {'unknown_outcome', 'budget'}):
            result = 'blocked'
        advisory = result == 'detected' and repair_kind == 'advisory' and checker == 'luau.lint'
        state = 'done' if result == 'check_passed' or advisory else 'failed' if result == 'detected' else 'blocked'
        repair_activity: dict = {'type': 'repair', 'result': result, 'state': state,
                                 'checker': checker, 'kind': repair_kind}
        for key, top in (('count', 100), ('attempt', 2)):
            count = _bounded_int(event.get(key), top)
            if count is not None:
                repair_activity[key] = count
        if result == 'check_passed':
            phase = ('Tool call returned successfully' if checker == 'tool.result'
                     else _REPAIR_CHECKS[checker] + ' passed')
        elif result == 'blocked':
            phase = ('Focused repair limit reached' if repair_kind == 'budget' and repair_activity.get('attempt') == 2
                     else 'Work paused for a repair' if repair_kind == 'budget'
                     else 'Tool outcome needs inspection' if repair_kind == 'unknown_outcome'
                     else 'Automatic repair paused')
        else:
            phase = ('Luau advisory check reported possible issues' if advisory
                     else 'A tool reported a problem' if repair_kind == 'tool_error'
                     else 'A tool outcome is unconfirmed' if repair_kind == 'unknown_outcome'
                     else _REPAIR_CHECKS[checker] + ' reported a problem')
        return {'phase': phase, 'activity': repair_activity}
    if kind in {'luau_check_started','luau_repair_started','luau_check_finished'}:
        state=str(event.get('state',''))
        result=state if state in {'passed','failed','repaired','unavailable'} else ''
        activity={'type':'luau_check','state':'running' if kind != 'luau_check_finished'
                  else 'failed' if result in {'failed','unavailable'} else 'done'}
        if kind == 'luau_check_finished' and result:
            activity['result']=result
        if kind == 'luau_repair_started':
            activity['repair']=True
        return {'phase':'Fixing the Luau code' if kind == 'luau_repair_started' else 'Checking the Luau code'
                if kind == 'luau_check_started' else 'Luau check finished','activity':activity}
    if kind.startswith('best_of_n_'):
        # Generate several, test, keep what works (star/best_of_n.py): numbers only, never answer text.
        n = _bounded_int(event.get('n'), 8)
        index = _bounded_int(event.get('index'), 8)
        passed, ran = _bounded_int(event.get('passed'), 20), _bounded_int(event.get('ran'), 20)
        score = f' ({passed}/{ran} checks)' if passed is not None and ran else ''
        if kind == 'best_of_n_started' and n:
            return {'phase': f'Writing {n} versions to test'}
        if kind == 'best_of_n_candidate' and index:
            return {'phase': f'Version {index} ' + ('written' if event.get('state') == 'written' else 'did not finish')}
        if kind == 'best_of_n_checked' and index:
            return {'phase': f'Checked version {index}{score}'}
        if kind == 'best_of_n_judging':
            return {'phase': 'Comparing the versions that passed'}
        if kind == 'best_of_n_repair':
            return {'phase': 'No version passed every check: fixing the best one'}
        if kind == 'best_of_n_selected' and index:
            return {'phase': f'Keeping version {index}{score}'}
        if kind == 'best_of_n_skipped':
            return {'phase': 'Model slots busy: writing one version'}
        return {'phase': 'Testing versions'}
    if kind == 'model_turn':
        activity={'type':'turn'}
        for key in ('step','max_steps'):
            count=_bounded_int(event.get(key), 64)
            if count:
                activity[key]=count
        return {'phase':'Thinking','activity':activity}
    if kind == 'finished':
        activity={'type':'finished'}
        for key in ('model_calls','tool_calls'):
            count=_bounded_int(event.get(key), 999)
            if count is not None:
                activity[key]=count
        return {'phase':'Finishing the answer','activity':activity}
    if kind in {'saved','run_completed'}:
        return {'phase':'Saving verified task record','activity':{'type':'saved'}}
    if kind in {'tool_started','tool_finished','tool_rejected'}:
        state=('running' if kind == 'tool_started' else 'blocked' if kind == 'tool_rejected'
               else 'failed' if event.get('is_error') else 'done')
        activity={'type':'tool','state':state}
        name=event.get('tool')
        # A rejected name never passed authorization and may be invented by the model.
        if kind != 'tool_rejected' and isinstance(name, str) and _TOOL_NAME.fullmatch(name):
            activity['tool']=name
        return {'phase':'A tool request was not permitted' if kind == 'tool_rejected'
                else 'Using an authorized local tool','activity':activity}
    if kind in {'tool_call','tool_result','tool_output'}:
        return {'phase':'Using an authorized local tool'}
    if kind == 'model_responding':
        # First streamed chunk: the server has read the prompt and started to write.
        return {'phase':'The model is writing'}
    if kind == 'tool_requested':
        # The model began to write a tool call. Nothing is authorized or run yet, so no name.
        return {'phase':'Preparing a tool request'}
    if kind == 'model_started':
        # Routing and context are ready; the request goes out next (after Studio connects, if it is used).
        return {'phase':'Contacting the model'}
    if kind == 'documents_started':
        return {'phase': 'Reading attached documents'}
    if kind == 'documents_ready':
        return {'phase': 'Attached documents ready'}
    # An event without wording of its own still reads as a sentence, never as an internal name.
    return {'phase':'STAR is working'}


# Bridge actions that save a user message first and then try to answer it.
TURN_ACTIONS = frozenset({'sendMessage', 'generateImage', 'runTeam'})


@dataclass(frozen=True)
class TurnRef:
    """The saved user message a running turn answers (set once that message is stored)."""
    project: str
    chat_id: str
    user_id: int


def failure_outcome(action: str, exc: Exception, *, cancelled: bool = False,
                    settings_file: Path | None = None) -> tuple[str, str]:
    """Return ``(status, user_message)`` for a worker that raised.

    status is 'cancelled' when the user pressed Stop (or the error says so) and
    'failed' otherwise. The message is what the UI shows and what is stored.
    """
    from .model_health import explain_model_failure
    if cancelled or 'cancelled by user' in str(exc).lower():
        return 'cancelled', explain_model_failure(RuntimeError('cancelled by user'))
    if settings_file is not None:
        # Provider-aware wording (STAR Server vs local brain) and the server status light.
        return 'failed', describe_failure(action, exc, settings_file)
    if (action in {'sendMessage', 'startBrain', 'testModel'}
            and (getattr(exc, 'status_code', None) is not None
                 or type(exc).__name__ in {'APIConnectionError', 'APITimeoutError'}
                 or 'System message must be at the beginning' in str(exc))):
        return 'failed', explain_model_failure(exc)
    return 'failed', media_failure(exc) or f'{type(exc).__name__}: {str(exc)[:350]}'


def record_turn_failure(home: Path, turn: TurnRef, status: str, detail: str) -> bool:
    """Persist the terminal record of a turn that ended without an answer.

    Never raises: a storage problem must not hide the original error from the UI.
    """
    try:
        chats = Conversations(home / 'conversations.sqlite3')
        try:
            chats.add_terminal(turn.project, turn.chat_id, turn.user_id, status, detail)
        finally:
            chats.close()
        return True
    except Exception:
        return False


def run_worker(request_id: str, action: str, worker, *, emit, home: Path,
               current_turn, cancelled, settings_file: Path | None = None, settled=lambda: None) -> None:
    """Run one bridge worker and emit exactly one result or error event.

    A failed or cancelled chat/image/team turn is stored BEFORE its error event is
    emitted, so a reload or restart shows the same history the UI just displayed.
    `settled()` runs just before the event (after a failure is stored): the bridge clears its
    busy flag there, so a message sent the moment the interface sees the result is accepted.
    """
    try:
        data = worker()
    except Exception as exc:
        status, detail = failure_outcome(action, exc, cancelled=bool(cancelled()),
                                         settings_file=settings_file)
        turn = current_turn() if action in TURN_ACTIONS else None
        if turn is not None:
            record_turn_failure(home, turn, status, detail)
        settled()
        emit(request_id, 'error', detail)
        return
    settled()
    try:
        emit(request_id, 'result', data)
    except Exception as exc:
        emit(request_id, 'error', f'{type(exc).__name__}: {str(exc)[:350]}')


def roblox_state(home: Path) -> dict:
    """Roblox connection summary for the interface: no network call and never the key."""
    try:
        return RobloxCloud(home=home).status()
    except Exception:
        return {'key_present': False, 'source': '', 'state': 'no_key', 'message': '', 'last_check': None,
                'test_experience': None, 'pending_actions': 0, 'denied_place_ids': [],
                'denied_universe_ids': []}


def file_allowed(path: Path, approved: set[Path]) -> Path:
    resolved = path.expanduser().resolve(strict=True)
    if resolved not in approved:
        raise PermissionError('Choose the file through STAR Attach before using it')
    if resolved.stat().st_size > 700_000_000:
        raise ValueError('Media file exceeds the supported size limit')
    return resolved


def _chat_view(home: Path, settings: Settings, busy: bool = False) -> dict:
    """The chat part of the state: what changes when the owner opens, starts or deletes a chat."""
    chats = Conversations(home / 'conversations.sqlite3')
    try:
        active_chat = chats.active_chat(settings.project)
        chat_threads = chats.list_chats(settings.project)
        recent = chats.recent_records(settings.project, limit=80, chat_id=active_chat)
        retry = chats.retry_state(settings.project, active_chat, busy=busy)
        projects = sorted(set(chats.projects() + [settings.project]))
    finally:
        chats.close()
    messages = []
    for i, record in enumerate(recent):
        role, body, created = record['role'], record['body'], record['created']
        entry = {'id':f'saved-{i}', 'role':role,'text':body,'created':created}
        if role == 'assistant':
            # The stored row id lets the owner rate this answer; `feedback` is their current thumb.
            entry['mid'] = record['id']
            if record['feedback']:
                entry['feedback'] = record['feedback']
        if record['status'] != 'complete':
            entry['status'] = record['status']  # 'failed' | 'cancelled' terminal record
        preview = chat_image(home, body) if role == 'assistant' else None
        if preview:
            entry.update(preview)
        messages.append(entry)
    return {'project': settings.project, 'projects': projects, 'messages': messages,
            'active_chat': active_chat, 'chats': chat_threads, 'retry': retry}


def _chat_state(settings_file: Path, busy: bool = False) -> dict:
    """Answer to newChat/switchChat/deleteChat: no bundle imports, status probes or keyring reads."""
    return _chat_view(app_data(), Settings.load(settings_file), busy)


def _get_state(settings_file: Path, runtime: Runtime, busy: bool = False, studio_status=None) -> dict:
    settings = Settings.load(settings_file)
    home = app_data()
    try:
        lesson_bundle = import_bundled_lessons(home, __version__, enabled=settings.practice_lessons_enabled)
    except (OSError, ValueError, sqlite3.Error) as exc:
        lesson_bundle = {'status': 'error', 'message': str(exc)[:160], 'imported': 0}
    try:
        learning_bundle = import_learning_bundle(home, __version__, auto_live=settings.learning_auto_live,
                                                 project=settings.project)
    except (OSError, ValueError, sqlite3.Error) as exc:
        learning_bundle = {'status': 'error', 'message': str(exc)[:160]}
    chat = _chat_view(home, settings, busy)
    brain = BrainInstall.load(home / 'brain.json')
    workshop = ToolWorkshop(home=home,project=settings.project)
    try:
        tool_workshop_status=workshop.status()
    finally:
        workshop.close()
    return {
        'version':__version__,'build':read_build_info(),**chat,
        'settings':asdict(settings),
        'brain_installed':brain is not None,'brain_running':runtime.status()=='running',
        'model_router_running':runtime.router_running(),
        'tool_workshop':tool_workshop_status,
        'analytics':get_dashboard(home,settings.project),
        'learning':learning_status(home,settings.project),
        'lesson_bundle':lesson_bundle,
        'learning_bundle':learning_bundle,
        'credentials':credential_status(),
        'server':server_status(settings),
        'roblox':roblox_state(home),
        'intelligence':for_settings(settings,home).status(),
        'mcp':MCPGateway(settings).status(),
        'blender':blender_status(settings),
        'studio':connection_status(settings, studio_status, home=settings_file.parent),
        'release_url':'https://github.com/oncoursemail/Star-AI/releases/latest',
    }


def close_for_session(shell, manager=None):
    """Close the real window on a Qt session-end / Restart Manager request."""
    shell.close()


def launch():
    try:
        from PySide6.QtCore import QObject, QUrl, Slot, Signal, QTimer
        from PySide6.QtWidgets import QApplication, QMainWindow, QFileDialog
        from PySide6.QtGui import QDesktopServices
        from PySide6.QtWebEngineCore import QWebEnginePage
        from PySide6.QtWebEngineWidgets import QWebEngineView
        from PySide6.QtWebChannel import QWebChannel
    except ImportError as exc:
        raise RuntimeError('Install STAR desktop requirements including PySide6 WebEngine') from exc

    index = react_index()
    if not index.is_file():
        raise FileNotFoundError(
            f'STAR React UI not built at {index}. Run `cd frontend && npm install && npm run build` first. '
            'The Windows release workflow builds the interface automatically.'
        )

    class RestrictedPage(QWebEnginePage):
        def acceptNavigationRequest(self, url, navigation_type, is_main_frame):
            if not is_main_frame:
                return True
            if url.isLocalFile():
                try:
                    urlpath = Path(url.toLocalFile()).resolve(strict=True)
                    if urlpath == index.resolve():
                        return True
                except OSError:
                    return False
            if url.scheme() == 'https' and url.host() in {'github.com','docs.github.com','create.roblox.com','huggingface.co'}:
                QDesktopServices.openUrl(url)
            return False

    class Bridge(QObject):
        event = Signal(str)
        shutdownRequested = Signal()
        def __init__(self, host):
            super().__init__()
            self.host = host
            self.settings_file = app_data() / 'settings.json'
            self.runtime = Runtime()
            self.studio_status = None
            self.pool = ThreadPoolExecutor(max_workers=2, thread_name_prefix='star-react')
            self.research_running = threading.Event()
            # Starts no public network activity unless the owner opts in.
            self.research_timer = QTimer(self)
            self.research_timer.setInterval(60 * 60 * 1000)
            self.research_timer.timeout.connect(self._research_tick)
            self.research_timer.start()
            QTimer.singleShot(10_000, self._research_tick)
            self.shutdownRequested.connect(QApplication.instance().quit)
            self.allowed_files: set[Path] = set()
            self.active_task = False
            self.cancel_chat = threading.Event()
            self.turn: TurnRef | None = None
            self.active_update = False
            self.pending_update = None
            self._closing = False
            self.warmer = Warmer()
            self.draft_warmer = DraftWarmer()
            self.digester = Digester()
            self.comfy_launcher = ComfyLauncher()
            self.clips = ClipService()  # No capture until explicit owner-controlled OBS actions.
            self.clip_library = ClipLibrary()  # No folder until explicitly selected through Qt.
            self.moments = MomentsEvents()  # Own-game events, local GG only; no auto-trigger.
            self.discord = DiscordSupervisor(app_data())
            self.discord.begin()
            # Opt-in only; a few seconds after launch so the window is not kept waiting.
            QTimer.singleShot(3_000, self._discord_autostart)
            try:   # Use my GPU: armed, not loaded; it loads with the first question that needs it
                gpu_helper.HELPER.configure(Settings.load(self.settings_file), app_data())
            except Exception:
                pass
            from . import presolve   # opt-in overnight pre-solving: until it is switched on it only reads the setting
            presolve.start_nightly(self.settings_file, app_data())
            self.voice = VoiceBridge(lambda call_id, data: self._emit(call_id, 'voice', data),
                                     settings_path=app_data() / 'voice.json', save_turn=self._save_voice_turn)

        def _discord_autostart(self):
            if self._closing:
                return
            try:
                start_if_opted_in(self.discord, Settings.load(self.settings_file).discord_autostart)
            except Exception:
                pass  # a bad settings file must not stop STAR from opening; the page shows the bot's state

        def _research_tick(self):
            """Check due official sources off the GUI thread, at most daily.

            The desktop owns this scheduler, not the model or external web text.
            Each failure is recorded as a source status; nothing is trusted,
            executed or committed to GitHub. The timer merely checks eligibility.
            """
            if self.active_task or self.research_running.is_set():
                return
            if not Settings.load(self.settings_file).research_auto_check:
                return
            self.research_running.set()

            def worker():
                try:
                    from .evolution_research import ResearchWatcher
                    with ResearchWatcher(app_data() / 'research-watch.sqlite3') as watcher:
                        due = watcher.due_sources()
                        if due:
                            watcher.check_many(due)
                finally:
                    self.research_running.clear()

            try:
                self.pool.submit(worker)
            except RuntimeError:
                self.research_running.clear()

        def _warm_target(self):
            """What a message sent now would talk to. Runs on the warm-up thread."""
            settings=Settings.load(self.settings_file)
            home=app_data()
            chat_id=None
            if (home/'conversations.sqlite3').is_file():
                chats=Conversations(home/'conversations.sqlite3')
                try: chat_id=chats.active_chat(settings.project)
                finally: chats.close()
            return settings,home,chat_id

        def _warm(self, request_id: str = '', check: bool = True, then=None):
            """Check the selected model server and prime its prompt cache, off the UI thread.

            It is not a turn: nothing is saved, `active_task` stays False, and any
            real request cancels it (see WARM_UP_STOPPERS). Cloud providers are skipped.
            `then(report)` runs on the warm-up thread once it has finished.
            """
            def finished(report):
                if request_id:self._emit(request_id,'result',report)
                if then is not None:then(report)
            self.warmer.start(
                self._warm_target, check=check,
                on_checked=(lambda report:self._emit(request_id,'progress',{'phase':'Server checked'})) if request_id else None,
                on_done=finished if (request_id or then is not None) else None)

        def _warm_draft(self, body: dict) -> dict:
            """Settings > Start thinking while I type: the server reads the draft into its prompt cache.
            Answers at once; the request runs on its own thread (star/prefill_warm.py)."""
            text=body.get('prompt')
            if not isinstance(text,str) or len(text)>30000:raise ValueError('Invalid draft')
            if self.active_task:
                return {'primed':False,'skipped':'busy'}
            mode=str(body.get('mode')) if body.get('mode') in ('auto','fast','agent') else 'auto'
            prefix=SESSION_CAPABILITIES if Settings.load(self.settings_file).session_capabilities_prompt else ''
            self.draft_warmer.submit(self._warm_target,prefix+text,mode=mode,research=body.get('research') is True)
            return {'queued':True}

        def _digest_target(self):
            settings=Settings.load(self.settings_file)
            return settings,app_data(),settings.project

        def _digest_when_idle(self, report=None):
            """After a turn and its cache warm-up: let the fast model reword raw captures into
            candidate lessons. Not a turn, never trusted output, and any real request stops it."""
            if not may_start_automatic(report,turn_running=self.active_task,voice_call=self._in_voice_call()):
                return
            self.digester.start(self._digest_target)

        def _in_voice_call(self):
            try:return bool(self.voice.handle('voiceStatus',{}).get('inCall'))
            except Exception:return False

        def _save_voice_turn(self, user_text: str, reply_text: str):
            # A call shows up in the active chat like typed messages do.
            settings = Settings.load(self.settings_file)
            chats = Conversations(app_data() / 'conversations.sqlite3')
            try:
                active_chat = chats.active_chat(settings.project)
                chats.add(settings.project, 'user', user_text, chat_id=active_chat)
                if reply_text:
                    chats.add(settings.project, 'assistant', reply_text, chat_id=active_chat)
            finally:
                chats.close()

        def _emit(self, request_id: str, kind: str, data):
            payload={'requestId':request_id,'kind':kind,'data':data}
            self.event.emit(json.dumps(payload,default=str))

        def _capture_screen(self) -> dict:
            """Hide STAR, grab the screen it is on, show STAR again, and store one PNG."""
            from PySide6.QtCore import QBuffer, QByteArray, QEventLoop, QIODevice, QTimer as _Timer, Qt
            from PySide6.QtGui import QGuiApplication
            window=self.host
            screen=window.screen() if hasattr(window,'screen') else None
            screen=screen or QGuiApplication.primaryScreen()
            if screen is None:
                raise RuntimeError('No screen is available to capture')
            visible=window.isVisible()
            if visible:
                window.hide()  # STAR itself is not what the owner wants it to look at
                pause=QEventLoop()
                _Timer.singleShot(320,pause.quit)
                pause.exec()
            try:
                pixmap=screen.grabWindow(0)
            finally:
                if visible:
                    window.show();window.raise_();window.activateWindow()
            if pixmap.isNull():
                raise RuntimeError('Windows did not return a picture of the screen')
            def encode(image,fmt,quality=-1)->bytes:
                data=QByteArray();buffer=QBuffer(data);buffer.open(QIODevice.OpenModeFlag.WriteOnly)
                ok=image.save(buffer,fmt,quality);buffer.close()
                if not ok:raise RuntimeError('Could not encode the screenshot')
                return bytes(data)
            path=store_screen_capture(encode(pixmap,'PNG'),app_data())
            self.allowed_files.add(path)
            thumb=pixmap.scaledToWidth(min(480,pixmap.width()),Qt.TransformationMode.SmoothTransformation)
            return describe_screen_capture(path,pixmap.width(),pixmap.height(),
                                           screen_preview_url(encode(thumb,'JPEG',78),'image/jpeg'))

        def _run(self, request_id: str, action: str, worker):
            settled=[]
            def settle():
                # Once only: after the event a new turn may already have started and set these again.
                if action in TURN_ACTIONS and not settled:
                    settled.append(True)
                    self.turn=None
                    self.active_task=False
            def task():
                try:
                    run_worker(request_id, action, worker, emit=self._emit, home=app_data(),
                               current_turn=lambda: self.turn, cancelled=self.cancel_chat.is_set,
                               settings_file=self.settings_file, settled=settle)
                finally:
                    settle()     # also when emitting itself failed
                    if action=='installUpdate':self.active_update=False
            self.pool.submit(task)

        def _start_brain(self, info: BrainInstall):
            # This helper performs an actual completion before changing settings
            # and stops a newly launched engine if validation fails.
            from .brain_runtime_health import start_verified_brain
            return start_verified_brain(
                self.runtime, info, self.settings_file, app_data())

        def _start_model_router(self):
            if self.active_task:
                raise RuntimeError('Stop the active chat before switching STAR models')
            # The helper refuses non-local providers and never switches the
            # owner away from STAR Server while the router is loading.
            info = BrainInstall.load(app_data()/'brain.json')
            source = info.executable if info is not None else Settings.load(self.settings_file).llama_server
            return self.runtime, self.settings_file, app_data(), source

        def _run_chat(self, request_id, prompt, selected, mode='auto', research=False, github=False, retry_id=None):
            home=app_data()
            settings=Settings.load(self.settings_file)
            if not settings.model.strip():
                raise ValueError(missing_model_message(settings))
            chats=Conversations(home/'conversations.sqlite3')
            try:
                active_chat=chats.active_chat(settings.project)
                if retry_id is not None:
                    user_id=chats.recover_turn(settings.project,active_chat,retry_id,prompt)
                else:
                    user_id=chats.add(settings.project,'user',prompt,chat_id=active_chat)
            finally:
                chats.close()
            self.turn=TurnRef(settings.project,active_chat,user_id)
            with tempfile.TemporaryDirectory(prefix='star-media-') as directory:
                # Pictures as they are; a video as sampled frames plus a transcript of its sound, sent
                # only where Settings says video understanding runs; pinned references for a turn
                # about looks; the "not watched" rule for a bare video link (star/chat_media.py).
                if any(path.suffix.lower() in {'.mp4','.mov','.mkv','.webm','.avi'} for path in selected):
                    self._emit(request_id,'progress',{'phase':'Sampling frames and transcribing the sound…'})
                media=prepare_turn(settings,home,prompt,selected,Path(directory)/('m_'+uuid.uuid4().hex),
                                   cancelled=self.cancel_chat.is_set)
                pics=media.pictures
                full_prompt=media.prompt(prompt)
                documents=media.documents
                learned={}
                instant_used=False
                def relay(e):
                    nonlocal instant_used
                    if e.get('event') == 'instant_selected':
                        instant_used = True
                    # What the turn taught is reported with the result, not as a progress step.
                    if e.get('event')=='lessons_captured':
                        learned.update(accepted=int(e.get('accepted',0)),candidates=int(e.get('candidates',0)),
                                       replaced=int(e.get('replaced',0)),not_kept=int(e.get('not_kept',0)))
                        return
                    if e.get('event')=='lessons_capture_failed':
                        learned.update(capture_failed=1)
                        return
                    self._emit(request_id,'progress',sanitize_event(e))
                if settings.session_capabilities_prompt:
                    full_prompt = SESSION_CAPABILITIES + full_prompt
                answer=run_task(settings,full_prompt,pics,on_event=relay,
                    stream_tokens=True, mode=mode, research=research, cancel_event=self.cancel_chat, github_enabled=github, chat_id=active_chat,
                    owner_text=prompt, studio_configuration_home=self.settings_file.parent, attachment_count=len(selected),
                    **({'documents': documents} if documents else {}))
                # STAR states what a video answer was based on, whatever the model wrote.
                answer+=media.footer
            if self.cancel_chat.is_set():
                raise RuntimeError('cancelled by user')
            if provider_kind(settings)=='lan' and not instant_used:
                note_server_result(settings,True,'ok')
            chats=Conversations(home/'conversations.sqlite3')
            try:
                chats.add(settings.project,'assistant',answer,chat_id=active_chat)
            finally:
                chats.close()
            # While the owner reads the answer, let the server read it too: the next
            # message then starts from a fully cached conversation. Cancelled by any request.
            # Once that is done the server is idle, which is when raw captures get reworded.
            if not instant_used:
                self._warm(check=False,then=self._digest_when_idle)
            return {'answer':answer,'learned':learned} if learned else {'answer':answer}

        def _run_image(self, request_id, prompt, files=(), size='square', followup=False, display_prompt=None, retry_id=None):
            settings=Settings.load(self.settings_file)
            home=app_data()
            shown=display_prompt or prompt     # the words the owner typed; `prompt` is what the picture model gets
            self._emit(request_id,'progress',{'phase':'Editing the image on this PC…' if files or followup else 'Creating your image on this PC...'})
            chats=Conversations(home/'conversations.sqlite3')
            try:
                active_chat=chats.active_chat(settings.project)
                if retry_id is not None:
                    user_id=chats.recover_turn(settings.project,active_chat,retry_id,shown)
                else:
                    user_id=chats.add(settings.project,'user',shown,chat_id=active_chat)
            finally:
                chats.close()
            self.turn=TurnRef(settings.project,active_chat,user_id)
            chat_id = active_chat
            source=files[0] if files else None
            if followup and source is None:
                source=latest_generated_path(home, settings.project, active_chat)
                if source is None:
                    raise ValueError('The previous picture is no longer available to edit.')
            # The chosen place first: a choice that cannot make pictures fails here, before ComfyUI is started.
            media_places.require(settings,'images',home)
            if settings.media_images=='pc':
                # Never two big models on the card: Use my GPU unloads before the picture is made.
                gpu_helper.HELPER.yield_to('the image engine is making a picture')
            if not image_gen.status(settings)['running']:
                if not effective_comfy_home(settings):
                    raise ComfyError('not_running', 'No image engine is set up: pictures are made by ComfyUI on this PC, it is not '
                                     'running, and STAR found no ComfyUI folder to start it from. Choose that folder in Settings → '
                                     'Where STAR generates (or start ComfyUI yourself), then ask again.')
                self._emit(request_id,'progress',{'phase':'Starting the image engine...'})
                self.comfy_launcher.start(settings,home)
                if self.cancel_chat.is_set():
                    raise RuntimeError('cancelled by user')
                self._emit(request_id,'progress',{'phase':'Creating your image on this PC...'})
            result=generate_chat_image(settings,prompt,home,cancel_event=self.cancel_chat,size=size,
                                       source=source,
                                       mask=files[1] if len(files)>1 else None)
            chats=Conversations(home/'conversations.sqlite3')
            try:
                chats.add(settings.project,'assistant',result['message'],chat_id=chat_id)
            finally:
                chats.close()
            return {'answer':result['answer'],'image':result['image']}

        def _run_team(self, request_id: str, prompt: str, research: bool = False):
            """One user request, four bounded read-only specialists, one stored answer."""
            from .team_service import run_research_team
            import asyncio
            home = app_data()
            settings = Settings.load(self.settings_file)
            if not settings.model.strip():
                raise ValueError(missing_model_message(settings, teams=True))
            if provider_kind(settings) == 'cloud':
                raise ValueError('STAR Teams runs on your own hardware. Select On-device or STAR Server as the provider.')
            chats = Conversations(home / "conversations.sqlite3")
            try:
                active_chat = chats.active_chat(settings.project)
                user_id = chats.add(settings.project, "user", prompt, chat_id=active_chat)
            finally:
                chats.close()
            self.turn = TurnRef(settings.project, active_chat, user_id)
            from .team_cancellation import run_until_cancelled
            async def run():
                return await run_until_cancelled(
                    run_research_team(
                        settings=settings, prompt=prompt, home=home, research=research,
                        on_event=lambda event: self._emit(
                            request_id, 'progress', sanitize_event(event)),
                    ),
                    is_cancelled=self.cancel_chat.is_set,
                )
            answer, team = asyncio.run(run())
            chats = Conversations(home / "conversations.sqlite3")
            try:
                chats.add(settings.project, "assistant", answer, chat_id=active_chat)
            finally:
                chats.close()
            return {
                "answer": answer,
                "agents": len(team.results),
                "peak_concurrency": team.peak_concurrency,
                "elapsed_ms": team.elapsed_ms,
            }

        def _clip_action(self, action: str, body: dict, rid: str) -> str:
            """STAR Clips, clip folder, SteelSeries Moments and Game Lab (kept out of invoke for pyright)."""
            if action == 'gameLabCatalog':
                return json.dumps({'ok': True, 'data': game_lab_catalog(
                    query=body.get('query', ''), category=body.get('category', ''), limit=28)})
            if action in CLIP_INTEROP_ACTIONS:
                if action == 'clipChooseFolder':
                    folder = QFileDialog.getExistingDirectory(
                        self.host, 'Choose a local game clip folder (read-only)')
                    if not folder:
                        return json.dumps({'ok': True, 'data': {'cancelled': True}})
                    self._run(rid, action, lambda: self.clip_library.choose(Path(folder)))
                    return json.dumps({'ok': True, 'pending': True, 'requestId': rid})
                if action == 'clipListFolder':
                    self._run(rid, action, self.clip_library.list_clips)
                    return json.dumps({'ok': True, 'pending': True, 'requestId': rid})
                if action == 'clipClearFolder':
                    if body.get('confirm') is not True:
                        raise PermissionError('Disconnecting clips needs a user action.')
                    return json.dumps({'ok': True, 'data': self.clip_library.clear()})
                if action == 'clipOpenFile':
                    if body.get('confirm') is not True:
                        raise PermissionError('Opening a video needs a user action.')
                    # File ids, not user/model paths; verify selection and symlinks again.
                    selected = self.clip_library.allowed_clip(str(body.get('id', '')))
                    opened = QDesktopServices.openUrl(QUrl.fromLocalFile(str(selected)))
                    if not opened:
                        raise RuntimeError('Windows could not open the selected clip.')
                    return json.dumps({'ok': True, 'data': {'opened': True}})
                # GameSense producer sends only fixed local protocol events to
                # human-claimed STAR_* developer games; never arbitrary live titles.
                self._run(rid, action, lambda: self.moments.handle(action, body))
                return json.dumps({'ok': True, 'pending': True, 'requestId': rid})
            if action in CLIP_ACTIONS:
                # Local OBS WebSocket I/O is kept off the Qt/React UI thread.
                # No model tool exposes these recording controls.
                self._run(rid, action, lambda: self.clips.handle(action, body))
                return json.dumps({'ok': True, 'pending': True, 'requestId': rid})
            raise PermissionError('Unsupported STAR Clips action.')

        @Slot(str,result=str)
        def invoke(self, raw: str) -> str:
            try:
                if len(raw)>100000:
                    raise ValueError('Request is too large')
                body=json.loads(raw)
                if not isinstance(body,dict):raise ValueError('Invalid request')
                action=body.get('action')
                if action not in ALLOWED_ACTIONS:raise PermissionError('Action not permitted')
                rid=str(body.get('requestId',''))[:80]
                if action in WARM_UP_STOPPERS:self.warmer.cancel();self.draft_warmer.cancel()
                if action in WARM_UP_STOPPERS or action in VOICE_ACTIONS:self.digester.cancel()
                if action=='warmDraft':return json.dumps({'ok':True,'data':self._warm_draft(body)})
                if action=='warmUp':
                    if self.active_task:
                        return json.dumps({'ok':True,'data':{'primed':False,'skipped':'busy'}})
                    self._warm(rid)
                    return json.dumps({'ok':True,'pending':True,'requestId':rid})
                if action in VOICE_ACTIONS:
                    if action in VOICE_PLACE_ACTIONS:
                        # Speech runs where Settings says; a place that does not exist is refused, not replaced.
                        media_places.require(Settings.load(self.settings_file),'voice',app_data())
                    return json.dumps({'ok':True,'data':self.voice.handle(action, body, rid)})
                if action in ('gpuHelperStatus','gpuHelperSet'):
                    if action=='gpuHelperSet':
                        enabled=body.get('enabled')
                        if type(enabled) is not bool:raise ValueError('Choose on or off')
                        saved=Settings.load(self.settings_file)
                        saved.use_my_gpu=enabled
                        saved.save(self.settings_file)
                        gpu_helper.HELPER.configure(saved,app_data(),start=enabled)
                    return json.dumps({'ok':True,'data':gpu_helper.HELPER.status()})
                if action in DISCORD_ACTIONS:
                    saved=Settings.load(self.settings_file)
                    if action=='discordSetAutostart':
                        enabled=body.get('enabled')
                        if type(enabled) is not bool:raise ValueError('Choose on or off')
                        saved.discord_autostart=enabled
                        saved.save(self.settings_file)
                    return json.dumps({'ok':True,'data':handle_discord_action(action,self.discord,autostart=saved.discord_autostart)})
                if action == 'gameLabCatalog' or action in CLIP_INTEROP_ACTIONS or action in CLIP_ACTIONS:
                    return self._clip_action(action, body, rid)
                if action in MEDIA_ACTIONS:
                    def media_worker():
                        return handle_media_action(
                            action, body, settings=Settings.load(self.settings_file), home=app_data(),
                            allowed_file=lambda path: file_allowed(path, self.allowed_files),
                            launcher=self.comfy_launcher)
                    if action in SLOW_MEDIA_ACTIONS:
                        self._run(rid,action,media_worker)
                        return json.dumps({'ok':True,'pending':True,'requestId':rid})
                    return json.dumps({'ok':True,'data':media_worker()},default=str)
                if action in {'researchStatus', 'researchCheck', 'researchEvidence', 'researchNominate'}:
                    # Read-only public documentation, observed into a local candidate-only ledger.
                    # No model-selected host, reviewed-memory promotion or GitHub publish permission.
                    def research_task():
                        from .evolution_research import ResearchWatcher
                        with ResearchWatcher(app_data() / 'research-watch.sqlite3') as watcher:
                            if action == 'researchStatus':
                                return watcher.status()
                            if action == 'researchEvidence':
                                return watcher.evidence(body.get('observation'))
                            if action == 'researchNominate':
                                project = Settings.load(self.settings_file).project
                                return watcher.nominate(body.get('observation'), home=app_data(), project=project)
                            return watcher.check_many()
                    if action == 'researchCheck':
                        if self.active_task:
                            raise RuntimeError('Finish the active task before checking research sources')
                        self._run(rid, action, research_task)
                        return json.dumps({'ok':True,'pending':True,'requestId':rid})
                    return json.dumps({'ok':True,'data':research_task()},default=str)
                if action=='bootstrap':return json.dumps({'ok':True,'data':_get_state(self.settings_file,self.runtime,busy=self.active_task,studio_status=self.studio_status)})
                if action=='brainSnapshot':return json.dumps({'ok':True,'data':brain_snapshot(self.settings_file,app_data())})
                if action=='plannerStatus':return json.dumps({'ok':True,'data':planner_snapshot(self.settings_file)})
                if action=='pickFiles':
                    kind=body.get('kind')
                    if kind=='audio':
                        names, _=QFileDialog.getOpenFileNames(self.host,'Select audio references','','Audio files (*.wav *.mp3 *.m4a *.flac *.ogg *.aac)')
                    elif kind=='image':
                        names, _=QFileDialog.getOpenFileNames(self.host,'Choose images','','Images (*.png *.jpg *.jpeg *.webp)')
                    else:
                        names, _=QFileDialog.getOpenFileNames(self.host,'Attach references','','References (*.png *.jpg *.jpeg *.webp *.mp4 *.mov *.mkv *.webm *.avi *.wav *.mp3 *.m4a *.flac *.ogg *.aac *.txt *.md *.pdf *.docx *.pptx *.csv *.tsv *.xlsx *.json *.rbxmx *.rbxlx *.rbxm *.rbxl)')
                    picked=[]
                    for name in names[:8]:
                        path=Path(name).resolve(strict=True)
                        if path.is_file() and path.stat().st_size<=700_000_000:
                            self.allowed_files.add(path)
                            picked.append(str(path))
                    return json.dumps({'ok':True,'data':picked})
                if action=='switchProject':
                    project=str(body.get('project','')).strip()
                    if not project or len(project)>60 or any(ch in project for ch in '\\/:*?"<>|\x00'):
                        raise ValueError('Project name must be 1–60 characters without path separators')
                    settings=Settings.load(self.settings_file)
                    settings.project=project;settings.save(self.settings_file)
                    return json.dumps({'ok':True,'data':_get_state(self.settings_file,self.runtime,busy=self.active_task)})
                if action=='newChat':
                    if self.active_task:raise RuntimeError('Wait for the current answer before starting a new chat')
                    settings=Settings.load(self.settings_file)
                    conversations=Conversations(app_data()/'conversations.sqlite3')
                    try: conversations.new_chat(settings.project)
                    finally: conversations.close()
                    self._warm(check=False)
                    return json.dumps({'ok':True,'data':_chat_state(self.settings_file)})
                if action=='switchChat':
                    # The running turn keeps its original chat_id; switching only changes the viewed thread.
                    chat_id=str(body.get('chatId',''))[:80]
                    settings=Settings.load(self.settings_file)
                    conversations=Conversations(app_data()/'conversations.sqlite3')
                    try: conversations.switch_chat(settings.project,chat_id)
                    finally: conversations.close()
                    if not self.active_task:self._warm(check=False)
                    busy=bool(self.active_task and self.turn is not None and self.turn.chat_id==chat_id)
                    return json.dumps({'ok':True,'data':_chat_state(self.settings_file,busy=busy)})
                if action=='renameChat':
                    chat_id=str(body.get('chatId',''))[:80]
                    settings=Settings.load(self.settings_file)
                    conversations=Conversations(app_data()/'conversations.sqlite3')
                    try: title=conversations.rename_chat(settings.project,chat_id,str(body.get('title',''))[:400])
                    finally: conversations.close()
                    return json.dumps({'ok':True,'data':{'chatId':chat_id,'title':title}})
                if action=='deleteChat':
                    # The interface waits out its Undo window before sending this; the owner chose it.
                    chat_id=str(body.get('chatId',''))[:80]
                    if self.active_task and self.turn is not None and self.turn.chat_id==chat_id:
                        raise RuntimeError('Stop the answer in this chat before deleting it')
                    settings=Settings.load(self.settings_file)
                    conversations=Conversations(app_data()/'conversations.sqlite3')
                    try: conversations.delete_chat(settings.project,chat_id)
                    finally: conversations.close()
                    return json.dumps({'ok':True,'data':_chat_state(self.settings_file,busy=self.active_task)})
                if action=='captureScreen':
                    # Only an explicit "Take screenshot" press reaches here (consent: true, per use).
                    require_screen_consent(body)
                    return json.dumps({'ok':True,'data':self._capture_screen()})
                if action in LEARNED_ACTIONS or action in CORRECTION_ACTIONS:
                    # Owner clicks in What STAR learned this week / corrections; `approved` is the click itself.
                    settings=Settings.load(self.settings_file)
                    handler=handle_learned_action if action in LEARNED_ACTIONS else handle_correction_action
                    return json.dumps({'ok':True,'data':handler(app_data(),settings.project,action,body)},default=str)
                if action in LESSON_ACTIONS:
                    # Review, export and feedback are explicit owner actions in the interface.
                    settings=Settings.load(self.settings_file)
                    data=handle_lesson_action(app_data(),settings.project,action,body)
                    if action=='exportLessons':
                        # The file goes where the owner chooses, like the review bundle.
                        name=re.sub(r'[^A-Za-z0-9._-]+','-',settings.project).strip('-') or 'project'
                        suggested=str(Path.home()/f"STAR-lessons-{name}-{time.strftime('%Y%m%d',time.gmtime())}.json")
                        filename,_=QFileDialog.getSaveFileName(self.host,'Export lessons',suggested,'JSON (*.json)')
                        if not filename:
                            return json.dumps({'ok':True,'data':{'cancelled':True}})
                        data=write_export(Path(filename),data)
                    return json.dumps({'ok':True,'data':data},default=str)
                if action in ROBLOX_ACTIONS:
                    # Explicit owner clicks in Settings. The ones that talk to Roblox run off the UI thread.
                    if action in ROBLOX_NETWORK_ACTIONS:
                        self._run(rid,action,lambda:handle_roblox_action(app_data(),action,body))
                        return json.dumps({'ok':True,'pending':True,'requestId':rid})
                    return json.dumps({'ok':True,'data':handle_roblox_action(app_data(),action,body)})
                if action=='digestLessons':
                    # "Summarise now": the same background step, started by the owner for even one capture.
                    if self.active_task:raise RuntimeError('Wait for the current answer before summarising captures')
                    def digested(report):
                        self._emit(rid,'result',report)
                        # The chat's own model answered: prime its conversation cache again.
                        if report.get('shared_model') and not self.active_task:self._warm(check=False)
                    started=self.digester.start(self._digest_target,minimum=1,on_done=digested)
                    if started is None:raise RuntimeError('STAR is already summarising captures')
                    return json.dumps({'ok':True,'pending':True,'requestId':rid})
                if action=='rememberDecision':
                    from .learning import approve_learning
                    settings=Settings.load(self.settings_file)
                    receipt=approve_learning(
                        app_data(), project=settings.project,
                        text=body.get('text'),
                        kind=str(body.get('kind','decision')),
                        replaces_note_id=body.get('replaces_note_id'),
                        human_approved=body.get('approved') is True,
                    )
                    return json.dumps({'ok':True,'data':asdict(receipt)})
                if action=='listLearning':
                    from .knowledge import KnowledgeStore
                    settings=Settings.load(self.settings_file)
                    store=KnowledgeStore(app_data()/'knowledge')
                    try:
                        notes=[{'id':n.id,'kind':n.kind,'text':n.text[:1200],
                                'created':n.created,'source':n.source}
                               for n in store.find(settings.project,'',reviewed_only=True,limit=30)
                               if n.source=='user:explicit-approved-decision'][:12]
                    finally:
                        store.close()
                    return json.dumps({'ok':True,'data':{'notes':notes}})
                if action=='saveSettings':
                    if self.active_task:
                        raise RuntimeError('Wait for the current task before changing connections or permissions')
                    old=apply_setting_changes(Settings.load(self.settings_file),body.get('settings'))
                    old.save(self.settings_file)
                    gpu_helper.HELPER.configure(old,app_data())
                    if old.research_auto_check:
                        QTimer.singleShot(200, self._research_tick)
                    return json.dumps({'ok':True,'data':asdict(old)})
                if action in STUDIO_HOST_ACTIONS:
                    return json.dumps({'ok':True,'data':handle_studio_host(action,body,self.settings_file)})
                if action=='testBlender':
                    import asyncio
                    from .blender_bridge import BlenderController
                    settings=Settings.load(self.settings_file)
                    self._run(rid,action,lambda:asyncio.run(
                        BlenderController(settings=settings,home=self.settings_file.parent).probe()))
                    return json.dumps({'ok':True,'pending':True,'requestId':rid})
                if action=='saveProviderKey':
                    name=str(body.get('provider',''))
                    token=body.get('key','')
                    save_api_key(name,token)
                    return json.dumps({'ok':True,'data':{'connected':True}})
                if action=='serverKeyFileStatus':
                    from .server_key_file import key_file_status
                    return json.dumps({'ok':True,'data':key_file_status()})
                if action=='importServerKeyFile':
                    from .server_key_file import import_key_file
                    return json.dumps({'ok':True,'data':import_key_file()})
                if action=='clearProviderKey':
                    name=str(body.get('provider',''))
                    clear_api_key(name)
                    return json.dumps({'ok':True,'data':{'connected':False}})
                if action=='selectFolder':
                    selected=QFileDialog.getExistingDirectory(self.host, 'Choose a local notes or project folder')
                    return json.dumps({'ok':True,'data':{'path':str(selected) if selected else ''}})
                if action=='exportReviewBundle':
                    include_screen=body.get('includeScreenshot',False)
                    if type(include_screen) is not bool:
                        raise ValueError('Invalid screenshot selection')
                    stamp=time.strftime('%Y%m%d',time.gmtime())
                    suggested=str(Path.home()/f'STAR-review-v{__version__}-{stamp}.zip')
                    filename,_=QFileDialog.getSaveFileName(
                        self.host, 'Export STAR review bundle', suggested, 'ZIP archive (*.zip)')
                    if not filename:
                        return json.dumps({'ok':True,'data':{'cancelled':True}})
                    destination=Path(filename).expanduser()
                    if not destination.suffix:
                        destination=destination.with_suffix('.zip')
                    screenshot=None
                    if include_screen:
                        # Optional explicit screenshot may expose the currently visible
                        # chat, so the React option defaults to unchecked.
                        from PySide6.QtCore import QBuffer, QIODevice
                        buffer=QBuffer()
                        buffer.open(QIODevice.OpenModeFlag.WriteOnly)
                        if not self.host.view.grab().save(buffer,'PNG'):
                            buffer.close()
                            raise RuntimeError('Could not capture current screen')
                        screenshot=bytes(buffer.data())
                        buffer.close()
                    def worker():
                        result=export_review_bundle(
                            app_data(),Settings.load(self.settings_file),destination,
                            runtime_status=self.runtime.status(),screenshot_png=screenshot)
                        return {'filename':result.name,'screenshot_included':bool(screenshot),
                                'saved_to_user_selected_location':True}
                    self._run(rid,action,worker)
                    return json.dumps({'ok':True,'pending':True,'requestId':rid})
                if action=='openLegacy':
                    raise PermissionError('The legacy UI is diagnostic-only; start STAR.exe --legacy-ui explicitly if necessary.')
                if action=='copyText':
                    content=str(body.get('text',''))
                    if len(content)>300000:raise ValueError('Too much text')
                    QApplication.clipboard().setText(content)
                    return json.dumps({'ok':True,'data':True})
                if action=='openDataFolder':
                    path=app_data();path.mkdir(parents=True,exist_ok=True)
                    QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))
                    return json.dumps({'ok':True,'data':True})
                if action=='cancelMessage':
                    if self.active_task:
                        self.cancel_chat.set()
                    return json.dumps({'ok':True,'data':{'cancel_requested':self.active_task}})
                if action=='runTeam':
                    if self.active_task:raise RuntimeError('STAR is already handling a task')
                    prompt=str(body.get('prompt','')).strip()
                    if not 2 <= len(prompt) <= 12000:
                        raise ValueError('Team prompt must be 2–12,000 characters')
                    if body.get('files'):
                        raise ValueError('STAR Teams currently supports text only. Turn off Team mode to attach files.')
                    research = body.get('research', False)
                    if type(research) is not bool:
                        raise ValueError('Team Research mode must be true or false')
                    self.cancel_chat = threading.Event()
                    self.active_task=True
                    try:
                        self._run(rid,action,lambda:self._run_team(rid,prompt,research))
                    except Exception:
                        self.active_task=False
                        raise
                if action=='sendMessage':
                    if self.active_task:raise RuntimeError('STAR is already handling a task')
                    prompt=str(body.get('prompt','')).strip()
                    if not prompt or len(prompt)>30000:raise ValueError('Message must be 1–30,000 characters')
                    files=body.get('files') or []
                    if not isinstance(files,list) or len(files)>8:raise ValueError('Too many attachments')
                    selected=[file_allowed(Path(str(f)),self.allowed_files) for f in files]
                    mode=body.get('mode','auto')
                    if mode not in ('fast','auto','agent'):
                        raise ValueError('Choose Fast, Auto, or Agent mode')
                    research=body.get('research',False)
                    if not isinstance(research,bool):
                        raise ValueError('Invalid research flag')
                    github=body.get('github',False)
                    if not isinstance(github,bool) or (github and mode != 'agent'):
                        raise ValueError('GitHub inspection requires Agent mode')
                    self.cancel_chat = threading.Event()
                    self.active_task=True
                    try:
                        retry_id=body.get('retryMessageId')
                        if retry_id is not None:
                            if type(retry_id) is not int or retry_id < 1 or selected:
                                raise ValueError('Invalid Retry request')
                            chats=Conversations(app_data()/'conversations.sqlite3')
                            try:
                                current=Settings.load(self.settings_file).project
                                chats.recover_turn(current,chats.active_chat(current),retry_id,prompt)
                            finally:
                                chats.close()
                        self._run(rid,action,lambda:self._run_chat(rid,prompt,selected,mode=mode,research=research,github=github,retry_id=retry_id))
                    except Exception:
                        self.active_task=False
                        raise
                elif action=='generateImage':
                    if self.active_task:raise RuntimeError('STAR is already handling a task')
                    prompt=str(body.get('prompt','')).strip()
                    if not 1<=len(prompt)<=1500:raise ValueError('Image prompt must be 1–1500 characters')
                    # What the owner typed in chat, when `prompt` is the part the picture model should get.
                    display=body.get('display_prompt')
                    if display is not None:
                        if not isinstance(display,str) or not 1<=len(display.strip())<=1500:
                            raise ValueError('Invalid image request text')
                        display=display.strip()
                    # Optional: the picture to edit, then a mask (white = the part to change).
                    files=body.get('files') or []
                    if not isinstance(files,list) or len(files)>2:
                        raise ValueError('Attach the picture to edit and, if you want, one mask')
                    pictures=[file_allowed(Path(str(f)),self.allowed_files) for f in files]
                    size=body.get('size','square')
                    if not isinstance(size,str):raise ValueError('Invalid image size')
                    retry_id=body.get('retryMessageId')
                    if retry_id is not None and (type(retry_id) is not int or retry_id<1 or pictures):
                        raise ValueError('Invalid Retry request')
                    self.active_task=True
                    self.cancel_chat = threading.Event()
                    try:
                        if retry_id is not None:
                            chats=Conversations(app_data()/'conversations.sqlite3')
                            try:
                                current=Settings.load(self.settings_file).project
                                chats.recover_turn(current,chats.active_chat(current),retry_id,display or prompt)
                            finally:
                                chats.close()
                        self._run(rid,action,lambda:self._run_image(rid,prompt,pictures,size,body.get('followup') is True,display,retry_id))
                    except Exception:
                        self.active_task=False
                        raise
                elif action=='installBrain':
                    def worker():
                        info=install_brain(app_data(),progress=lambda e:self._emit(rid,'progress',e))
                        return self._start_brain(info)
                    self._run(rid,action,worker)
                elif action=='startBrain':
                    def worker():
                        info=BrainInstall.load(app_data()/'brain.json')
                        if info is None:raise RuntimeError('Download STAR Brain first')
                        return self._start_brain(info)
                    self._run(rid,action,worker)
                elif action=='startModelRouter':
                    if self.active_task:
                        raise RuntimeError('Stop the current chat before switching models')
                    self._run(rid,action,self._start_model_router)
                elif action=='stopBrain':
                    if self.active_task:
                        raise RuntimeError('Stop the current task before stopping the model server')
                    if self.runtime.status() != 'running':
                        return json.dumps({'ok':True,'data':{'stopped':False}})
                    self._run(rid,action,lambda:(self.runtime.stop() or {'stopped':True}))
                elif action=='testModelTeam':
                    if self.active_task:
                        raise RuntimeError('Finish the current chat before testing other models')
                    def worker():
                        import asyncio
                        from .model_fleet import check_configured_team
                        return asyncio.run(check_configured_team(
                            Settings.load(self.settings_file),
                            on_progress=lambda e:self._emit(rid,'progress',e)))
                    self._run(rid,action,worker)
                elif action=='testServer':
                    # Timed health -> key -> limits -> tiny chat check of the saved
                    # STAR Server. The key stays in the keyring; only step names,
                    # timings and model IDs go back to the interface.
                    self._run(rid,action,lambda:probe_server(Settings.load(self.settings_file)))
                elif action=='listModels':
                    def worker():return {'models':query_models(Settings.load(self.settings_file))}
                    self._run(rid,action,worker)
                elif action=='testModel':
                    def worker():
                        import asyncio
                        from .model_health import probe_chat_endpoint
                        current=Settings.load(self.settings_file)
                        result=asyncio.run(probe_chat_endpoint(current))
                        if provider_kind(current)=='lan':
                            note_server_result(current,True,'ok')
                        return result
                    self._run(rid,action,worker)
                elif action in {'listCustomTools','previewCustomTool',
                                  'approveCustomTool','disableCustomTool'}:
                    identifier=body.get('id')
                    query=body.get('query')
                    if action!='listCustomTools' and (type(identifier) is not int or identifier<1):
                        raise ValueError('A valid custom tool ID is required')
                    def worker():
                        from .knowledge import KnowledgeStore
                        from .workspace import Workspace
                        current=Settings.load(self.settings_file)
                        if not current.tool_workshop_enabled:
                            raise PermissionError('Tool Workshop is disabled')
                        home=app_data()
                        knowledge=KnowledgeStore(home/'knowledge')
                        workshop=ToolWorkshop(home=home,project=current.project,
                            knowledge=knowledge,
                            workspace=Workspace(Path(current.workspace)) if current.workspace else None,
                            intelligence=for_settings(current,home))
                        try:
                            if action=='listCustomTools':
                                return workshop.catalog()
                            if action=='previewCustomTool':
                                return workshop.run(identifier,query,preview=True)
                            if action=='approveCustomTool':
                                return workshop.approve(identifier)
                            return workshop.disable(identifier)
                        finally:
                            workshop.close()
                            knowledge.close()
                    self._run(rid,action,worker)
                elif action=='testMcpConnection':
                    server=str(body.get('server',''))
                    if server not in {'graphify_docs','graphify_local','obsidian_live'}:
                        raise ValueError('Unknown MCP connector')
                    def worker():
                        import asyncio
                        gateway=MCPGateway(Settings.load(self.settings_file))
                        # Probe does not call any server tool or perform writes.
                        return asyncio.run(gateway.probe(server))
                    self._run(rid,action,worker)
                elif action=='discoverStudio':
                    target = validate_target(body.get('target'))
                    def discover_worker():
                        current = Settings.load(self.settings_file)
                        if current.studio_target != target:
                            raise ValueError('Studio connection changed; test the selected connection again')
                        self.studio_status = check_studio(current, self.settings_file.parent)
                        return self.studio_status
                    self._run(rid,action,discover_worker)
                elif action=='selectStudio':
                    if self.active_task:
                        raise RuntimeError('Wait for the current task before selecting a Studio')
                    identifier, target = body.get('studio_id'), validate_target(body.get('target'))
                    def select_worker():
                        import asyncio
                        current = Settings.load(self.settings_file)
                        if current.studio_target != target:
                            raise ValueError('Studio connection changed; test the selected connection again')
                        report = asyncio.run(select_instance(current, identifier, home=self.settings_file.parent))
                        latest = Settings.load(self.settings_file)
                        if latest.studio_target != target or self.active_task:
                            raise ValueError('Studio connection changed while selecting; try again')
                        latest.studio_id = current.studio_id
                        latest.studio_edit = False
                        latest.studio_luau = False
                        latest.save(self.settings_file)
                        self.studio_status = report
                        return report
                    self._run(rid,action,select_worker)
                elif action=='checkUpdates':
                    from .updates import get_latest
                    self._run(rid,action,lambda:asdict(get_latest()))
                elif action=='installUpdate':
                    if self.active_update:
                        raise RuntimeError('STAR is already installing an update')
                    self.active_update = True
                    self._run(rid,action,lambda:prepare_desktop_update(self,rid,app_data()))
                elif action=='transcribe':
                    path=file_allowed(Path(str(body.get('file',''))),self.allowed_files)
                    from .media_features import transcribe_audio
                    self._run(rid,action,lambda:{'text':transcribe_audio(path)})
                return json.dumps({'ok':True,'pending':True,'requestId':rid})
            except Exception as exc:
                return json.dumps({'ok':False,'error':f'{type(exc).__name__}: {str(exc)[:380]}'})

        def close(self):
            # Restart Manager, session end and ordinary window close share this path.
            # Record the cancellation before stopping services: Qt may exit while a
            # background worker is still waiting on its provider.
            if self._closing:
                return
            self._closing = True
            self.research_timer.stop()
            self.cancel_chat.set()
            if self.turn is not None:
                _, detail = failure_outcome('sendMessage', RuntimeError('cancelled by user'), cancelled=True)
                record_turn_failure(app_data(), self.turn, 'cancelled', detail)
            # Stop owned child processes before any forced exit can interrupt cleanup.
            self.comfy_launcher.stop()      # only a ComfyUI that STAR itself started
            gpu_helper.HELPER.shutdown()    # Use my GPU: the model server STAR started
            self.discord.close()            # the Discord bot STAR started (if any) stops with STAR
            self.warmer.cancel()
            self.draft_warmer.cancel()
            self.runtime.stop()
            # A provider thread may be stuck in native I/O and ThreadPoolExecutor
            # workers are non-daemon. The packaged Windows fallback starts only
            # after child cleanup; it is not a deadline for the entire shutdown.
            # The daemon timer has no effect if Python exits normally.
            if os.name == 'nt' and getattr(sys, 'frozen', False):
                # A staged update starts Setup after the window closes, so give it room.
                seconds = 20.0 if getattr(self, 'pending_update', None) is not None else 1.8
                deadline = threading.Timer(seconds, lambda: os._exit(0))
                deadline.daemon = True
                deadline.start()
            self.voice.close()
            self.pool.shutdown(wait=False,cancel_futures=True)

    class Shell(QMainWindow):
        def __init__(self):
            super().__init__()
            self.setWindowTitle(f'STAR Intelligence — v{__version__}')
            self.resize(1440,900)
            self.setMinimumSize(920,650)
            self.view=QWebEngineView(self)
            self.page=RestrictedPage(self.view)
            self.view.setPage(self.page)
            self.setCentralWidget(self.view)
            self.channel=QWebChannel(self.view.page())
            self.bridge=Bridge(self)
            self.channel.registerObject('starBridge',self.bridge)
            self.view.page().setWebChannel(self.channel)
            url=QUrl.fromLocalFile(str(index.resolve()))
            url.setQuery('desktop=1')
            self.view.load(url)
        def closeEvent(self,event):
            self.bridge.close()
            return super().closeEvent(event)

    app=QApplication.instance() or QApplication(sys.argv)
    app.setApplicationName('STAR Intelligence')
    app.setStyle('Fusion')
    from .single_instance import DesktopInstance, bypass_single_instance
    shell = None

    def activate():
        if shell is not None:
            if shell.isMinimized():
                shell.showNormal()
            shell.show()
            shell.raise_()
            shell.activateWindow()

    instance = None
    if not bypass_single_instance():
        instance = DesktopInstance(app_data(), activate)
        if not instance.primary:
            return 0
    def make_shell():
        window = Shell()
        # Windows Restart Manager asks Qt to end the session via commitDataRequest.
        # aboutToQuit also covers app.quit() without a close event.
        app.commitDataRequest.connect(lambda manager: close_for_session(window, manager))
        app.aboutToQuit.connect(window.bridge.close)
        return window

    def adopt(window):
        nonlocal shell
        shell = window

    # Closes the window and releases the instance lock, then runs a staged update Setup.
    return run_desktop(app, make_shell, instance, adopt)
