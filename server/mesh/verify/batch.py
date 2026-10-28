"""Optional parallel model calls for one repair round; validators stay on the caller thread.

A shared instance bounds active calls across HTTP requests. It retains no prompts/results between runs.
Running callbacks must enforce their own I/O timeout; this class does not claim to cancel them.
"""
from __future__ import annotations

import json
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass

MAX_JOBS = 64
MAX_PROMPT_BYTES = 256 * 1024


@dataclass(frozen=True)
class Outcome:
    reply: str = ""
    error: str = ""
    model_ms: float = 0.0
    called: bool = False
    skipped: str = ""


class RepairBatch:
    def __init__(self, workers: int = 1, *, coalesce: bool = False, wait_s: float = 0.25):
        if type(workers) is not int or not 1 <= workers <= 4:
            raise ValueError("repair_workers must be an integer from 1 to 4")
        if type(coalesce) is not bool:
            raise ValueError("repair_coalesce must be a boolean")
        if isinstance(wait_s, bool) or not isinstance(wait_s, (int, float)) or not 0 <= wait_s <= 5:
            raise ValueError("repair_wait_s must be from 0 to 5 seconds")
        self.workers, self.coalesce, self.wait_s = workers, coalesce, wait_s
        self._capacity = threading.BoundedSemaphore(workers)

    def _call(self, messages: str, caller) -> Outcome:
        if not self._capacity.acquire(timeout=self.wait_s):
            return Outcome(error="repair capacity busy; original block retained", skipped="capacity")
        start = time.perf_counter()
        try:
            reply = caller(json.loads(messages))
            if not isinstance(reply, str):
                raise TypeError("repair caller must return text")
            return Outcome(reply=reply, model_ms=(time.perf_counter() - start) * 1000, called=True)
        except Exception as error:
            return Outcome(error=f"fix call failed: {type(error).__name__}",
                           model_ms=(time.perf_counter() - start) * 1000, called=True)
        finally:
            self._capacity.release()

    def run(self, messages: list[list[dict]], caller) -> tuple[list[Outcome], dict]:
        """Same-round exact prompts may share one outcome; each original block still needs validation.

        One caller/model configuration is fixed by the caller for this run. Failures and successes are discarded
        on return, so later rounds make fresh attempts. Submission windows never exceed `workers` futures.
        """
        unique: list[str] = []
        seen: dict[str, int] = {}
        positions: list[int | None] = []
        coalesced = 0
        byte_count = 0
        for message in messages:
            key = json.dumps(message, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False)
            if self.coalesce and key in seen:
                positions.append(seen[key])
                coalesced += 1
            elif len(unique) >= MAX_JOBS or byte_count + len(key) > MAX_PROMPT_BYTES:
                positions.append(None)
            else:
                positions.append(len(unique))
                if self.coalesce:
                    seen[key] = len(unique)
                unique.append(key)
                byte_count += len(key)
        outcomes: list[Outcome] = []
        if self.workers == 1:
            outcomes = [self._call(message, caller) for message in unique]
        elif unique:
            unavailable = Outcome(error="repair executor unavailable; original block retained", skipped="dispatch")
            try:
                with ThreadPoolExecutor(max_workers=self.workers, thread_name_prefix="litha-repair") as pool:
                    for offset in range(0, len(unique), self.workers):
                        pending = []
                        for message in unique[offset:offset + self.workers]:
                            try:
                                pending.append(pool.submit(self._call, message, caller))
                            except Exception:
                                pending.append(None)
                        for future in pending:
                            try:
                                outcomes.append(future.result() if future is not None else unavailable)
                            except Exception:
                                outcomes.append(unavailable)
            except Exception:
                outcomes.extend([unavailable] * (len(unique) - len(outcomes)))
        refused = Outcome(error="repair batch budget reached; original block retained", skipped="budget")
        return [outcomes[position] if position is not None else refused for position in positions], {
            "model_calls": sum(result.called for result in outcomes),
            "coalesced_blocks": coalesced,
            "capacity_skipped": sum(result.skipped == "capacity" for result in outcomes),
            "dispatch_skipped": sum(result.skipped == "dispatch" for result in outcomes),
            "budget_skipped": positions.count(None),
            "model_ms": sum(result.model_ms for result in outcomes),
        }
