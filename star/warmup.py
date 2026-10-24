"""Check the selected model server and prime its prompt cache, in the background.

A CPU model server reads a new prompt slowly, so the first message after STAR
starts used to pay for the whole static start of the request (the rules, the
project memory and the earlier turns of the open chat). `warm_up` sends that
exact start once, asking for a single token, so the server already holds it
when the owner presses Send.

It is deliberately harmless:

  * own hardware only: it returns at once for a cloud provider, without any
    network call, so it can never spend a hosted provider's quota;
  * it reads the conversation and checkpoint databases and writes nothing: no
    message, no run record, no analytics row, so it is never a user turn;
  * it is cancellable at any moment through `cancel_event` (the app sets it
    as soon as a real request starts) and never raises;
  * for STAR Server it first runs the cheap reachability/key/model check, so
    the status light is truthful before the first message.
"""
from __future__ import annotations
import asyncio
import sqlite3
import threading
from pathlib import Path
from time import perf_counter

from .agent import make_system_message
from .brain_router import select_route
from .context_layout import assemble
from .desktop_core import (Settings, app_data, chat_history, memory_scope_for, stable_memory)
from .model_health import note_server_result, probe_server
from .providers import (llama_request_fields, look_for_busy_slots, open_client, own_warm_ended, own_warm_started,
                        provider_kind)
from . import server_roles, turn_memory
from .conversation_memory import compose_memory, read_checkpoint

# The priming turn. It is the last message of the request, so nothing after the
# cached start depends on it; the single generated token is thrown away.
PRIME_TEXT = "."
# A Fast-mode message that goes to the main model on a server with a fleet (and to
# the one configured model everywhere else). Only used to ask the router which model.
MAIN_MODEL_PROBE = "How do I write a Luau script in Roblox?"


def _checkpoint(home: Path, scope: str) -> str:
    """Read the compacted checkpoint without creating or changing the database."""
    file = home / 'checkpoints.sqlite3'
    if not file.is_file():
        return ''
    try:
        connection = sqlite3.connect(f'{file.as_uri()}?mode=ro', uri=True)
        try:
            row = connection.execute('SELECT summary FROM checkpoints WHERE project=?', (scope,)).fetchone()
        finally:
            connection.close()
    except sqlite3.Error:
        return ''
    return row[0] if row and isinstance(row[0], str) else ''


def request_builder(settings: Settings, home: Path, chat_id: str | None):
    """`(build, scope, history)`: `build(model, tools, guidance, text=PRIME_TEXT)` makes one request
    with the conversation's real start (system message, memory, earlier turns) and `text` as the
    last user message, on the conversation's slot of `model`."""
    history = chat_history(settings, home, chat_id)[0] if (home / 'conversations.sqlite3').is_file() else []
    scope = memory_scope_for(settings, chat_id)
    memory = compose_memory(stable_memory(settings, _checkpoint(home, scope)),
                            read_checkpoint(home / 'conversations.sqlite3', settings.project, chat_id))

    def build(model: str, tools, guidance: str, text: str = PRIME_TEXT) -> dict:
        system = make_system_message(memory, tools_attached=bool(tools), guidance=guidance if tools else '')
        messages, _ = assemble(system, history, {'role': 'user', 'content': [{'type': 'text', 'text': text}]})
        return {'model': model, 'messages': messages, 'tools': list(tools) if tools else None,
                'extras': llama_request_fields(settings, conversation=scope, tools=bool(tools), model=model,
                                               prime=True)}

    return build, scope, history


def prefix_requests(settings: Settings, home: Path, chat_id: str | None) -> list[dict]:
    """The requests whose start equals the start of the next message, most likely first.

    Built with the same functions a real turn uses (`make_system_message`,
    `chat_history`, `llama_request_fields`), so the bytes match by construction.

    1. The shape of this chat's last request in this process (its model and, after
       a tool-using turn, the very tool list it sent): the next message most
       likely has the same shape. After an Agent turn this is the tool prompt, so
       the warm-up extends that cached prompt instead of replacing it. Before the
       first turn (app start) this is plain chat on the quick model.
    2. Each other chat model of the server (the quick model, and the main model
       that answers Roblox and coding questions), when the chat has earlier turns
       to read: with the shape this chat last sent to that model (so a tool
       prompt it holds is extended, not replaced), else plain chat. Each model
       keeps its own copy of the conversation, so without this the first
       question that goes to the other model reads the whole window (measured:
       37 s on the main model for a full window).

    Never two requests for the same model: its slot holds one prompt, and a
    second request would replace the first. So on a single-model server there is
    one request, and after a tool turn it is the tool prompt, not plain chat.
    """
    build, scope, history = request_builder(settings, home, chat_id)
    routed = server_roles.effective(settings)
    quick = select_route(routed, 'hello', mode='fast').model
    main = select_route(routed, MAIN_MODEL_PROBE, mode='fast').model
    # Do not reuse a previous request shape when this profile/chat has no
    # persisted history. This also prevents an in-process profile switch (and
    # test profiles) from priming unrelated tool prompts under the same scope.
    shape = turn_memory.last_shape(scope) if history else None
    if shape and shape.get('model'):
        targets = [build(shape['model'], shape.get('tools'), str(shape.get('guidance') or ''))]
    else:
        targets = [build(quick, None, '')]
    endpoint = str(getattr(settings, 'server_endpoint', ''))
    sent = turn_memory.model_shapes(scope)
    for model in (quick, main):
        if not history or any(server_roles.same_model(endpoint, model, target['model']) for target in targets):
            continue
        last = next((known for known in sent if server_roles.same_model(endpoint, model, known['model'])), None)
        targets.append(build(last['model'], last.get('tools'), str(last.get('guidance') or '')) if last
                       else build(model, None, ''))
    return targets


def prefix_request(settings: Settings, home: Path, chat_id: str | None) -> dict:
    """The first (most likely) of `prefix_requests`."""
    return prefix_requests(settings, home, chat_id)[0]


async def _prime(settings: Settings, request: dict, cancel_event, timeout: float | None) -> dict:
    """Send the one-token request; stop the moment `cancel_event` is set."""
    async with open_client(settings, request_timeout=timeout) as client:
        # After a tool-using turn the request starts with the same tool list that turn sent.
        tools = {'tools': request['tools'], 'tool_choice': 'auto'} if request.get('tools') else {}

        async def send(extras):
            stream = await client.chat.completions.create(
                model=request['model'], messages=request['messages'], max_tokens=1, temperature=0,
                stream=True, **tools, **({'extra_body': extras} if extras else {}))
            timings = None
            if hasattr(stream, '__aiter__'):
                async for chunk in stream:
                    timings = getattr(chunk, 'timings', None) or timings
            return timings

        async def call():
            try:
                return await send(request['extras'])
            except Exception as exc:
                # A server that is not llama.cpp may refuse the cache fields.
                if not request['extras'] or getattr(exc, 'status_code', None) not in (400, 422):
                    raise
                return await send(None)

        # On STAR Server the slot is marked as this app's own, so the turn does not take it for another client.
        mark = own_warm_started(settings, request['model'], (request.get('extras') or {}).get('id_slot'))
        job = asyncio.create_task(call())
        try:
            while True:
                if cancel_event is not None and cancel_event.is_set():
                    return {'primed': False, 'cancelled': True}
                done, _ = await asyncio.wait({job}, timeout=0.1)
                if done:
                    timings = job.result()
                    found = {'primed': True}
                    if isinstance(timings, dict):
                        for key, name in (('prompt_n', 'prompt_tokens_read'), ('cache_n', 'prompt_tokens_cached')):
                            if type(timings.get(key)) is int:
                                found[name] = timings[key]
                    return found
        finally:
            stopped = not job.done()
            if stopped:
                job.cancel()   # closes the HTTP stream; the server stops after the batch it is reading
                await asyncio.gather(job, return_exceptions=True)
            own_warm_ended(mark, cancelled=stopped)


async def _slot_busy(settings: Settings, request: dict, probe) -> bool:
    """Issue 118: is the slot this warm-up names generating for another client right now?

    Such a warm-up would wait for that whole answer and then push it out of the slot, and on a llama.cpp
    server before b11583 it is worse: the server loads the warm-up's cached prompt into the busy slot and
    the other client's answer goes on with the wrong context (unrelated text, or it stops mid-script)."""
    slot = (request.get('extras') or {}).get('id_slot')
    if type(slot) is not int:
        return False
    try:
        return slot in await probe(settings, request['model'], conversation='warm-up-busy-check')
    except Exception:
        return False


def warm_up(settings: Settings, *, home: Path | None = None, chat_id: str | None = None,
            cancel_event=None, on_checked=None, check: bool = True, transport=None,
            probe=look_for_busy_slots) -> dict:
    """Check the server (STAR Server only) and prime the cache. Never raises.

    Returns a small nonsecret report: `skipped` (why nothing was done), or
    `ok`/`code` from the check and `primed` plus the token counts the server
    reported. `on_checked(report)` is called as soon as the check is finished,
    before the slower priming request, so the interface can show the result.
    """
    began = perf_counter()
    def done(**fields) -> dict:
        return {'primed': False, **fields, 'ms': int((perf_counter() - began) * 1000)}
    try:
        settings.validate()
        kind = provider_kind(settings)
    except Exception:
        return done(skipped='settings')
    if kind == 'cloud':
        return done(skipped='cloud')
    if not settings.model.strip():
        return done(skipped='no_model')
    cancelled = lambda: cancel_event is not None and cancel_event.is_set()
    report = None
    if kind == 'lan':
        if check:
            try:
                report = probe_server(settings, transport=transport, chat=False)
            except Exception:
                return done(skipped='check_failed')
            if on_checked is not None:
                try:
                    on_checked(report)
                except Exception:
                    pass
            if not report.get('ok'):
                return done(ok=False, code=str(report.get('code', '')))
    if cancelled():
        return done(cancelled=True, **({'ok': True, 'code': 'ok'} if report else {}))
    checked = {'ok': True, 'code': 'ok'} if report else {}
    try:
        requests = prefix_requests(settings, home or app_data(), chat_id)
        request = requests[0]
    except Exception as exc:
        # Nothing was sent: a chat database or setting that cannot be read is a
        # local problem and says nothing about the server.
        return done(skipped='no_request', error=type(exc).__name__, **checked)
    if kind == 'lan' and asyncio.run(_slot_busy(settings, request, probe)):
        return done(skipped='slot_busy', **checked)
    # The optional bank is purely an accelerator for this same chat's already
    # authorized prompt. The ordinary prompt remains authoritative if restore
    # fails, and the model never receives an extra bank tool or instruction.
    bank = None
    bank_home = home or app_data()
    if kind == 'lan':
        from . import cache_banks
        if cache_banks.enabled():
            bank = cache_banks.plan(settings, request, scope=memory_scope_for(settings, chat_id))
            if bank is not None and not cancelled():
                try:
                    bank_restore = asyncio.run(cache_banks.restore(
                        settings, bank_home, bank, cancel_event=cancel_event))
                except Exception:
                    bank_restore = {'performed': False, 'reason': 'unavailable'}
            else:
                bank_restore = None
        else:
            bank_restore = None
    else:
        bank_restore = None
    try:
        result = asyncio.run(_prime(settings, request, cancel_event, None))
    except Exception as exc:
        status = getattr(exc, 'status_code', None)
        if kind == 'lan' and (status is None or status in (401, 403, 503)):
            # Unreachable, timed out, wrong key or loading: the light must not say "ready".
            note_server_result(settings, False, 'request_failed')
        return done(error=type(exc).__name__, **({'ok': False, 'code': 'request_failed'} if kind == 'lan' else {}))
    if report:
        result.update(ok=True, code='ok')
    # Save only a successful, completed, uncancelled priming request. A failed
    # /slots feature never delays or changes the ordinary model conversation.
    if bank is not None and result.get('primed') and not cancelled():
        try:
            bank_save = asyncio.run(cache_banks.save(
                settings, bank_home, bank, cancel_event=cancel_event))
        except Exception:
            bank_save = {'performed': False, 'reason': 'unavailable'}
        result['cache_bank'] = {
            'restored': bool(bank_restore and bank_restore.get('performed')),
            'saved': bool(bank_save.get('performed')),
            'restore_reason': str((bank_restore or {}).get('reason', ''))[:50],
            'save_reason': str(bank_save.get('reason', ''))[:50],
        }
    result['history_messages'] = len(request['messages']) - 2
    result['model'] = str(request['model'])[:180]
    result['with_tools'] = bool(request.get('tools'))
    # The quick model too, when the first request was for another model. Best effort:
    # a failure here says nothing about the server the owner is using.
    also = 0
    for extra in requests[1:]:
        if cancelled() or not result.get('primed'):
            break
        if kind == 'lan' and asyncio.run(_slot_busy(settings, extra, probe)):
            continue
        try:
            also += bool(asyncio.run(_prime(settings, extra, cancel_event, None)).get('primed'))
        except Exception:
            break
    if also:
        result['also_primed'] = also
    return done(**result)


class Warmer:
    """Runs at most one warm-up at a time, each on a daemon thread of its own.

    Starting a new one cancels the one before it. `cancel()` returns at once;
    the running request is dropped within a tenth of a second.
    """

    def __init__(self, run=warm_up):
        self._run = run
        self._lock = threading.Lock()
        self._cancel = threading.Event()
        self.thread: threading.Thread | None = None

    def cancel(self) -> None:
        with self._lock:
            self._cancel.set()

    def start(self, load, *, check: bool = True, on_checked=None, on_done=None) -> threading.Thread:
        """`load()` returns (settings, home, chat_id). It runs on the new thread, so
        the caller (the UI thread) never touches a file or the network."""
        with self._lock:
            self._cancel.set()
            cancel = self._cancel = threading.Event()

        def task():
            report = {'primed': False, 'skipped': 'error'}
            try:
                settings, home, chat_id = load()
                report = self._run(settings, home=home, chat_id=chat_id, cancel_event=cancel,
                                   on_checked=on_checked, check=check)
            except Exception:
                pass
            finally:
                if on_done is not None:
                    try:
                        on_done(report)
                    except Exception:
                        pass

        thread = threading.Thread(target=task, name='star-warm-up', daemon=True)
        self.thread = thread
        thread.start()
        return thread
