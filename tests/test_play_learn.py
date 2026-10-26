"""star/play/learn: labels, consented recording, dataset split, filtered behaviour cloning, eval history, and a tiny
CPU-only policy trained for a few steps on the fake DotGame (no real screen, input or GPU)."""
from __future__ import annotations

import datetime
import json
import random

import pytest

from star.play.learn.actions import GameSpec, InputState, spec_for
from star.play.learn.evaluate import Attempt, EvalResult, evaluate, history, session_attempt, wilson


def _spec(**kw) -> GameSpec:
    base = dict(game="t", keys=("w", "a", "d", "space"), buttons=("left",), frame_size=(16, 9), stack=2)
    return GameSpec(**{**base, **kw})


# ---- labels (pure Python) -----------------------------------------------------------------------------------------

def test_mouse_bins_are_foveated_symmetric_and_invertible():
    s = _spec(mouse_bins=11, mouse_max=100.0, mu=12.0)
    assert s.mouse_bin(0) == s.still_bin == 5
    assert s.mouse_bin(-1e9) == 0 and s.mouse_bin(1e9) == 10
    assert [s.mouse_bin(d) for d in (-100, -10, 10, 100)] == [0, 10 - s.mouse_bin(10), s.mouse_bin(10), 10]
    for i in range(11):
        assert s.mouse_bin(s.bin_center(i)) == i
    widths = [s.bin_center(i + 1) - s.bin_center(i) for i in range(5, 10)]
    assert widths == sorted(widths) and widths[-1] > 4 * widths[0]       # fine near zero, coarse for flicks


def test_input_state_counts_short_taps_and_ignores_other_keys():
    st = InputState(_spec())
    st.key("space", True)
    st.key("space", False)                   # a tap shorter than one step
    st.key("w", True)
    st.key("q", True)                        # not a game key: never labelled
    st.move(30, -4)
    label = st.take()
    assert label.keys == (1, 0, 0, 1) and label.dx == 30 and label.dy == -4
    again = st.take()
    assert again.keys == (1, 0, 0, 0) and again.dx == 0 and again.idle is False   # w still held, tap gone


def test_chat_box_pauses_labels_until_it_closes():
    st = InputState(_spec(chat_open=("slash",), chat_close=("enter", "escape")))
    st.key("w", True)
    st.key("slash", True)
    for ch in "hello wasd":
        st.key(ch, True)
        st.key(ch, False)
    st.move(50, 0)
    assert st.take() is None                 # nothing typed in chat reaches a label
    st.key("enter", True)
    label = st.take()
    assert label.keys == (0, 0, 0, 0) and label.dx == 0


def test_mouse_buttons_do_not_collide_with_arrow_keys():
    st = InputState(_spec(keys=("left",), buttons=("left",)))
    st.button("left", True)
    label = st.take()
    assert label.buttons == (1,) and label.keys == (0,)


def test_presets_and_overrides():
    assert spec_for("roblox_obby").window == "Roblox"
    assert spec_for("roblox_obby", hz=10).hz == 10
    spec = spec_for("minecraft")
    assert GameSpec.from_dict(json.loads(json.dumps(spec.to_dict()))) == spec


# ---- heavy-work rule, evaluation, history (pure Python) -----------------------------------------------------------

def test_heavy_ok_follows_pc_guard_rule():
    from star.play.learn.__main__ import heavy_ok
    day = datetime.datetime(2026, 10, 26, 18, 0, tzinfo=datetime.timezone.utc)
    night = datetime.datetime(2026, 10, 26, 6, 0, tzinfo=datetime.timezone.utc)
    assert heavy_ok(night, idle=0)[0]
    assert not heavy_ok(day, idle=10)[0]
    assert heavy_ok(day, idle=301)[0]


def test_wilson_interval():
    lo, hi = wilson(8, 10)
    assert round(lo, 3) == 0.490 and round(hi, 3) == 0.943
    assert wilson(0, 0) == (0.0, 1.0)


def test_evaluate_writes_history_and_her_life_log(tmp_path):
    from star.home.life import Life
    life = Life(tmp_path / "home")
    outcomes = [True, False, True, True]
    result = evaluate("roblox_obby", lambda i: Attempt(outcomes[i], float(outcomes[i]), 3.0,
                                                        "" if outcomes[i] else "fell"),
                      4, policy="abc123", root=tmp_path, life=life)
    assert (result.successes, result.rate, result.notes) == (3, 0.75, ["fell"])
    rows = history("roblox_obby", tmp_path)
    assert rows[-1]["successes"] == 3 and rows[-1]["policy"] == "abc123"
    logged = life.history()[-1]
    assert logged["activity"] == "eval roblox_obby" and logged["verified"] and "3/4" in logged["summary"]


class _FakeFast:
    def __init__(self) -> None:
        self.on_moment = []


class _FakeSession:
    def __init__(self, kinds) -> None:
        self.fast, self.kinds, self.stopped = _FakeFast(), kinds, False

    def start(self) -> None:
        for kind in self.kinds:
            for listener in self.fast.on_moment:
                listener(kind, 0.0)

    def stop(self) -> None:
        self.stopped = True


def test_session_attempt_judges_by_game_moments():
    made = []

    def factory(kinds):
        def make():
            made.append(_FakeSession(kinds))
            return made[-1]
        return make

    t = {"now": 0.0}

    def sleep(s):
        t["now"] += s

    run = session_attempt(factory(["checkpoint"]), success=("checkpoint",), failure=("death",),
                          clock=lambda: t["now"], sleep=sleep)
    assert run(0).success and made[-1].stopped
    assert not session_attempt(factory(["death", "checkpoint"]), success=("checkpoint",), failure=("death",),
                               clock=lambda: t["now"], sleep=sleep)(0).success
    slow = session_attempt(factory([]), success=("checkpoint",), timeout_s=1.0, clock=lambda: t["now"], sleep=sleep)(0)
    assert not slow.success and slow.note == "failed: timeout"


def test_promotion_needs_a_better_candidate():
    from star.play.learn.improve import better

    def r(k, prog):
        return EvalResult("g", "p", 10, k, k / 10, 0, 1, prog, 1.0, "", [])

    assert better(r(6, 0.6), r(5, 0.5))
    assert not better(r(5, 0.5), r(5, 0.5))
    assert not better(r(4, 0.9), r(5, 0.5))
    assert better(r(5, 0.7), r(5, 0.5))


# ---- recording (numpy) --------------------------------------------------------------------------------------------

try:
    import numpy as np
except ImportError:                          # the pure-Python tests above still run without numpy
    np = None
pytestmark_np = pytest.mark.skipif(np is None, reason="numpy not installed")


def _recorder(tmp_path, spec, **kw):
    from star.play.learn.recorder import Recorder
    lines = []
    rec = Recorder(spec, consent="owner agreed in chat (test)", who="owner", root=tmp_path, notify=lines.append,
                   session_id="s1", **kw)
    return rec, lines


@pytestmark_np
def test_recorder_needs_consent_and_says_it_is_recording(tmp_path):
    from star.play.learn.recorder import Recorder
    with pytest.raises(PermissionError):
        Recorder(_spec(), consent="  ", who="owner", root=tmp_path)
    clock = {"t": 0.0}
    rec, lines = _recorder(tmp_path, _spec(window="Roblox"), remind_s=10.0, clock=lambda: clock["t"])
    rec.start()
    assert lines and lines[0].startswith("[STAR rec] recording t: game window 'Roblox' only")
    for i in range(30):
        clock["t"] = i * 1.0
        rec.step(np.zeros((9, 16, 3), np.uint8), clock["t"])
    rec.stop()
    assert sum("still recording" in line for line in lines) == 2 and "stopped" in lines[-1]


@pytestmark_np
def test_recorder_pairs_each_frame_with_the_input_that_followed_it(tmp_path):
    from star.play.learn.recorder import load_session
    rec, _ = _recorder(tmp_path, _spec(), shard_steps=3)
    rec.start()
    for i in range(7):
        frame = np.full((18, 32, 3), i * 10, np.uint8)              # shrunk 2x to 16x9
        rec.step(frame, float(i))
        if i % 2 == 0:
            rec.state.key("d", True)
            rec.state.move(5 * i, 0)
        else:
            rec.state.key("d", False)
    rec.mark("checkpoint")
    path = rec.stop()
    s = load_session(path)
    assert s["frames"].shape == (6, 9, 16, 3) and len(s["meta"]["shards"]) == 2
    assert [int(f[0, 0, 0]) for f in s["frames"]] == [0, 10, 20, 30, 40, 50]
    assert s["keys"][:, 2].tolist() == [1, 0, 1, 0, 1, 0]           # frame i -> what was done after seeing it
    assert s["delta"][:, 0].tolist() == [0, 0, 10, 0, 20, 0]
    assert s["meta"]["markers"] == [{"step": 6, "kind": "checkpoint", "t": None}]
    assert s["meta"]["consent"].startswith("owner agreed")


@pytestmark_np
def test_recorder_drops_steps_when_the_game_window_is_not_in_front(tmp_path):
    from star.play.learn.recorder import load_session
    front = {"ok": True}
    rec, _ = _recorder(tmp_path, _spec(), guard=lambda: front["ok"])
    rec.start()
    for i in range(10):
        front["ok"] = i not in (4, 5)
        rec.step(np.full((9, 16, 3), i, np.uint8), float(i))
    s = load_session(rec.stop())
    assert [int(f[0, 0, 0]) for f in s["frames"]] == [0, 1, 2, 6, 7, 8]   # 3 waited for input when focus went
    assert s["gap"].tolist() == [1, 0, 0, 1, 0, 0] and s["meta"]["paused_steps"] == 2


@pytestmark_np
def test_shrink_averages_blocks():
    from star.play.learn.recorder import shrink
    img = np.zeros((4, 4, 3), np.uint8)
    img[:2, :2] = 200
    out = shrink(img, (2, 2))
    assert out.shape == (2, 2, 3) and out[0, 0, 0] == 200 and out[1, 1, 0] == 0
    assert shrink(np.full((720, 1280, 3), 7, np.uint8), (128, 72)).shape == (72, 128, 3)


@pytestmark_np
def test_sink_tap_records_what_star_sends(tmp_path):
    from star.play.humanlike import RecordingSink
    from star.play.learn.recorder import SinkTap
    st = InputState(_spec())
    inner = RecordingSink(clock=lambda: 0.0)
    tap = SinkTap(inner, st)
    tap.key("w", True)
    tap.move_rel(7, 1)
    tap.button("left", True)
    tap.move_to(100, 100)
    tap.move_to(110, 95)
    label = st.take()
    assert [c[0] for c in inner.calls] == ["key", "move_rel", "button", "move_to", "move_to"]
    assert label.keys[0] == 1 and label.buttons == (1,) and (label.dx, label.dy) == (17, -4)


# ---- dataset and filtered selection (numpy) -----------------------------------------------------------------------

def _write_session(tmp_path, name, who, n, markers=(), gap_at=()):
    from star.play.learn.recorder import Recorder
    spec = _spec()
    rec = Recorder(spec, consent="test", who=who, root=tmp_path, notify=lambda s: None, session_id=name)
    rec.start()
    for i in range(n + 1):
        if i in gap_at:
            rec.cut()
        rec.step(np.full((9, 16, 3), i % 250, np.uint8), float(i))
        rec.state.key("w", i % 3 == 0)
        for step, kind in markers:
            if step == i:                                   # after step i, i frames are stored
                rec.mark(kind)
    return rec.stop()


@pytestmark_np
def test_corpus_split_by_session_and_episode_masks(tmp_path):
    from star.play.learn.dataset import Corpus
    a = _write_session(tmp_path, "a", "owner", 40, markers=[(10, "checkpoint"), (25, "death")])
    b = _write_session(tmp_path, "b", "star", 20, markers=[(20, "checkpoint")])
    c = Corpus.from_sessions([a, b], max_episode_s=0.3)            # 0.3 s at 20 Hz = 6 steps per episode
    assert len(c) == 60
    ep = c.episode[:40].tolist()
    assert ep[:4] == [0] * 4 and ep[4:10] == [1] * 6 and ep[19:25] == [-1] * 6 and ep[25:] == [0] * 15
    train, val = c.split(0.3)
    assert set(c.session[val]) == {1} and set(c.session[train]) == {0}
    x = c.stack(np.array([5]))
    assert x.shape == (1, 6, 9, 16) and x[0, 0, 0, 0] == 4 and x[0, 3, 0, 0] == 5    # oldest frame first


@pytestmark_np
def test_gaps_break_frame_stacks_and_single_session_split_has_a_margin(tmp_path):
    from star.play.learn.dataset import Corpus
    a = _write_session(tmp_path, "a", "owner", 30, gap_at=(10,))
    c = Corpus.from_sessions([a])
    usable = set(c.usable().tolist())
    assert 0 not in usable and 1 in usable and 9 not in usable and 10 in usable  # stack never spans the cut
    train, val = c.split(0.2)
    assert train.max() < val.min() - c.spec.stack
    rng = np.random.default_rng(0)
    assert len(c.thin_idle(c.usable(), 0.0, rng)) == int((~c.idle[c.usable()]).sum())


@pytestmark_np
def test_select_steps_keeps_success_and_mixes_human_replay(tmp_path):
    from star.play.learn.dataset import Corpus
    from star.play.learn.improve import select_steps
    a = _write_session(tmp_path, "a", "owner", 60, markers=[(50, "death")])
    b = _write_session(tmp_path, "b", "star", 60, markers=[(20, "checkpoint"), (40, "death"), (60, "checkpoint")])
    c = Corpus.from_sessions([a, b], max_episode_s=0.5)            # 10 steps per episode
    idx, n_success = select_steps(c, replay_frac=0.5)
    assert n_success == 20
    chosen = set(idx.tolist())
    assert all(c.episode[i] != -1 for i in chosen)                  # never a step from a failed episode
    star_steps = [i for i in chosen if c.session[i] == 1]
    assert len(star_steps) == 20 and all(c.episode[i] == 1 for i in star_steps)
    assert len(chosen) - 20 == 20                                    # replay is half of the result


@pytestmark_np
def test_policy_actor_sends_changes_and_smooth_mouse():
    from star.play.humanlike import Actuator, RecordingSink
    from star.play.learn.adapter import PolicyAction, PolicyActor
    actor = PolicyActor(Actuator(RecordingSink(clock=lambda: 0.0)), period=0.05, rng=random.Random(1))
    first = actor.events(PolicyAction(frozenset({"w", "d"}), frozenset({"right"}), 40.0, -6.0), 10.0)
    downs = sorted(e.a for e in first if e.kind == "key_down")
    assert downs == ["d", "w"] and any(e.kind == "button_down" for e in first)
    moves = [e for e in first if e.kind == "move_rel"]
    assert sum(e.a for e in moves) == 40 and sum(e.b for e in moves) == -6
    assert all(10.0 < e.t <= 10.05 + 1e-9 for e in moves)
    steps = [abs(e.a) for e in moves]
    assert max(steps[len(steps) // 3: 2 * len(steps) // 3]) > steps[0]  # slow-fast-slow, not constant speed
    second = actor.events(PolicyAction(frozenset({"w"}), frozenset(), 0.0, 0.0), 10.05)
    assert sorted((e.kind, e.a) for e in second) == [("button_up", "right"), ("key_up", "d")]


# ---- tiny policy on the CPU (torch) -------------------------------------------------------------------------------

def _dot_corpus(tmp_path, episodes=60, eps=0.0):
    from star.play.learn.dataset import Corpus
    from star.play.learn.recorder import sessions
    from star.play.learn.synthetic import dot_spec, record_demos
    spec = dot_spec((16, 9))
    record_demos(tmp_path / "recordings", spec, episodes, eps=eps, seed=3)
    return spec, Corpus.from_sessions(sessions(tmp_path / "recordings", spec.game))


@pytestmark_np
def test_tiny_policy_learns_the_fake_game_on_cpu(tmp_path):
    torch = pytest.importorskip("torch")
    from star.play.learn.policy import TrainConfig, build, evaluate as val_metrics, load_policy, train
    spec, corpus = _dot_corpus(tmp_path)
    _, val = corpus.split()
    torch.manual_seed(0)
    before = val_metrics(build(spec, (8, 16), 64), corpus, val, torch.device("cpu"))
    cfg = TrainConfig(steps=120, batch=32, eval_every=40, widths=(8, 16), hidden=64, device="cpu", lr=2e-3)
    summary = train(corpus, tmp_path / "m", cfg, log=lambda s: None)
    model, ckpt = load_policy(tmp_path / "m" / "best.pt", torch.device("cpu"))
    after = val_metrics(model, corpus, val, torch.device("cpu"))
    assert summary["params"] < 200_000 and ckpt["spec"]["game"] == "synthetic_dot"
    assert after["loss"] < 0.8 * before["loss"]
    assert after["mouse_within1"] > before["mouse_within1"]
    assert (tmp_path / "m" / "metrics.jsonl").read_text().count("\n") == 3


@pytestmark_np
def test_policy_controller_limits_and_reflex_session_records_her_play(tmp_path):
    torch = pytest.importorskip("torch")
    from star.play.capture import FakeFrames
    from star.play.humanlike import RecordingSink
    from star.play.learn.adapter import FrameObserver, PolicyController, reflex_session
    from star.play.learn.policy import build, load_policy, save, TrainConfig
    from star.play.learn.recorder import Recorder, load_session
    from star.play.planner import Goal
    spec = _spec(mouse_max=50.0)
    save(build(spec, (8,), 32), spec, {"abs_delta_p99": 12.0}, {}, tmp_path / "p.pt", TrainConfig())
    model, ckpt = load_policy(tmp_path / "p.pt", torch.device("cpu"))
    ctl = PolicyController(model, ckpt, rng=random.Random(0), min_toggle_s=0.06)
    flip = {"n": 0}

    def probs(stack):
        flip["n"] += 1
        on = float(flip["n"] % 2)
        outer = np.zeros(spec.mouse_bins)
        outer[-1] = 1.0
        return {"keys": np.array([on, 0, 0, 0]), "buttons": np.array([0.0]), "mx": outer, "my": outer[::-1].copy()}

    ctl.probabilities = probs
    obs = FrameObserver(FakeFrames(lambda i: np.zeros((9, 16, 3), np.uint8)), spec)()
    held = []
    for tick in range(12):                                   # 20 ms ticks: the policy asks to flip W every tick
        action = ctl.decide(obs, Goal("play"), tick * 0.02)[0]
        held.append("w" in action.keys)
        assert action.dx == 12.0 and action.dy == -12.0      # capped at the human p99 speed, not 50 px
    flips = sum(a != b for a, b in zip(held, held[1:]))
    assert 2 <= flips <= 4                                   # at most one flip per 60 ms
    assert ctl.decide(obs, Goal("wait"), 1.0)[0].keys == frozenset()

    rec = Recorder(spec, consent="test", who="star", root=tmp_path / "rec", notify=lambda s: None).start()
    sink = RecordingSink(clock=lambda: 0.0)
    frames = FakeFrames(lambda i: np.full((9, 16, 3), i, np.uint8))
    session = reflex_session(tmp_path / "p.pt", source=frames, sink=sink, recorder=rec, device=torch.device("cpu"))
    for _ in range(6):
        session.fast.tick()
        session.actuator.pump(now=1e9)
    session.fast.on_moment[0]("checkpoint", 0.0)
    assert session.fast.ticks == 6 and session.fast.goal.name == "play"
    s = load_session(rec.stop())
    assert len(s["frames"]) == 5 and s["meta"]["who"] == "star" and s["meta"]["markers"][0]["kind"] == "checkpoint"
    sent_dx = sum(c[1] for c in sink.calls if c[0] == "move_rel")
    assert sent_dx != 0 and float(s["delta"][:, 0].sum()) != 0     # her own mouse moves are in the labels
    assert set(s["mouse"][:, 0].tolist()) <= set(range(spec.mouse_bins))


@pytestmark_np
def test_self_improvement_round_promotes_only_through_the_eval_gate(tmp_path):
    torch = pytest.importorskip("torch")
    from star.play.learn.adapter import PolicyController
    from star.play.learn.improve import improve, models_dir, promote
    from star.play.learn.policy import TrainConfig, load_policy, train
    from star.play.learn.recorder import Recorder
    from star.play.learn.synthetic import play, policy_act
    spec, corpus = _dot_corpus(tmp_path, episodes=40, eps=0.3)
    tiny = dict(batch=32, widths=(8, 16), hidden=64, device="cpu")
    train(corpus, tmp_path / "base", TrainConfig(steps=60, eval_every=60, lr=2e-3, **tiny), log=lambda s: None)
    assert improve(spec.game, tmp_path, lambda c: None)["why"].startswith("no current policy")
    promote(tmp_path / "base" / "best.pt", spec.game, tmp_path, {"why": "base"})
    model, ckpt = load_policy(models_dir(tmp_path, spec.game) / "current.pt", torch.device("cpu"))
    rec = Recorder(spec, consent="test", who="star", root=tmp_path / "recordings", notify=lambda s: None,
                   session_id="star-1").start()
    play(spec, 30, policy_act(PolicyController(model, ckpt, rng=random.Random(2))), seed=9, recorder=rec)
    rec.stop()
    calls = []

    def attempt_for(path):
        calls.append(path.name)
        good = len(calls) == 2                               # the candidate is evaluated second
        return lambda i: Attempt(good or i == 0, 1.0, 1.0)

    report = improve(spec.game, tmp_path, attempt_for, n_eval=4, cfg=TrainConfig(steps=20, eval_every=20, **tiny),
                     min_success_steps=10, log=lambda s: None)
    assert report["done"] and report["promoted"] and calls == ["current.pt", "best.pt"]
    base = models_dir(tmp_path, spec.game)
    assert (base / "previous.pt").exists()
    receipt = json.loads((base / "receipts.jsonl").read_text().splitlines()[-1])
    assert receipt["incumbent_rate"] == 0.25 and receipt["candidate_rate"] == 1.0
    assert [r["successes"] for r in history(spec.game, tmp_path)] == [1, 4]
    worse = improve(spec.game, tmp_path, lambda p: (lambda i: Attempt(p.name == "current.pt", 1.0, 1.0)), n_eval=3,
                    cfg=TrainConfig(steps=10, eval_every=10, **tiny), min_success_steps=10, log=lambda s: None)
    assert worse["done"] and not worse["promoted"]
    assert (base / "receipts.jsonl").read_text().count("\n") == 2   # base + the one promotion
