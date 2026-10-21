export type Project = { name: string }
export type ChatMessage = { id: string; role: 'user'|'assistant'|'event'; text: string; created?: string; attachments?: string[]; previews?: string[]; image?: string; status?: 'failed'|'cancelled'; mid?: number; feedback?: 'up'|'down' }
/** The newest question that got no answer, as derived by the desktop host; survives restarts. */
export type RetryState = { status: 'failed'|'cancelled'|'interrupted'; detail: string; prompt: string; message_id: number; created: string }
export type AppSettings = { endpoint: string; provider: 'local'|'star_server'|'groq'|'openrouter'|'gemini'|'cerebras'; model: string; fast_model: string; reasoning_model: string; roblox_model: string; vision_model: string; router_models_dir: string; router_context: number; gpu_layers: number; instant_route_enabled?: boolean|null; project: string; workspace: string; studio_id: string; studio_target?: StudioTarget; studio_edit: boolean; workspace_edit: boolean; debug_evidence_enabled?: boolean; minecraft_tools_enabled?: boolean; live_show_enabled?: boolean; max_calls: number; context_chars: number; reduced_motion: boolean; obsidian_vault: string; obsidian_enabled: boolean; skills_enabled: boolean; graphify_enabled: boolean; comfy_workflow: string; comfy_prompt_node: string; comfy_port: number; mcp_graphify_docs: boolean; mcp_graphify_local: boolean; mcp_graphify_port: number; mcp_obsidian_live: boolean; blender_enabled?: boolean; blender_edit?: boolean; blender_motion_qa?: boolean; blender_executable?: string; roblox_research_enabled: boolean; asset_forge_enabled?: boolean; commerce_enabled?: boolean; tool_workshop_enabled: boolean; specialists_enabled: boolean; specialist_parallelism: number; server_endpoint?: string; allow_cgnat?: boolean; server_timeout?: number; server_parallel?: number; server_context_tokens?: number; knowledge_endpoint?: string; learning_auto_accept?: boolean; learning_digest?: boolean; learning_digest_cloud?: boolean; practice_lessons_enabled?: boolean; worked_examples_enabled?: boolean; learning_auto_live?: boolean; research_auto_check?:boolean; deep_research_enabled?:boolean; scholarly_research_enabled?:boolean; discord_autostart?: boolean; media_images?: MediaPlace; media_voice?: MediaPlace; media_video?: MediaPlace; media_chat_auto?: boolean; session_capabilities_prompt?: boolean; media_use_references?: boolean; comfy_home?: string; ffmpeg_dir?: string; picture_max_side?: number; studio_own_places?: boolean; studio_luau?: boolean; luau_run_before_answer?: boolean; studio_tool_examples?: boolean; project_rules_enabled?: boolean; luau_retry_ladder?: boolean; presolve_enabled?: boolean; skill_pack_embeddings?: boolean; web_auto_search?: boolean; roblox_docs_live_enabled?: boolean; use_my_gpu?: boolean; gpu_helper_server?: string; gpu_helper_model?: string; gpu_idle_minutes?: number; github_repository_access_source?: 'gh'|'env'; mcp_github_repositories?: boolean; prefill_while_typing?: boolean; edit_diff?: boolean }
/** One timed step of the STAR Server check. The server key is never part of any report. */
export type ServerStep = { name:string; status:'ok'|'failed'|'skipped'; ms:number; detail:string }
export type ServerReport = { ok:boolean; code:string; message:string; steps:ServerStep[]; models:string[]; model:string; context_tokens:number|null; slots:number|null; first_token_ms:number|null; sample:string; roles?:ServerRole[] }
/** Nonsecret summary from the desktop host. `ok` is null until the server has been checked. */
/** Which server model does which job. `source`: manual = set by the owner, server = discovered, default = the one configured model. */
export type ServerRole = { role:string; label:string; model:string; source:'manual'|'server'|'default' }
export type ServerStatus = { selected:boolean; configured:boolean; key_present:boolean; model_selected:boolean; ok:boolean|null; code:string; checked_at:string; roles?:ServerRole[] }
export type Analytics = { started: number; succeeded: number; failed: number; tools: number; rejected: number; median_ms: number|null; messages: number; project: string; period_days: number; trend: Array<{date:string;runs:number}>; recent: Array<{type:string;at:string;duration_ms:number|null;detail:string}>; learning?: LearningActivity }
/** Counted learning events of the analytics period, plus current totals. Never estimated. */
export type LearningActivity = { captured:number; accepted:number; used:number; pending?:number; accepted_now?:number; uses_total?:number }
export type LessonStatus = 'candidate'|'accepted'|'rejected'|'superseded'|'merged'
/** One lesson as the desktop host stores it: project-scoped text with where it came from. */
export type Lesson = { id:number; project:string; kind:string; text:string; status:LessonStatus; source:string; source_type:string; evidence:string; created:string; updated:string; supersedes_id:number|null; merged_into:number|null; uses:number; last_used:string; origin:string }
export type LessonCounts = { candidate:number; accepted:number; rejected:number; superseded:number; merged:number; pending:number; uses:number; practice?:number }
/** One item of "What STAR learned this week" (star/learned_week.py). */
export type LearnedItem = { id:number; kind:'lesson'|'example'; title:string; evidence:string; gate:{decision?:string; wins?:number; losses?:number; tasks?:number; k?:number; p_better?:number|null}; live_at:string; expires_at:string; days_left:number|null; state:'live'|'undone'|'expired'|'kept'; uses:number }
export type LearnedWeek = { project:string; items:LearnedItem[]; counts:Record<string,number> }
/** An owner correction that may become a regression test (star/corrections.py). */
export type CorrectionItem = { id:number; created:string; source:'app'|'discord'; prompt:string; answer:string; correction:string; cause:string; status:'candidate'|'approved'|'dismissed'; task_id:string }
export type CorrectionListing = { project:string; corrections:CorrectionItem[]; counts:{candidate:number; approved:number; dismissed:number}; suite:string }
export type IntelligenceStatus = {
  skills: {enabled:boolean;count:number;names:string[]};
  graphify: {enabled:boolean;export_detected:boolean;path:string;note:string};
  obsidian: {enabled:boolean;read_only:boolean;note:string};
  roblox_research?: {enabled:boolean}
}
export type BlenderStatus = {enabled:boolean;installed:boolean;edit_enabled:boolean;executable:string;connection:string;ready:boolean;note:string}
export type McpStatus = { servers: Array<{name:string;enabled:boolean;protocol:string;credential_ready:boolean;state:string;read_only:boolean}> }
export type ChatThread = { id:string; title:string; created:string; updated:string }
export type CustomToolRecipe = { id:number;name:string;description:string;status:'pending'|'approved'|'rejected'|'disabled';tests:number;created_at:string;last_tested_at?:string|null;reviewed_at?:string|null;sources:string[] }
export type CustomToolCatalog = {project:string;tools:CustomToolRecipe[];notice:string}
export type WorkshopStatus = {pending:number;approved:number;rejected:number;disabled:number;read_only:boolean}
export type BuildInfo = {stamped:boolean; source_commit:string; head_commit:string; run_url:string; build_event:string; note:string}
/** Settings > Use my GPU (star/gpu_helper.py), as the host reports it. */
export type GpuHelperStatus = { state:'off'|'starting'|'ready'|'busy'|'idle'|'failed'; label:string; text:string; tokens_per_second:number|null; enabled:boolean }
export type BootData = { version:string; build?:BuildInfo; project:string; projects:string[]; messages:ChatMessage[]; active_chat:string; chats:ChatThread[]; settings:AppSettings; brain_installed:boolean; brain_running:boolean; model_router_running?:boolean; analytics:Analytics; release_url:string; intelligence?:IntelligenceStatus; credentials:Record<string,boolean>; mcp?:McpStatus; blender?:BlenderStatus; tool_workshop?:WorkshopStatus; server?:ServerStatus; retry?:RetryState|null; learning?:LessonCounts; roblox?:RobloxStatus; studio?:StudioConnectionStatus }
/** What chat navigation (newChat, switchChat, deleteChat) returns: only the chat part of BootData. */
export type ChatState = Pick<BootData,'project'|'projects'|'messages'|'active_chat'|'chats'|'retry'>
/** Where a media capability runs: the STAR Brains (servers) or this PC's graphics card (star/media_places.py). */
export type MediaPlace = 'servers'|'pc'
export type MediaOption = { id: MediaPlace; label: string; available: boolean; note: string; reason: string; /** false: this install can never offer it (not a setting away); older hosts omit it. */ fixable?: boolean }
export type MediaCapability = { id: 'images'|'voice'|'video'; title: string; field: string; chosen: MediaPlace; options: MediaOption[] }
export type MediaStatus = { places: MediaCapability[]; images: { running: boolean; ready: boolean; missing: string[]; model: string; message: string; version?: string }; sizes: Array<{id: string; label: string}>; can_start: boolean; detected_home?: string; ffmpeg: { found: boolean; message: string }; measured_on: string; references: number }
export type MediaReference = { id: string; label: string; note: string; width: number; height: number; added: string; preview: string }
export type MediaComparison = { reference: {id: string; label: string}; image: string; saved: string; candidate: string; differences: string[]; measured: { lines: string[] }; model: string; seconds: number; model_error: string }
/** `voice` events belong to a voice call or a voice preview; they are keyed by the request that started it. */
export type BackendEvent = { requestId:string; kind:'result'|'progress'|'error'|'voice'; data:unknown }
/** Roblox Open Cloud connection as the desktop host reports it. The API key itself is never part of any of these. */
export type RobloxState = 'no_key'|'unchecked'|'valid'|'missing_permission'|'invalid'|'revoked'|'unreachable'
export type RobloxAccount = { user_id:number|null; name:string }
export type RobloxCapability = { id:string; label:string; granted:boolean; needs:string[]; status:number|null; evidence:string }
/** Result of the Test button: harmless calls only, each with its HTTP status. */
export type RobloxCheck = { state:RobloxState; message:string; checked_at:string; source:string; reason?:string; account?:RobloxAccount; expires?:string; capabilities:RobloxCapability[]; calls:Array<{call:string;status:number|null;note?:string}>; missing?:string[]; warnings?:string[] }
export type RobloxExperience = { universe_id:number; place_id:number; name:string; visibility:string; verified_at:string; owner_user_id?:number }
export type RobloxStatus = { key_present:boolean; source:string; state:RobloxState; message:string; last_check:{state:RobloxState;message:string;checked_at:string;account?:RobloxAccount;missing?:string[]}|null; test_experience:RobloxExperience|null; pending_actions:number; denied_place_ids:number[]; denied_universe_ids?:number[]; check?:RobloxCheck }
/** A publish or test run the model asked for. Nothing is sent to Roblox until the owner approves it. */
export type RobloxAction = { id:string; kind:'publish'|'run_test'; status:'pending'|'running'|'done'|'failed'|'unknown'|'rejected'|'expired'; summary:string; target:{universe_id:number;place_id:number;name:string}; created:string; expires:string; detail:Record<string,unknown>; result?:Record<string,unknown> }

export type StudioTarget='local_pc'|'host_launcher'
export type StudioConnectionStatus={target:StudioTarget;label:string;state:'not_checked'|'unconfigured'|'connected'|'no_instances'|'unavailable';checked_at:string;tool_count:number;instances:Array<{id:string;name:string}>;selected_id:string;selected_valid:boolean;reason_code:string;local_mcp:string;server_name:string;diagnostic?:{stage:string;reason:string}|null}
/** Whether a STAR Studio server connection is stored, and where it comes from. The address and command are never sent to the page. */
export type StudioHostStatus={configured:boolean;source:'environment'|'settings'|'none'|'invalid'}

/** The voice catalog as the desktop host lists it (star/voice/bridge.py, docs/STAR_VOICE_CALLS.md section 9). */
export type VoiceStyle={id:string;name:string;summary:string;preview_line:string}
export type VoiceEntry={id:string;name:string;style:string;archetype:string;engine:string;licence:string;notes:string;recommended_for:string[];callable:boolean;reason:string;latency?:{first_audio_seconds?:number|null;first_audio_kind?:string;device?:string}}
export type VoiceCatalog={styles:VoiceStyle[];voices:VoiceEntry[];selected:{voiceId:string;voice:string;style:string;speed:number}}
export type VoiceEngineStatus={available:boolean;missingPackages:string[];missingModels:string[];serverConfigured:boolean;inCall:boolean}

/** Settings > Discord: what the desktop host reports about the Discord bot (star/discord_supervisor.py). Never a token, an ID or a path. */
export type DiscordState='not_configured'|'stopped'|'starting'|'connected'|'backoff'|'error'|'external'
export type DiscordStatus={state:DiscordState;message:string;problem:string;missing:string[];running:boolean;connected:boolean;external:boolean;wantsRunning:boolean;restarts:number;crashes:number;lastExitCode:number|null;retryInSeconds:number|null;logFile:string;autostart:boolean}
