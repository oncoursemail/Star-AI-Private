"""Roblox skill packs: short guidance distilled from the official documentation.

A pack is an ordinary Agent Skill (a folder with SKILL.md and references/, the format read by
`star.agent_skills`), shipped inside the application. Unlike a skill the model has to ask for, a pack
is chosen here, in code, from the user's words: it is added to the turn only when the prompt is a
Roblox question AND names the pack's topic, so unrelated prompts are byte-for-byte unchanged.

Where it goes: `desktop_core.run_task` appends the rendered block to `turn_sections`, which
`star.agent.volatile_context` puts after the user's own words. It never enters the system message,
which stays byte-stable for the model server's prompt cache.

Cost: the text is read by the model on every turn it is added. Only the best-matching pack is added
(MAX_PACKS_PER_TURN = 1). Bodies must fit MAX_BODY_CHARS; richer, unmeasured design packs remain opt-in.
Do not extend latency measurements from the shorter measured packs to these longer packs.

Whether a pack is on is decided by evidence, not by hope: a pack is enabled by default (DEFAULT_ENABLED)
only after the evaluation gate (docs/evals.md) showed that it does not lower the golden-task score.
`STAR_SKILL_PACKS` overrides it: `off`, `all`, or a comma list of pack names.
"""
from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
import os
from pathlib import Path
import re

from ..agent_skills import _frontmatter
from .engines import ENGINE_CONTEXTS, ENGINE_TOPICS

PACKS_DIR = Path(__file__).resolve().parent
ENV_VAR = "STAR_SKILL_PACKS"
MAX_BODY_CHARS = 6400
MAX_PACKS_PER_TURN = 1
MAX_BLOCK_CHARS = 6500
BLOCK_HEADING = "SKILL PACKS (guidance from STAR, distilled from the official documentation; not part of the request)"

# Enabled by default: only packs the gate allowed with at least one measured improvement (docs/evals.md,
# "Measured results"). The others stay shipped and can be switched on with STAR_SKILL_PACKS, but were either
# blocked (a confirmed regression), inconclusive (the no-pack arm flips on the same task) or showed no gain.
DEFAULT_ENABLED: tuple[str, ...] = (
    "roblox-secure-remotes",
    "roblox-animation-craft",
    "roblox-vfx",
    "roblox-building-layout",
    "eng-verify-before-done",
)

# The prompt must read as a Roblox question at all ...
_ROBLOX_CONTEXT = re.compile(
    r"\b(?:roblox|luau|studio|workspace|LocalScript|ModuleScript|ServerScriptService|ServerStorage|ReplicatedStorage|"
    r"StarterGui|StarterPlayer\w*|StarterCharacterScripts|PlayerGui|ScreenGui|Instance\.new|game:GetService|"
    r"Humanoid|RemoteEvent|RemoteFunction|DataStore\w*|OnServerEvent|BindToClose|R6|R15)\b", re.IGNORECASE)

_GODOT_CONTEXT = re.compile(r"\b(?:godot(?:\s*4)?|gdscript|PackedScene|CharacterBody2D|Node2D|Control\s+node)\b", re.IGNORECASE)
GODOT_PACKS = frozenset(("godot-scenes-and-nodes", "godot-gdscript-typing-and-signals",
                         "godot-physics-and-input", "godot-ui-and-themes"))

# ... and name the pack's topic.
TRIGGERS: dict[str, re.Pattern] = {
    "godot-scenes-and-nodes": re.compile(r"\b(?:PackedScene|instantiate|scene tree|node tree|add_child|owner|@onready|scenes|nodes)\b", re.IGNORECASE),
    "godot-gdscript-typing-and-signals": re.compile(r"\b(?:gdscript|static typing|typed|signal|signals|@export|Callable|emit|connect)\b", re.IGNORECASE),
    "godot-physics-and-input": re.compile(r"\b(?:CharacterBody2D|move_and_slide|physics|InputMap|input action|is_on_floor|velocity|_physics_process)\b", re.IGNORECASE),
    "godot-ui-and-themes": re.compile(r"\b(?:Control|Theme|Button|Container|anchors|size_flags|UI|themes|layout)\b", re.IGNORECASE),
    "roblox-ui-layout": re.compile(
        r"\b(?:ScreenGui|SurfaceGui|BillboardGui|UDim2|UIListLayout|UIGridLayout|UIScale|UIPadding|UICorner|UIStroke|"
        r"UIAspectRatioConstraint|UISizeConstraint|UITextSizeConstraint|ScrollingFrame|TextButton|TextLabel|TextBox|"
        r"ImageLabel|ImageButton|PlayerGui|StarterGui|HUD|GUI|UI|menu|nameplate|safe area|notch|TweenService|"
        r"AutomaticCanvasSize|ViewportSize)\b", re.IGNORECASE),
    "roblox-secure-remotes": re.compile(
        r"\b(?:RemoteEvent|RemoteFunction|UnreliableRemoteEvent|OnServerEvent|OnClientEvent|FireServer|FireClient|"
        r"FireAllClients|InvokeServer|InvokeClient|exploit\w*|anti-?cheat|cheat\w*|ProcessReceipt|developer product|"
        r"validate|server-authoritative|never trust)\b", re.IGNORECASE),
    "roblox-datastore-safety": re.compile(
        r"\b(?:DataStore\w*|data ?stores?|UpdateAsync|GetAsync|SetAsync|BindToClose|ProcessReceipt|developer product|"
        r"save (?:the )?(?:player|data)|player data|autosave|session lock\w*)\b", re.IGNORECASE),
    "roblox-animation-tools": re.compile(
        r"\b(?:Animator|AnimationTrack|LoadAnimation|animations?|animate|R6|R15|RigType|Motor6D|Tool|Grip\w*|Equipped|"
        r"Unequipped|Handle|attachments?|rigs?|AnimationId|KeyframeMarker|marker)\b", re.IGNORECASE),
    "roblox-performance-streaming": re.compile(
        r"\b(?:performance|optimi[sz]\w*|lag\w*|frame ?rate|FPS|MicroProfiler|StreamingEnabled|streaming|RenderStepped|"
        r"Heartbeat|polling|every frame|object pool\w*|pooling|Debris|garbage|ModelStreamingMode)\b", re.IGNORECASE),
    # Creation packs (animation craft, effects, building, UI looks).
    "roblox-animation-craft": re.compile(
        r"\b(?:anticipation|follow-?through|easing|eased?|wind-?up|frame data|startup|recovery|cancel ?window|combo|move-?set|"
        r"IKControl|inverse kinematics|damped|damping|spring|secondary motion|procedural|AdjustWeight|AdjustSpeed|cross-?fade|"
        r"blend\w*|GetMarkerReachedSignal|animation events?|markers?|hit window|AnimationPriority|keyframes?|overshoot\w*|"
        r"interpolat\w*)\b", re.IGNORECASE),
    "roblox-vfx": re.compile(
        r"\b(?:ParticleEmitter|particles?|Beam|Trail|Attachment[01]|Emit|LightEmission|NumberSequence|ColorSequence|VFX|"
        r"visual effects?|particle effects?|emitters?|sparks?|burst|shockwave|embers?|smoke|muzzle flash|explosion|laser)\b",
        re.IGNORECASE),
    "roblox-building-layout": re.compile(
        r"\b(?:grid|snap\w*|studs?|modular|level design|level layout|doorway|Atmosphere|ClockTime|Lighting|OutdoorAmbient|"
        r"BloomEffect|ColorCorrectionEffect|SunRaysEffect|PivotTo|Terrain|walls?|floors?|rooms?|ceilings?|corridors?|obby|"
        r"lobby)\b", re.IGNORECASE),
    "roblox-ui-styles": re.compile(
        r"\b(?:theme[sd]?|style[sd]?|styling|palette|glass|neon|gradient|UIGradient|UIStroke|UICorner|hover|dark mode|contrast|"
        r"readable|design system|flat|cartoon\w*|chunky|skeuomorphic|look and feel)\b", re.IGNORECASE),
    "roblox-environment-art": re.compile(
        r"\b(?:environment art|environment design|foliage|swaying trees?|tree sway|wind sway|"
        r"winter shrine|torii|snowy forest|volcanic crypt|catacombs?|dungeon|"
        r"SurfaceAppearance|PBR|texture atlas|reference screenshot|art direction|"
        r"volumetric|skinned trees?|environmental storytelling|lighting preset)\b",
        re.IGNORECASE),
    # Engineering-method packs adapted from MIT-licensed collections (see THIRD_PARTY_NOTICES.md).
    "game-obby": re.compile(r"\b(?:obby|checkpoint|checkpoints|kill brick|stage progression|obstacle course)\b", re.IGNORECASE),
    "game-tycoon": re.compile(r"\b(?:tycoon|dropper|droppers|collector|collectors|purchase button|factory plot)\b", re.IGNORECASE),
    "game-simulator": re.compile(r"\b(?:simulator|clicker|rebirth|rebirths|leaderstats|upgrade loop)\b", re.IGNORECASE),
    "game-rounds": re.compile(r"\b(?:rounds|round-based|intermission|round state|round timer|round winner|minigame)\b", re.IGNORECASE),
    "game-inventory": re.compile(r"\b(?:inventory|equip|unequip|item pickup|item ownership|backpack)\b", re.IGNORECASE),
    "game-npc-quests": re.compile(r"\b(?:NPC quest|NPC quests|quest|quests|quest reward|quest dialogue|dialogue)\b", re.IGNORECASE),
    "eng-debugging": re.compile(
        r"\b(?:debug\w*|bugs?|root cause|fix(?:es)?|stack trace|errors?|crash\w*|broken|fails|failing|attempt to \w+|regression)\b",
        re.IGNORECASE),
    "eng-test-first": re.compile(
        r"\b(?:test-?first|TDD|tests? first|unit tests?|write (?:the )?tests?|red-?green|failing tests?|regression tests?|"
        r"asserts?)\b", re.IGNORECASE),
    "eng-verify-before-done": re.compile(
        r"\b(?:verif\w*|double-?check\w*|how (?:do|can) I (?:know|confirm|be sure)|(?:what|how) you (?:checked|tested)|"
        r"make sure (?:it|this) works|confirm (?:that|it))\b", re.IGNORECASE),
    # Shipped for explicit evaluation only; do not enable before the gate passes.
    "roblox-game-math": re.compile(
        r"\b(?:vectors?|Vector3|dot products?|cross products?|CFrame composition|CFrame|look[- ]?at|"
        r"lerp|easing(?: families)?|critically damped|springs?|quadratic|cubic|B[eé]zier|projectiles?|gravity|"
        r"angle wrapping|weighted random|seeded random|fixed[- ]timestep|raycast geometry)\b", re.IGNORECASE),
    # Design guidance, not implementation recipes; unmeasured and OFF by default.
    "design-core-loop-and-progression": re.compile(
        r"\b(?:core loops?|progression design|progression pacing|reward schedules?|difficulty curves?)\b", re.IGNORECASE),
    "design-onboarding-and-tutorial": re.compile(
        r"\b(?:onboarding|first[- ]time user experience|first (?:60|sixty) seconds|teaching by doing|tutorial design)\b",
        re.IGNORECASE),
    "design-game-feel": re.compile(
        r"\b(?:game feel|action feedback|input feel|impact feedback|camera feedback|sound feedback|feedback timing)\b",
        re.IGNORECASE),
    "design-level-and-obby-layout": re.compile(
        r"\b(?:obby layout|checkpoint spacing|level readability|level flow|risk and reward|risk[- ]reward)\b", re.IGNORECASE),
    "design-economy-and-fair-monetisation": re.compile(
        r"\b(?:economy|currency sinks?|currency sources?|inflation|fair moneti[sz]ation|paid random items?|odds disclosure)\b",
        re.IGNORECASE),
    "design-ui-ux-for-games": re.compile(
        r"\b(?:game UX|UI hierarchy|information hierarchy|thumb zones?|mobile[- ]first|readable text|colou?r[- ]blind)\b",
        re.IGNORECASE),
    # Service implementation recipes. Default OFF until an independent evaluation passes.
    "roblox-datastore-service-patterns": re.compile(
        r"\b(?:DataStoreService|GetRequestBudgetForRequestType|StandardRead|StandardWrite|UpdateAsync|session[- ]locks?)\b",
        re.IGNORECASE),
    "roblox-remote-event-function-patterns": re.compile(
        r"\b(?:RemoteFunction|OnServerInvoke|InvokeServer|RemoteEvent|OnServerEvent|FireClient|remote rate limits?)\b",
        re.IGNORECASE),
    "roblox-tweenservice-easing": re.compile(
        r"\b(?:TweenService|TweenInfo|EasingDirection|EasingStyle|TweenBase|PlaybackState|tween cancellation)\b",
        re.IGNORECASE),
    # Field lessons from a large Studio port project (docs/research/paintball-practice-proposals.md has the practice
    # ideas). Shipped OFF until the evaluation gate measures them.
    "roblox-studio-mcp-workflow": re.compile(
        r"\b(?:Studio MCP|MCP|cloud save|save confirmation|Version History|ChangeHistoryService|undo|Rojo|installer|"
        r"install (?:script|pipeline|snippet)|require coverage|screen ?capture|screenshots?|Edit mode|datamodel|"
        r"Archivable|rbxl|rbxm|place backup)\b", re.IGNORECASE),
    "roblox-replication-hot-paths": re.compile(
        r"\b(?:replication|replicat\w+|PivotTo|SetAttribute|GetAttribute|attributes?|UnreliableRemoteEvent|bandwidth|"
        r"network budget|network traffic|items per second|per-frame|hot path|allocations?|GetDescendants|"
        r"LocalTransparencyModifier|sequence numbers?)\b", re.IGNORECASE),
    "roblox-editable-memory-streaming": re.compile(
        r"\b(?:EditableMesh|EditableImage|CreateEditableMeshAsync|CreateEditableImage\w*|FixedSize|memory budget|"
        r"Content\.fromObject|TintMask|AlphaMode|ModelStreamingMode|Persistent|Atomic|streams? in|streamed in|"
        r"BatchSetValues)\b", re.IGNORECASE),
    "roblox-asset-upload-moderation": re.compile(
        r"\b(?:upload\w*|moderat\w+|off-?platform|barcodes?|QR codes?|asset review|asset approval|SHA-?256|hash gate|"
        r"thumbnail state|blocked assets?|re-?upload\w*|import queue)\b", re.IGNORECASE),
    "roblox-multi-agent-studio": re.compile(
        r"\b(?:multi-?agents?|several agents|two agents|parallel agents|Codex|Claude|integrator|claims?|claimed|"
        r"Studio lock|mutex|handoff|hand-?off|normal play|playtest acceptance|acceptance tests?|verdicts?|"
        r"INCOMPLETE|two clients|Server and Clients|late join)\b", re.IGNORECASE),
    "roblox-architecture-blender": re.compile(
        r"\b(?:Blender|architecture|architectural|facades?|rooflines?|gables?|glTF|GLB|FBX|3D Importer|"
        r"UV unwrap\w*|modelling|modeling)\b", re.IGNORECASE),
    # Other-engine packs (star/skill_packs/engines.py): opt-in, each chosen only when the prompt names its engine.
    **ENGINE_TOPICS,
    # Gameplay and platform recipes with typed (--!strict) examples. Default OFF until the evaluation gate passes.
    "roblox-combat-hitboxes": re.compile(
        r"\b(?:hit ?box(?:es)?|hitscan|hit detection|hit validation|melee|swords?|guns?|weapons?|damage|TakeDamage|"
        r"GetPartBoundsInBox|GetPartBoundsInRadius|GetPartsInPart|OverlapParams|RaycastParams|combat|attack cooldown)\b",
        re.IGNORECASE),
    "roblox-pathfinding-npc": re.compile(
        r"\b(?:PathfindingService|pathfinding|CreatePath|ComputeAsync|GetWaypoints|MoveToFinished|PathWaypoint|"
        r"PathfindingModifier|PathfindingLink|navigation mesh|navmesh|NPC (?:AI|movement|chase|patrol)|chase|patrol)\b",
        re.IGNORECASE),
    "roblox-physics-constraints": re.compile(
        r"\b(?:LinearVelocity|AngularVelocity|AlignPosition|AlignOrientation|VectorForce|BodyVelocity|BodyPosition|BodyGyro|"
        r"BodyForce|body movers?|mover constraints?|constraints?|ApplyImpulse|AssemblyLinearVelocity|SetNetworkOwner|"
        r"network ownership|knockback|HingeConstraint|SpringConstraint)\b", re.IGNORECASE),
    "roblox-collection-tags": re.compile(
        r"\b(?:CollectionService|GetTagged|AddTag|HasTag|GetInstanceAddedSignal|GetInstanceRemovedSignal|tags?|tagged|"
        r"attributes?|SetAttribute|GetAttribute|GetAttributeChangedSignal|component pattern)\b", re.IGNORECASE),
    "roblox-input-devices": re.compile(
        r"\b(?:ContextActionService|BindAction|UserInputService|InputBegan|gameProcessedEvent|PreferredInput|"
        r"LastInputTypeChanged|TouchEnabled|GamepadEnabled|gamepad|controller|touch controls?|mobile buttons?|keybinds?|"
        r"InputAction|InputContext|InputBinding|cross-?platform input|console)\b", re.IGNORECASE),
    "roblox-sound-design": re.compile(
        r"\b(?:SoundService|SoundGroup|Sound|sounds?|audio|music|sfx|RollOffMode|RollOffMaxDistance|PlaybackSpeed|"
        r"AudioPlayer|AudioEmitter|AudioListener|AudioDeviceOutput|Wire|PlayLocalSound|footsteps?|volume)\b",
        re.IGNORECASE),
    "roblox-luau-specs": re.compile(
        r"\b(?:TestEZ|describe|expect|specs?|unit tests?|test suites?|spec files?|test runner|testable|"
        r"dependency injection|pure functions?|Jest|beforeEach)\b", re.IGNORECASE),
    "roblox-marketplace-purchases": re.compile(
        r"\b(?:MarketplaceService|ProcessReceipt|PromptProductPurchase|PromptGamePassPurchase|UserOwnsGamePassAsync|"
        r"developer products?|game ?pass(?:es)?|Robux|purchases?|PurchaseGranted|NotProcessedYet|receipts?)\b",
        re.IGNORECASE),
    "roblox-teleport-matchmaking": re.compile(
        r"\b(?:TeleportService|TeleportAsync|TeleportOptions|ReserveServer|reserved servers?|TeleportInitFailed|"
        r"GetJoinData|teleport\w*|matchmaking|match ?queue|queues?|MemoryStoreService|MemoryStoreQueue|"
        r"MemoryStoreSortedMap|lobby to match|party|parties)\b", re.IGNORECASE),
    "roblox-open-cloud": re.compile(
        r"\b(?:Open Cloud|OpenCloud|apis\.roblox\.com|cloud/v2|x-api-key|HttpService|RequestAsync|GetSecret|secrets? store|"
        r"MessagingService|SubscribeAsync|webhooks?|external (?:server|service|tool)|from (?:outside|Python|Node))\b",
        re.IGNORECASE),
    "roblox-purchases-badges": re.compile(
        r"\b(?:ProcessReceipt|PurchaseId|PromptProductPurchase|PromptGamePassPurchase|UserOwnsGamePassAsync|"
        r"BadgeService|AwardBadgeAsync|UserHasBadgeAsync|developer products?|game passes?|purchase receipts?|leaderstats)\b",
        re.IGNORECASE),
    # Style-agnostic ability VFX (style profiles + timeline composer + typed Luau modules). OFF until evaluated.
    "roblox-vfx-composer": re.compile(
        r"\b(?:ability (?:vfx|effects?)|anime (?:vfx|effects?|ability)|vfx style|art style|style profiles?|"
        r"screen flash|camera shake|shockwave rings?|ground cracks?|vortex|energy pillar|charge-?up|aura|"
        r"colou?r inversion|flash frames?|dissipat\w*|impact frames?)\b", re.IGNORECASE),
    # Cutscenes and facial expressions (timeline, camera paths, FaceControls, typed Luau modules). OFF until evaluated.
    "roblox-cutscenes": re.compile(
        r"\b(?:cut-?scenes?|cinematics?|cinematic camera|camera (?:paths?|shots?|dolly|crane|fly-?through)|"
        r"CameraType\.Scriptable|Scriptable camera|letterbox\w*|skip button|FaceControls|facial (?:expressions?|animation)|"
        r"dynamic heads?|FACS|expressions? (?:change|player)|lip-?sync|talking animation|"
        r"Catmull-?Rom|camera splines?|depth of field|DepthOfFieldEffect|boss intro)\b", re.IGNORECASE),
    # EXPERIMENTAL XPBD secondary-motion kernel and rig preflight (SmartBone 2 comparison). OFF until evaluated.
    "roblox-secondary-motion-lab": re.compile(
        r"\b(?:SmartBone(?: ?2)?|XPBD|secondary motion|jiggle bones?|spring bones?|bone chains?|hair physics|cloth physics|"
        r"cosmetic physics|AnimationConstraint|ponytail|capes?|dangling)\b", re.IGNORECASE),
    # 2026 platform changes from the official docs (action-wave1-20261025). OFF until the evaluation gate measures them.
    "roblox-server-authority": re.compile(
        r"\b(?:server authority|server-authoritative (?:movement|physics|simulation|game)|AuthorityMode|"
        r"BindToSimulation|SetPredictionMode|client prediction|predict\w*|rollback|resimulat\w*|netcode|"
        r"NextGenerationReplication|UseFixedSimulation|competitive (?:game|shooter|fps|racing)|flyhacks?|speedhacks?|"
        r"server authority game|for prediction|in the simulation)\b",
        re.IGNORECASE),
    "roblox-luau-new-solver": re.compile(
        r"\b(?:type solver|new solver|UseNewLuauTypeSolver|LuauTypeCheckMode|--!strict|--!nonstrict|strict mode|"
        r"type check\w*|type errors?|blocked type|type functions?|export type|type annotations?|typed Luau)\b",
        re.IGNORECASE),
    "roblox-data-limits-2026": re.compile(
        r"\b(?:data ?store limits?|rate limits?|throttl\w*|request budgets?|GetRequestBudgetForRequestType|"
        r"SetRateLimitForRequestType|DataStoreRequestType|quota\w*|how many (?:requests|saves|writes)|"
        r"storage limit|4 ?MB|Open Cloud (?:limits?|data ?stores?)|data ?store errors?|30[1-6] error|limits?|"
        r"per minute|how (?:big|large|long|many)|budgets?|storage|shared with Open Cloud)\b",
        re.IGNORECASE),
}


@dataclass(frozen=True)
class Pack:
    name: str
    description: str
    body: str
    file: Path


@lru_cache(maxsize=1)
def available() -> tuple[Pack, ...]:
    """Every pack shipped in this folder, in the order of TRIGGERS. A broken pack is skipped, never fatal."""
    found = []
    for name in TRIGGERS:
        file = PACKS_DIR / name / "SKILL.md"
        try:
            fields, body = _frontmatter(file.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, ValueError):
            continue
        if fields.get("name") != name or not fields.get("description"):
            continue
        found.append(Pack(name, fields["description"], body.strip(), file))
    return tuple(found)


def enabled_names(environ=None, *, home=None) -> frozenset[str]:
    """Pack names that may be used now: STAR_SKILL_PACKS, else DEFAULT_ENABLED."""
    raw = (os.environ if environ is None else environ).get(ENV_VAR, "").strip().lower()
    known = {p.name for p in available()}
    if not raw:
        defaults = frozenset(known & set(DEFAULT_ENABLED))
        if home is not None:
            from ..promoter import enabled_skill_packs
            return enabled_skill_packs(home, defaults)
        return defaults
    if raw in {"off", "none", "no", "false", "0"}:
        return frozenset()
    if raw in {"all", "on", "true", "1"}:
        return frozenset(known)
    parts = {part.strip() for part in raw.split(",")}
    if "engines" in parts:
        # Shorthand for every other-engine pack, on top of the packs enabled by default.
        parts |= set(ENGINE_CONTEXTS) | set(DEFAULT_ENABLED)
    return frozenset(known & parts)


def select(prompt, *, enabled=None, limit: int = MAX_PACKS_PER_TURN, home=None) -> list[Pack]:
    """The packs for this prompt, best match first. Empty for anything that is not a Roblox question."""
    if not isinstance(prompt, str) or not prompt.strip() or len(prompt) > 20_000:
        return []
    # The prompt test comes first: it is a regular expression, while the enabled set with `home`
    # opens the knowledge database (promoter switches). Most prompts are not Roblox or Godot
    # questions and return here without touching it. Same result in either order.
    roblox_context = bool(_ROBLOX_CONTEXT.search(prompt))
    godot_context = bool(_GODOT_CONTEXT.search(prompt))
    # Other-engine packs: the prompt must name that engine (ENGINE_CONTEXTS); naming it is enough.
    engines = {name for name, context in ENGINE_CONTEXTS.items() if context.search(prompt)}
    if not roblox_context and not godot_context and not engines:
        return []
    allowed = enabled_names(home=home) if enabled is None else frozenset(enabled)
    if not allowed:
        return []
    engines &= allowed
    scored = []
    for order, pack in enumerate(available()):
        if pack.name in ENGINE_CONTEXTS:
            if pack.name in engines:
                hits = ({m.group(0).lower() for m in ENGINE_CONTEXTS[pack.name].finditer(prompt)} |
                        {m.group(0).lower() for m in TRIGGERS[pack.name].finditer(prompt)})
                # A named engine outranks Roblox packs: "port my RemoteEvent to Bevy" wants the Bevy pack.
                scored.append((0, -len(hits), order, pack))
        elif pack.name in allowed and ((pack.name in GODOT_PACKS and godot_context and not roblox_context) or
                                      (pack.name not in GODOT_PACKS and roblox_context and not godot_context)):
            hits = {m.group(0).lower() for m in TRIGGERS[pack.name].finditer(prompt)}
            # One generic word ("UI", "Tool", "validate") is not enough to spend the reader's time.
            if len(hits) >= 2 or any(len(h) > 6 for h in hits):
                scored.append((1, -len(hits), order, pack))
    return [item[-1] for item in sorted(scored, key=lambda item: item[:3])[:max(0, limit)]]


def render(packs) -> str:
    """The text added to the turn under BLOCK_HEADING, '' when no pack applies. Bounded by MAX_BLOCK_CHARS."""
    packs = list(packs)
    if not packs:
        return ""
    text = "\n\n".join(p.body for p in packs)
    return text[:MAX_BLOCK_CHARS].rstrip() + "\n"


def matching_names(prompt, *, enabled=None) -> list[str]:
    return [p.name for p in select(prompt, enabled=enabled)]
