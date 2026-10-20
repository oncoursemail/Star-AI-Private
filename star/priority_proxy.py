"""STAR priority proxy: owner requests first, background work paused and resumed, never lost.

A small HTTP proxy in front of the llama.cpp router (stdlib only, one thread per request). Every STAR client can go
through it. The class says how urgent the client is:

    P0  owner chat, voice, Discord      P1  tasks the owner assigned
    P2  conductor, agents, game work    P3  night school, evals, indexing, Studio Lab, playtest learning

A client gets its class from the port it uses (the main port has `default_class`; `class_ports` adds e.g. 8083 =
P3, so http://<brain>:8083/v1 is a valid STAR server URL for a background client), from a URL prefix /p0../p3, or
from the header `X-Star-Priority: P0..P3` (strongest last). Only chat and text completions on the models named in
the config are scheduled (not requests asking for logprobs); everything else (embeddings, /slots, /v1/models, other
models) is passed through unchanged.

Rules, per model (a model has `slots` parallel slots in llama.cpp):
  * A request starts when its model has a free slot. Background (P2/P3) also needs the model's `bg_cap` room.
  * A P0/P1 request that finds every slot taken pauses the lowest-priority running request (P3 before P2, the
    newest first). With `solo_p0` (default on) any P0 request pauses ALL running background requests on every
    scheduled model while it runs, plus `grace_s` after it, so the owner's answer gets the whole CPU (brain 1 is
    CPU-bound: three streams share the same memory bandwidth).
  * Pausing = closing the upstream connection; llama.cpp stops that generation at the next token and frees the slot
    (the KV cache of the slot, or the server's RAM prompt cache, keeps the prompt and the text so far).
  * Resuming = the same request again with the text so far as the start of the answer (chat:
    `continue_final_message`; completions: prompt + text), `max_tokens` reduced by the tokens already made. The
    prompt cache turns the re-sent prefix into a cache hit, so only a few tokens are read again. The client sees a
    pause, then the rest of the same answer: nothing lost, nothing twice.
  * The proxy always streams from upstream (so it holds the partial text) and gives a non-streaming client the one
    JSON answer it asked for.
  * Cases that cannot be continued exactly (tool-call output, grammar / JSON-schema output, n > 1, a prompt that is
    not plain text): a non-streaming one starts over (nothing was sent to the client yet, counted as a restart); a
    streaming one is not paused once it has sent such output.

Status and metrics: GET /priority/v1/status (free from loopback, key elsewhere): per class requests, queue wait,
first token, preemptions, resumes, tokens read again on resume, paused seconds; per model running/queued requests;
`p0_active` (used by star/cpu_priority.py to pause CPU jobs). One JSON line per finished request goes to --log.

Run: python -m star.priority_proxy --config /opt/star/config/priority.json   (see server/priority/).
"""
from __future__ import annotations

import argparse
from dataclasses import dataclass, field
import hmac
import http.client
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import itertools
import json
import os
from pathlib import Path
import select
import socket
import threading
import time
from typing import Any, Callable
import urllib.parse

CLASS_NAMES = ("P0", "P1", "P2", "P3")
SCHEDULED_PATHS = {"/v1/chat/completions": "chat", "/chat/completions": "chat",
                   "/v1/completions": "text", "/completions": "text"}
HOP_HEADERS = {"connection", "keep-alive", "proxy-authenticate", "proxy-authorization", "te", "trailer",
               "transfer-encoding", "upgrade", "host", "content-length", "x-star-priority"}
LIMIT_FIELDS = ("max_tokens", "max_completion_tokens", "n_predict")
CONSTRAINED_FIELDS = ("grammar", "json_schema", "response_format")


# --- configuration --------------------------------------------------------------------------------------------------

@dataclass
class ModelPolicy:
    name: str
    slots: int = 2                    # fallback when the upstream does not say (detected from /props at first use)
    bg_cap: int = 0                   # background requests at once on this model; 0 = as many as there are slots
    aliases: tuple[str, ...] = ()
    detect: bool = True

    def cap(self) -> int:
        return self.slots if self.bg_cap <= 0 else min(self.bg_cap, self.slots)


@dataclass
class Config:
    upstream: str = "http://127.0.0.1:8080"
    host: str = "0.0.0.0"
    port: int = 8097
    key_file: str = ""
    default_class: int = 2
    solo_p0: bool = True
    grace_s: float = 2.0
    solo_keep: int = 0                # background generations that keep running while a P0 runs (the oldest P2 first)
    solo_max_s: float = 120.0         # a P0 running longer than this no longer holds background off (a stuck request
                                      # must not starve background work: seen live 2026-10-20, a P0 stuck 10 min)
    assign_slots: bool = True         # pin each request to a slot that is free (keeps a paused answer's slot)
    class_ports: dict[int, int] = field(default_factory=dict)   # extra listen port -> default class on it
    log: str = ""
    models: dict[str, ModelPolicy] = field(default_factory=lambda: {
        "star-fast": ModelPolicy("star-fast", 2, 0, ("star-code", "star-vision")),
        "star-voice": ModelPolicy("star-voice", 2, 0, ("star-quick",))})

    @classmethod
    def load(cls, path: str) -> "Config":
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        cfg = cls()
        for key in ("upstream", "host", "key_file", "log"):
            if key in data:
                setattr(cfg, key, str(data[key]))
        for key in ("port",):
            if key in data:
                setattr(cfg, key, int(data[key]))
        if "default_class" in data:
            cfg.default_class = parse_class(str(data["default_class"]), 2)
        if "solo_p0" in data:
            cfg.solo_p0 = bool(data["solo_p0"])
        if "grace_s" in data:
            cfg.grace_s = float(data["grace_s"])
        if "solo_keep" in data:
            cfg.solo_keep = max(0, int(data["solo_keep"]))
        if "solo_max_s" in data:
            cfg.solo_max_s = float(data["solo_max_s"])
        if "assign_slots" in data:
            cfg.assign_slots = bool(data["assign_slots"])
        if "class_ports" in data:
            cfg.class_ports = {int(port): parse_class(str(cls), cfg.default_class)
                               for port, cls in data["class_ports"].items()}
        if "models" in data:
            cfg.models = {}
            for name, row in data["models"].items():
                cfg.models[name] = ModelPolicy(name, int(row.get("slots", 2)), int(row.get("bg_cap", 0)),
                                               tuple(row.get("aliases", ())), bool(row.get("detect", True)))
        return cfg

    def canonical(self, model: str) -> str:
        for policy in self.models.values():
            if model == policy.name or model in policy.aliases:
                return policy.name
        return ""


def parse_class(text: str, default: int) -> int:
    text = (text or "").strip().upper()
    if text.startswith("P"):
        text = text[1:]
    return int(text) if text in ("0", "1", "2", "3") else default


def read_keys(path: str) -> list[str]:
    try:
        return [line.strip() for line in Path(path).read_text(encoding="utf-8").splitlines()
                if line.strip() and not line.strip().startswith("#")]
    except OSError:
        return []


# --- scheduler ------------------------------------------------------------------------------------------------------

class Gone(Exception):
    """The client went away while its request waited."""


@dataclass(eq=False)
class Job:
    cls: int
    model: str
    seq: int
    state: str = "new"                # new | queued | running | pausing | paused | done
    preemptible: bool = True
    cancel: Callable[[], None] | None = None
    queued_at: float = 0.0
    paused_at: float = 0.0
    pauses: int = 0
    slot: int | None = None           # the llama.cpp slot it was sent to (kept while paused, for its resume)
    started_at: float = 0.0           # when it last started running


@dataclass
class ClassStats:
    requests: int = 0
    admitted: int = 0
    wait_sum_s: float = 0.0
    wait_max_s: float = 0.0
    first_token: list[float] = field(default_factory=list)
    preemptions: int = 0
    resumes: int = 0
    restarts: int = 0
    paused_s: float = 0.0
    resume_prompt_tokens: int = 0     # tokens llama.cpp read again for resumed segments (timings.prompt_n)
    resume_cached_tokens: int = 0     # tokens it took from the cache for them (timings.cache_n)
    tokens_out: int = 0
    errors: int = 0

    def view(self) -> dict:
        ft = sorted(self.first_token)
        pick = (lambda q: round(ft[min(len(ft) - 1, int(q * len(ft)))], 3)) if ft else (lambda q: None)
        return {"requests": self.requests, "wait_avg_s": round(self.wait_sum_s / self.admitted, 3) if self.admitted
                else None, "wait_max_s": round(self.wait_max_s, 3), "first_token_p50_s": pick(0.5),
                "first_token_p95_s": pick(0.95), "first_token_max_s": ft[-1] if ft else None,
                "preemptions": self.preemptions, "resumes": self.resumes, "restarts": self.restarts,
                "paused_s": round(self.paused_s, 2), "resume_prompt_tokens": self.resume_prompt_tokens,
                "resume_cached_tokens": self.resume_cached_tokens, "tokens_out": self.tokens_out,
                "errors": self.errors}


class Scheduler:
    """Admission and preemption. All state behind one condition variable; `cancel` callbacks never block."""

    def __init__(self, cfg: Config, *, clock: Callable[[], float] = time.monotonic):
        self.cfg, self._clock = cfg, clock
        self._cv = threading.Condition()
        self._seq = itertools.count()
        self._queued: list[Job] = []
        self._running: dict[str, list[Job]] = {name: [] for name in cfg.models}
        self._paused: dict[str, list[Job]] = {name: [] for name in cfg.models}
        self._last_p0_end = -1e18
        self.stats = [ClassStats() for _ in CLASS_NAMES]

    # the public calls ------------------------------------------------------------------------------------------------
    def new_job(self, cls: int, model: str) -> Job:
        with self._cv:
            self.stats[cls].requests += 1
            return Job(cls, model, next(self._seq))

    def acquire(self, job: Job, gone: Callable[[], bool] = lambda: False, poll_s: float = 0.25) -> float:
        """Block until `job` may run. Returns the seconds waited. Raises Gone when `gone()` turns true first."""
        with self._cv:
            start = self._clock()
            job.state, job.queued_at = "queued", start
            self._queued.append(job)
            self._schedule()
            while job.state == "queued":
                if gone():
                    self._queued.remove(job)
                    job.state = "done"
                    self._schedule()
                    raise Gone()
                self._cv.wait(poll_s)
                self._schedule()            # a grace period may have ended
            waited = self._clock() - start
            st = self.stats[job.cls]
            st.admitted += 1
            st.wait_sum_s += waited
            st.wait_max_s = max(st.wait_max_s, waited)
            if job.paused_at:
                st.paused_s += self._clock() - job.paused_at
                job.paused_at = 0.0
            return waited

    def attach(self, job: Job, cancel: Callable[[], None]) -> bool:
        """Register how to stop the job's upstream request. False when a pause was already asked for."""
        with self._cv:
            job.cancel = cancel
            return job.state == "running"

    def set_preemptible(self, job: Job, value: bool) -> bool:
        """False when the job is already being paused (the caller then must not emit what it holds)."""
        with self._cv:
            if job.state != "running":
                return False
            job.preemptible = value
            return True

    def pausing(self, job: Job) -> bool:
        with self._cv:
            return job.state == "pausing"

    def paused(self, job: Job) -> None:
        """The job's upstream request ended because of a pause: free its slot; it will acquire() again."""
        with self._cv:
            self._drop(job)
            job.state, job.paused_at, job.cancel = "paused", self._clock(), None
            self._paused[job.model].append(job)
            self._schedule()

    def release(self, job: Job) -> None:
        with self._cv:
            if job.state in ("queued",):
                self._queued.remove(job)
            self._drop(job)
            if job.cls == 0:
                self._last_p0_end = self._clock()
            job.state, job.cancel, job.slot = "done", None, None
            self._schedule()

    def note(self, cls: int, **values: float) -> None:
        with self._cv:
            st = self.stats[cls]
            for key, value in values.items():
                if key == "first_token":
                    st.first_token.append(float(value))
                    del st.first_token[:-500]
                else:
                    setattr(st, key, getattr(st, key) + value)

    def set_slots(self, model: str, slots: int) -> None:
        with self._cv:
            if slots >= 1 and self.cfg.models[model].slots != slots:
                self.cfg.models[model].slots = slots
                self._schedule()

    def take_slot(self, job: Job, busy: set[int], wanted: object = None) -> int | None:
        """The llama.cpp slot for the job's next upstream request, or None (let the server place it). Never a slot a
        running request of ours holds or that the server reports busy (another client). Order: the job's own slot
        from before its pause, the client's id_slot, then a slot no paused answer is waiting for (owner requests take
        the highest number, background the lowest), then any free slot."""
        with self._cv:
            n = self.cfg.models[job.model].slots
            held = {j.slot for j in self._running[job.model] if j is not job and j.slot is not None}
            free = [s for s in range(n) if s not in held and s not in busy]
            if not free:
                job.slot = None
                return None
            kept = {j.slot for j in self._paused[job.model] if j is not job and j.slot is not None}
            spare = [s for s in free if s not in kept] or free
            if job.slot in free:
                pick = job.slot
            elif type(wanted) is int and wanted in spare:
                pick = wanted
            else:
                pick = max(spare) if job.cls <= 1 else min(spare)
            job.slot = pick
            return pick

    def p0_active(self) -> bool:
        with self._cv:
            return self._p0_holding() or self._clock() - self._last_p0_end < self.cfg.grace_s

    def view(self) -> dict:
        with self._cv:
            now = self._clock()
            models = {}
            for name, policy in self.cfg.models.items():
                models[name] = {
                    "slots": policy.slots, "bg_cap": policy.cap(),
                    "running": [{"class": CLASS_NAMES[j.cls], "state": j.state, "pauses": j.pauses,
                                 "preemptible": j.preemptible} for j in self._running[name]],
                    "queued": [{"class": CLASS_NAMES[j.cls], "wait_s": round(now - j.queued_at, 2),
                                "pauses": j.pauses} for j in self._queued if j.model == name]}
            return {"p0_active": self._p0_holding() or now - self._last_p0_end < self.cfg.grace_s,
                    "solo_p0": self.cfg.solo_p0, "models": models,
                    "classes": {CLASS_NAMES[i]: st.view() for i, st in enumerate(self.stats)}}

    # the rules (lock held) -------------------------------------------------------------------------------------------
    def _drop(self, job: Job) -> None:
        for table in (self._running, self._paused):
            jobs = table.get(job.model, [])
            if job in jobs:
                jobs.remove(job)

    def _solo(self) -> bool:
        return self.cfg.solo_p0 and (self._p0_holding() or self._clock() - self._last_p0_end < self.cfg.grace_s)

    def _p0_holding(self) -> bool:
        """A P0 that may hold background off: queued, or running for less than solo_max_s."""
        now = self._clock()
        return any(j.cls == 0 for j in self._queued) or any(
            j.cls == 0 and now - j.started_at < self.cfg.solo_max_s for jobs in self._running.values() for j in jobs)

    def _fits(self, job: Job, solo: bool) -> bool:
        policy, running = self.cfg.models[job.model], self._running[job.model]
        if len(running) >= policy.slots:
            return False
        if job.cls >= 2:
            if sum(1 for j in running if j.cls >= 2) >= policy.cap():
                return False
            if solo and self._background_running() >= self.cfg.solo_keep:
                return False
        return True

    def _background_running(self) -> int:
        return sum(1 for jobs in self._running.values() for j in jobs if j.cls >= 2 and j.state != "pausing")

    def _schedule(self) -> None:
        solo = self._solo()
        for job in sorted(self._queued, key=lambda j: (j.cls, j.seq)):
            if self._fits(job, solo):
                self._queued.remove(job)
                if job in self._paused[job.model]:
                    self._paused[job.model].remove(job)
                job.state, job.started_at = "running", self._clock()
                self._running[job.model].append(job)
        self._preempt(solo)
        self._cv.notify_all()

    def _preempt(self, solo: bool) -> None:
        if solo and self._p0_holding():
            background = sorted((j for jobs in self._running.values() for j in jobs if j.cls >= 2 and j.state == "running"),
                                key=lambda j: (j.preemptible, j.cls, j.seq))     # kept first: unpausable, P2, oldest
            for job in background[self.cfg.solo_keep:]:
                if job.preemptible:
                    self._pause(job)
        for name, running in self._running.items():
            waiting = sorted((j for j in self._queued if j.model == name and j.cls <= 1), key=lambda j: (j.cls, j.seq))
            freeing = sum(1 for j in running if j.state == "pausing")
            for urgent in waiting[freeing:]:
                victims = sorted((j for j in running if j.state == "running" and j.preemptible and j.cls > urgent.cls),
                                 key=lambda j: (-j.cls, -j.seq))
                if not victims:
                    break
                self._pause(victims[0])

    def _pause(self, job: Job) -> None:
        job.state = "pausing"
        job.pauses += 1
        self.stats[job.cls].preemptions += 1
        if job.cancel is not None:
            try:
                job.cancel()
            except OSError:
                pass


# --- one answer, possibly in several segments -----------------------------------------------------------------------

@dataclass
class Answer:
    """What the upstream has produced so far for one client request, across pauses."""
    kind: str                          # chat | text
    id: str = ""
    created: int = 0
    model: str = ""
    content: str = ""
    reasoning: str = ""
    tools: dict[int, dict] = field(default_factory=dict)
    finish: str | None = None
    prompt_tokens: int = 0
    completion_tokens: int = 0         # finished segments
    segment_tokens: int = 0            # the current segment (timings_per_token, else counted chunks)
    timings: dict = field(default_factory=dict)
    exact: bool = True                 # False once output was made that a continuation cannot reproduce

    def absorb(self, chunk: dict) -> bool:
        """Add one upstream stream chunk. True when it carried generated output."""
        if not self.id:
            self.id, self.created, self.model = str(chunk.get("id") or ""), int(chunk.get("created") or 0), \
                str(chunk.get("model") or "")
        made = False
        for choice in chunk.get("choices") or []:
            if self.kind == "chat":
                delta = choice.get("delta") or {}
                if delta.get("content"):
                    self.content += delta["content"]
                    made = True
                if delta.get("reasoning_content"):
                    self.reasoning += delta["reasoning_content"]
                    made = True
                for call in delta.get("tool_calls") or []:
                    made, self.exact = True, False
                    slot = self.tools.setdefault(int(call.get("index", 0)),
                                                 {"id": "", "type": "function", "function": {"name": "", "arguments": ""}})
                    if call.get("id"):
                        slot["id"] = call["id"]
                    fn = call.get("function") or {}
                    slot["function"]["name"] += fn.get("name") or ""
                    slot["function"]["arguments"] += fn.get("arguments") or ""
            elif choice.get("text"):
                self.content += choice["text"]
                made = True
            if choice.get("finish_reason"):
                self.finish = choice["finish_reason"]
        timings = chunk.get("timings")
        if isinstance(timings, dict):
            self.timings = timings
            if isinstance(timings.get("predicted_n"), int):
                self.segment_tokens = max(self.segment_tokens, timings["predicted_n"])
        elif made:
            self.segment_tokens += 1
        usage = chunk.get("usage")
        if isinstance(usage, dict) and not self.prompt_tokens:
            self.prompt_tokens = int(usage.get("prompt_tokens") or 0)
        return made

    def end_segment(self) -> None:
        self.completion_tokens += self.segment_tokens
        self.segment_tokens = 0

    def reset(self) -> None:
        """Forget the output (the answer starts over); the id the client saw stays."""
        self.content, self.reasoning, self.tools, self.finish = "", "", {}, None
        self.completion_tokens = self.segment_tokens = 0
        self.timings, self.exact = {}, True

    def response(self) -> dict:
        usage = {"prompt_tokens": self.prompt_tokens, "completion_tokens": self.completion_tokens,
                 "total_tokens": self.prompt_tokens + self.completion_tokens}
        if self.kind == "text":
            return {"id": self.id, "object": "text_completion", "created": self.created, "model": self.model,
                    "choices": [{"index": 0, "text": self.content, "logprobs": None, "finish_reason": self.finish}],
                    "usage": usage, "timings": self.timings}
        message: dict[str, Any] = {"role": "assistant", "content": self.content if (self.content or not self.tools)
                                   else None}
        if self.reasoning:
            message["reasoning_content"] = self.reasoning
        if self.tools:
            message["tool_calls"] = [self.tools[i] for i in sorted(self.tools)]
        return {"id": self.id, "object": "chat.completion", "created": self.created, "model": self.model,
                "choices": [{"index": 0, "message": message, "finish_reason": self.finish}],
                "usage": usage, "timings": self.timings}


def continuable(kind: str, body: dict) -> bool:
    """Can a cut-off answer to this request be continued exactly from its text?"""
    if any(body.get(k) not in (None, "", {}) for k in CONSTRAINED_FIELDS):
        return False
    if int(body.get("n") or 1) > 1 or int(body.get("n_cmpl") or 1) > 1:
        return False
    if kind == "text":
        return isinstance(body.get("prompt"), str)
    messages = body.get("messages")
    if not isinstance(messages, list) or not messages:
        return False
    last = messages[-1]
    return not (isinstance(last, dict) and last.get("role") == "assistant" and not isinstance(last.get("content", ""), str))


def limit_of(body: dict) -> tuple[str, int] | None:
    for key in LIMIT_FIELDS:
        value = body.get(key)
        if isinstance(value, int) and value > 0:
            return key, value
    return None


def continuation(kind: str, body: dict, answer: Answer) -> dict | None:
    """The request that continues `answer` where it stopped, or None when its token budget is used up."""
    out = dict(body)
    limit = limit_of(body)
    if limit is not None:
        left = limit[1] - answer.completion_tokens
        if left <= 0:
            return None
        out[limit[0]] = left
    if not answer.content and not answer.reasoning:
        return out                     # nothing was generated yet: the same request again
    if kind == "text":
        out["prompt"] = body["prompt"] + answer.content
        return out
    messages = list(body["messages"])
    prefill = ""
    if isinstance(messages[-1], dict) and messages[-1].get("role") == "assistant":
        prefill = str(messages.pop().get("content") or "")
    msg: dict[str, Any] = {"role": "assistant", "content": prefill + answer.content}
    if answer.reasoning:
        msg["reasoning_content"] = answer.reasoning
    out["messages"] = messages + [msg]
    out["continue_final_message"] = "reasoning_content" if answer.reasoning and not answer.content and not prefill \
        else True
    out["add_generation_prompt"] = False
    return out


# --- the HTTP side --------------------------------------------------------------------------------------------------

class Upstream:
    """One upstream HTTP request. The request is sent at once; `response()` waits for the headers (llama.cpp sends
    them with the first token). `abort()` from any thread stops it, also while `response()` waits: the socket is shut
    down, the reading thread sees the end of the stream, and llama.cpp cancels the generation and frees the slot.
    `close()` belongs to the thread that reads (http.client objects are not thread-safe)."""

    def __init__(self, base: str, method: str, path: str, body: bytes | None, headers: dict[str, str],
                 timeout: float = 3600.0):
        parts = urllib.parse.urlsplit(base)
        self.conn = http.client.HTTPConnection(parts.hostname or "127.0.0.1", parts.port or 80, timeout=timeout)
        self.conn.request(method, (parts.path.rstrip("/") + path) or "/", body=body, headers=headers)
        self.sock = self.conn.sock
        self.resp: http.client.HTTPResponse | None = None

    def response(self) -> http.client.HTTPResponse:
        self.resp = self.conn.getresponse()
        return self.resp

    def abort(self) -> None:
        if self.sock is not None:
            try:
                self.sock.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass

    def close(self) -> None:
        self.abort()
        try:
            self.conn.close()
        except OSError:
            pass


class Proxy:
    def __init__(self, cfg: Config):
        self.cfg = cfg
        self.sched = Scheduler(cfg)
        self.keys = read_keys(cfg.key_file) if cfg.key_file else []
        self._detected: dict[str, float] = {}
        self._log_lock = threading.Lock()

    def authorized(self, header: str) -> bool:
        if not self.keys:
            return True
        token = header[7:].strip() if header.lower().startswith("bearer ") else ""
        return any(hmac.compare_digest(token, key) for key in self.keys)

    def detect_slots(self, model: str, headers: dict[str, str]) -> None:
        """The model's slot count from upstream /props (at first use, then every 5 minutes)."""
        policy = self.cfg.models[model]
        if not policy.detect or time.monotonic() - self._detected.get(model, -1e9) < 300:
            return
        self._detected[model] = time.monotonic()
        try:
            up = Upstream(self.cfg.upstream, "GET", "/props?model=" + urllib.parse.quote(model), None,
                          {k: v for k, v in headers.items() if k.lower() == "authorization"}, timeout=5.0)
            resp = up.response()
            data = json.loads(resp.read(1 << 20) or b"{}") if resp.status == 200 else {}
            up.close()
            slots = data.get("total_slots") if isinstance(data, dict) else None
            if isinstance(slots, int):
                self.sched.set_slots(model, slots)
        except (OSError, ValueError, http.client.HTTPException):
            pass

    def busy_slots(self, model: str, headers: dict[str, str]) -> set[int]:
        """Slots the server reports as working (any client), from /slots; empty when it cannot be read."""
        try:
            up = Upstream(self.cfg.upstream, "GET", "/slots?model=" + urllib.parse.quote(model), None,
                          {k: v for k, v in headers.items() if k.lower() == "authorization"}, timeout=3.0)
            resp = up.response()
            data = json.loads(resp.read(1 << 22) or b"[]") if resp.status == 200 else []
            up.close()
        except (OSError, ValueError, http.client.HTTPException):
            return set()
        return {row["id"] for row in data if isinstance(row, dict) and isinstance(row.get("id"), int)
                and row.get("is_processing")} if isinstance(data, list) else set()

    def write_log(self, row: dict) -> None:
        if not self.cfg.log:
            return
        with self._log_lock:
            try:
                with open(self.cfg.log, "a", encoding="utf-8") as handle:
                    handle.write(json.dumps(row) + "\n")
            except OSError:
                pass


@dataclass
class Turn:
    """The state of one scheduled client request while it is served (possibly in several segments)."""
    cls: int
    kind: str
    req: dict
    stream: bool
    wants_usage: bool
    wants_timings: bool
    exact: bool
    answer: Answer
    t0: float
    first_token: float | None = None
    started: bool = False              # stream headers sent to the client
    replied: bool = False              # a complete reply (JSON or error) was sent
    sent_any: bool = False             # generated output reached the client
    segments: int = 0
    wait_s: float = 0.0
    resumed_prompt: int = 0
    resumed_cache: int = 0
    status: str = "ok"
    error: str = ""


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = "star-priority"
    proxy: Proxy                       # set on the class by make_server

    def log_message(self, format: str, *args: Any) -> None:  # noqa: A002  (quiet: the JSON log has what matters)
        return

    # helpers --------------------------------------------------------------------------------------------------------
    def _split(self) -> tuple[int, str]:
        cls, path = getattr(self.server, "default_class", self.proxy.cfg.default_class), self.path
        head = path.split("/", 2)
        if len(head) > 1 and head[1].lower() in ("p0", "p1", "p2", "p3"):
            cls, path = int(head[1][1]), "/" + (head[2] if len(head) > 2 else "")
        if self.headers.get("X-Star-Priority"):
            cls = parse_class(self.headers["X-Star-Priority"], cls)
        return cls, path

    def _forward_headers(self) -> dict[str, str]:
        return {k: v for k, v in self.headers.items() if k.lower() not in HOP_HEADERS}

    def _body(self) -> bytes:
        length = int(self.headers.get("Content-Length") or 0)
        return self.rfile.read(length) if length > 0 else b""

    def _send_raw(self, status: int, raw: bytes, content_type: str = "application/json") -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def _send_json(self, status: int, data: dict) -> None:
        self._send_raw(status, json.dumps(data).encode("utf-8"))

    def _chunk(self, data: bytes) -> None:
        if data:
            try:
                self.wfile.write(b"%x\r\n%s\r\n" % (len(data), data))
                self.wfile.flush()
            except OSError:
                raise Gone() from None

    def _gone(self) -> bool:
        """The client closed its connection (checked while its request waits)."""
        try:
            readable, _, _ = select.select([self.connection], [], [], 0)
            return bool(readable) and self.connection.recv(1, socket.MSG_PEEK) == b""
        except (OSError, ValueError):
            return True

    def _loopback(self) -> bool:
        return self.client_address[0] in ("127.0.0.1", "::1")

    # verbs ----------------------------------------------------------------------------------------------------------
    def do_GET(self) -> None:
        self._route("GET")

    def do_POST(self) -> None:
        self._route("POST")

    def do_DELETE(self) -> None:
        self._route("DELETE")

    def do_PUT(self) -> None:
        self._route("PUT")

    def do_PATCH(self) -> None:
        self._route("PATCH")

    def do_OPTIONS(self) -> None:
        self._route("OPTIONS")

    def do_HEAD(self) -> None:
        self._route("HEAD")

    def _route(self, method: str) -> None:
        cls, path = self._split()
        body = self._body() if method in ("POST", "PUT", "PATCH", "DELETE") else b""
        if path.startswith("/priority/v1/status"):
            if not self._loopback() and not self.proxy.authorized(self.headers.get("Authorization", "")):
                self._send_json(401, {"error": "key required"})
                return
            self._send_json(200, self.proxy.sched.view())
            return
        kind = SCHEDULED_PATHS.get(path.split("?", 1)[0]) if method == "POST" else None
        if kind:
            try:
                req = json.loads(body or b"{}")
            except ValueError:
                req = None
            model = self.proxy.cfg.canonical(str(req.get("model") or "")) if isinstance(req, dict) else ""
            if model and isinstance(req, dict) and not req.get("logprobs") and not req.get("n_probs"):
                if not self.proxy.authorized(self.headers.get("Authorization", "")):
                    self._send_json(401, {"error": {"code": 401, "message": "Invalid API Key",
                                                    "type": "authentication_error"}})
                    return
                self._scheduled(cls, kind, model, path, req)
                return
        self._passthrough(method, path, body)

    # passthrough ----------------------------------------------------------------------------------------------------
    def _passthrough(self, method: str, path: str, body: bytes) -> None:
        try:
            up = Upstream(self.proxy.cfg.upstream, method, path, body or None, self._forward_headers())
            resp = up.response()
        except (OSError, http.client.HTTPException):
            self._send_json(502, {"error": "upstream unreachable"})
            return
        try:
            self.send_response(resp.status)
            for key, value in resp.getheaders():
                if key.lower() not in HOP_HEADERS:
                    self.send_header(key, value)
            if method == "HEAD":
                self.send_header("Content-Length", resp.getheader("Content-Length") or "0")
                self.end_headers()
                return
            self.send_header("Transfer-Encoding", "chunked")
            self.end_headers()
            while True:
                data = resp.read1(65536)
                if not data:
                    break
                self._chunk(data)
            self.wfile.write(b"0\r\n\r\n")
        except (OSError, http.client.HTTPException, Gone):
            self.close_connection = True
        finally:
            up.close()

    # scheduled ------------------------------------------------------------------------------------------------------
    def _scheduled(self, cls: int, kind: str, model: str, path: str, req: dict) -> None:
        proxy, sched = self.proxy, self.proxy.sched
        headers = self._forward_headers()
        headers["Content-Type"] = "application/json"
        proxy.detect_slots(model, headers)
        turn = Turn(cls, kind, req, bool(req.get("stream")), bool((req.get("stream_options") or {}).get("include_usage")),
                    bool(req.get("timings_per_token")), continuable(kind, req), Answer(kind), time.monotonic())
        job = sched.new_job(cls, model)
        job.preemptible = turn.exact or not turn.stream
        current: dict | None = req
        try:
            while current is not None:
                turn.wait_s += sched.acquire(job, self._gone)
                outcome = self._segment(job, turn, path, headers, current)
                if outcome != "paused":
                    break
                sched.paused(job)                   # give the slot back, then go on where the answer stopped
                current = self._next_request(turn)
            if turn.status == "ok" and not turn.replied:
                if turn.stream:
                    self._chunk(b"data: [DONE]\n\n")
                else:
                    self._send_json(200, turn.answer.response())
                    turn.replied = True
            if turn.status != "ok" and not turn.started and not turn.replied:
                self._send_json(502, {"error": {"code": 502, "message": turn.error or "upstream failed"}})
            if turn.started:
                self.wfile.write(b"0\r\n\r\n")
                self.wfile.flush()
        except Gone:
            turn.status = "client gone"
        except (OSError, http.client.HTTPException):
            turn.status = "client gone"
            self.close_connection = True
        except Exception:
            turn.status, turn.error = "error", "proxy error"
            raise
        finally:
            sched.release(job)
            tokens = turn.answer.completion_tokens
            sched.note(cls, tokens_out=tokens, resume_prompt_tokens=turn.resumed_prompt,
                       resume_cached_tokens=turn.resumed_cache, errors=1 if turn.status == "error" else 0)
            if turn.first_token is not None:
                sched.note(cls, first_token=turn.first_token)
            proxy.write_log({"t": round(time.time(), 3), "class": CLASS_NAMES[cls], "model": model, "kind": kind,
                             "stream": turn.stream, "status": turn.status, "error": turn.error,
                             "wait_s": round(turn.wait_s, 3),
                             "first_token_s": round(turn.first_token, 3) if turn.first_token is not None else None,
                             "total_s": round(time.monotonic() - turn.t0, 3), "tokens": tokens, "pauses": job.pauses,
                             "segments": turn.segments + 1, "resume_prompt_tokens": turn.resumed_prompt,
                             "resume_cached_tokens": turn.resumed_cache})

    def _next_request(self, turn: Turn) -> dict | None:
        """After a pause: the continuation, the original request again (output that cannot be continued; never
        reached for a streaming client that has sent such output), or None when the token budget is used up."""
        sched = self.proxy.sched
        turn.segments += 1
        if turn.exact and turn.answer.exact:
            nxt = continuation(turn.kind, turn.req, turn.answer)
            if nxt is None:
                turn.answer.finish = "length"
                return None
            sched.note(turn.cls, resumes=1)
            return nxt
        turn.answer.reset()
        turn.segments = 0
        sched.note(turn.cls, restarts=1)
        return turn.req

    def _segment(self, job: Job, turn: Turn, path: str, headers: dict[str, str], current: dict) -> str:
        """Send one upstream request and relay its stream. Returns "done", "paused" or "error"."""
        sched, answer = self.proxy.sched, turn.answer
        body = dict(current)
        body["stream"] = True
        body["stream_options"] = {"include_usage": True}
        body["timings_per_token"] = True
        if turn.segments:
            body.setdefault("cache_prompt", True)
        if self.proxy.cfg.assign_slots:
            slot = sched.take_slot(job, self.proxy.busy_slots(job.model, headers), turn.req.get("id_slot"))
            if slot is None:
                body.pop("id_slot", None)
            else:
                body["id_slot"] = slot
        answer.timings = {}
        try:
            up = Upstream(self.proxy.cfg.upstream, "POST", path, json.dumps(body).encode("utf-8"), headers)
        except (OSError, http.client.HTTPException):
            turn.status, turn.error = "error", "upstream unreachable"
            return "error"
        if not sched.attach(job, up.abort):
            up.close()
        done = False
        try:
            try:
                resp = up.response()
            except (OSError, ValueError, http.client.HTTPException):
                if sched.pausing(job):
                    return "paused"
                turn.status, turn.error = "error", "upstream unreachable"
                return "error"
            if resp.status != 200:
                raw = resp.read(1 << 20)
                if turn.segments and not turn.sent_any:          # a continuation was refused: start over once
                    answer.reset()
                    turn.exact, turn.segments = False, 0
                    sched.note(turn.cls, restarts=1)
                    return "paused"
                turn.status, turn.error = "error", f"upstream {resp.status}"
                if not turn.started:
                    self._send_raw(resp.status, raw, resp.getheader("Content-Type") or "application/json")
                    turn.replied = True
                return "error"
            if turn.stream and not turn.started:
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
                self.send_header("Cache-Control", "no-cache")
                self.send_header("Transfer-Encoding", "chunked")
                self.end_headers()
                turn.started = True
            done = self._relay(job, turn, resp)
        finally:
            up.close()
            answer.end_segment()
            if turn.segments:
                turn.resumed_prompt += int(answer.timings.get("prompt_n") or 0)
                turn.resumed_cache += int(answer.timings.get("cache_n") or 0)
        if turn.status != "ok":
            return "error"
        if done or answer.finish:
            return "done"
        if sched.pausing(job):
            return "paused"
        turn.status, turn.error = "error", "upstream ended early"
        return "error"

    def _relay(self, job: Job, turn: Turn, resp: http.client.HTTPResponse) -> bool:
        """Read upstream SSE lines into the answer (and to a streaming client). True when the stream finished."""
        sched, answer = self.proxy.sched, turn.answer
        try:
            while True:
                line = resp.readline()
                if not line:
                    return False
                text = line.decode("utf-8", "replace").strip()
                if not text.startswith("data:"):
                    continue
                data = text[5:].strip()
                if data == "[DONE]":
                    return True
                try:
                    chunk = json.loads(data)
                except ValueError:
                    continue
                if "error" in chunk and not chunk.get("choices"):
                    turn.status, turn.error = "error", str(chunk.get("error"))[:200]
                    if turn.stream:
                        self._chunk(b"data: " + data.encode("utf-8") + b"\n\n")
                        turn.replied = True
                    return True
                if turn.stream and job.preemptible and _has_tool_calls(chunk):
                    # tool-call output cannot be continued: from here on this answer is not paused; if a pause
                    # was already asked for, drop the chunk unsent and continue later from the text before it
                    if not sched.set_preemptible(job, False):
                        return False
                made = answer.absorb(chunk)
                if made and turn.first_token is None:
                    turn.first_token = time.monotonic() - turn.t0
                if turn.stream:
                    out = self._client_chunk(chunk, turn)
                    if out is not None:
                        self._chunk(b"data: " + json.dumps(out).encode("utf-8") + b"\n\n")
                        turn.sent_any = turn.sent_any or made
        except (OSError, ValueError, http.client.HTTPException):    # upstream closed (a pause) or failed
            return False

    def _client_chunk(self, chunk: dict, turn: Turn) -> dict | None:
        """The upstream chunk as the client should see it: one id for the whole answer, no second role line, usage
        and per-token timings only when asked for, and usage counting every segment."""
        answer = turn.answer
        out = dict(chunk)
        out["id"], out["created"] = answer.id, answer.created
        choices = out.get("choices") or []
        if "usage" in out and not choices:
            if not turn.wants_usage:
                return None
            usage = dict(out["usage"])
            usage["prompt_tokens"] = answer.prompt_tokens
            usage["completion_tokens"] = answer.completion_tokens + answer.segment_tokens
            usage["total_tokens"] = usage["prompt_tokens"] + usage["completion_tokens"]
            out["usage"] = usage
        finishing = any(c.get("finish_reason") for c in choices)
        if "timings" in out and not turn.wants_timings and not finishing:
            del out["timings"]
        if turn.segments and answer.kind == "chat":
            fixed = []
            for choice in choices:
                delta = dict(choice.get("delta") or {})
                delta.pop("role", None)
                if not delta and not choice.get("finish_reason"):
                    continue
                fixed.append({**choice, "delta": delta})
            if choices and not fixed:
                return None
            out["choices"] = fixed
        return out


def _has_tool_calls(chunk: dict) -> bool:
    return any((choice.get("delta") or {}).get("tool_calls") for choice in chunk.get("choices") or [])


class FrontDoor(ThreadingHTTPServer):
    request_queue_size = 256          # the stdlib default (5) refuses connections in a burst of embedding calls


def make_servers(cfg: Config) -> list[ThreadingHTTPServer]:
    """The main port (default class) and one listener per class port, all sharing one scheduler: a client is labelled
    by the port it uses (http://<brain>:8083/v1 = P3) without a path a strict URL check would refuse."""
    proxy = Proxy(cfg)
    handler = type("BoundHandler", (Handler,), {"proxy": proxy})
    servers = []
    for port, cls in [(cfg.port, cfg.default_class), *cfg.class_ports.items()]:
        server = FrontDoor((cfg.host, port), handler)
        server.daemon_threads = True
        server.default_class = cls       # type: ignore[attr-defined]
        servers.append(server)
    return servers


def make_server(cfg: Config) -> ThreadingHTTPServer:
    return make_servers(cfg)[0]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m star.priority_proxy", description="STAR priority proxy (see the module docstring)")
    parser.add_argument("--config", default=os.environ.get("STAR_PRIORITY_CONFIG", ""))
    parser.add_argument("--upstream")
    parser.add_argument("--host")
    parser.add_argument("--port", type=int)
    parser.add_argument("--key-file")
    parser.add_argument("--log")
    args = parser.parse_args(argv)
    cfg = Config.load(args.config) if args.config else Config()
    for key in ("upstream", "host", "port", "key_file", "log"):
        value = getattr(args, key)
        if value is not None:
            setattr(cfg, key, value)
    servers = make_servers(cfg)
    for extra in servers[1:]:
        threading.Thread(target=extra.serve_forever, daemon=True).start()
    ports = ", ".join(f"{s.server_address[1]}={CLASS_NAMES[s.default_class]}" for s in servers)   # type: ignore[attr-defined]
    print(f"star priority proxy on {cfg.host} ports {ports} -> upstream, models {', '.join(cfg.models)}", flush=True)
    try:
        servers[0].serve_forever()
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
