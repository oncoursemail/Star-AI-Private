"""STAR starts thinking while you type (Settings > Answers, off by default).

While the owner types, the interface sends the draft (after a pause, see frontend/src/draftWarm.ts). This
module lets the model server read the exact start the real turn will have: the conversation's system message,
memory and earlier turns, then the owner's words so far, on the slot that turn will use. On Enter the server
then reads only the last few words and this turn's reference block (which comes after the owner's words,
star.agent.volatile_context), instead of the whole message.

How: STAR's models are hybrid (recurrent layers), and llama.cpp can reuse a cached prompt only up to a saved
checkpoint. It saves one at the start of the last user message and 4 tokens before the end of each prompt.
A chat request for the draft ends with the template's closing tokens, so its end-of-prompt checkpoint lies
after the owner's words and the real turn could only go back to the start of the message (measured: the turn
then re-read the whole message). So the request is rendered by the server's own chat template
(`/apply-template`), cut right after the owner's words, and sent as raw text (`/v1/completions`, one token):
its checkpoint lands 4 tokens before the end of the draft, inside what the real turn will send.

Harmless by construction, like the post-answer warm-up (star/warmup.py):

  * own hardware only (STAR Server or the on-PC brain); a cloud provider is never sent anything;
  * nothing is saved and the answer text cannot change: the request only fills the server's prompt cache;
  * at most one draft request at a time; a newer draft waits and replaces older ones (no queue); a long draft
    (a paste) goes in chunks of CHUNK_CHARS, so the server is never more than one chunk away from a real request;
  * any real request cancels it (react_shell WARM_UP_STOPPERS). The server finishes the batch it is reading
    and keeps it (measured on build 11541: a request cut off after 8 s left 1,927 of 2,443 tokens cached),
    and the turn stays on that slot (providers.own_warm_started) instead of taking it for another client's;
  * small budget: on STAR Server it first asks which slots of that model are generating. All busy: nothing
    is sent (it would wait behind someone else's answer). Some busy (night school, another client, a
    summary): only a draft of at most BUSY_MAX_CHARS, into an idle slot, the one the turn will take;
  * with "Use my GPU" on and the PC's model loaded and free, a draft for that model goes to the PC (the turn
    will), without holding it; it never loads the PC model.

The turn's reference block (documentation passages, skill packs, lessons, notes: ~1,000-1,500 tokens for a Roblox
question) also comes after the owner's words. Once the draft is primed and no newer draft waits, `turn_tail` builds
that block for the draft with the functions the turn uses (desktop_core.base_sections / reference_sections) and
primes it too, up to the time line (the only part that changes every minute), then the whole request once with
this minute's time line. On Enter with the same text in the same minute the server reads ~4 tokens; in a later
minute, the time line and the template's closing tokens; so while the owner has not pressed Enter, the whole request
is sent again a moment after each minute change (DraftWarmer keep_fresh). Skipped when the turn would add something
the draft cannot know (web search, attached documents, a Studio connection, a diff-only edit); a mismatch costs a
cache miss, never a different answer.
"""
from __future__ import annotations

import asyncio
import re
import threading
import time
from pathlib import Path
from time import perf_counter

from .brain_router import deep_request, is_roblox_task, select_route
from .desktop_core import (Settings, base_sections, memory_scope_for, model_context_char_budget,
                           needs_project_tools, needs_studio_connection, reference_sections)
from .providers import (connection_for, llama_request_fields, look_for_busy_slots, own_warm_ended,
                        own_warm_started, provider_kind, server_slots)
from . import gpu_helper, server_roles, turn_memory
from .warmup import request_builder

# Tests replace this with an httpx mock transport; None means the real network.
_TRANSPORT = None

# Shorter drafts are not worth a request: the interface waits for this many characters too.
MIN_CHARS = 12
# While another request is generating on that model, only drafts up to this size are sent (about 400 tokens:
# a few seconds of shared CPU on STAR Server, and only when the owner is about to send anyway).
BUSY_MAX_CHARS = 1600
# One draft request adds at most this much new text after what the previous draft primed (about 110 tokens, ~3 s
# of prompt reading on star-fast). The server reads a request to the end of its batch even after a cancel, and
# star-fast's batch is 2048 tokens: an unchunked long paste could hold the server ~55 s before the turn on Enter
# or any other client's request could start. Chunks bound that wait to one chunk.
CHUNK_CHARS = 400
# The time line has minute resolution: once the minute changes, the primed whole request is stale (Enter would read
# ~50 tokens, ~3 s on brain 1). The app sends the whole request again a moment after each minute change while the
# owner has not pressed Enter (at most MAX_REFRESHES of them; each reads ~50 tokens).
MAX_REFRESHES = 10
REFRESH_AFTER_S = 1.0

# The draft text the last request primed, and where: (chat, model, slot) -> text. Only the newest is kept.
_PRIMED: dict = {}


def chunk_ends(draft: str, start: int, size: int = CHUNK_CHARS) -> list[int]:
    """Cut points in `draft` after its first `start` characters (already primed): each at most `size` characters
    after the previous one, moved back to just after a space or line break in the second half of the step when
    there is one. The last cut point is the end of the draft."""
    ends, at = [], max(0, min(start, len(draft)))
    while len(draft) - at > size:
        end = at + size
        space = max(draft.rfind(' ', at + size // 2, end), draft.rfind('\n', at + size // 2, end))
        at = space + 1 if space >= 0 else end
        ends.append(at)
    return ends + [len(draft)]


def _common_length(a: str, b: str) -> int:
    n = min(len(a), len(b))
    return next((i for i in range(n) if a[i] != b[i]), n)


def _text_of(message: dict) -> str:
    content = message.get('content')
    if isinstance(content, str):
        return content
    return ''.join(part.get('text', '') for part in content or () if isinstance(part, dict))


def draft_request(settings: Settings, home: Path, chat_id: str | None, text: str, *, mode: str = 'auto',
                  research: bool = False) -> tuple[dict | None, str]:
    """(the request a turn with `text` would start with, '') or (None, why not).

    The model is the one the router picks for this text (as `desktop_core.run_task` does). A turn that will
    attach tools is warmed only with the tool list this chat last sent to that model (the conversation's tool
    list stays put on STAR Server); with none known nothing is sent, because a plain prompt would replace the
    tool prompt the slot holds.
    """
    wants_deep, text = deep_request(text)
    if wants_deep:
        return None, 'deep'
    build, scope, history = request_builder(settings, home, chat_id)
    recent_users = [_text_of(m) for m in history if m.get('role') == 'user'][-3:]
    project_tools = needs_project_tools(text, recent_users, blender=settings.blender_enabled is True)
    referential = len(text) <= 160 and bool(re.search(
        r'\b(?:it|this|that|same|continue|again|those|these)\b', text, re.I))
    roblox_context = bool(project_tools and referential and any(is_roblox_task(turn) for turn in recent_users))
    route = select_route(server_roles.effective(settings), text, mode=mode, research=research,
                         project_tools=project_tools, roblox_context=roblox_context)
    if not route.use_tools:
        return build(route.model, None, '', text), ''
    endpoint = str(getattr(settings, 'server_endpoint', ''))
    shape = next((known for known in turn_memory.model_shapes(scope)
                  if known.get('tools') and server_roles.same_model(endpoint, route.model, known['model'])), None)
    if shape is None:
        return None, 'tools_unknown'
    return build(shape['model'], shape['tools'], str(shape.get('guidance') or ''), text), ''


def _on_pc(settings: Settings, request: dict):
    """(request, the PC server's address) when the turn would go to the PC now, else (request, None).

    With an address the caller must end with `gpu_helper.HELPER.warm_end()`."""
    if provider_kind(settings) != 'lan' or settings.use_my_gpu is not True:
        return request, None
    if not gpu_helper.wanted(settings, {'model': request['model'], 'messages': request['messages']}):
        return request, None
    base = gpu_helper.HELPER.warm_begin()
    if not base:
        return request, None
    extras = {key: value for key, value in (request.get('extras') or {}).items() if key != 'id_slot'}
    return {**request, 'model': gpu_helper.NAME, 'extras': extras}, base


async def _send_prefix(settings: Settings, request: dict, cancel_event, pc_base: str | None,
                       chat_key: str = '', others_busy=None, primed: str | None = None,
                       whole: bool = False) -> dict:
    """Render `request` with the server's chat template, cut it after the draft, send that text for one token:
    in chunks (`chunk_ends`) from what the previous draft of this chat primed on this model and slot.
    `primed` (default: the whole last message) is the start of the last message to send, when the message
    goes on past what may be primed (`turn_tail`: the time line). `whole`: after the chunks, the whole rendered
    request too, closing tokens included (`turn_tail`: Enter within the same minute then reads ~4 tokens; in a
    later minute the server goes back to the previous chunk's checkpoint, before the time line).

    Stops the moment `cancel_event` is set (the connection is closed; the server keeps what it read), and before
    the next chunk when `await others_busy()` says another client's request is running: a chunk read beside a
    generating slot slows every one of its tokens (brain 1: 1.3 tok/s instead of 8.6), and the turn on Enter
    reads the rest anyway."""
    import httpx
    endpoint, key = (pc_base, '') if pc_base else connection_for(settings)
    endpoint = endpoint.rstrip('/')
    root = endpoint[:-len('/v1')] if endpoint.endswith('/v1') else endpoint
    headers = {'Authorization': f'Bearer {key}'} if key else {}
    extras = dict(request.get('extras') or {})
    template = {'model': request['model'], 'messages': request['messages']}
    if request.get('tools'):
        template['tools'] = request['tools']
    if extras.get('chat_template_kwargs'):
        template['chat_template_kwargs'] = extras.pop('chat_template_kwargs')
    draft = _text_of(request['messages'][-1]) if primed is None else primed
    mark = None if pc_base else own_warm_started(settings, request['model'], extras.get('id_slot'))

    async def call(http) -> dict:
        rendered = await http.post(root + '/apply-template', json=template, headers=headers)
        rendered.raise_for_status()
        prompt = str(rendered.json().get('prompt') or '')
        cut = prompt.rfind(draft)
        if cut < 0:
            return {'skipped': 'template'}
        where = (chat_key, request['model'], extras.get('id_slot'), pc_base)
        before = _PRIMED.get(where, '')
        found: dict = {'primed': True}
        start = _common_length(before, draft)
        ends: list = chunk_ends(draft, start)
        if whole:
            ends = [None] if start == len(draft) else ends + [None]
        for number, end in enumerate(ends):
            if number and others_busy is not None and await others_busy():
                found['yielded'] = True
                break
            reply = await http.post(endpoint + '/completions', headers=headers, json={
                'model': request['model'], 'prompt': prompt if end is None else prompt[:cut + end], 'max_tokens': 1,
                'temperature': 0, **extras})
            reply.raise_for_status()
            if end is not None:
                _PRIMED.clear()
                _PRIMED[where] = draft[:end]
            timings = reply.json().get('timings') or {}
            if type(timings.get('prompt_n')) is int:
                found['prompt_tokens_read'] = found.get('prompt_tokens_read', 0) + timings['prompt_n']
            if number == 0 and type(timings.get('cache_n')) is int:
                found['prompt_tokens_cached'] = timings['cache_n']
        if len(ends) > 1:
            found['chunks'] = len(ends)
        return found

    stopped = False
    try:
        async with httpx.AsyncClient(trust_env=False, transport=_TRANSPORT,
                                     timeout=httpx.Timeout(600.0, connect=10.0)) as http:
            job = asyncio.create_task(call(http))
            try:
                while True:
                    if cancel_event is not None and cancel_event.is_set():
                        return {'primed': False, 'cancelled': True}
                    done, _ = await asyncio.wait({job}, timeout=0.1)
                    if done:
                        return job.result()
            finally:
                stopped = not job.done()
                if stopped:
                    job.cancel()
                    await asyncio.gather(job, return_exceptions=True)
    finally:
        own_warm_ended(mark, cancelled=stopped)


def _recent_users(settings: Settings, home: Path, chat_id: str | None, text: str) -> list[str]:
    """The earlier user messages run_task will see for `text` (its `recent_users`, once the UI has saved it)."""
    from .desktop_core import Conversations
    if not (home / 'conversations.sqlite3').is_file():
        return []
    chats = Conversations(home / 'conversations.sqlite3')
    try:
        rows = chats.raw_history_records(settings.project, chat_id)
    finally:
        chats.close()
    recent = ([(row['role'], row['body']) for row in rows if row['role'] in {'user', 'assistant'}]
              + [('user', text)])[-12:-1]
    return [body for role, body in recent if role == 'user']


def turn_tail(settings: Settings, home: Path, chat_id: str | None, text: str, request: dict, *,
              mode: str = 'auto', research: bool = False) -> tuple[str, int, str]:
    """(the last message the turn will send for `text`, how much of it may be primed, '') or ('', 0, why not).

    Built as run_task builds it: base_sections + reference_sections + star.agent.volatile_context, with the
    tool list `request` carries. What may be primed ends before the time line: it is the last line of the block
    and the only part that changes every minute (its length does not, so the sections are cut the same).
    """
    from datetime import datetime
    from .agent import volatile_context
    from .clock import now_line
    from .context_layout import final_user_text
    from .live_context import wants_fresh_web
    from . import desktop_core, edit_format, lessons as learning
    if research:
        return '', 0, 'research'
    if settings.web_auto_search is not False and wants_fresh_web(text):
        return '', 0, 'web'
    if settings.edit_diff is True and edit_format.find_edit(text) is not None:
        return '', 0, 'edit_diff'
    recent_users = _recent_users(settings, home, chat_id, text)
    project_tools = needs_project_tools(text, recent_users, blender=settings.blender_enabled is True,
                                        github_repositories=settings.mcp_github_repositories is True)
    referential = len(text) <= 160 and bool(re.search(
        r'\b(?:it|this|that|same|continue|again|those|these)\b', text, re.I))
    roblox_context = bool(project_tools and referential and any(is_roblox_task(turn) for turn in recent_users[-3:]))
    route = select_route(server_roles.effective(settings), text, mode=mode, research=research,
                         project_tools=project_tools, roblox_context=roblox_context, home=home)
    if route.use_tools != bool(request.get('tools')) or not server_roles.same_model(
            str(getattr(settings, 'server_endpoint', '')), route.model, request['model']):
        return '', 0, 'route'
    if (route.use_tools and settings.studio_id
            and needs_studio_connection(text, recent_users, blender=settings.blender_enabled is True)):
        return '', 0, 'studio'
    if (home / 'documents.sqlite3').is_file():
        from .documents import DocumentStore
        if DocumentStore(home, settings.project, chat_id).context(
                text, budget_chars=min(6000, settings.context_chars // 3)):
            return '', 0, 'documents'
    knowledge = lesson_store = None
    if (home / 'knowledge').is_dir():
        from .knowledge import KnowledgeStore
        knowledge = KnowledgeStore(home / 'knowledge')
        lesson_store = learning.LessonStore(knowledge=knowledge)
    try:
        sections, _ = base_sections(settings.project, text, route.quick, knowledge, lesson_store)
    finally:
        if knowledge is not None:
            knowledge.close()
    allowed = model_context_char_budget(settings, route.model)

    async def references():
        async with desktop_core.open_client(settings) as client:   # the turn's client (run_task)
            if provider_kind(settings) == 'lan' and settings.use_my_gpu is True:
                client = gpu_helper.GpuRoutingClient(client, settings)
            return await reference_sections(
                settings, home, route, text, recent_users, sections, mode=mode, quick=route.quick,
                memory_limit=max(700, allowed - 3200), allowed_context_chars=allowed, document_block='',
                client=client, event=lambda _event: None)
    _docs, limit = asyncio.run(references())
    now = now_line()
    block = volatile_context(learning.guard_sections(sections), tools_attached=bool(request.get('tools')),
                             mode=mode, limit=limit, today=datetime.now().astimezone().strftime('%Y-%m-%d'),
                             now=now)
    at = block.rfind(now)
    if at < 0:
        return '', 0, 'no_time_line'
    return final_user_text(text, block), len(text) + 2 + at, ''


def _next_minute(cancel_event, superseded) -> bool:
    """Wait until the minute changes (plus REFRESH_AFTER_S). False when the draft was cancelled or replaced meanwhile."""
    until = (time.time() // 60 + 1) * 60 + REFRESH_AFTER_S
    while time.time() < until:
        if (cancel_event is not None and cancel_event.is_set()) or (superseded is not None and superseded()):
            return False
        time.sleep(0.2)
    return True


def warm_draft(settings: Settings, home: Path, chat_id: str | None, text: str, *, mode: str = 'auto',
               research: bool = False, cancel_event=None, probe=look_for_busy_slots, superseded=None,
               keep_fresh: bool = False) -> dict:
    """Send the draft's start to the model server. Never raises; returns a small nonsecret report.

    `keep_fresh`: after the whole request is primed, stay (until cancelled, replaced or MAX_REFRESHES minutes) and
    send it again with the new time line whenever the minute changes. The call then returns only at that point."""
    began = perf_counter()

    def done(**fields) -> dict:
        return {'primed': False, **fields, 'ms': int((perf_counter() - began) * 1000)}
    try:
        settings.validate()
        kind = provider_kind(settings)
    except Exception:
        return done(skipped='settings')
    if settings.prefill_while_typing is not True:
        return done(skipped='off')
    if kind == 'cloud':
        return done(skipped='cloud')
    if not settings.model.strip() or len(text.strip()) < MIN_CHARS:
        return done(skipped='short' if settings.model.strip() else 'no_model')
    try:
        request, why = draft_request(settings, home, chat_id, text, mode=mode, research=research)
    except Exception as exc:
        return done(skipped='no_request', error=type(exc).__name__)
    if request is None:
        return done(skipped=why)
    request, pc_base = _on_pc(settings, request)
    try:
        busy_note: dict = {}
        if pc_base is None and kind == 'lan':
            # Budget: while the server answers someone else (night school, another client, a helper), only a short
            # draft goes, and never into a busy slot. Asked like the turn asks (`look_for_busy_slots`), so a chat
            # whose slot is busy moves to the idle one now, and the turn finds its draft there.
            scope = memory_scope_for(settings, chat_id)
            try:
                busy = asyncio.run(probe(settings, request['model'], conversation=scope))
            except Exception:
                busy = frozenset()
            if busy:
                slots = server_slots(settings, request['model'])
                if (slots and len(busy) >= slots) or len(text) > BUSY_MAX_CHARS:
                    return done(skipped='server_busy', model=str(request['model'])[:180])
                # The slot choice of a turn (it reads the answer above): a chat whose slot is busy moves to an idle
                # one and stays there, so the turn on Enter goes where this draft went.
                llama_request_fields(settings, conversation=scope, model=request['model'],
                                     tools=bool(request.get('tools')))
                request, _ = draft_request(settings, home, chat_id, text, mode=mode, research=research)
                if request is None:
                    return done(skipped='no_request')
                busy_note = {'server_busy': True}
        if cancel_event is not None and cancel_event.is_set():
            return done(cancelled=True)
        if pc_base is None and kind == 'lan':
            # Saved project memory (opt-in): an empty slot (model restarted) gets the banked start back first.
            from . import cache_banks
            if cache_banks.enabled():
                mark = own_warm_started(settings, request['model'], (request.get('extras') or {}).get('id_slot'))
                try:
                    busy_note['cache_bank'] = asyncio.run(cache_banks.prepare(settings, home, request,
                                                                              cancel_event=cancel_event))
                except Exception:
                    busy_note['cache_bank'] = {'bank': 'skipped', 'reason': 'unavailable'}
                finally:
                    own_warm_ended(mark, cancelled=cancel_event is not None and cancel_event.is_set())
        try:
            others_busy = None
            if pc_base is None and kind == 'lan':
                scope = memory_scope_for(settings, chat_id)

                async def probe_others() -> bool:
                    # This app's own draft is marked (own_warm_started), so a busy slot here is another client's.
                    try:
                        return bool(await probe(settings, request['model'], conversation=scope))
                    except Exception:
                        return False
                others_busy = probe_others
            result = asyncio.run(_send_prefix(settings, request, cancel_event, pc_base, str(chat_id or ''),
                                              others_busy))
        except Exception as exc:
            return done(error=type(exc).__name__)
        if (result.get('primed') and not result.get('yielded')
                and not (cancel_event is not None and cancel_event.is_set())
                and not (superseded is not None and superseded())):
            # The draft is in and no newer one waits: prime this turn's reference block after it (`turn_tail`).
            try:
                message, length, why = turn_tail(settings, home, chat_id, text, request, mode=mode,
                                                 research=research)
                if message and not (cancel_event is not None and cancel_event.is_set()):
                    def with_message(body: str) -> dict:
                        return {**request, 'messages': [*request['messages'][:-1], {
                            **request['messages'][-1], 'content': [{'type': 'text', 'text': body}]}]}

                    async def stop_between_chunks() -> bool:
                        # The owner typed on (a newer draft waits) or another client is generating.
                        return bool((superseded is not None and superseded())
                                    or (others_busy is not None and await others_busy()))
                    more = asyncio.run(_send_prefix(settings, with_message(message), cancel_event, pc_base,
                                                    str(chat_id or ''), stop_between_chunks, primed=message[:length]))
                    if more.get('primed') and not more.get('yielded') and not more.get('cancelled'):
                        # Then the whole request with the time line of NOW (reading the block took a while).
                        from .clock import now_line
                        old = message[length:].split('\n', 1)[0]
                        message = message[:length] + now_line() + message[length + len(old):]
                        last = asyncio.run(_send_prefix(settings, with_message(message), cancel_event, pc_base,
                                                        str(chat_id or ''), stop_between_chunks,
                                                        primed=message[:length], whole=True))
                        more['whole'] = bool(last.get('primed') and not last.get('cancelled'))
                        refreshed = 0
                        while keep_fresh and more['whole'] and refreshed < MAX_REFRESHES and _next_minute(
                                cancel_event, superseded):
                            if others_busy is not None and asyncio.run(others_busy()):
                                break
                            old = message[length:].split('\n', 1)[0]
                            message = message[:length] + now_line() + message[length + len(old):]
                            last = asyncio.run(_send_prefix(settings, with_message(message), cancel_event, pc_base,
                                                            str(chat_id or ''), stop_between_chunks,
                                                            primed=message[:length], whole=True))
                            if not last.get('primed') or last.get('cancelled'):
                                break
                            refreshed += 1
                        if refreshed:
                            more['refreshed'] = refreshed
                    result['tail'] = {key: more[key] for key in ('primed', 'yielded', 'cancelled', 'skipped',
                                                                 'prompt_tokens_read', 'chunks', 'whole', 'refreshed')
                                      if key in more}
                else:
                    result['tail'] = {'skipped': why or 'cancelled'}
            except Exception as exc:
                result['tail'] = {'error': type(exc).__name__}
        return done(**result, model=str(request['model'])[:180], on_pc=pc_base is not None,
                    with_tools=bool(request.get('tools')), **busy_note)
    finally:
        if pc_base:
            gpu_helper.HELPER.warm_end()


class DraftWarmer:
    """At most one draft warm-up at a time, on one daemon thread.

    `submit` while one is running keeps only the newest draft; it is sent when the running one ends (the
    server then reads only what was typed since). `cancel()` drops the pending draft and stops the running
    request within a tenth of a second (the server keeps what it already read).
    """

    def __init__(self, run=warm_draft, keep_fresh: bool = False):
        self._run = run
        self._keep_fresh = keep_fresh
        self._lock = threading.Lock()
        self._pending = None
        self._cancel = threading.Event()
        self.thread: threading.Thread | None = None
        self.last: dict = {}

    def cancel(self) -> None:
        with self._lock:
            self._pending = None
            self._cancel.set()

    def submit(self, load, text: str, *, mode: str = 'auto', research: bool = False) -> None:
        """`load()` returns (settings, home, chat_id) and runs on the worker thread, never on the UI thread."""
        with self._lock:
            self._pending = (load, text, mode, research)
            if self._cancel.is_set():
                self._cancel = threading.Event()   # the cancelled request keeps the old one
            if self.thread is not None and self.thread.is_alive():
                return
            self.thread = threading.Thread(target=self._work, name='star-draft-warm', daemon=True)
            self.thread.start()

    def _work(self) -> None:
        while True:
            with self._lock:
                job, self._pending = self._pending, None
                cancel = self._cancel
                if job is None or cancel.is_set():
                    self.thread = None
                    return
            load, text, mode, research = job
            try:
                settings, home, chat_id = load()
                self.last = self._run(settings, home, chat_id, text, mode=mode, research=research,
                                      cancel_event=cancel, superseded=lambda: self._pending is not None,
                                      **({'keep_fresh': True} if self._keep_fresh else {}))
            except Exception as exc:
                self.last = {'primed': False, 'error': type(exc).__name__}
