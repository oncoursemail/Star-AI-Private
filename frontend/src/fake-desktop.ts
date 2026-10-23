/**
 * Test double for STAR's Qt WebChannel host.
 *
 * It implements the same contract the Python Bridge exposes to the page
 * (`window.qt`, `QWebChannel`, `starBridge.invoke(json, cb)` and the `event`
 * signal) plus a tiny in-memory "database" so tests can drive the UI the way
 * the real backend does: persist a user message, stream deltas, then persist
 * the answer (or a terminal failure record) and emit the matching event.
 *
 * Tests built on this are written against behaviour only: bridge messages out,
 * bridge events in, visible text asserted. They never reference class names.
 */
import {act} from '@testing-library/react'

export type Call = {action: string; payload: Record<string, unknown>; requestId: string}
export type Reply = {ok: boolean; data?: unknown; pending?: boolean; error?: string}
type Row = {id: string; role: 'user' | 'assistant' | 'event'; text: string; created: string; status?: string; mid?: number; feedback?: string; image?: string}

/** Mirrors `asdict(Settings())` in star/desktop_core.py; loosely typed on purpose. */
export const backendSettings = {
  endpoint: 'http://127.0.0.1:8080/v1', provider: 'local', model: 'qwen-test', fast_model: '',
  reasoning_model: '', roblox_model: '', vision_model: '', strata_enabled: false,
  strata_endpoint: 'http://127.0.0.1:8082/v1', strata_model: 'strata', strata_reasoning: 'auto',
  strata_context_tokens: 32768, strata_timeout: 900, strata_vision_enabled: true, strata_loop_guard_enabled: true,
  router_models_dir: '', router_context: 4096,
  gpu_layers: 25, instant_route_enabled: false, project: 'STAR', workspace: '', studio_id: '', studio_target: 'local_pc', studio_edit: false, workspace_edit: false,
  max_calls: 12, context_chars: 26000, reduced_motion: true, obsidian_vault: '', obsidian_enabled: false,
  skills_enabled: true, graphify_enabled: true, comfy_workflow: '', comfy_prompt_node: '6', comfy_port: 8188,
  mcp_graphify_docs: false, mcp_graphify_local: false, mcp_graphify_port: 8931, mcp_obsidian_live: false,
  blender_enabled: false, blender_edit: false, blender_executable: '',
  roblox_research_enabled: true, asset_forge_enabled: false, commerce_enabled: true, tool_workshop_enabled: true, specialists_enabled: true, specialist_parallelism: 1,
  practice_lessons_enabled: false, worked_examples_enabled: false, presolve_enabled: false,
}

const analytics = {started: 0, succeeded: 0, failed: 0, tools: 0, rejected: 0, median_ms: null, messages: 0,
  project: 'STAR', period_days: 14, trend: [], recent: []}

let counter = 0
const stamp = () => new Date(Date.UTC(2026, 9, 10, 12, 0, counter++)).toISOString()

export function installFakeDesktop() {
  const calls: Call[] = []
  let listener: ((raw: string) => void) | null = null
  let db: Row[] = []
  let retry: unknown = null
  let reported: Record<string, unknown> = {}
  const handlers = new Map<string, (call: Call) => Reply | void>()

  const boot = () => ({
    version: '1.0.0', project: 'STAR', projects: ['STAR'], active_chat: 'chat-1',
    chats: [{id: 'chat-1', title: 'Test chat', created: stamp(), updated: stamp()}],
    // Like the real host: every stored answer carries its row id, so it can be rated.
    messages: db.map((m, i) => ({...m, id: `saved-${i}`, ...(m.role === 'assistant' ? {mid: m.mid ?? i + 1} : {})})), retry,
    settings: backendSettings, brain_installed: true, brain_running: true, analytics,
    release_url: 'https://github.com/oncoursemail/Star-AI/releases/latest', credentials: {},
    ...reported,
  })

  const reply = (call: Call): Reply => {
    const custom = handlers.get(call.action)?.(call)
    if (custom) return custom
    switch (call.action) {
      case 'bootstrap': return {ok: true, data: boot()}
      case 'sendMessage': case 'generateImage': case 'runTeam': {
        // The real worker saves the user message first, then answers asynchronously.
        if (call.payload.retryMessageId === undefined) db.push({id: '', role: 'user', text: String(call.payload.prompt), created: stamp()})
        retry = null
        return {ok: true, pending: true}
      }
      case 'cancelMessage': return {ok: true, data: {cancel_requested: true}}
      default: return {ok: true, data: null}
    }
  }

  const native = {
    invoke(serialized: string, callback: (raw: string) => void) {
      const {requestId, action, ...payload} = JSON.parse(serialized)
      const call: Call = {action, payload, requestId}
      calls.push(call)
      const result = reply(call)
      queueMicrotask(() => callback(JSON.stringify(result)))
    },
    event: {connect(fn: (raw: string) => void) { listener = fn }},
  }
  class FakeChannel {
    constructor(_transport: unknown, ready: (channel: {objects: {starBridge: typeof native}}) => void) {
      ready({objects: {starBridge: native}})
    }
  }
  Object.assign(window, {qt: {webChannelTransport: {}}, QWebChannel: FakeChannel})
  // jsdom lacks these browser APIs which the chat view touches.
  if (!window.matchMedia) {
    window.matchMedia = ((query: string) => ({matches: false, media: query, onchange: null,
      addEventListener() {}, removeEventListener() {}, addListener() {}, removeListener() {}, dispatchEvent: () => false})) as typeof window.matchMedia
  }
  Element.prototype.scrollTo = Element.prototype.scrollTo || (() => {})
  Element.prototype.scrollIntoView = Element.prototype.scrollIntoView || (() => {})

  const emit = (requestId: string, kind: 'progress' | 'result' | 'error' | 'voice', data: unknown) =>
    act(() => { listener?.(JSON.stringify({requestId, kind, data})) })
  const requestOf = (action: string, index = -1) => {
    const found = calls.filter(c => c.action === action)
    const call = found.at(index)
    if (!call) throw new Error(`The page never sent ${action}`)
    return call.requestId
  }

  return {
    calls,
    snapshot: () => boot(),
    saved: () => db.map((m,i) => ({...m,id: `saved-${i}`})),
    sent: (action: string) => calls.filter(c => c.action === action),
    requestOf,
    /** Start every test from a clean backend. */
    reset(messages: Row[] = [], nextRetry: unknown = null) {
      calls.length = 0; handlers.clear(); retry = nextRetry; reported = {}
      db = messages.map(m => ({...m, created: m.created || stamp()}))
    },
    /** Change what the host reports from now on (saved settings, the server check), as a real save or check would. */
    host(state: Record<string, unknown>) { reported = {...reported, ...state} },
    /** Override how the host answers one action (for example, refuse `sendMessage`). */
    onAction(action: string, handler: (call: Call) => Reply | void) { handlers.set(action, handler) },
    delta: (requestId: string, text: string) => emit(requestId, 'progress', {phase: 'Generating response', delta: text}),
    phase: (requestId: string, phase: string) => emit(requestId, 'progress', {phase}),
    /** The backend saved the assistant message, then returned the answer. */
    complete(requestId: string, answer: string) {
      db.push({id: '', role: 'assistant', text: answer, created: stamp()})
      retry = null
      return emit(requestId, 'result', {answer})
    },
    /** Post-#8 behaviour: a terminal record is stored before the error event is emitted. */
    fail(requestId: string, detail: string, status: 'failed' | 'cancelled' = 'failed') {
      db.push({id: '', role: 'event', text: detail, created: stamp(), status})
      retry = {status, detail, prompt: [...db].reverse().find(m => m.role === 'user')?.text ?? '', message_id: 1, created: stamp()}
      return emit(requestId, 'error', detail)
    },
    emitRaw: emit,
  }
}

export type FakeDesktop = ReturnType<typeof installFakeDesktop>
