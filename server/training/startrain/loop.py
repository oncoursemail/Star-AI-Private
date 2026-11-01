"""The generation loop: one request at a time, checkpoint after every candidate, resumable.

Per candidate: pick a topic (weighted, capped), take an idea from the pool (drafted by the small model), let the
main model write the task and its tests, let the main model solve the task from the task text alone, then run the
gates. Everything is appended to the JSONL files and the state file is rewritten atomically before the next
candidate starts, so a stop or a crash costs at most the candidate in flight.
"""
from __future__ import annotations

import hashlib
import random
import time

from . import gates as G
from . import parse, prompts, quiet, topics
from . import similarity as sim
from .brain import BrainError, Yielded
from .store import Store, now_iso

TOPIC_BY_ID = topics.by_id()

# Only solution-controlled failures are repairable. Task/test/decontamination
# failures are never shown to the solver as something it can talk its way past.
_REPAIRABLE_G0 = frozenset({
    "code_length", "response_length", "forbidden_call", "checking_disabled",
    "missing_strict_header", "cast_to_any", "strict_unverifiable", "debug_print",
})
_REPAIRABLE_GATES = frozenset({"G6", "G1", "G2", "G3"})


class Generator:
    def __init__(self, settings, brain, tools, decontam, store: Store, stop, log=print):
        self.s = settings
        self.brain = brain
        self.tools = tools
        self.decontam = decontam
        self.store = store
        self.stop = stop
        self.log = log
        self.memory = G.Memory()
        self._load_memory()
        self.consecutive_errors = 0
        self.run_started = time.monotonic()

    # --- startup -------------------------------------------------------------------------------------------------
    def _load_memory(self) -> None:
        vectors = dict(self.store.load_vectors())
        from .store import read_jsonl
        for row in read_jsonl(self.store.kept_path):
            fp = sim.fingerprint(row["prompt"], row["code"], row.get("tests", ""))
            self.memory.add(row["id"], fp, vectors.get(row["id"]))

    # --- helpers -------------------------------------------------------------------------------------------------
    def _yield_reason(self) -> str:
        if self.stop():
            return "stop"
        reason = quiet.pause_reason(self.s, None)           # pause file, lock, window
        if reason:
            return reason
        return "interactive" if self.brain.others_active(own_model=self._own_model, chat_models_only=True) else ""

    _own_model: str | None = None

    def _chat(self, model: str, messages: list[dict], *, max_tokens: int, temperature: float, stage: str, seed: int):
        self._own_model = model
        t0 = time.monotonic()
        try:
            result = self.brain.chat(model, messages, max_tokens=max_tokens, temperature=temperature,
                                     should_yield=self._yield_reason, seed=seed)
        finally:
            self._own_model = None
            self.store.state["seconds"]["llm"] += time.monotonic() - t0
        self.store.state["tokens"]["prompt"] += result["prompt_tokens"]
        self.store.state["tokens"]["completion"] += result["completion_tokens"]
        result["stage"] = stage
        return result

    def _pick_topic(self, rng: random.Random) -> topics.Topic:
        st = self.store.state
        total_kept = max(1, st["kept"])
        best, best_score = None, -1.0
        for t in topics.TOPICS:
            info = st["by_topic"].get(t.id, {"candidates": 0, "kept": 0})
            if st["kept"] >= 40 and info["kept"] / total_kept > self.s.cluster_cap * 1.5:
                continue                                      # no cluster above ~7.5 percent of the set
            score = t.weight / (1 + info["candidates"]) * (0.8 + 0.4 * rng.random())
            if score > best_score:
                best, best_score = t, score
        return best or rng.choice(topics.TOPICS)

    def _next_idea(self, topic: topics.Topic, seed: int) -> tuple[str, dict | None]:
        pool = self.store.state["ideas"].setdefault(topic.id, [])
        meta = None
        if not pool:
            reply = self._chat(self.s.idea_model, [{"role": "system", "content": prompts.IDEA_SYSTEM},
                                                   {"role": "user", "content": prompts.ideas_user(topic)}],
                               max_tokens=420, temperature=0.9, stage="ideas", seed=seed)
            meta = reply
            pool.extend(parse.parse_ideas(reply["text"]))
            if not pool:
                pool.append(topic.text)
        return pool.pop(0), meta

    # --- one candidate ------------------------------------------------------------------------------------------
    def make_candidate(self) -> dict | None:
        """Returns the finished record (kept or rejected), or None when the work was dropped (yield / stop)."""
        st = self.store.state
        index = st["candidates"] + 1
        rng = random.Random(self.s.seed * 1000003 + index)
        topic = self._pick_topic(rng)
        difficulty = max(1, min(3, topic.difficulty + rng.choice((-1, 0, 0, 1))))
        cid = f"sv-{index:06d}"
        t_start = time.monotonic()
        base = {"id": cid, "created": now_iso(), "topic": topic.id, "category": topic.category,
                "mode": topic.mode, "difficulty": difficulty}
        idea, _ = self._next_idea(topic, rng.randrange(1 << 30))
        base["idea"] = idea

        def rejected(gate: str, code: str, detail: str, extra: dict | None = None) -> dict:
            row = {**base, "gate": gate, "code": code, "detail": detail[:300], **(extra or {}),
                   "seconds": round(time.monotonic() - t_start, 1)}
            self.store.record_rejected(row)
            return row

        # 1. the task and its tests
        reply = self._chat(self.s.task_model, [{"role": "system", "content": prompts.TASK_SYSTEM},
                                               {"role": "user", "content": prompts.task_user(topic, idea, difficulty)}],
                           max_tokens=1700, temperature=0.7, stage="task", seed=rng.randrange(1 << 30))
        base["tokens_task"] = reply["completion_tokens"]
        if reply["finish"] == "length":
            return rejected("T", "task_truncated", "the task writer ran out of tokens")
        prompt, tests, problem = parse.parse_task(reply["text"])
        if problem:
            return rejected("T", "task_unparsable", problem)
        base["prompt"], base["tests"] = prompt, tests

        # 2. an independent solution from the task text alone
        reply = self._chat(self.s.solver_model, prompts.solver_messages(prompt, topic.mode), max_tokens=1700,
                           temperature=0.6, stage="solution", seed=rng.randrange(1 << 30))
        base["tokens_solution"] = reply["completion_tokens"]
        if reply["finish"] == "length":
            return rejected("S", "solution_truncated", "the solver ran out of tokens")
        code, problem = parse.parse_solution(reply["text"])
        if problem:
            return rejected("S", "solution_unparsable", problem)
        base["response"], base["code"] = reply["text"].strip(), code

        # 3. the gates, cheapest first. Optional repair is verifier-driven:
        # the solver receives only a compact failure summary, never the tests or
        # evaluator implementation, and every replacement must pass the same gates.
        gate_seconds = 0.0
        gt = time.monotonic()
        verdict, infos, fp = self.run_gates(base, rng)
        gate_seconds += time.monotonic() - gt
        repairs: list[dict] = []
        repair_tokens = 0
        for repair_round in range(1, self.s.solver_repair_rounds + 1):
            repairable = verdict.gate in _REPAIRABLE_GATES or (
                verdict.gate == "G0" and verdict.code in _REPAIRABLE_G0
            )
            if verdict.ok or not repairable:
                break
            trigger = f"{verdict.gate}:{verdict.code}"
            feedback_fingerprint = trigger + ":" + verdict.detail
            before_sha = hashlib.sha256(base["code"].encode("utf-8")).hexdigest()
            # Semantic execution failures are re-solved without the failed
            # answer in context; second+ attempts also switch to fresh
            # re-exploration to avoid repeatedly anchoring on one approach.
            fresh_reexplore = verdict.gate == "G3" or repair_round > 1
            strategy = "fresh_reexplore" if fresh_reexplore else "local_repair"
            reply = self._chat(
                self.s.solver_model,
                prompts.repair_messages(
                    base["prompt"], None if fresh_reexplore else base["response"], topic.mode,
                    verdict.gate, verdict.code, verdict.detail,
                ),
                max_tokens=1700,
                temperature=0.45 if fresh_reexplore else 0.25,
                stage="repair",
                seed=rng.randrange(1 << 30),
            )
            repair_tokens += reply["completion_tokens"]
            if reply["finish"] == "length":
                repairs.append({"round": repair_round, "trigger": trigger, "result": "truncated",
                                "before_sha256": before_sha})
                verdict = G.reject("S", "repair_truncated", "the repair ran out of tokens")
                infos = {}
                break
            repaired_code, problem = parse.parse_solution(reply["text"])
            if problem:
                repairs.append({"round": repair_round, "trigger": trigger, "result": "unparsable",
                                "before_sha256": before_sha})
                verdict = G.reject("S", "repair_unparsable", problem)
                infos = {}
                break
            after_sha = hashlib.sha256(repaired_code.encode("utf-8")).hexdigest()
            if after_sha == before_sha:
                repairs.append({"round": repair_round, "trigger": trigger, "result": "no_change",
                                "before_sha256": before_sha, "after_sha256": after_sha})
                verdict = G.reject("S", "repair_no_change", "repair returned byte-identical code")
                infos = {}
                break
            repairs.append({
                "round": repair_round,
                "trigger": trigger,
                "strategy": strategy,
                "result": "candidate",
                "before_sha256": before_sha,
                "after_sha256": after_sha,
                "feedback_sha256": hashlib.sha256(feedback_fingerprint.encode("utf-8")).hexdigest(),
            })
            base["response"], base["code"] = reply["text"].strip(), repaired_code
            gt = time.monotonic()
            verdict, infos, fp = self.run_gates(base, rng)
            gate_seconds += time.monotonic() - gt

        self.store.state["seconds"]["gates"] += gate_seconds
        base["generation_mode"] = "verifier-repair" if repairs else "single-pass"
        if repairs:
            base["repairs"] = repairs
            base["tokens_repairs"] = repair_tokens
        if not verdict.ok:
            return rejected(verdict.gate, verdict.code, verdict.detail, {"gates": infos} if infos else None)
        vector = infos.pop("_vector", None)
        row = {**base, "gates": infos, "verification": "pure-luau-vm" if topic.mode == "pure" else "mock-verified",
               "teacher": {"task": self.s.task_model, "solver": self.s.solver_model, "ideas": self.s.idea_model},
               "sources": ["owner-open-weight-models-synthetic"], "decontam_index": self.decontam.digest[:16],
               "gate_log_sha256": G.gate_log_hash(base, infos), "tool_versions": self.tools.versions,
               "seconds": round(time.monotonic() - t_start, 1)}
        self.store.record_kept(row, vector)
        self.memory.add(cid, fp, vector)
        return row

    def run_gates(self, c: dict, rng: random.Random):
        s, tools = self.s, self.tools
        infos: dict = {}
        for name, fn in (("G0", lambda: G.g0_shape(c, s)), ("G6", lambda: G.g6_deprecated(c))):
            v = fn()
            if not v.ok:
                return v, infos, None
            infos[name] = {"ok": True}
        fp = sim.fingerprint(c["prompt"], c["code"], c["tests"])
        hit = self.decontam.check_text(fp)
        if hit:
            return G.reject("G8", "suite_overlap", hit), infos, fp
        infos["G8"] = {"text": "clear"}
        twin = self.memory.duplicate_of(fp, s)
        if twin:
            return G.reject("G7", "near_duplicate", "like " + twin), infos, fp
        infos["G7"] = {"text": "clear"}
        v = G.g1_g2(c, tools)
        if not v.ok:
            return v, infos, fp
        infos["G1"] = {"ok": True}
        infos["G2"] = v.info
        v = G.g3_tests(c, tools, s)
        if not v.ok:
            return v, infos, fp
        infos["G3"] = v.info
        v = G.g4_sanity(c, tools, s, rng.randrange(1 << 30))
        infos["G4"] = v.info
        if not v.ok:
            return v, infos, fp
        # embedding checks last: they cost a model request
        vector = self.brain.embed(s.embed_model, [self.decontam_prefix() + c["prompt"][:2000]])[0]
        twin, cos = self.memory.nearest(vector)
        infos["G7"]["max_cosine"] = round(cos, 3)
        if cos >= s.dup_cosine:
            return G.reject("G7", "near_duplicate_embedding", f"cosine {cos:.2f} with {twin}"), infos, fp
        suite_cos = self.decontam.max_cosine(vector)
        infos["G8"]["max_cosine"] = round(suite_cos, 3)
        hit = self.decontam.check_vector(vector)
        if hit:
            return G.reject("G8", "suite_overlap_embedding", f"{hit} (cosine {suite_cos:.2f})"), infos, fp
        infos["_vector"] = vector
        return G.Verdict(), infos, fp

    @staticmethod
    def decontam_prefix() -> str:
        from .decontam import EMBED_PREFIX
        return EMBED_PREFIX

    # --- the loop -----------------------------------------------------------------------------------------------
    def run(self, *, max_candidates: int = 0, max_seconds: float = 0.0, report=lambda: None) -> None:
        st = self.store.state
        st["runs"].append({"start": now_iso(), "stop": None, "candidates": 0, "kept": 0})
        run_info = st["runs"][-1]
        started = time.monotonic()
        done = 0
        try:
            while not self.stop():
                if max_candidates and done >= max_candidates:
                    break
                if max_seconds and time.monotonic() - started >= max_seconds:
                    break
                waited = quiet.wait_until_clear(self.s, self.brain, self.stop, self.log)
                for key, secs in waited.items():
                    st["paused"][key] = st["paused"].get(key, 0.0) + secs
                if self.stop():
                    break
                t0 = time.monotonic()
                try:
                    row = self.make_candidate()
                    self.consecutive_errors = 0
                except Yielded as y:
                    self.log(f"yield: dropped the request in flight ({y.reason}); timeline {getattr(self.brain, 'last_trace', {})}")
                    st["paused"]["dropped_requests_" + y.reason] = st["paused"].get("dropped_requests_" + y.reason, 0) + 1
                    self.store.save()
                    continue
                except BrainError as exc:
                    self.consecutive_errors += 1
                    st["infra_errors"] += 1
                    delay = min(30 * self.consecutive_errors, 300)
                    self.log(f"brain error ({exc}); retrying in {delay}s")
                    self.store.save()
                    if self.consecutive_errors >= 12:
                        raise
                    t1 = time.monotonic()
                    while time.monotonic() - t1 < delay and not self.stop():
                        time.sleep(1)
                    st["paused"]["errors"] = st["paused"].get("errors", 0.0) + delay
                    continue
                st["seconds"]["active"] += time.monotonic() - t0
                run_info["candidates"] += 1
                done += 1
                if row is not None and "gate" not in row:
                    run_info["kept"] += 1
                    self.log(f"kept {row['id']} [{row['topic']}] assertions={row['gates']['G3'].get('assertions')} "
                             f"kill={row['gates']['G4'].get('kill_rate')} ({row['seconds']}s)")
                elif row is not None:
                    self.log(f"rejected {row['id']} [{row['topic']}] {row['gate']}:{row['code']} {row['detail'][:90]}")
                self.store.save()
                if done % self.s.report_every == 0:
                    report()
        finally:
            run_info["stop"] = now_iso()
            self.store.save()
            report()


def new_run_id() -> str:
    return hashlib.sha1(now_iso().encode()).hexdigest()[:8]
