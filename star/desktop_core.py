"""STAR Desktop's local-only backend. The Qt GUI calls this from worker threads."""
from __future__ import annotations
import asyncio
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import re
import sqlite3
import logging
import time
from .analytics import AnalyticsStore
from .atomic_io import atomic_write_text, move_aside
from dataclasses import dataclass, asdict, replace, field
from contextlib import AsyncExitStack
from typing import Callable

from .agent import execute, HistoryWindowPressure
from .media import image_part
from .memory import Memory
from . import conversation_memory
from .workspace import Workspace
from .intelligence import for_settings
from .reverse_engineering import for_settings as reverse_engineering_for
from .mcp_connections import MCPGateway
from .tool_workshop import ToolWorkshop
from .specialist_agents import ResearchTeam
from .providers import (ALL_PROVIDERS, background_client, call_limits, connection_for, llama_request_fields,
                        look_for_busy_slots, model_slots_full,
                        model_unavailable, open_client,
                        provider_kind, server_context_tokens, validate_lan_endpoint)
from .brain_router import (select_route, validate_alias, is_roblox_task, deep_request, ROBLOX_QUALITY_NOTES,
                           busy_downgrade_allowed)
from .instant_route import decide_instant_route, loaded_local_model, answer_on_pc
from . import server_roles, turn_memory
from .doc_knowledge import validate_knowledge_endpoint
from . import doc_grounding, skill_packs, roblox_errors
from . import best_of_n
from . import edit_format
from . import studio_loop, studio_tool_examples
from . import project_rules
from . import gpu_helper
from .studio_connections import default_target, validate_target


def app_data() -> Path:
    # Don't store data beside the exe: installations under Program Files are read-only.
    if os.name == 'nt':
        base = Path(os.environ.get('APPDATA') or Path.home() / 'AppData' / 'Roaming')
        return base / 'STAR'
    return Path(os.environ.get('XDG_DATA_HOME', Path.home() / '.local' / 'share')) / 'star-ai'


@dataclass
class Settings:
    endpoint: str = 'http://127.0.0.1:8080/v1'
    provider: str = 'local'
    model: str = ''
    fast_model: str = ''
    reasoning_model: str = ''
    roblox_model: str = ''
    vision_model: str = ''
    project: str = 'STAR'
    workspace: str = ''
    studio_id: str = ''
    studio_target: str = field(default_factory=default_target)
    studio_edit: bool = False
    # The sandbox rule itself is code (star/studio_loop.py): edits only in a blank unsaved place.
    studio_own_places: bool = False       # ...and, when on, in places owned by STAR's own Roblox account
    studio_luau: bool = False             # let STAR run Luau in that sandbox (needed to create instances)
    studio_tool_examples: bool = False    # opt-in: one example call appended to each error-prone Studio tool
    workspace_edit: bool = False
    debug_evidence_enabled: bool = False  # opt-in report analysis; never grants process execution or attachment
    max_calls: int = 12
    context_chars: int = 26000
    llama_server: str = ''
    gguf_model: str = ''
    gpu_layers: int = 25
    router_models_dir: str = ''
    router_context: int = 4096
    reduced_motion: bool = False
    comfy_workflow: str = ''
    comfy_prompt_node: str = '6'
    comfy_port: int = 8188
    # Where media runs (star/media_places.py): 'pc' = this PC's graphics card, 'servers' = the STAR Brains.
    media_images: str = 'pc'
    media_voice: str = 'pc'
    media_video: str = 'servers'
    media_chat_auto: bool = True
    session_capabilities_prompt: bool = False
    media_use_references: bool = True     # give a project's pinned reference images to image and UI work
    comfy_home: str = ''                  # folder of the ComfyUI install STAR may start ('' = started by hand)
    ffmpeg_dir: str = ''                  # folder with ffmpeg and ffprobe ('' = look on PATH)
    # Longest side, in pixels, of a picture as the STAR Server or the on-device brain reads it
    # (0 = full size). The attached file itself is never changed. See star/media.py.
    picture_max_side: int = 1280
    obsidian_vault: str = ''
    obsidian_enabled: bool = False
    skills_enabled: bool = True
    graphify_enabled: bool = True
    roblox_research_enabled: bool = True
    asset_forge_enabled: bool = False     # owner opt-in; external asset search also needs Roblox research
    tool_workshop_enabled: bool = True
    specialists_enabled: bool = True
    # Local reverse-engineering tools (star/reverse_engineering.py). Off by default; opt-in.
    # Defensive, workspace-confined analysis of your own/permitted binaries only.
    reverse_engineering_enabled: bool = False
    specialist_parallelism: int = 1
    team_timeout_min: int = 30      # bounded specialist request deadline, seconds
    team_timeout_max: int = 900     # allows slow on-device and STAR Server inference
    mcp_graphify_docs: bool = False
    mcp_graphify_local: bool = False
    mcp_graphify_port: int = 8931
    mcp_obsidian_live: bool = False
    mcp_github_repositories: bool = False  # explicit opt-in; fixed read-only repository discovery
    github_repository_access_source: str = 'gh'  # existing GitHub CLI account, or explicit env token
    blender_enabled: bool = False          # only attach STAR's local Blender MCP when requested
    blender_edit: bool = False             # explicit owner permission for new isolated scene jobs
    blender_executable: str = ''           # installed local executable; '' = discover without downloading
    blender_brain2: bool = False           # use the Blender on brain 2 (the second STAR server) instead of a local one
    blender_motion_qa: bool = False        # offer the read-only animation motion check tool (star/animation_regression.py)
    # STAR Server (provider 'star_server'): an owner-entered private LAN address.
    # The server key is never stored here; it lives in the OS keyring.
    server_endpoint: str = ''
    allow_cgnat: bool = False         # opt in to Tailscale / carrier-grade NAT; metadata IP stays blocked
    server_timeout: int = 600        # seconds of silence allowed for one server request
    server_parallel: int = 1         # match the server's llama.cpp -np slot count
    server_context_tokens: int = 0   # per-request context; 0 = use what the server reports
    instant_route_enabled: bool | None = False   # Explicit opt-in; legacy None stays off
    # STAR Knowledge (official docs search, API lookup, Luau checks) on the same private
    # network: '' = the STAR Server's host on the knowledge port, 'off' = never ask it.
    knowledge_endpoint: str = ''
    luau_run_before_answer: bool = False  # explicit opt-in, remote sandbox only
    # STAR search (self-hosted SearXNG behind star-search-gateway, server/searxng): '' = the STAR
    # Server's host on port 8093, 'off' = never ask it. Used when no Brave/Tavily key is set.
    search_endpoint: str = ''
    # Search the web automatically for questions about news, prices, weather or "latest" things.
    web_auto_search: bool = True
    # Learning (star/lessons.py). Lessons are local project notes, never weights.
    learning_auto_accept: bool = True     # False = "review everything": even my own words wait for approval
    learning_digest: bool = True          # let the fast model reword raw captures into candidates, in the background
    learning_digest_cloud: bool = False   # ...also when the selected provider is a hosted one
    practice_lessons_enabled: bool = False  # off until the owner opts in
    worked_examples_enabled: bool = False   # read-only retrieval, off until owner opts in
    gold_examples_enabled: bool = False     # verified licence-recorded examples (star/gold_bank.py), opt-in
    presolve_enabled: bool = False          # overnight pre-solved answers (star/presolve.py), off until owner opts in
    # Owner default (O1): night school's text lessons that won the paired gate go live for 14 days, visibly, with undo
    # (star/learned_week.py). False = bundles only add candidates that wait for review.
    learning_auto_live: bool = True
    research_auto_check: bool = False      # opt-in daily public-doc checks while desktop is open
    deep_research_enabled: bool = False    # candidate: bounded page reading for Team + Research
    scholarly_research_enabled: bool = False  # deep research also asks Crossref/OpenAlex metadata (star/public_research.py)
    # Generate several, test, keep what works (star/best_of_n.py): 'off' or 'auto' (2 to best_of_n_max candidates
    # for code requests on STAR Server, as many as the free model slots allow). Off until the owner opts in.
    best_of_n: str = 'off'
    best_of_n_max: int = 4
    discord_autostart: bool = False        # opt-in: STAR Desktop starts and supervises the Discord bot (star/discord_supervisor.py)
    roblox_docs_live_enabled: bool = False  # opt-in live retrieval from create.roblox.com/docs; STAR_ROBLOX_DOCS_LIVE=1 also enables
    project_rules_enabled: bool = False    # opt-in: add the workspace's AGENTS.md (star/project_rules.py) to each turn
    luau_retry_ladder: bool = False        # opt-in: a second, thinking repair after a failed Luau repair
    # Anti-slop post-check of the answer (star/slop.py): 'off', 'flag' (a note on invented APIs, unverifiable claims
    # and stubs) or 'trim' (the note, and filler lines outside code are removed). Off until the owner opts in.
    slop_check: str = 'off'
    # Opt-in (star/api_hints.py): the real member names of the Roblox classes a request names, from the local API
    # dump, as a per-turn reference section. Aimed at invented members, the most common slop in stored answers.
    api_hints_enabled: bool = False
    # Opt-in (star/edit_format.py): pasted code + "fix/change this" is answered with SEARCH/REPLACE blocks that STAR
    # applies and checks, instead of the whole file written again; a block that does not apply falls back to that.
    edit_diff: bool = False
    skill_pack_embeddings: bool = False    # opt-in: STAR Server embeddings pick a skill pack the keywords missed
    # Settings > "Use my GPU" (star/gpu_helper.py): STAR's code model on this PC's NVIDIA card, per request, the
    # server as fallback. Off by default. Paths '' = <app data>/gpu-helper/llama-server.exe and star-fast.gguf.
    use_my_gpu: bool = False
    gpu_helper_server: str = ''
    gpu_helper_model: str = ''
    gpu_idle_minutes: int = 10
    # Settings > "Start thinking while I type" (star/prefill_warm.py): while the owner types, the server reads the
    # conversation and the draft into its prompt cache, so the answer starts sooner. Off by default.
    prefill_while_typing: bool = False

    @classmethod
    def load(cls, file: Path):
        if not file.exists():
            return cls()
        raw = _read_settings_object(file)
        if raw is None:
            return cls()
        if 'studio_target' not in raw:
            # An old ID was selected on an unknown implicit route; never rebind its grants.
            raw = {**raw, 'studio_target': 'local_pc', 'studio_id': '', 'studio_edit': False, 'studio_luau': False}
        return cls(**{k: v for k, v in raw.items() if k in cls.__dataclass_fields__})

    def validate(self):
        validate_target(self.studio_target)
        for name in ('model', 'fast_model', 'reasoning_model', 'roblox_model', 'vision_model'):
            validate_alias(getattr(self, name), field=name)
        if not isinstance(self.provider, str) or self.provider not in ALL_PROVIDERS:
            raise ValueError('Unknown model provider')
        if not re.fullmatch(r'http://(?:127\.0\.0\.1|localhost):\d{2,5}/v1/?', self.endpoint):
            raise ValueError('Use a loopback local inference URL ending in /v1')
        port = int(self.endpoint.split(':')[-1].split('/')[0])
        if not 1 <= port <= 65535:
            raise ValueError('Invalid local inference port')
        self._validate_server()
        if self.instant_route_enabled is not None and type(self.instant_route_enabled) is not bool:
            raise ValueError('Instant answers setting must be true, false or automatic')
        if not self.project.strip() or len(self.project) > 100:
            raise ValueError('Project name is invalid')
        if any(type(getattr(self, key)) is not bool
               for key in ('obsidian_enabled', 'skills_enabled', 'graphify_enabled', 'debug_evidence_enabled',
                            'mcp_graphify_docs','mcp_graphify_local','mcp_obsidian_live','mcp_github_repositories',
                            'roblox_research_enabled', 'asset_forge_enabled', 'tool_workshop_enabled',
                            'specialists_enabled', 'learning_auto_accept', 'learning_digest',
                            'learning_digest_cloud', 'practice_lessons_enabled', 'worked_examples_enabled', 'learning_auto_live', 'research_auto_check', 'deep_research_enabled', 'scholarly_research_enabled', 'discord_autostart', 'roblox_docs_live_enabled', 'media_chat_auto', 'session_capabilities_prompt', 'media_use_references', 'studio_own_places', 'studio_luau', 'reverse_engineering_enabled',
                            'blender_enabled', 'blender_edit', 'blender_motion_qa', 'allow_cgnat', 'luau_run_before_answer', 'blender_brain2', 'studio_tool_examples', 'project_rules_enabled', 'luau_retry_ladder', 'skill_pack_embeddings', 'presolve_enabled', 'api_hints_enabled', 'gold_examples_enabled', 'edit_diff')):
            raise ValueError('Tool access settings must be true or false')
        if (not isinstance(self.github_repository_access_source, str)
                or self.github_repository_access_source not in {'gh', 'env'}):
            raise ValueError('GitHub repository credential source must be gh or env')
        if self.obsidian_vault and not Path(self.obsidian_vault).expanduser().is_dir():
            raise ValueError('Obsidian vault must be an existing folder')
        if self.obsidian_enabled and not self.obsidian_vault:
            raise ValueError('Select an Obsidian vault before enabling read access')
        if self.workspace and (not Path(self.workspace).expanduser().is_dir()):
            raise ValueError('Choose an existing workspace directory')
        if self.best_of_n not in ('off', 'auto') or type(self.best_of_n_max) is not int                 or not 2 <= self.best_of_n_max <= 8:
            raise ValueError('Best-of-N must be off or auto, with 2 to 8 candidates')
        if self.slop_check not in ('off', 'flag', 'trim'):
            raise ValueError('Slop check must be off, flag or trim')
        if type(self.specialist_parallelism) is not int or self.specialist_parallelism not in (1,2):
            raise ValueError('Limit specialists to 1 or 2 concurrent model calls')
        if (type(self.team_timeout_min) is not int or type(self.team_timeout_max) is not int
                or not 1 <= self.team_timeout_min <= self.team_timeout_max <= 1800):
            raise ValueError('Team timeout minimum/maximum must be 1 to 1800 seconds')
        if type(self.mcp_graphify_port) is not int or not 1024 <= self.mcp_graphify_port <= 65535:
            raise ValueError('Invalid local Graphify MCP port')
        if self.blender_edit and not self.blender_enabled:
            raise ValueError('Enable Blender before enabling Blender scene creation')
        if self.blender_brain2 and not self.blender_enabled:
            raise ValueError('Enable Blender before choosing the Blender on brain 2')
        if (not isinstance(self.blender_executable, str) or len(self.blender_executable) > 2048
                or '\x00' in self.blender_executable
                or self.blender_executable.startswith(('\\\\', '//'))
                or '://' in self.blender_executable):
            raise ValueError('Choose a trusted local Blender executable, not a URL or network share')
        if self.studio_edit and not self.studio_id.strip():
            raise ValueError('Choose a disposable Studio instance before editing')
        if not 1 <= self.comfy_port <= 65535 or not re.fullmatch(r'[A-Za-z0-9_-]{1,40}', self.comfy_prompt_node):
            raise ValueError('Invalid local image generation configuration')
        if any(getattr(self, key) not in ('pc', 'servers')
               for key in ('media_images', 'media_voice', 'media_video')):
            raise ValueError('Choose STAR Brains (servers) or This PC for each media capability')
        for key, label in (('comfy_home', 'ComfyUI folder'), ('ffmpeg_dir', 'FFmpeg folder')):
            value = getattr(self, key)
            if (not isinstance(value, str) or len(value) > 1024 or '\x00' in value
                    or value.lower().startswith(('http:', 'https:', 'file:', '\\\\'))):
                raise ValueError(f'Choose a local folder for the {label}')
        if type(self.picture_max_side) is not int or not (self.picture_max_side == 0
                                                           or 512 <= self.picture_max_side <= 4096):
            raise ValueError('Picture size for the brain must be 0 (full size) or 512 to 4096 pixels')
        if type(self.gpu_layers) is not int or not 0 <= self.gpu_layers <= 1000:
            raise ValueError('GPU layers must be between 0 and 1000')
        if type(self.router_context) is not int or not 512 <= self.router_context <= 32768:
            raise ValueError('Router context must be between 512 and 32768')
        if (not isinstance(self.router_models_dir, str)
                or len(self.router_models_dir) > 2048
                or '\x00' in self.router_models_dir
                or self.router_models_dir.lower().startswith(('http:', 'https:', 'file:'))):
            raise ValueError('Choose a local folder for the GGUF model router')
        if type(self.use_my_gpu) is not bool:
            raise ValueError('Use my GPU must be on or off')
        if type(self.prefill_while_typing) is not bool:
            raise ValueError('Start thinking while I type must be on or off')
        for key in ('gpu_helper_server', 'gpu_helper_model'):
            value = getattr(self, key)
            if (not isinstance(value, str) or len(value) > 1024 or '\x00' in value
                    or value.lower().startswith(('http:', 'https:', 'file:', '\\\\', '//'))):
                raise ValueError('Choose local files for Use my GPU, not a URL or network share')
        if type(self.gpu_idle_minutes) is not int or not 1 <= self.gpu_idle_minutes <= 240:
            raise ValueError('Use my GPU: idle minutes must be 1 to 240')
        if not 1 <= self.max_calls <= 30 or not 6000 <= self.context_chars <= 80000:
            raise ValueError('Invalid model call or context budget')

    def _validate_server(self):
        """STAR Server (LAN) settings. The loopback `endpoint` rule above is separate."""
        if not isinstance(self.server_endpoint, str):
            raise ValueError('STAR Server address must be text')
        if self.server_endpoint:
            validate_lan_endpoint(self.server_endpoint, allow_cgnat=self.allow_cgnat)
        elif provider_kind(self) == 'lan':
            validate_lan_endpoint('')  # raises the "enter your server address" message
        if not isinstance(self.knowledge_endpoint, str):
            raise ValueError('STAR Knowledge address must be text')
        if self.knowledge_endpoint and self.knowledge_endpoint != 'off':
            validate_knowledge_endpoint(self.knowledge_endpoint)
        if not isinstance(self.search_endpoint, str):
            raise ValueError('STAR search address must be text')
        if self.search_endpoint and self.search_endpoint != 'off':
            from .web_search import validate_search_endpoint
            validate_search_endpoint(self.search_endpoint)
        if not isinstance(self.web_auto_search, bool):
            raise ValueError('Automatic web search must be on or off')
        if type(self.server_timeout) is not int or not 30 <= self.server_timeout <= 1800:
            raise ValueError('STAR Server timeout must be 30 to 1800 seconds')
        if type(self.server_parallel) is not int or not 1 <= self.server_parallel <= 4:
            raise ValueError('STAR Server parallel requests must be 1 to 4')
        if (type(self.server_context_tokens) is not int
                or not (self.server_context_tokens == 0 or 1024 <= self.server_context_tokens <= 1_048_576)):
            raise ValueError('STAR Server context must be 0 (automatic) or 1024 to 1048576 tokens')

    def save(self, file: Path):
        self.validate()
        # configuration is nonsecret; never write bearer tokens here. Written in one step so a crash,
        # power cut or a reader in another STAR process never sees half a settings file.
        atomic_write_text(file, json.dumps(asdict(self), indent=2))


_log = logging.getLogger(__name__)


def _read_settings_object(file: Path) -> dict | None:
    """The saved settings as a dict, or None after moving a damaged file aside.

    A truncated or hand-broken settings.json used to raise on every Settings.load, so the desktop
    could not start and every bridge request failed. The file is read twice (a writer from an older
    STAR copy may still replace it in place) before it is renamed to settings.json.corrupt-<time>
    for the owner to inspect, and the defaults are used. The defaults are the safe ones: Studio
    editing, Luau execution and every opt-in feature are off.
    """
    problem = None
    damaged = 0
    for attempt in range(4):
        try:
            raw = json.loads(file.read_text(encoding='utf-8'))
        except FileNotFoundError:
            return None
        except ValueError as exc:            # also UnicodeDecodeError: the content is damaged
            problem = exc
            damaged += 1
            if damaged >= 2:
                break
            time.sleep(0.05)
            continue
        except OSError:
            # Locked or unreadable right now (another STAR process swapping it in on Windows, a virus
            # scanner, permissions): that is not damage, so the owner's file is never moved aside for it.
            if attempt == 3:
                raise
            time.sleep(0.05)
            continue
        if isinstance(raw, dict):
            return raw
        problem = TypeError(f'settings file holds {type(raw).__name__}, not an object')
        break
    backup = move_aside(file)
    _log.warning('STAR settings could not be read (%s); using defaults%s', type(problem).__name__,
                 f'; the damaged file was kept as {backup.name}' if backup else '')
    return None


TERMINAL_STATUSES = ('failed', 'cancelled')


# Gives every project whose pre-upgrade messages (chat_id 'legacy') have no chat row yet its
# 'Previous conversation' row. Runs on every open, so it must not read the whole messages table:
# the project names are walked through idx_chat_messages one index seek at a time (a "skip
# scan"), projects that already have their legacy row are left out (INSERT OR IGNORE would keep
# them unchanged anyway), and only the remaining projects' legacy rows are read, by index. The
# rows inserted are exactly those of the plain form
#   INSERT OR IGNORE ... SELECT ... FROM messages WHERE chat_id='legacy' GROUP BY project
# which scanned every message on every open.
LEGACY_CHAT_MIGRATION = (
    "INSERT OR IGNORE INTO chats (project,id,title,created,updated) "
    "SELECT project,'legacy','Previous conversation',MIN(created),MAX(created) "
    "FROM messages WHERE chat_id='legacy' AND project IN ("
    "WITH RECURSIVE projects(name) AS ("
    "SELECT MIN(project) FROM messages "
    "UNION ALL SELECT (SELECT MIN(project) FROM messages WHERE project>name) FROM projects WHERE name IS NOT NULL) "
    "SELECT name FROM projects WHERE name IS NOT NULL "
    "EXCEPT SELECT project FROM chats WHERE id='legacy') "
    "GROUP BY project"
)


class Conversations:
    """Persistent, project-scoped chat threads.

    Existing messages are migrated in-place into a legacy thread without deleting
    or rewriting their content. Callers that omit chat_id retain the historical
    project-wide recent() behavior; React explicitly selects a thread.
    """
    def __init__(self, db: Path):
        import sqlite3
        db.parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(db, timeout=30)
        self.connection.execute(
            'CREATE TABLE IF NOT EXISTS messages '
            '(id INTEGER PRIMARY KEY AUTOINCREMENT, project TEXT NOT NULL, '
            'role TEXT NOT NULL, body TEXT NOT NULL, created TEXT NOT NULL)'
        )
        columns = {row[1] for row in self.connection.execute('PRAGMA table_info(messages)')}
        if 'chat_id' not in columns:
            self.connection.execute(
                "ALTER TABLE messages ADD COLUMN chat_id TEXT NOT NULL DEFAULT 'legacy'"
            )
        # Turn outcome (additive; old rows and older STAR versions stay valid).
        # status is 'complete' except on the terminal 'event' record of a turn that
        # failed or was cancelled; reply_to is the user message row that record answers.
        if 'status' not in columns:
            self.connection.execute(
                "ALTER TABLE messages ADD COLUMN status TEXT NOT NULL DEFAULT 'complete'"
            )
        if 'reply_to' not in columns:
            self.connection.execute('ALTER TABLE messages ADD COLUMN reply_to INTEGER')
        self.connection.execute(
            'CREATE TABLE IF NOT EXISTS chats '
            '(project TEXT NOT NULL, id TEXT NOT NULL, title TEXT NOT NULL, '
            'created TEXT NOT NULL, updated TEXT NOT NULL, PRIMARY KEY (project,id))'
        )
        self.connection.execute(
            'CREATE TABLE IF NOT EXISTS active_chats '
            '(project TEXT PRIMARY KEY, chat_id TEXT NOT NULL)'
        )
        self.connection.execute(
            'CREATE INDEX IF NOT EXISTS idx_chat_messages '
            'ON messages(project,chat_id,id)'
        )
        # The owner's thumb on an answer (additive: a new table, nothing existing changes).
        self.connection.execute(
            'CREATE TABLE IF NOT EXISTS message_feedback '
            '(message_id INTEGER PRIMARY KEY, project TEXT NOT NULL, chat_id TEXT NOT NULL, '
            'value TEXT NOT NULL, updated TEXT NOT NULL)'
        )
        # A pre-upgrade conversation is preserved verbatim under one stable ID.
        self.connection.execute(LEGACY_CHAT_MIGRATION)
        self.connection.commit()

    def _next_chat_stamp(self, project: str) -> str:
        """Make per-project chat activity order stable at coarse clock ticks.

        Old SQLite databases have no sequence column. ISO UTC timestamps are
        kept in the existing fields; ties in legacy rows sort by rowid.
        """
        stamp = datetime.now(timezone.utc)
        newest = self.connection.execute(
            'SELECT updated FROM chats WHERE project=? '
            'ORDER BY updated DESC, rowid DESC LIMIT 1', (project,)
        ).fetchone()
        if newest:
            try:
                previous = datetime.fromisoformat(newest[0])
                if previous.tzinfo is None:
                    previous = previous.replace(tzinfo=timezone.utc)
                if stamp <= previous:
                    stamp = previous + timedelta(microseconds=1)
            except (TypeError, ValueError, OverflowError):
                # Older malformed dates are left untouched; new writes use UTC.
                pass
        return stamp.isoformat()

    def new_chat(self, project: str) -> str:
        import uuid
        # Reuse an already blank active thread instead of filling the history with
        # duplicate untitled chats when the New chat button is clicked repeatedly.
        current = self.connection.execute(
            'SELECT a.chat_id FROM active_chats a JOIN chats c '
            'ON c.project=a.project AND c.id=a.chat_id '
            'WHERE a.project=? AND NOT EXISTS '
            '(SELECT 1 FROM messages m WHERE m.project=a.project AND m.chat_id=a.chat_id)',
            (project,)
        ).fetchone()
        if current:
            return current[0]
        chat_id = uuid.uuid4().hex
        created = self._next_chat_stamp(project)
        with self.connection:
            self.connection.execute(
                'INSERT INTO chats(project,id,title,created,updated) VALUES (?,?,?,?,?)',
                (project, chat_id, 'New chat', created, created)
            )
            self.connection.execute(
                'INSERT INTO active_chats(project,chat_id) VALUES (?,?) '
                'ON CONFLICT(project) DO UPDATE SET chat_id=excluded.chat_id',
                (project, chat_id)
            )
        return chat_id

    def active_chat(self, project: str) -> str:
        found = self.connection.execute(
            'SELECT a.chat_id FROM active_chats a INNER JOIN chats c '
            'ON c.project=a.project AND c.id=a.chat_id WHERE a.project=?',
            (project,)
        ).fetchone()
        if found:
            return found[0]
        newest = self.connection.execute(
            'SELECT id FROM chats WHERE project=? ORDER BY updated DESC, rowid DESC LIMIT 1',
            (project,)
        ).fetchone()
        if newest:
            self.switch_chat(project, newest[0])
            return newest[0]
        return self.new_chat(project)

    def switch_chat(self, project: str, chat_id: str) -> None:
        found = self.connection.execute(
            'SELECT 1 FROM chats WHERE project=? AND id=?', (project, chat_id)
        ).fetchone()
        if not found:
            raise ValueError('Conversation not found in this workspace')
        with self.connection:
            self.connection.execute(
                'INSERT INTO active_chats(project,chat_id) VALUES (?,?) '
                'ON CONFLICT(project) DO UPDATE SET chat_id=excluded.chat_id',
                (project, chat_id)
            )

    def list_chats(self, project: str, limit: int = 60) -> list[dict]:
        return [
            {'id': chat_id, 'title': title, 'created': created, 'updated': updated}
            for chat_id, title, created, updated in self.connection.execute(
                'SELECT id,title,created,updated FROM chats WHERE project=? '
                'ORDER BY updated DESC, rowid DESC LIMIT ?', (project, limit)
            )
        ]

    def add(self, project: str, role: str, body: str, chat_id: str | None = None, *,
            status: str = 'complete', reply_to: int | None = None) -> int:
        """Store one message and return its row id."""
        if role not in {'user', 'assistant', 'event'}:
            raise ValueError('Invalid message role')
        if status != 'complete' and (status not in TERMINAL_STATUSES or role != 'event'
                                     or type(reply_to) is not int):
            raise ValueError('Only an event record that answers a user message can be failed or cancelled')
        stamp = self._next_chat_stamp(project)
        target = chat_id if chat_id is not None else 'legacy'
        with self.connection:
            if chat_id is None:
                self.connection.execute(
                    'INSERT OR IGNORE INTO chats(project,id,title,created,updated) '
                    'VALUES (?,?,?,?,?)',
                    (project, 'legacy', 'Previous conversation', stamp, stamp)
                )
            elif not self.connection.execute(
                'SELECT 1 FROM chats WHERE project=? AND id=?', (project, chat_id)
            ).fetchone():
                raise ValueError('Cannot save to a missing conversation')
            row = self.connection.execute(
                'INSERT INTO messages(project,role,body,created,chat_id,status,reply_to) '
                'VALUES (?,?,?,?,?,?,?)',
                (project, role, body, stamp, target, status, reply_to)
            ).lastrowid
            # Name new chats from their first prompt, without altering legacy titles.
            if role == 'user' and target != 'legacy':
                text = ' '.join(body.split())
                # A long first message is shortened for the title; the ellipsis says so
                # (the top bar used to show a title that simply stopped mid-word).
                first_line = (text if len(text) <= 64 else text[:63].rstrip() + '…') or 'New chat'
                self.connection.execute(
                    'UPDATE chats SET title=? WHERE project=? AND id=? AND title=?',
                    (first_line, project, target, 'New chat')
                )
            self.connection.execute(
                'UPDATE chats SET updated=? WHERE project=? AND id=?',
                (stamp, project, target)
            )
        return int(row)

    def add_terminal(self, project: str, chat_id: str, user_id: int, status: str, detail: str) -> int | None:
        """Record that the turn started by user message ``user_id`` ended without an answer.

        Idempotent: a turn gets at most one terminal record. Returns the new row id,
        or None when the turn was already closed.
        """
        if status not in TERMINAL_STATUSES:
            raise ValueError('Terminal status must be failed or cancelled')
        owner = self.connection.execute(
            "SELECT 1 FROM messages WHERE id=? AND project=? AND chat_id=? AND role='user'",
            (user_id, project, chat_id)
        ).fetchone()
        if not owner:
            raise ValueError('Terminal record must answer a user message in the same conversation')
        if self.connection.execute(
            "SELECT 1 FROM messages WHERE reply_to=? AND status!='complete'", (user_id,)
        ).fetchone():
            return None
        return self.add(project, 'event', detail[:2000], chat_id=chat_id,
                        status=status, reply_to=user_id)

    def recent(self, project: str, limit: int = 70, chat_id: str | None = None,
               include_events: bool = True):
        """Newest ``limit`` messages, oldest first. Model context passes include_events=False."""
        scope, args = ('project=?', [project]) if chat_id is None else ('project=? AND chat_id=?', [project, chat_id])
        if not include_events:
            scope += " AND role IN ('user','assistant')"
        rows = self.connection.execute(
            f'SELECT role,body,created FROM messages WHERE {scope} ORDER BY id DESC LIMIT ?',
            (*args, limit)
        ).fetchall()
        return list(reversed(rows))

    def raw_history_records(self, project: str, chat_id: str | None = None) -> list[dict]:
        """Full ID-bearing records of exactly one chat, including terminal outcomes."""
        return conversation_memory.raw_records(self.connection, project, chat_id)

    def recent_records(self, project: str, limit: int = 70, chat_id: str | None = None) -> list[dict]:
        """Like recent(), with row ids and turn outcome, for the UI state payload."""
        scope, args = ('project=?', [project]) if chat_id is None else ('project=? AND chat_id=?', [project, chat_id])
        rows = self.connection.execute(
            'SELECT id,role,body,created,status,reply_to,'
            '(SELECT value FROM message_feedback f WHERE f.message_id=messages.id) FROM messages '
            f'WHERE {scope} ORDER BY id DESC LIMIT ?', (*args, limit)
        ).fetchall()
        return [{'id': i, 'role': role, 'body': body, 'created': created,
                 'status': status, 'reply_to': reply_to, 'feedback': feedback or ''}
                for i, role, body, created, status, reply_to, feedback in reversed(rows)]

    def set_feedback(self, project: str, message_id: int, value: str) -> dict:
        """Store, change or clear ('') the owner's thumb on one answer of this project.

        Returns the chat, the answer and the question it answered, for the lesson record.
        """
        if value not in ('up', 'down', ''):
            raise ValueError('Feedback must be up, down or empty')
        row = self.connection.execute(
            "SELECT chat_id,body FROM messages WHERE id=? AND project=? AND role='assistant'",
            (message_id, project)
        ).fetchone()
        if not row:
            raise ValueError("Feedback must be about one of STAR's answers in this project")
        chat_id, answer = row
        asked = self.connection.execute(
            "SELECT body FROM messages WHERE project=? AND chat_id=? AND role='user' AND id<? "
            'ORDER BY id DESC LIMIT 1', (project, chat_id, message_id)
        ).fetchone()
        with self.connection:
            if value:
                self.connection.execute(
                    'INSERT INTO message_feedback(message_id,project,chat_id,value,updated) VALUES (?,?,?,?,?) '
                    'ON CONFLICT(message_id) DO UPDATE SET value=excluded.value,updated=excluded.updated',
                    (message_id, project, chat_id, value, datetime.now(timezone.utc).isoformat())
                )
            else:
                self.connection.execute('DELETE FROM message_feedback WHERE message_id=?', (message_id,))
        return {'chat_id': chat_id, 'answer': answer, 'question': asked[0] if asked else ''}

    def turn_context(self, project: str, chat_id: str | None, prompt: str = '') -> dict:
        """The message being answered now and what happened to the turn before it.

        For after-turn learning (star/lessons.py): a correction is linked to the answer it
        follows, and a repeat of a failed message is a retry. Read-only. `message_id` is None
        when the newest stored user message is not the one in `prompt` (a direct call that
        saved nothing).
        """
        target = chat_id if chat_id is not None else 'legacy'
        rows = self.connection.execute(
            'SELECT id,role,body,status,reply_to FROM messages WHERE project=? AND chat_id=? '
            'ORDER BY id DESC LIMIT 16', (project, target)
        ).fetchall()
        found = {'message_id': None, 'previous': None}
        users = [index for index, row in enumerate(rows) if row[1] == 'user']
        if not users:
            return found
        current = users[0]
        earlier = rows[current + 1:]
        if rows[current][2] and prompt.startswith(rows[current][2]) and not any(
                row[1] == 'assistant' for row in rows[:current]):
            found['message_id'] = rows[current][0]
        else:
            # The newest stored turn is already finished: it is the turn before this prompt.
            earlier = rows
        before = next((index for index, row in enumerate(earlier) if row[1] == 'user'), None)
        if before is None:
            return found
        asked = earlier[before]
        previous = {'message_id': asked[0], 'text': asked[2], 'outcome': 'none',
                    'answer_id': None, 'answer': '', 'detail': ''}
        for row in reversed(earlier[:before]):       # rows after that question, oldest first
            if row[1] == 'assistant':
                previous.update(outcome='answered', answer_id=row[0], answer=row[2])
                break
            if row[1] == 'event' and row[3] in TERMINAL_STATUSES and row[4] == asked[0]:
                previous.update(outcome=row[3], detail=row[2])
        found['previous'] = previous
        return found

    def retry_state(self, project: str, chat_id: str, busy: bool = False) -> dict | None:
        """What happened to the newest user message in a chat, if it got no answer.

        Returns None when the newest turn was answered (or there is no turn, or a
        task is still running). Otherwise: status failed/cancelled from the stored
        terminal record, or 'interrupted' when nothing at all was recorded after the
        message (for example STAR was closed mid-reply). Derived on read, never written.
        """
        last = self.connection.execute(
            "SELECT id,body,created FROM messages WHERE project=? AND chat_id=? AND role='user' "
            'ORDER BY id DESC LIMIT 1', (project, chat_id)
        ).fetchone()
        if not last:
            return None
        user_id, prompt, created = last
        after = self.connection.execute(
            'SELECT role,body,created,status,reply_to FROM messages '
            'WHERE project=? AND chat_id=? AND id>? ORDER BY id', (project, chat_id, user_id)
        ).fetchall()
        if any(role == 'assistant' for role, *_ in after):
            return None
        for role, body, stamp, status, reply_to in reversed(after):
            if role == 'event' and status in TERMINAL_STATUSES and reply_to == user_id:
                return {'status': status, 'detail': body, 'prompt': prompt,
                        'message_id': user_id, 'created': stamp}
        if busy:
            return None
        return {'status': 'interrupted',
                'detail': 'No reply was recorded for this message. STAR may have been closed before it finished.',
                'prompt': prompt, 'message_id': user_id, 'created': created}

    def recover_turn(self, project: str, chat_id: str, message_id: int, prompt: str) -> int:
        """Reuse an unanswered question after restart without inserting another user row."""
        state = self.retry_state(project, chat_id)
        if (state is None or type(message_id) is not int
                or state['message_id'] != message_id or state['prompt'] != prompt):
            raise ValueError('The question is no longer available for Retry')
        return message_id

    def rename_chat(self, project: str, chat_id: str, title: str) -> str:
        """Give one conversation of this project a title the owner chose. Returns the stored title."""
        clean = ' '.join(str(title or '').split())
        if not clean:
            raise ValueError('A chat name cannot be empty')
        if len(clean) > 80:
            clean = clean[:79].rstrip() + '…'
        if any(ord(ch) < 32 for ch in clean):
            raise ValueError('A chat name cannot contain control characters')
        with self.connection:
            changed = self.connection.execute(
                'UPDATE chats SET title=? WHERE project=? AND id=?', (clean, project, chat_id)
            ).rowcount
        if not changed:
            raise ValueError('Conversation not found in this workspace')
        return clean

    def delete_chat(self, project: str, chat_id: str) -> str:
        """Remove one conversation of this project: its messages, thumbs and context checkpoint.

        Generated image files are not touched (they stay in the STAR data folder). When the
        deleted chat was the open one, the newest remaining chat opens (or a new blank one).
        Returns the chat that is open afterwards.
        """
        if not self.connection.execute(
            'SELECT 1 FROM chats WHERE project=? AND id=?', (project, chat_id)
        ).fetchone():
            raise ValueError('Conversation not found in this workspace')
        with self.connection:
            self.connection.execute(
                'DELETE FROM message_feedback WHERE project=? AND chat_id=?', (project, chat_id))
            self.connection.execute(
                'DELETE FROM messages WHERE project=? AND chat_id=?', (project, chat_id))
            self.connection.execute(
                'DELETE FROM chats WHERE project=? AND id=?', (project, chat_id))
            if self.connection.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='conversation_checkpoints'"
            ).fetchone():
                self.connection.execute(
                    'DELETE FROM conversation_checkpoints WHERE project=? AND chat=?', (project, chat_id))
            self.connection.execute(
                'DELETE FROM active_chats WHERE project=? AND chat_id=?', (project, chat_id))
        return self.active_chat(project)

    def projects(self):
        return [r[0] for r in self.connection.execute('SELECT DISTINCT project FROM messages ORDER BY project')]

    def close(self):
        self.connection.close()


def recent_context(recent: list[tuple[str, str, str]], current_prompt: str) -> str:
    """Exclude the current turn if the UI already saved it to the conversation DB.

    This prevents the local model receiving the exact same new user request
    as both system-context history and the actual user message.
    """
    turns = list(recent)
    if turns and turns[-1][0] == 'user' and turns[-1][1] == current_prompt:
        turns.pop()
    return '\n'.join(f'{role}: {body[:1500]}' for role, body, _ in turns)


def query_models(settings: Settings) -> list[str]:
    settings.validate()
    import httpx
    endpoint, key = connection_for(settings)
    with httpx.Client(timeout=8, trust_env=False) as client:
        response = client.get(endpoint.rstrip('/') + '/models', headers={'Authorization': f'Bearer {key}'})
        response.raise_for_status()
        data = response.json()
        return [str(item['id']) for item in data.get('data', []) if isinstance(item, dict) and item.get('id')]


def check_studio(settings: Settings | None = None, home: Path | None = None):
    from .studio_connections import discover
    return asyncio.run(discover(settings or Settings(), home=home if home is not None else app_data()))


from .redact import redact_text


def redact_for_logs(value):
    """Image bytes are retained in the artifact store, not duplicated in transcripts."""
    if isinstance(value, dict):
        if value.get('type') == 'image_url':
            return {'type': 'image_url', 'image_url': '[media stored separately in approved project artifacts]'}
        return {str(k): redact_for_logs(v) for k, v in value.items()}
    if isinstance(value, list):
        return [redact_for_logs(v) for v in value]
    if isinstance(value, str):
        return redact_text(value)
    return value


def needs_project_tools(prompt: str, prior_user_turns: list[str] | None = None, *,
                        blender: bool = False, github_repositories: bool = False) -> bool:
    """Load task tools on explicit request or scoped short edit follow-up.

    User context hints are not permissions; executable scopes remain enforced.
    """
    text = prompt.lower()
    if github_repositories and re.search(r'\b(?:githubs?|metallic(?:-[a-z]{2})?)\b', text):
        return True
    scopes = ('studio', 'roblox', 'workspace', 'my project', 'my game', 'my files',
              'project folder', 'current place')
    if blender:   # only with the Blender switch on (Settings.blender_enabled); off, these stay plain chat
        scopes += ('blender', '3d asset', '3d model', '3d mesh', 'gltf', 'glb')
    actions = ('inspect', 'modify', 'edit', 'read ', 'fix ', 'fix it', 'change ',
               'create ', 'build ', 'implement', 'open ', 'scan ', 'add ',
               'remove ', 'delete ', 'test ', 'make it', 'update ')
    explicit_mcp = bool(re.search(r'\b(mcp|connected tools?|graphify docs|live obsidian)\b', text))
    requests_action = any(x in text for x in actions)
    if explicit_mcp:
        return True
    # Public Roblox game research is an explicit request for source-backed
    # information, not a Studio edit; load read-only tools when relevant.
    if (re.search(r'\b(?:roblox|luau|devforum)\b', text)
            and re.search(r'\b(?:games?|experiences?|visits|statistics|stats|playing|'
                          r'popular|compare|research|search|news|apis?|forums?|trends?)\b', text)):
        return True
    if (re.search(r'\b(?:create|propose|build|make|design)\b', text)
            and re.search(r'\b(?:custom|research|my|new|own)\s+tools?\b', text)):
        return True
    if not requests_action:
        return False
    if any(x in text for x in scopes):
        return True
    return bool(len(text) <= 160 and prior_user_turns
                and any(any(x in turn.lower() for x in scopes)
                        for turn in prior_user_turns[-3:] if isinstance(turn,str)))

def needs_studio_connection(prompt: str, prior_user_turns: list[str] | None = None, *,
                            blender: bool = False) -> bool:
    """Only connect to Roblox Studio for an actual selected-place operation.

    A configured studio_id is NOT a request to connect for every agent call.
    Public Roblox game stats, forum research, generic coding discussions,
    image generation and tool catalogues must remain independent of Studio.
    """
    if not isinstance(prompt,str) or not prompt.strip():
        return False
    text=prompt.lower()
    # Exporting a Blender asset for Roblox does not itself authorize Studio edits. Only with the Blender
    # switch on: with it off, a prompt that mentions Blender attaches Studio exactly as before.
    if blender and 'blender' in text and not any(term in text for term in (
            'studio', 'current place', 'selected place', 'my game', 'the place',
            'game hierarchy', 'explorer tree', 'datamodel', 'my project', 'my roblox game')):
        return False
    actions=('inspect','edit','modify','build','create','fix','test ','run ','playtest',
             'open ','change ','update ','delete ','remove ','add ','insert ','scan ')
    requests_action=any(a in text for a in actions)
    if not requests_action:
        return False
    studio_scopes=('studio','current place','selected place','my game',
                   'my project','my roblox game','the place','game hierarchy',
                   'explorer tree','datamodel')
    if any(term in text for term in studio_scopes):
        return True
    if 'roblox' in text and not any(term in text for term in (
        'statistics','stats','visits','favorites','playing','concurrent',
        'universe id','place id','news','devforum','forum','public api',
        'game search','game research','popular games')):
        return True
    return bool(len(text)<=160 and prior_user_turns
                and re.search(r'\b(?:it|this|that|same|continue|again)\b',text)
                and any(any(term in turn.lower() for term in studio_scopes)
                        for turn in prior_user_turns[-3:] if isinstance(turn,str)))


def model_context_char_budget(settings: Settings, model: str | None = None) -> int:
    """Conservative CHAR proxy, not an exact tokenizer, for managed local router.

    The router's ctx-size is in tokens; complex Luau/MCP schemas can have many
    tokens per character. Keep a reserve for the active user prompt, tools and
    response. Other inference endpoints retain their existing settings.
    """
    kind = provider_kind(settings)
    if kind == 'local' and settings.router_models_dir:
        # Even 8-GB GPUs can page heavily when the KV cache is oversized.
        return min(settings.context_chars, max(3000, 2 * (settings.router_context - 512)))
    if kind == 'lan':
        # Each llama-server slot has its own context. Use the owner's value or
        # the size the server itself reported; unknown keeps the saved budget.
        # `model` is the model the request is routed to (the quick model has a
        # smaller context than the main one).
        tokens = server_context_tokens(settings, model) or server_context_tokens(settings)
        if tokens:
            return min(settings.context_chars, max(3000, 2 * (tokens - 1024)))
    return settings.context_chars


# Characters of earlier turns replayed on STAR Server (see `history_char_budget`).
SERVER_HISTORY_CHARS = 12000


def history_char_budget(settings: Settings) -> int:
    """Characters of earlier turns to replay.

    Cached history costs nothing per turn; what costs is the first message
    after a start and each time the window moves, when the server reads what is
    in the window again (see conversation_memory.select_window: the window
    moves by half of this budget at a time, and one replayed message is at most
    a quarter of it).

      cloud        12000: a hosted provider reads fast.
      STAR Server  12000: measured on the owner's server (docs/agents/model-routing.md).
                   The old 6000 cut every replayed message at 1500 characters, less than
                   one Fast-mode answer, and kept one to three exchanges. 12000 keeps a
                   whole Fast-mode answer (3000 characters) and three to seven exchanges.
                   A window move re-reads about 6000 characters; the post-answer warm-up
                   does that while the owner reads the answer.
      on this PC   6000: small GPU models with small contexts; unchanged.

    One budget for every model of a server: the window is then the same request
    start whichever model answers.
    """
    allowed = model_context_char_budget(settings)
    kind = provider_kind(settings)
    if kind == 'cloud':
        return min(12000, allowed // 2)
    if kind == 'lan':
        return min(SERVER_HISTORY_CHARS, max(1500, allowed // 2))
    return min(6000, max(1500, allowed // 4))


def stable_memory(settings: Settings, checkpoint: str) -> str:
    """The byte-stable model prefix, shared with warm-up; no changed context hidden.

    Optional finite owner-reviewed knowledge is reference DATA, never new
    instructions. The same function is used by run_task and warm-up, so their
    leading tokens match and llama.cpp can reuse the prompt. Invalid banks fail
    closed to ordinary retrieval and the prior checkpoint.
    """
    # The bank is opt-in and local-private only; importing does no I/O or setup.
    from .knowledge_bank import stable_checkpoint
    return stable_checkpoint(settings, app_data(), checkpoint)


def memory_scope_for(settings: Settings, chat_id: str | None) -> str:
    return settings.project if chat_id in (None, 'legacy') else settings.project + '::chat::' + chat_id


def chat_history(settings: Settings, home: Path, chat_id: str | None):
    """Earlier turns of a chat exactly as the next request will replay them.

    Returns (history messages, newest stored rows). The same function feeds a
    real turn and the cache warm-up, so both start with identical bytes. A
    trailing user row is the message being answered now (already saved by the
    UI) and is not history; an earlier message that never got a reply (failed,
    stopped or interrupted) is left out, with no placeholder answer (see
    conversation_memory.select_window).
    """
    window, rows = chat_history_snapshot(settings, home, chat_id)
    return window.messages, [(row['role'], row['body']) for row in rows
                             if row['role'] in {'user', 'assistant'}][-12:]


def chat_history_snapshot(settings: Settings, home: Path, chat_id: str | None, *, current_text=None):
    """Full scoped originals and a pure bounded window, shared with warm-up."""
    budget = history_char_budget(settings)
    dialogue = Conversations(home / 'conversations.sqlite3')
    reuse = os.environ.get('STAR_FAST_HISTORY_SNAPSHOT') == '1'
    try:
        rows = dialogue.raw_history_records(settings.project, chat_id)
        window = conversation_memory.select_window(rows, budget, current_text=current_text)
        # Opt-in only: avoid a second SQLite file open while retaining
        # the source digest, scope and complete-turn checkpoint checks.
        if reuse:
            checkpoint = conversation_memory.read_checkpoint_connection(
                dialogue.connection, settings.project, chat_id, records=rows)
    finally:
        dialogue.close()
    if not reuse:
        checkpoint = conversation_memory.read_checkpoint(home / 'conversations.sqlite3', settings.project,
                                                          chat_id, records=rows)
    return with_sent_times(conversation_memory.respect_checkpoint(window, checkpoint)), rows


def with_sent_times(window):
    """Each replayed user turn ends with the time line it was first sent with.

    A plain chat turn is sent as the owner's words plus a context block holding only the
    current time (star.agent.volatile_context). Replaying the earlier turns with the same
    block, rebuilt from each message's stored timestamp, keeps the request starting with the
    bytes the model server already read. Same number and order of messages as the window.
    """
    from .clock import sent_line
    from .context_layout import context_block, final_user_text
    messages = list(window.messages)
    for index, group in enumerate(window.exchanges):
        position = 2 * index
        if position >= len(messages) or messages[position].get('role') != 'user':
            break
        line = sent_line(group[0].get('created', '')) if group else ''
        if line:
            messages[position] = {'role': 'user', 'content': final_user_text(
                messages[position]['content'], context_block((), tail=[line]))}
    return replace(window, messages=messages)


def current_turn_line(records) -> str:
    """The time line for the message being answered: from its stored timestamp (so the next turn
    replays the same bytes), with a live server-clock note if the clocks differ; else the time now."""
    from .clock import now_line, sent_line
    if records and records[-1].get('role') == 'user':
        line = sent_line(records[-1].get('created', ''), offset=None)
        if line:
            return line
    return now_line()


def picture_limit(settings) -> int | None:
    """Longest side of a picture as the model reads it: capped on our own hardware, untouched for hosted models."""
    if provider_kind(settings) not in ('lan', 'local'):
        return None
    return int(getattr(settings, 'picture_max_side', 1280) or 0) or None


def run_task(settings: Settings, prompt: str, images: list[Path] | None = None,
             on_event: Callable[[dict], None] | None = None,
             stream_tokens: bool = False, mode: str = 'auto', research: bool = False,
             cancel_event=None, github_enabled: bool = False, chat_id: str | None = None,
             owner_text: str | None = None, documents: list[Path] | None = None,
             studio_configuration_home: Path | None = None, attachment_count: int = 0) -> str:
    """User-controlled fast/automatic/agent routing; all hosted calls are opt-in.

    `owner_text` is what the owner typed, when `prompt` also carries text STAR added (an
    audio transcript, a note about video frames). Only the owner's own words can become an
    automatically accepted lesson.
    """
    from .knowledge import KnowledgeStore
    from . import lessons as learning
    settings.validate()
    # With consent, keep unreviewed code off the screen until review completes.
    stream_tokens = stream_tokens and not settings.luau_run_before_answer
    if mode not in {'auto', 'fast', 'agent'}:
        raise ValueError('Invalid chat mode')
    if not settings.model.strip():
        raise ValueError('Select a model in Settings, then test the connection')
    images = images or []
    for image in images:
        image_part(Path(image))
    home = app_data()
    home.mkdir(parents=True, exist_ok=True)
    from .promoter import expire_due
    expire_due(home)
    metrics = AnalyticsStore(home / 'analytics.sqlite3')
    started = time.monotonic()
    first_visible_token = False
    token_timing = {'requested': None, 'first': None, 'last': None}
    metrics.record(settings.project, 'run_started')
    def audited_event(event):
        nonlocal first_visible_token
        now = time.monotonic()
        if event.get('event') == 'model_turn' and token_timing['requested'] is None:
            token_timing['requested'] = now
        if event.get('event') == 'assistant_delta' and str(event.get('text','')).strip():
            if token_timing['first'] is None:
                token_timing['first'] = now
            token_timing['last'] = now
        if event.get('event') == 'assistant_delta' and not first_visible_token and str(event.get('text','')).strip():
            first_visible_token = True
            # Approximate first *visible* text delta from request start; no prompt
            # or model output is persisted in this operational metric.
            metrics.record(settings.project, 'first_token', elapsed_ms=int((time.monotonic()-started)*1000))
        if event.get('event') == 'tool_finished':
            metrics.record(settings.project, 'tool_completed', detail=str(event.get('tool', ''))[:80])
        elif event.get('event') == 'tool_rejected':
            metrics.record(settings.project, 'tool_rejected')
        if on_event:
            on_event(event)
    memory = Memory(home / 'checkpoints.sqlite3')
    memory_scope = memory_scope_for(settings, chat_id)
    knowledge = KnowledgeStore(home / 'knowledge')
    workshop = None
    document_store = None
    document_tools = None
    lesson_store = learning.LessonStore(knowledge=knowledge, record=metrics.record)
    recalled = []
    learned = {'grounding': None, 'messages': None, 'done': False}

    def learn_from_turn():
        """After the turn (answered, failed or stopped): record what it taught. Regular
        expressions and a few SQLite rows, no model call; a problem here never changes
        the outcome of the turn."""
        if learned['done']:
            return
        learned['done'] = True
        try:
            said = prompt if owner_text is None else owner_text
            chats = Conversations(home / 'conversations.sqlite3')
            try:
                turn = chats.turn_context(settings.project, chat_id, said)
            finally:
                chats.close()
            summary = learning.capture_turn(
                lesson_store, project=settings.project, chat_id=chat_id, owner_text=said, turn=turn,
                grounding=learned['grounding'], messages=learned['messages'],
                auto_accept=settings.learning_auto_accept is True)
            if on_event and (summary['accepted'] or summary['candidates'] or summary.get('not_kept')):
                on_event({'event': 'lessons_captured', 'accepted': summary['accepted'],
                          'candidates': summary['candidates'],
                          **({'replaced': summary['replaced']} if summary['replaced'] else {}),
                          **({'not_kept': summary['not_kept']} if summary.get('not_kept') else {})})
        except Exception as exc:
            # Never fail the turn, but never stop learning silently either. Type name only:
            # the message can carry a file path or the owner's words.
            _log.warning('Lesson capture failed (%s); this turn taught nothing', type(exc).__name__)
            if on_event:
                try:
                    on_event({'event': 'lessons_capture_failed', 'error': type(exc).__name__})
                except Exception:
                    pass
    try:
        # Evidence is attached only to this project and conversation. Later turns
        # can retrieve it without reopening files elsewhere on the computer.
        document_block = ''
        if documents or (home / 'documents.sqlite3').is_file():
            from .documents import DocumentStore
            from .document_tools import DocumentTools
            document_store = DocumentStore(home, settings.project, chat_id)
            if documents:
                audited_event({'event': 'documents_started'})
                attached = document_store.ingest([Path(path) for path in documents], cancel_event)
                audited_event({'event': 'documents_ready', 'documents': len(attached)})
            document_block = document_store.context(prompt, budget_chars=min(6000, settings.context_chars // 3))
            if document_block:
                document_tools = DocumentTools(document_store)
        # Earlier turns are sent as real user/assistant messages, oldest first, and the
        # window over them only moves in whole blocks: the request starts with the same
        # bytes turn after turn, which is what lets the model server reuse its cache.
        history_window, conversation_records = chat_history_snapshot(
            settings, home, chat_id, current_text=owner_text if owner_text is not None else prompt)
        history = history_window.messages
        recent_all = [(row['role'], row['body']) for row in conversation_records
                      if row['role'] in {'user', 'assistant'}][-12:]
        # The UI saved the message being answered before calling this; it is not a prior turn.
        route_history = (
            recent_all[:-1] if recent_all and recent_all[-1][0] == 'user'
            and recent_all[-1][1] and prompt.startswith(recent_all[-1][1]) else recent_all
        )
        recent_users = [body for role,body in route_history if role=='user']
        project_tools = needs_project_tools(prompt, recent_users, blender=settings.blender_enabled is True,
                                            github_repositories=settings.mcp_github_repositories is True)
        referential = len(prompt) <= 160 and bool(re.search(
            r'\b(?:it|this|that|same|continue|again|those|these)\b', prompt, re.I))
        roblox_context = bool(project_tools and referential
                              and any(is_roblox_task(turn) for turn in recent_users[-3:]))
        # STAR Server may offer several models: blank role fields are filled from what the
        # server listed (never saved, never over a role the owner set; other providers untouched).
        kind = provider_kind(settings)
        wants_deep, prompt = deep_request(prompt)     # "/deep ..." asks for the slow best-quality model
        route = select_route(server_roles.effective(settings),prompt,mode=mode,image_count=len(images),
                             research=research,project_tools=project_tools,
                             roblox_context=roblox_context,
                             deep_model=server_roles.deep_model(settings) if wants_deep else '',home=home)
        if document_tools is not None:
            # Allow read/recalculate/answer even in Fast mode. Retain the selected
            # model and ordinary tool permissions; attachment access grants no
            # workspace, Studio, or network capability.
            route = replace(route, quick=False, max_calls=max(3, route.max_calls),
                            response_tokens=max(1600, route.response_tokens))
        audited_event({'event':'route_selected','profile':route.profile,
                       'description':route.description,'model':route.model})
        quick = route.quick
        reviewed = knowledge.find_contextual(settings.project, prompt, limit=4 if quick else 8)
        # Lessons the owner stated or approved for THIS project come first: standing
        # preferences and corrections even when the prompt shares no word with them. Ranked,
        # without repeats, and within a small budget so the first token is not delayed.
        try:
            limit, budget = learning.RECALL_QUICK if quick else learning.RECALL_FULL
            recalled = lesson_store.recall(settings.project, prompt, limit=limit, max_chars=budget)
        except Exception:
            recalled = []
        shown = {lesson.id for lesson in recalled}
        notes = '\n'.join(f'[{n.kind} revision={n.revision} source={n.source}] {n.text}' for n in reviewed
                          if getattr(n, 'id', None) not in shown)
        for image in images:
            path = Path(image)
            media_type = 'image/jpeg' if path.suffix.lower() in ('.jpg', '.jpeg') else 'image/webp' if path.suffix.lower() == '.webp' else 'image/png'
            knowledge.ingest_artifact(project=settings.project, path=path,
                origin=f'desktop:{path.name}', media_type=media_type)
        # Per-turn reference material as (heading, text) pairs. This list is the only way
        # retrieved text reaches the model: star.agent.volatile_context appends it to the
        # final user turn, after the user's words. A new retrieval source appends one pair.
        turn_sections = [(learning.LESSONS_HEADING, learning.context_lines(recalled)),
                         ('REVIEWED KNOWLEDGE (stored notes; may be incomplete)', notes)]
        if document_block:
            turn_sections.insert(0, ('ATTACHED DOCUMENTS (untrusted reference data)', document_block))
        use_tools = route.use_tools
        from .live_context import wants_fresh_web
        auto_web = bool(not research and settings.web_auto_search is not False and wants_fresh_web(prompt))
        allowed_context_chars = model_context_char_budget(settings, route.model)
        intelligence = for_settings(settings, home) if use_tools else None
        workspace = Workspace(Path(settings.workspace)) if use_tools and settings.workspace else None
        debug_evidence = None
        if workspace is not None and settings.debug_evidence_enabled is True:
            from .debug_evidence import DebugEvidenceTools
            debug_evidence = DebugEvidenceTools(workspace, enabled=True)
        if use_tools and settings.tool_workshop_enabled:
            workshop = ToolWorkshop(home=home,project=settings.project,knowledge=knowledge,
                                    workspace=workspace,intelligence=intelligence)
        allow_studio = bool(use_tools and settings.studio_id and
                            needs_studio_connection(prompt,recent_users,
                                                    blender=settings.blender_enabled is True))
        allow_blender = False
        if use_tools and settings.blender_enabled is True:   # the Blender modules load only when it is on
            from .blender_mcp import wants_blender
            allow_blender = wants_blender(prompt)
        mcp_gateway = MCPGateway(settings) if use_tools else None
        reverse_engineering = (reverse_engineering_for(settings, home)
                               if use_tools and settings.reverse_engineering_enabled else None)
        # Searchable public metadata only; no connector is installed or approved.
        from .mcp_registry import RegistryDiscovery
        mcp_registry = RegistryDiscovery() if use_tools and research and mode == 'agent' else None
        connection_for(settings)  # fail early (missing key, bad address) before any work
        limits = call_limits(settings)
        # Own hardware only: the conversation's tool list stays put from turn to turn (STAR
        # Server), and the shape of this request is kept for the post-answer warm-up.
        tools_kept = (turn_memory.for_conversation(memory_scope, sticky=kind == 'lan')
                      if kind != 'cloud' else None)
        answered_by = ''
        model_stats = {}
        instant_answer = None
        tools_ran = False
        inner_event = audited_event
        def audited_event(event):
            nonlocal answered_by, tools_ran
            if event.get('event') == 'model_answered':
                answered_by = str(event.get('model') or '')
                model_stats.update(first_token_ms=event.get('first_token_ms'),
                                   tokens_per_second=event.get('tokens_per_second'),
                                   estimated_tokens=event.get('estimated_tokens') is True)
            elif event.get('event') == 'tool_started':
                tools_ran = True
            inner_event(event)
        prepared_conversation = None
        async def run():
            nonlocal prepared_conversation, instant_answer, first_visible_token
            # Opt-in (star/presolve.py): a request that closely matches one STAR answered and checked
            # overnight gets that answer at once, marked; the same request sent again gets a fresh one.
            if (settings.presolve_enabled is True and not images and not documents and not attachment_count
                    and not research):
                from . import presolve
                solved = presolve.take(home, settings.project, chat_id, owner_text or prompt)
                if solved is not None:
                    text = presolve.marked(solved)
                    first_visible_token = True
                    audited_event({'event': 'presolved_answer', 'created': solved.created})
                    audited_event({'event': 'assistant_delta', 'text': text})
                    audited_event({'event': 'finished', 'model_calls': 0, 'tool_calls': 0})
                    return (text, [{'role': 'user', 'content': prompt}, {'role': 'assistant', 'content': text}], [])
            # Do not touch the PC's model unless this standalone text turn is eligible.
            # The loopback /models probe reads only residency; a router's unloaded model
            # is never selected and no llama.cpp process is started or downloaded.
            eligible = dict(prompt=prompt, mode=mode, provider=kind,
                            enabled=settings.instant_route_enabled is True,
                            installed=bool(settings.gguf_model or settings.router_models_dir),
                            attachments=len(images) + len(documents or ()) + max(0, attachment_count),
                            tools=use_tools or document_tools is not None or bool(github_enabled),
                            research=research or auto_web, documentation=route.grounding.retrieve != 'none',
                            deep=wants_deep, followup=referential or roblox_context
                            or bool(owner_text is not None and owner_text != prompt))
            if decide_instant_route(**eligible, loaded_model='resident').use_local:
                try:
                    local_model = await loaded_local_model(settings.endpoint)
                except Exception:
                    local_model = ''
                if decide_instant_route(**eligible, loaded_model=local_model).use_local:
                    try:
                        instant_answer = await answer_on_pc(settings.endpoint, local_model, prompt)
                    except Exception:
                        # Local text was buffered, not streamed to the chat. The original
                        # server request can now run unchanged, exactly once.
                        audited_event({'event': 'instant_fallback', 'model': route.model})
                    else:
                        first_visible_token = True
                        metrics.record(settings.project, 'first_token',
                                       elapsed_ms=instant_answer.first_token_ms)
                        audited_event({'event': 'instant_selected', 'model': instant_answer.model})
                        audited_event({'event': 'model_answered', 'model': instant_answer.model})
                        audited_event({'event': 'assistant_delta', 'text': instant_answer.text})
                        audited_event({'event': 'finished', 'model_calls': 1, 'tool_calls': 0})
                        return (instant_answer.text,
                                [{'role': 'user', 'content': prompt},
                                 {'role': 'assistant', 'content': instant_answer.text}], [])
            from .web_search import search_web, source_context
            from . import live_context
            live_context.refresh_server_clock_soon(settings)   # the STAR Server's clock, for the time line
            if research:
                audited_event({'event': 'search_started'})
                found = await search_web(prompt[:600], limit=5)
                turn_sections.append(('WEB SEARCH', source_context(found)))
                audited_event({'event': 'search_finished'})
            elif auto_web:
                # A question about what is happening now: search without waiting for the switch.
                # A failure is one line in the context (the model says so), never a failed turn.
                audited_event({'event': 'search_started'})
                web_text, _sources = await live_context.auto_search(prompt, settings=settings)
                if web_text:
                    turn_sections.append(('WEB SEARCH', web_text))
                audited_event({'event': 'search_finished'})
            # One client per task, with the selected provider's own time limits.
            async with open_client(settings) as client:
                if kind == 'lan' and settings.use_my_gpu is True:
                    # STAR's code model on this PC's graphics card when it is ready; the server otherwise and
                    # whenever the PC fails (star/gpu_helper.py). Everything else in this turn is unchanged.
                    if not gpu_helper.HELPER.enabled:
                        gpu_helper.HELPER.configure(settings, home)
                    client = gpu_helper.GpuRoutingClient(client, settings)
                # Summaries, sub-agents, specialists and code repair are not the conversation:
                # on STAR Server they carry no id_slot, the server places them (providers.llama_request_fields).
                helper = background_client(client, settings, conversation=memory_scope)
                specialists = (ResearchTeam(
                    client=helper,model=route.subagent_model,project=settings.project,
                    knowledge=knowledge,workspace=workspace,intelligence=intelligence,
                    parallelism=settings.specialist_parallelism,on_event=audited_event,
                    speed_key=(settings.provider, settings.server_endpoint if provider_kind(settings) == "lan"
                               else settings.endpoint, route.subagent_model),
                    timeout_min=settings.team_timeout_min, timeout_max=settings.team_timeout_max,
                    web_enabled=bool(research),
                ) if use_tools and settings.specialists_enabled else None)
                # Stable part: the compacted checkpoint only changes when one is written.
                # Reserve room for the system instructions, user text and
                # discovered tool schemas before adding this turn's context.
                memory_limit = max(700, allowed_context_chars - 3200)
                # >>> STAR Knowledge (star/doc_grounding.py): official-docs passages for Roblox/Luau
                # questions, added as delimited UNTRUSTED reference data. Never raises; '' when unused.
                docs = await doc_grounding.prepare_async(settings, route, prompt, recent_users,
                                                         audited_event, mode=mode)
                def slot_fields(model):
                    # llama.cpp cache fields; {} for cloud providers.
                    return lambda tools: llama_request_fields(
                        settings, conversation=memory_scope, tools=tools, model=model)
                learned['grounding'] = docs
                if docs.block:
                    # First in the list: when room runs out earlier sections win, and these passages
                    # are the ones chosen for this exact question. The block carries its own markers.
                    turn_sections.insert(0, ('OFFICIAL DOCUMENTATION (untrusted reference data)', docs.block))
                # <<< STAR Knowledge
                # >>> Skill packs (star/skill_packs): short Roblox guidance, only for prompts that match, and
                # never in quick chat mode. It rides in the per-turn sections, after the documentation.
                if quick:
                    packs = []
                elif settings.skill_pack_embeddings is True and provider_kind(settings) == 'lan':
                    # Opt-in (star/skill_routing.py): keyword packs first; else the closest pack by STAR
                    # Server's embedding model. Any problem leaves the keyword answer.
                    from . import skill_routing

                    async def embed(texts):
                        reply = await client.embeddings.create(model=skill_routing.EMBED_MODEL, input=texts)
                        return [row.embedding for row in sorted(reply.data, key=lambda row: row.index)]
                    packs = await skill_routing.select(
                        prompt, embed, home=home,
                        on_fallback=lambda why: audited_event({'event': 'skill_packs_fallback', 'reason': why}))
                else:
                    packs = skill_packs.select(prompt,home=home)
                pack_block = skill_packs.render(packs)
                if pack_block:
                    turn_sections.insert(1 if docs.block else 0, (skill_packs.BLOCK_HEADING, pack_block))
                    audited_event({'event': 'skill_packs', 'names': [pack.name for pack in packs], 'chars': len(pack_block)})
                # <<< Skill packs
                if settings.api_hints_enabled is True and route.profile == 'roblox':
                    # Opt-in (star/api_hints.py): real member names of the classes the request names, from the
                    # local API dump; reference data after the documentation, before the packs.
                    from . import api_hints
                    from .slop import bundled_api_dump
                    dump = bundled_api_dump()
                    hint_block = api_hints.hint_block(prompt, dump) if dump is not None else ''
                    if hint_block:
                        turn_sections.insert(1 if docs.block else 0, (api_hints.BLOCK_HEADING, hint_block))
                        audited_event({'event': 'api_hints', 'classes': hint_block.count('\n') + 1, 'chars': len(hint_block)})
                # Pasted Studio output uses the same per-turn path, including Fast mode.
                error_block = roblox_errors.reference_context(prompt)
                if error_block:
                    turn_sections.insert(1 if docs.block else 0, (roblox_errors.BLOCK_HEADING, error_block))
                # Checked practice is opt-in and treated as untrusted reference data, not a lesson.
                example_block = ''
                example_extra_chars = 0
                if settings.worked_examples_enabled is True:
                    from . import worked_examples
                    base_chars = (min(3000 if quick else 10000, memory_limit)
                                  + len(docs.block) + len(document_block) + len(pack_block)
                                  + len(error_block))
                    heading_chars = len(worked_examples.HEADING) + 2
                    room = min(worked_examples.MAX_PROMPT_CHARS - heading_chars,
                               max(0, allowed_context_chars - 3200 - base_chars - heading_chars))
                    if room >= 200:
                        try:
                            example_block, selected_examples = worked_examples.select(
                                home, settings.project, prompt, max_chars=room)
                        except (OSError, sqlite3.DatabaseError, ValueError):
                            example_block, selected_examples = '', []
                        if example_block:
                            example_extra_chars = len(example_block) + heading_chars
                            turn_sections.append((worked_examples.HEADING, example_block))
                            audited_event({'event': 'worked_example_used',
                                           'count': len(selected_examples), 'chars': len(example_block)})
                # Opt-in (star/gold_bank.py): the closest verified gold examples, Roblox route only, never in quick mode.
                if settings.gold_examples_enabled is True and route.profile == 'roblox' and not quick:
                    from . import gold_bank
                    async def gold_embed(texts):
                        reply = await client.embeddings.create(model=gold_bank.EMBED_MODEL, input=texts)
                        return [row.embedding for row in sorted(reply.data, key=lambda row: row.index)]
                    gold_room = min(gold_bank.MAX_BLOCK_CHARS, max(0, allowed_context_chars - 3200 - example_extra_chars
                                                               - len(gold_bank.HEADING) - 2 - min(10000, memory_limit)
                                                               - len(docs.block) - len(document_block)
                                                               - len(pack_block) - len(error_block)))
                    gold_block, gold_used = await gold_bank.select(
                        prompt, gold_embed if provider_kind(settings) == 'lan' else None, max_chars=gold_room,
                        on_fallback=lambda why: audited_event({'event': 'gold_examples_fallback', 'reason': why}))
                    if gold_block:
                        example_extra_chars += len(gold_block) + len(gold_bank.HEADING) + 2
                        turn_sections.append((gold_bank.HEADING, gold_block))
                        audited_event({'event': 'gold_examples_used', 'ids': [item.id for item in gold_used],
                                       'chars': len(gold_block)})
                # Opt-in project rules (star/project_rules.py): the workspace's AGENTS.md, as reference data.
                rules_chars = 0
                if settings.project_rules_enabled is True and settings.workspace and not quick:
                    rules = project_rules.load(settings.workspace)
                    if rules:
                        turn_sections.append((project_rules.HEADING, rules[1]))
                        rules_chars = len(rules[1]) + len(project_rules.HEADING) + 2
                        audited_event({'event': 'project_rules', 'file': rules[0], 'chars': len(rules[1])})
                kwargs = dict(client=client, model=route.model, prompt=prompt, image_paths=images,
                              now=current_turn_line(conversation_records),
                              project_memory=stable_memory(settings, memory.get(memory_scope)),
                              history=history,
                              preserve_history=True,
                              # Only the lessons section may look like lessons (guard_sections).
                              turn_sections=learning.guard_sections(turn_sections), mode=mode,
                              # The documentation block has its own budget (brain_router.GROUNDING_BUDGET);
                              # it is added on top so stored notes keep the room they had before.
                              turn_context_chars=(min(3000 if quick else 10000, memory_limit) + len(docs.block)
                                                  + len(document_block) + len(pack_block) + len(error_block)
                                                  + example_extra_chars + rules_chars),
                              # Standing guidance for every tool-using turn (the short
                              # plain-chat rules carry their own Roblox line).
                              guidance=ROBLOX_QUALITY_NOTES,
                              request_extras=slot_fields(route.model),
                              tool_memory=tools_kept, helper_client=helper,
                              image_max_side=picture_limit(settings),
                              max_calls=route.max_calls,
                              context_chars=allowed_context_chars,
                              checkpoint=lambda s: memory.put(memory_scope, s), on_event=audited_event,
                              workspace=workspace, workspace_edit=settings.workspace_edit and use_tools,
                              stream_tokens=stream_tokens, response_tokens=route.response_tokens,
                              subagent_model=route.subagent_model,
                              web_search_enabled=bool((research or auto_web) and mode == 'agent'),
                              web_settings=settings,
                              subagents_enabled=(mode == 'agent'),
                              subagent_parallelism=limits.parallel,
                              github_enabled=bool(mode == 'agent' and github_enabled),
                              intelligence=intelligence, mcp_gateway=mcp_gateway,
                              mcp_registry=mcp_registry,
                              tool_workshop=workshop, specialists=specialists)
                if document_tools is not None:
                    kwargs['document_tools'] = document_tools
                if reverse_engineering is not None:
                    kwargs['reverse_engineering'] = reverse_engineering
                if debug_evidence is not None:
                    kwargs['debug_evidence'] = debug_evidence
                # Generate several, test, keep what works (star/best_of_n.py): only for a code request on STAR Server
                # (not Agent mode, no Studio, Blender, pictures or documents), with the owner's setting on. A candidate
                # that asks for a tool is dropped, and a main answer that used tools is kept as it is.
                # None = the turn runs exactly as before.
                several = await best_of_n.for_turn(
                    settings, route, prompt, client=helper, knowledge=docs.client,
                    eligible=(kind == 'lan' and mode != 'agent' and not images and document_tools is None
                              and not document_block and not allow_studio and not allow_blender),
                    quick_model=str(getattr(server_roles.effective(settings), 'fast_model', '') or ''),
                    on_event=audited_event)
                if several is not None:
                    kwargs['on_first_request'] = several.on_first_request
                # Opt-in diff-only edits (star/edit_format.py): pasted code plus a change request is answered with
                # SEARCH/REPLACE blocks that STAR applies and checks here. Plain chat turns only, not with best-of-N.
                edit = (edit_format.find_edit(prompt)
                        if settings.edit_diff is True and several is None and mode != 'agent' and not images
                        and document_tools is None and not document_block and not allow_studio
                        and not allow_blender else None)
                if edit is not None:
                    kwargs['prompt'] = edit.prompt
                    audited_event({'event': 'edit_diff_started', 'lines': edit.source.count('\n')})
                audited_event({'event': 'model_started'})
                async def answer_with(model):
                    nonlocal prepared_conversation
                    window, candidate = history_window, None
                    for attempt in range(5):
                        candidate = await conversation_memory.prepare(
                            helper, model, home / 'conversations.sqlite3', settings.project, chat_id,
                            conversation_records, window,
                            summary_chars=min(6000, max(700, allowed_context_chars // 4)),
                            cancel_event=cancel_event, on_event=audited_event, candidate=candidate)
                        # Issue 118: is the chat's slot busy with another client right now? Then this
                        # turn takes an idle slot (providers.look_for_busy_slots; never raises, <0.5 s).
                        await look_for_busy_slots(settings, model, conversation=memory_scope)
                        kwargs.update(model=model, request_extras=slot_fields(model), history=window.messages,
                            project_memory=conversation_memory.compose_memory(
                                stable_memory(settings, memory.get(memory_scope)), candidate.checkpoint))
                        try:
                            async with AsyncExitStack() as connections:
                                tool_kwargs = dict(kwargs)
                                if allow_blender:
                                    if settings.blender_brain2 is True:
                                        from .blender_brain2 import connect_brain2_blender as connect_blender
                                    else:
                                        from .blender_mcp import connect_blender
                                    tool_kwargs["blender"] = await connections.enter_async_context(
                                        connect_blender(settings, home))
                                if allow_studio:
                                    from .local_mcp import connect_studio
                                # One guarded connection per attempt: a retry below happens only when
                                # nothing was sent to the model or to Studio, so nothing is replayed.
                                    guarded = await connections.enter_async_context(
                                        connect_studio(settings, home,
                                            studio_configuration_home=studio_configuration_home))
                                    # The tool list is the connector's own, read now. What STAR may do in
                                    # the open place is decided in code from what that place is.
                                    discovered = guarded.discovered
                                    if settings.studio_tool_examples:
                                        # Description text only; what may run is still decided by policy.
                                        discovered = studio_tool_examples.with_examples(discovered)
                                    sections = list(kwargs.get('turn_sections') or ())
                                    # The verdict's text can quote the place; like every other section
                                    # it may not look like lessons (guard_sections).
                                    sections.extend(learning.guard_sections(
                                        [('ROBLOX STUDIO PLACE', guarded.verdict.reason)]))
                                    outcome = await execute(**{**tool_kwargs, 'turn_sections': sections}, studio=guarded,
                                        discovered=discovered, studio_id=settings.studio_id,
                                        may_edit=guarded.verdict.editable,
                                        allow_luau=guarded.verdict.editable and settings.studio_luau)
                                    result = studio_loop.with_report(outcome, guarded)
                                else:
                                    result = await execute(**tool_kwargs)
                        except HistoryWindowPressure as pressure:
                            if pressure.dispatched or pressure.tool_actions_started:
                                raise conversation_memory.ConversationRetentionError(
                                    'Conversation context needs another recap after model/tool work; task stopped '
                                    'without replaying actions. Original dialogue and prefix checkpoint are unchanged.')
                            if pressure.dropped != window.messages[:len(pressure.dropped)]:
                                raise conversation_memory.ConversationRetentionError(
                                    'Request pressure does not match complete original exchanges; task stopped.')
                            if attempt == 4:
                                raise conversation_memory.ConversationRetentionError(
                                    'Conversation preparation exceeded four budget retries; task stopped '
                                    'with originals and the previous prefix checkpoint unchanged.')
                            window = conversation_memory.omit_messages(window, len(pressure.dropped))
                            continue
                        prepared_conversation = candidate
                        return result
                used = route
                # Interactive chat must not queue behind background answers (evals, night school) that hold
                # every slot of the main model: general chat (no tools, images, documents or code) is answered
                # by the quick model instead (brain_router.busy_downgrade_allowed; one probe, <0.5 s).
                quick_name = str(getattr(server_roles.effective(settings), 'fast_model', '') or '')
                if (kind == 'lan' and not use_tools and not images and document_tools is None
                        and not document_block and quick_name and quick_name != route.model
                        and busy_downgrade_allowed(prompt, route.profile)
                        and await model_slots_full(settings, route.model)):
                    used = replace(route, model=quick_name)
                    audited_event({'event': 'route_busy_quick', 'model': quick_name})
                try:
                    try:
                        result = await answer_with(used.model)
                    except Exception as exc:
                        # A role's model that is missing or will not load: answer with the single
                        # configured model instead, once, and only if nothing was shown or run yet.
                        if (kind != 'lan' or used.model == settings.model or first_visible_token
                                or tools_ran or not model_unavailable(exc)):
                            raise
                        server_roles.mark_failed(settings, used.model)
                        used = replace(route, model=settings.model, subagent_model=(
                            settings.model if route.subagent_model == route.model else route.subagent_model))
                        if specialists is not None:
                            specialists.model = used.subagent_model
                        kwargs.update(subagent_model=used.subagent_model)
                        audited_event({'event': 'route_fallback', 'model': settings.model})
                        result = await answer_with(settings.model)
                except BaseException:
                    # The main answer failed or the turn was cancelled: stop the extra candidates too, so they
                    # do not keep generating on the server slots after the turn is over.
                    if several is not None:
                        await several.run.cancel()
                    raise
                if edit is not None and not tools_ran and result is not None:
                    done = await asyncio.to_thread(edit_format.finish, edit, result[0],
                                                   check=docs.client.luau_check if docs.client is not None else None)
                    audited_event({'event': 'edit_diff_finished', 'ok': done.ok, 'reason': done.reason[:160],
                                   'edits': done.edits})
                    if done.ok:
                        result = (done.answer, *result[1:])
                    else:
                        # The edit did not apply or checked worse: the normal full answer, asked once.
                        kwargs['prompt'] = prompt
                        if stream_tokens:
                            audited_event({'event': 'assistant_delta', 'text':
                                           '\n\n*(The edit did not apply cleanly; STAR is writing the full code.)*\n\n'})
                        result = await answer_with(used.model)
                if several is not None:
                    # The best of the candidates (the main answer above is candidate 1) replaces the answer.
                    result = await several.apply(result, used.model, started=started, budget=route.task_timeout,
                                                 tools_ran=tools_ran)
                # STAR Knowledge: static Luau check of the answer's code, then the sources list.
                result = await doc_grounding.finalize(docs, used, result, model_client=helper, prompt=prompt,
                                                      started=started, on_event=audited_event, settings=settings,
                                                      retry_ladder=settings.luau_retry_ladder is True,
                                                      thinking=provider_kind(settings) in ('local', 'lan'))
                return several.footer(result) if several is not None else result
        # Bound an entire task, not just each of up to 12 individual model calls.
        task_timeout = route.task_timeout
        async def controlled_run():
            """Cooperative user cancellation interrupts active async API and Studio calls."""
            job = asyncio.create_task(run())
            deadline = time.monotonic() + task_timeout
            try:
                while True:
                    if cancel_event is not None and cancel_event.is_set():
                        raise RuntimeError('STAR task cancelled by user')
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        raise TimeoutError('Task time limit exceeded')
                    done, _ = await asyncio.wait({job}, timeout=min(0.15, remaining))
                    if done:
                        return await job
            finally:
                if not job.done():
                    job.cancel()
                    await asyncio.gather(job, return_exceptions=True)
        try:
            answer, msgs, archive = asyncio.run(controlled_run())
        except TimeoutError as exc:
            advice = ('Try Fast mode or a smaller prompt, or raise the STAR Server timeout in Settings.'
                      if provider_kind(settings) == 'lan' else
                      'Try Fast mode, a smaller prompt, or a hosted provider.')
            raise TimeoutError(f'STAR exceeded its {task_timeout}s task budget. {advice}') from exc
        first = token_timing['first']
        requested = token_timing['requested']
        measured_first = (instant_answer.first_token_ms if instant_answer is not None else
                          model_stats.get('first_token_ms') if model_stats.get('first_token_ms') is not None else
                          max(0, int((first - requested) * 1000)) if first is not None and requested is not None else None)
        throughput = (instant_answer.tokens_per_second if instant_answer is not None else
                      model_stats.get('tokens_per_second'))
        brain = ('pc' if instant_answer is not None or kind == 'local'
                 else 'server' if kind == 'lan' else 'cloud')
        stats = {'brain': brain, 'model': answered_by or route.model,
                 'first_token_ms': measured_first, 'tokens_per_second': throughput,
                 'estimated_tokens': (instant_answer.estimated_tokens if instant_answer is not None
                                      else model_stats.get('estimated_tokens', True))}
        audited_event({'event': 'answer_stats', **stats})
        stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%f')
        runs = home / 'runs' / stamp
        runs.mkdir(parents=True, exist_ok=True)
        (runs / 'transcript.json').write_text(json.dumps(redact_for_logs({
            'messages': msgs, 'archive': archive,
            # Which model was asked and which one the server said answered.
            'route': {'profile': route.profile, 'requested_model': route.model,
                      'answered_model': answered_by or route.model},
            'answer_stats': stats}), ensure_ascii=False, default=str), encoding='utf-8')
        (runs / 'answer.md').write_text(redact_text(answer), encoding='utf-8')
        memory.event(memory_scope, {'run_id': stamp, 'answer': redact_text(answer[:10000])})
        # Failed/cancelled answers, budget refusals and required archive/log
        # failures never advance retention. Validate source/CAS after persistence.
        if prepared_conversation is not None:
            conversation_memory.commit(home / 'conversations.sqlite3', prepared_conversation,
                                       cancel_event=cancel_event)
        audited_event({'event': 'saved', 'run_id': stamp})
        metrics.record(settings.project, 'run_succeeded',elapsed_ms=int((time.monotonic()-started)*1000))
        # The answer exists: count the lessons that were in its context, then learn from the turn.
        try:
            lesson_store.mark_used(settings.project, recalled)
        except Exception:
            pass
        learned['messages'] = msgs
        learn_from_turn()
        return answer
    except Exception as exc:
        metrics.record(settings.project, 'run_failed', elapsed_ms=int((time.monotonic()-started)*1000),
                       detail=type(exc).__name__)
        # A stated preference is still the owner's even when this turn failed or was stopped.
        learn_from_turn()
        raise
    finally:
        if document_store is not None:
            document_store.close()
        if workshop is not None:
            workshop.close()
        knowledge.close()
        memory.close()
        metrics.close()
