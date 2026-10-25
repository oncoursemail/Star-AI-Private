"""Standalone deterministic host simulator; NO actual game or streamer."""
import unittest
from star.game_navigation import GameFrame, SeenTile
from star.game_closed_loop import ClosedLoopPilot, PracticeScope


def observed(seq=1, player=(0, 0), *, world=("...", "...", "..G"),
             game="sim", session="owner_trial"):
    height, width = len(world), len(world[0])
    visible = []
    for x, y in ((player[0], player[1]), (player[0] - 1, player[1]),
                 (player[0] + 1, player[1]), (player[0], player[1] - 1),
                 (player[0], player[1] + 1)):
        if 0 <= x < width and 0 <= y < height:
            code = world[y][x]
            kind = "wall" if code == "#" else "hazard" if code == "!" else (
                "goal" if code == "G" else "floor")
            visible.append(SeenTile((x, y), kind))
    return GameFrame(game, session, seq, width, height, player, tuple(visible))


def scope(**kw):
    return PracticeScope("sim", "owner_trial", 3, 3, mode="practice",
                         sandbox_approved=True, **kw)


class ClosedLoopTests(unittest.TestCase):
    def test_opt_in_scopes(self):
        with self.assertRaises(PermissionError):
            PracticeScope("sim", "owner_trial", 3, 3, mode="practice")
        for kw in ({"width": True}, {"width": 65}, {"game": "bad string"},
                   {"max_actions": 0}, {"ticket_ttl_ms": 0},
                   {"max_frame_age_ms": 0}, {"action_timeout_ms": 0}):
            params = dict(game="sim", session="owner_trial", width=3, height=3)
            params.update(kw)
            with self.subTest(kw=kw), self.assertRaises(ValueError):
                PracticeScope(**params)
        with self.assertRaises(ValueError):
            PracticeScope("sim", "owner_trial", 3, 3, mode="unknown")

    def test_type_and_trusted_observation(self):
        with self.assertRaises(TypeError):
            ClosedLoopPilot("bad")
        p = ClosedLoopPilot(scope())
        with self.assertRaises(PermissionError):
            p.observe(observed(), observed_ms=0)
        with self.assertRaises(TypeError):
            p.observe("bad", observed_ms=0, trusted_host=True)
        with self.assertRaises(ValueError):
            p.observe(observed(session="another"), observed_ms=0, trusted_host=True)
        self.assertEqual(p.summary()["frames"], 0)

    def test_requires_one_observation_per_dispatch(self):
        p = ClosedLoopPilot(scope())
        self.assertIsNone(p.offer(now_ms=0))
        p.observe(observed(), observed_ms=0, trusted_host=True)
        ticket = p.offer(now_ms=1)
        self.assertIsNotNone(ticket)
        self.assertIsNone(p.offer(now_ms=1))
        with self.assertRaises(PermissionError):
            p.acknowledge_dispatched(ticket.ticket, now_ms=2)
        self.assertFalse(p.acknowledge_dispatched(999, now_ms=2, host_dispatched=True))
        self.assertTrue(p.acknowledge_dispatched(ticket.ticket, now_ms=2, host_dispatched=True))
        self.assertFalse(p.acknowledge_dispatched(ticket.ticket, now_ms=2, host_dispatched=True))
        self.assertIsNone(p.offer(now_ms=3))
        r = p.observe(observed(2, ticket.destination), observed_ms=4, trusted_host=True)
        self.assertTrue(r.movement_verified)
        self.assertEqual(p.summary()["movements_verified"], 1)
        self.assertIsNotNone(p.offer(now_ms=4))

    def test_stale_frames_and_time(self):
        p = ClosedLoopPilot(scope())
        p.observe(observed(), observed_ms=20, trusted_host=True)
        with self.assertRaises(ValueError):
            p.observe(observed(), observed_ms=21, trusted_host=True)
        with self.assertRaises(ValueError):
            p.offer(now_ms=19)
        with self.assertRaises(ValueError):
            p.offer(now_ms=True)
        self.assertIsNone(p.offer(now_ms=2_000))
        self.assertEqual(p.summary()["actions_dispatched"], 0)

    def test_ticket_expiry_fails_closed(self):
        p = ClosedLoopPilot(scope(ticket_ttl_ms=4))
        p.observe(observed(), observed_ms=10, trusted_host=True)
        ticket = p.offer(now_ms=12)
        self.assertFalse(p.acknowledge_dispatched(ticket.ticket, now_ms=17, host_dispatched=True))
        self.assertEqual(p.summary()["actions_dispatched"], 0)
        self.assertIsNotNone(p.offer(now_ms=18))

    def test_host_can_reject_and_stop(self):
        p = ClosedLoopPilot(scope())
        p.observe(observed(), observed_ms=0, trusted_host=True)
        t = p.offer(now_ms=1)
        p.stop("host_rejected")
        self.assertFalse(p.acknowledge_dispatched(t.ticket, now_ms=2, host_dispatched=True))
        self.assertIsNone(p.offer(now_ms=2))
        with self.assertRaises(RuntimeError):
            p.observe(observed(2), observed_ms=3, trusted_host=True)
        self.assertEqual(p.summary()["stopped_reason"], "host_rejected")
        with self.assertRaises(ValueError):
            p.stop("undocumented")

    def test_blocked_latches_fail_closed(self):
        p = ClosedLoopPilot(scope())
        p.observe(observed(), observed_ms=0, trusted_host=True)
        t = p.offer(now_ms=1)
        p.acknowledge_dispatched(t.ticket, now_ms=2, host_dispatched=True)
        r = p.observe(observed(2, (0, 0)), observed_ms=3, trusted_host=True)
        self.assertEqual(r.stopped_reason, "movement_mismatch")
        self.assertEqual(p.summary()["movements_verified"], 0)
        self.assertIsNone(p.offer(now_ms=4))

    def test_timeout_latches_fail_closed(self):
        p = ClosedLoopPilot(scope(action_timeout_ms=2))
        p.observe(observed(), observed_ms=0, trusted_host=True)
        t = p.offer(now_ms=1)
        p.acknowledge_dispatched(t.ticket, now_ms=2, host_dispatched=True)
        r = p.observe(observed(2, t.destination), observed_ms=5, trusted_host=True)
        self.assertEqual(r.stopped_reason, "action_timeout")
        self.assertFalse(r.movement_verified)

    def test_uncommanded_move_latches(self):
        p = ClosedLoopPilot(scope())
        p.observe(observed(), observed_ms=0, trusted_host=True)
        p.observe(observed(2, (0, 1)), observed_ms=1, trusted_host=True)
        self.assertEqual(p.stopped_reason, "uncommanded_move")

    def test_pending_ticket_invalidated_by_new_frame(self):
        p = ClosedLoopPilot(scope())
        p.observe(observed(), observed_ms=0, trusted_host=True)
        t = p.offer(now_ms=1)
        p.observe(observed(2), observed_ms=2, trusted_host=True)
        self.assertFalse(p.acknowledge_dispatched(t.ticket, now_ms=2, host_dispatched=True))
        self.assertIsNotNone(p.offer(now_ms=2))

    def test_play_wont_guess_unknown_world(self):
        p = ClosedLoopPilot(PracticeScope("sim", "owner_trial", 3, 3))
        p.observe(observed(), observed_ms=0, trusted_host=True)
        self.assertIsNone(p.offer(now_ms=0))

    def test_hazards_not_offered(self):
        p = ClosedLoopPilot(scope())
        world = ("S#!", "###", "..G")
        p.observe(observed(world=world), observed_ms=0, trusted_host=True)
        self.assertIsNone(p.offer(now_ms=0))

    def test_budget_prevents_runaway_play(self):
        p = ClosedLoopPilot(scope(max_actions=1))
        p.observe(observed(), observed_ms=0, trusted_host=True)
        t = p.offer(now_ms=1)
        p.acknowledge_dispatched(t.ticket, now_ms=2, host_dispatched=True)
        p.observe(observed(2, t.destination), observed_ms=3, trusted_host=True)
        self.assertIsNone(p.offer(now_ms=4))
        self.assertEqual(p.stopped_reason, "action_budget_exhausted")

    def test_goal_is_verified_before_announcing(self):
        world = ("SG.", "...", "...")
        p = ClosedLoopPilot(scope())
        p.observe(observed(world=world), observed_ms=0, trusted_host=True)
        ticket = p.offer(now_ms=1)
        self.assertEqual(ticket.destination, (1, 0))
        p.acknowledge_dispatched(ticket.ticket, now_ms=2, host_dispatched=True)
        r = p.observe(observed(2, (1, 0), world=world), observed_ms=3, trusted_host=True)
        self.assertTrue(r.goal_reached)
        self.assertEqual(p.stopped_reason, "goal_reached")
        self.assertIsNone(p.offer(now_ms=4))

    def test_host_simulation_multiple_unseen_maps(self):
        maps = (
            ("S..", "##.", ".#G"),
            ("S.#", "...", "#.G"),
            ("S..", ".#.", "..G"),
            ("S.#", "..#", "..G"),
        )
        for world in maps:
            with self.subTest(world=world):
                p = ClosedLoopPilot(scope(max_actions=60))
                pos = (0, 0)
                for seq in range(1, 61):
                    frame = observed(seq, pos, world=world)
                    receipt = p.observe(frame, observed_ms=seq * 10,
                                        trusted_host=True)
                    if receipt.goal_reached:
                        break
                    ticket = p.offer(now_ms=seq * 10 + 1)
                    self.assertIsNotNone(ticket, f"stuck: {world} {p.summary()}")
                    self.assertTrue(p.acknowledge_dispatched(
                        ticket.ticket, now_ms=seq * 10 + 2, host_dispatched=True))
                    pos = ticket.destination
                    self.assertNotIn(world[pos[1]][pos[0]], "#!")
                else:
                    self.fail("Did not reach simulator goal")
                self.assertEqual(world[pos[1]][pos[0]], "G")
                self.assertEqual(p.summary()["actions_dispatched"],
                                 p.summary()["movements_verified"])


if __name__ == "__main__":
    unittest.main()
