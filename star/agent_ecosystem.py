"""Research-backed, **default-off** roster for STAR's future multi-agent conductor.

This module is a source-linked discovery and admission PREVIEW. It never
installs software, runs subprocesses, authenticates providers, calls inference,
modifies project files, exposes private context, or promotes lessons.

A free/open-source agent harness does not imply free inference. Never derive
usage rights, billing, permissions or readiness from catalog metadata alone.
Only a trusted STAR host may construct live AgentObservation records from
version-pinned, owner-authorized capability and entitlement probes.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

Access = Literal["local_runtime", "account_quota", "bring_your_own_model", "subscription_or_api"]
Kind = Literal["coding_agent", "general_agent", "browser_agent", "inference_runtime", "media_runtime"]
Integration = Literal["cli", "acp", "rpc", "app_server", "sdk", "local_api"]
_CAPS = frozenset({"code", "review", "research", "browser", "mcp", "image", "video",
                   "audio", "3d", "local_inference", "game_engine"})
_KINDS = frozenset({"coding_agent", "general_agent", "browser_agent", "inference_runtime", "media_runtime"})
_INTEGRATIONS = frozenset({"cli", "acp", "rpc", "app_server", "sdk", "local_api"})
_ACCESS = frozenset({"local_runtime", "account_quota", "bring_your_own_model", "subscription_or_api"})


@dataclass(frozen=True, slots=True)
class AgentSpec:
    id: str
    name: str
    kind: Kind
    integration: Integration
    access: Access
    capabilities: frozenset[str]
    source: str
    notes: str
    open_source_harness: bool

    def __post_init__(self) -> None:
        if not self.id.isascii() or not self.id.replace("_", "").isalnum() or len(self.id) > 40:
            raise ValueError("Invalid agent identifier")
        if self.kind not in _KINDS or self.integration not in _INTEGRATIONS or self.access not in _ACCESS:
            raise ValueError("Invalid agent category")
        if type(self.capabilities) is not frozenset or not self.capabilities <= _CAPS:
            raise ValueError("Unknown agent capabilities")
        if not self.source.startswith("https://") or not 8 < len(self.source) < 260:
            raise ValueError("Agent needs a source URL")


def _spec(agent_id: str, name: str, kind: Kind, integration: Integration, access: Access,
          capabilities: str, source: str, notes: str, *, oss: bool = True) -> AgentSpec:
    return AgentSpec(agent_id, name, kind, integration, access, frozenset(capabilities.split()),
                     source, notes, oss)


# This is a shortlist of candidate AGENT/TOOLS frontends, not hosted models or
# a claim that any of these services are connected to STAR. Capabilities refer
# only to documented candidate features and still require real adapter probes.
AGENTS: tuple[AgentSpec, ...] = (
    _spec("gemini_cli", "Google Gemini CLI", "coding_agent", "cli", "account_quota",
          "code review research mcp", "https://github.com/google-gemini/gemini-cli",
          "Published eligible free account quotas; current model/usage entitlement must be probed."),
    _spec("opencode", "OpenCode", "coding_agent", "acp", "bring_your_own_model",
          "code review mcp", "https://github.com/anomalyco/opencode",
          "Documented ACP and headless server; model access and cost depend on provider."),
    _spec("goose", "goose", "general_agent", "acp", "bring_your_own_model",
          "code review research mcp", "https://github.com/aaif-goose/goose",
          "Open-source local agent; MCP extensions and ACP; models are separate."),
    _spec("openhands", "OpenHands", "coding_agent", "sdk", "bring_your_own_model",
          "code review", "https://github.com/OpenHands/software-agent-sdk",
          "SDK supports sandboxed workspaces; execution hosting and models can cost extra."),
    _spec("aider", "Aider", "coding_agent", "cli", "bring_your_own_model",
          "code review", "https://github.com/Aider-AI/aider",
          "Codebase mapping and local/hosted LLMs; integrate headless only after probe."),
    _spec("cline", "Cline", "coding_agent", "cli", "bring_your_own_model",
          "code review browser mcp", "https://github.com/cline/cline",
          "IDE/CLI agent; browser and MCP tools require explicit permissions."),
    _spec("continue_cli", "Continue CLI", "coding_agent", "cli", "bring_your_own_model",
          "code review mcp", "https://github.com/continuedev/continue",
          "Supports headless CLI with scoped tool permissions; provider account may be required."),
    _spec("qwen_code", "Qwen Code", "coding_agent", "cli", "bring_your_own_model",
          "code review mcp", "https://github.com/QwenLM/qwen-code",
          "Qwen OAuth free tier discontinued 2026-04-15; other model providers available."),
    _spec("kilo_code", "Kilo Code", "coding_agent", "cli", "bring_your_own_model",
          "code review browser mcp", "https://github.com/Kilo-Org/kilocode",
          "Open-source agent, provider rates/quotas vary; no blanket bypass mode."),
    _spec("pi", "Pi coding agent", "coding_agent", "rpc", "bring_your_own_model",
          "code review", "https://github.com/badlogic/pi-mono",
          "JSONL RPC and SDK; extensions can run arbitrary code if installed."),
    _spec("omp", "Oh My Pi (OMP)", "coding_agent", "rpc", "bring_your_own_model",
          "code review research mcp", "https://github.com/can1357/oh-my-pi",
          "Optional Python RPC client; LSP/DAP and edits need installed adapters and scoped execution. "
          "Catalog entry is not an installed worker or a free model entitlement."),
    _spec("swe_agent", "SWE-agent", "coding_agent", "cli", "bring_your_own_model",
          "code review", "https://github.com/SWE-agent/SWE-agent",
          "Research/software-repair agent; assess isolation and licensing per revision."),
    _spec("hermes_agent", "Hermes Agent", "general_agent", "cli", "bring_your_own_model",
          "code review research mcp", "https://github.com/NousResearch/hermes-agent",
          "Self-improving skill proposals require STAR independent review, not automatic promotion."),
    _spec("plandex", "Plandex", "coding_agent", "cli", "bring_your_own_model",
          "code review", "https://github.com/plandex-ai/plandex",
          "Large-project plan/diff isolation; Windows works via WSL; models are separate."),
    _spec("openclaw", "OpenClaw", "general_agent", "cli", "bring_your_own_model",
          "code research mcp", "https://github.com/openclaw/openclaw",
          "Broad gateway/device integrations; high-risk permissions, default-off candidate only."),
    _spec("browser_use", "Browser Use", "browser_agent", "sdk", "bring_your_own_model",
          "browser research", "https://github.com/browser-use/browser-use",
          "Python open-source library; inference/browser hosting may be paid."),
    _spec("codex", "OpenAI Codex", "coding_agent", "app_server", "subscription_or_api",
          "code review mcp", "https://github.com/openai/codex",
          "Official app-server/SDK; model entitlement and terms are provider-controlled.", oss=True),
    _spec("claude_code", "Claude Code", "coding_agent", "cli", "subscription_or_api",
          "code review mcp", "https://code.claude.com/docs/en/overview",
          "Official CLI/Agent SDK; some subscriptions work within official limits.", oss=False),
    _spec("github_copilot", "GitHub Copilot CLI/SDK", "coding_agent", "sdk", "subscription_or_api",
          "code review mcp", "https://github.com/github/copilot-sdk",
          "SDK/harness availability and inference rights depend on account.", oss=True),
    _spec("ollama", "Ollama", "inference_runtime", "local_api", "local_runtime",
          "local_inference", "https://github.com/ollama/ollama",
          "Local inference runtime, NOT a complete editing agent by itself."),
    _spec("llamacpp", "llama.cpp", "inference_runtime", "local_api", "local_runtime",
          "local_inference", "https://github.com/ggml-org/llama.cpp",
          "Existing STAR provider; local weights, compute and memory required."),
    _spec("comfyui", "ComfyUI", "media_runtime", "local_api", "bring_your_own_model",
          "image video audio 3d", "https://github.com/Comfy-Org/ComfyUI",
          "Local media workflow service, NOT an LLM coding agent; model license varies."),
)

_BY_ID = {item.id: item for item in AGENTS}
if len(_BY_ID) != len(AGENTS):
    raise RuntimeError("Duplicate ecosystem agent identifiers")


@dataclass(frozen=True, slots=True)
class AgentObservation:
    """Trusted host observation; never construct from model-generated metadata.

    model_access_verified is about a real, permitted health/entitlement test,
    NOT proof of free use or verified competency. available capabilities are
    also host-tested subsets, not the spec's whole documented feature list.
    """

    agent_id: str
    installed: bool
    model_access_verified: bool
    capabilities_verified: frozenset[str]
    no_charge_verified: bool = False

    def __post_init__(self) -> None:
        if self.agent_id not in _BY_ID:
            raise ValueError("Unknown catalog agent")
        if any(type(v) is not bool for v in (self.installed, self.model_access_verified, self.no_charge_verified)):
            raise ValueError("Observation booleans required")
        if type(self.capabilities_verified) is not frozenset or (
                not self.capabilities_verified <= _BY_ID[self.agent_id].capabilities):
            raise ValueError("Observation cannot claim undocumented capability")


@dataclass(frozen=True, slots=True)
class CandidatePreview:
    id: str
    name: str
    source: str
    integration: str
    access: str
    status: Literal["ready_for_owner_review", "not_available", "not_authorized", "not_verified"]
    reason: str


def catalog(*, required: frozenset[str] = frozenset(), limit: int = 24) -> tuple[AgentSpec, ...]:
    """Read-only discovery. No inference, fetching, probing or side effects."""
    if type(required) is not frozenset or not required <= _CAPS or type(limit) is not int or not 1 <= limit <= 32:
        raise ValueError("Invalid catalog filter")
    return tuple(item for item in AGENTS if required <= item.capabilities)[:limit]


def plan_candidates(
    *,
    required: frozenset[str],
    observations: tuple[AgentObservation, ...] = (),
    approved_ids: frozenset[str] = frozenset(),
    allow_external_data: bool = False,
    require_zero_spend: bool = True,
    limit: int = len(AGENTS),
) -> tuple[CandidatePreview, ...]:
    """Preview *potential* team members without launching/authorizing any agent.

    Only explicitly approved providers with real trusted host observations can
    become ready_for_owner_review. Even that status is NOT permission to run a
    subprocess, transfer files, or spend money. All execution requires a
    separate scope/cost/tool gate in the actual conductor runtime.
    """
    if (type(required) is not frozenset or not required or not required <= _CAPS
            or type(approved_ids) is not frozenset or not approved_ids <= _BY_ID.keys()
            or any(type(v) is not str for v in approved_ids)
            or type(allow_external_data) is not bool or type(require_zero_spend) is not bool
            or type(limit) is not int or not 1 <= limit <= len(AGENTS)):
        raise ValueError("Invalid candidate policy")
    if type(observations) is not tuple or len(observations) > len(AGENTS) or not all(
        isinstance(x, AgentObservation) for x in observations
    ):
        raise ValueError("Expected bounded trusted host observations")
    if len({x.agent_id for x in observations}) != len(observations):
        raise ValueError("Duplicate observation IDs")
    observed = {o.agent_id: o for o in observations}
    rows: list[CandidatePreview] = []
    for spec in catalog(required=required, limit=len(AGENTS)):
        rec = observed.get(spec.id)
        if spec.id not in approved_ids:
            status, reason = "not_authorized", "Owner has not enabled this agent"
        elif not rec or not rec.installed or not rec.model_access_verified:
            status, reason = "not_available", "Installation and actual model access have not both been verified"
        elif not required <= rec.capabilities_verified:
            status, reason = "not_verified", "Required capability has not passed a trusted host probe"
        elif not allow_external_data and spec.access != "local_runtime":
            status, reason = "not_authorized", "External-project transfer not approved; a local model in a BYO harness must be verified separately"
        elif require_zero_spend and not rec.no_charge_verified:
            status, reason = "not_authorized", "No-charge model route and quota not verified"
        else:
            status, reason = "ready_for_owner_review", "Candidate only; still requires scoped execution authorization"
        rows.append(CandidatePreview(spec.id, spec.name, spec.source, spec.integration,
                                     spec.access, status, reason))
        if len(rows) >= limit:
            break
    return tuple(rows)
