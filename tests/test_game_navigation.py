"""Symbolic game navigation regression tests; not a real Studio playtest."""
from __future__ import annotations
import unittest
from star.game_navigation import GameFrame, NavigationBelief, SeenTile

def frame(seq=1, player=(0, 0), tiles=None, *, width=5, height=5, game="g", session="s"):
    if tiles is None:
        tiles = {player: "floor"}
    return GameFrame(game, session, seq, width, height, player,
                     tuple(SeenTile(point, kind) for point, kind in tiles.items()))

class GameNavigationTests(unittest.TestCase):
    def test_initially_abstains(self):
        b = NavigationBelief()
        self.assertIsNone(b.advise().action)
        self.assertEqual(b.advise().reason, "awaiting_host_observation")

    def test_host_required(self):
        b = NavigationBelief()
        with self.assertRaises(PermissionError):
            b.observe(frame())
        with self.assertRaises(TypeError):
            b.observe("fake", trusted_host=True)

    def test_validation(self):
        cases = [dict(seq=0), dict(seq=True), dict(seq=10001),
                 dict(width=65), dict(width=0), dict(width=True),
                 dict(game="unsafe slash"), dict(session="x" * 65),
                 dict(player=(5, 0)), dict(player=(True, 0)),
                 dict(tiles={(0, 0): "wall"}), dict(tiles={(0, 0): "hazard"}),
                 dict(tiles={(0, 0): "unknown"})]
        for kw in cases:
            with self.subTest(kw=kw), self.assertRaises(ValueError):
                frame(**kw)

    def test_duplicate_and_capacity(self):
        with self.assertRaises(ValueError):
            GameFrame("g", "s", 1, 5, 5, (0, 0), 
                      (SeenTile((0, 0), "floor"), SeenTile((0, 0), "goal")))
        with self.assertRaises(ValueError):
            GameFrame("g", "s", 1, 5, 5, (0, 0),
                      tuple([SeenTile((0, 0), "floor")] * 257))
        with self.assertRaises(ValueError):
            GameFrame("g", "s", 1, 5, 5, (0, 0), (SeenTile((0, 0), "floor"), SeenTile((True,0), "goal")))

    def test_replay_identity(self):
        b = NavigationBelief()
        b.observe(frame(), trusted_host=True)
        for f in (frame(), frame(game="another", seq=2),
                  frame(session="another", seq=2), frame(width=6, seq=2)):
            with self.subTest(f=f), self.assertRaises(ValueError):
                b.observe(f, trusted_host=True)
        self.assertEqual(b.observed_cells, 1)
        b.observe(frame(seq=2), trusted_host=True)

    def test_play_does_not_guess(self):
        b = NavigationBelief()
        b.observe(frame(), trusted_host=True)
        self.assertIsNone(b.advise().action)
        self.assertIsNone(b.advise(mode="practice").action)
        self.assertIsNone(b.advise(mode="play", sandbox_approved=True).action)
        self.assertEqual(b.advise(mode="practice", sandbox_approved=True).action, "right")

    def test_observed_hazard_wall_block(self):
        b = NavigationBelief()
        b.observe(frame(width=2, height=2, tiles={
            (0, 0): "floor", (1, 0): "wall", (0, 1): "hazard"}), trusted_host=True)
        self.assertEqual(b.advise(mode="practice", sandbox_approved=True).reason, "no_safe_frontier")

    def test_finds_long_verified_route(self):
        b = NavigationBelief()
        b.observe(frame(tiles={(0, 0): "floor", (1, 0): "wall",
            (0, 1): "floor", (0, 2): "floor", (1, 2): "floor",
            (2, 2): "goal", (1, 1): "hazard"}), trusted_host=True)
        a = b.advise()
        self.assertEqual(a.action, "down")
        self.assertEqual(a.reason, "verified_route")
        self.assertEqual(a.path[-1], (2, 2))
        self.assertFalse(a.exploratory)

    def test_unknown_shortcut_rejected(self):
        b = NavigationBelief()
        b.observe(frame(tiles={(0, 0): "floor", (2, 0): "goal"}), trusted_host=True)
        self.assertIsNone(b.advise().action)
        self.assertEqual(b.advise(mode="practice", sandbox_approved=True).action, "right")

    def test_world_change(self):
        b = NavigationBelief()
        b.observe(frame(width=3, height=2, tiles={(0, 0): "floor",
            (1, 0): "floor", (2, 0): "goal", (0, 1): "floor",
            (1, 1): "floor", (2, 1): "floor"}), trusted_host=True)
        self.assertEqual(b.advise().action, "right")
        b.observe(frame(seq=2, width=3, height=2,
                         tiles={(0, 0): "floor", (1, 0): "wall"}), trusted_host=True)
        self.assertEqual(b.advise().action, "down")

    def test_goal(self):
        b = NavigationBelief()
        b.observe(frame(tiles={(0, 0): "goal"}), trusted_host=True)
        self.assertEqual(b.advise().reason, "goal_reached")

    def test_no_safe_frontier(self):
        b = NavigationBelief()
        b.observe(frame(width=1, height=1), trusted_host=True)
        self.assertEqual(b.advise(mode="practice", sandbox_approved=True).reason, "no_safe_frontier")

    def test_frontier_path_through_known_space(self):
        b = NavigationBelief()
        b.observe(frame(width=3, height=2, tiles={(0, 0): "floor",
            (1, 0): "floor", (0, 1): "hazard"}), trusted_host=True)
        a = b.advise(mode="practice", sandbox_approved=True)
        self.assertEqual(a.action, "right")
        self.assertTrue(a.exploratory)
        self.assertEqual(a.path[-1], (2, 0))

    def test_large_belief_has_bounded_frontier(self):
        b = NavigationBelief()
        # Fill most of a 64x64 map through legal snapshots, 256 cells max
        # per frame, all from the same host. Leave a right-side frontier.
        points = [(x, y) for y in range(64) for x in range(63)
                  if (x, y) != (0, 0)]
        for seq, start in enumerate(range(0, len(points), 255), start=1):
            visible = {(0, 0): "floor"}
            visible.update({p: "floor" for p in points[start:start + 255]})
            b.observe(frame(seq=seq, width=64, height=64, tiles=visible),
                      trusted_host=True)
        self.assertEqual(b.observed_cells, 63 * 64)
        move = b.advise(mode="practice", sandbox_approved=True)
        self.assertTrue(move.exploratory)
        self.assertEqual(move.path[-1][0], 63)
        self.assertIn(move.action, {"right", "down"})

    def test_idempotent_and_mode_validation(self):
        b = NavigationBelief()
        b.observe(frame(), trusted_host=True)
        self.assertEqual(b.advise(), b.advise())
        with self.assertRaises(ValueError):
            b.advise(mode="root")
        with self.assertRaises(ValueError):
            b.advise(sandbox_approved=1)

    def test_host_simulated_goal(self):
        # Independently-owned tiny fixture, unseen by NavigationBelief:
        world = ("S....#", "##.###", "...G.#", ".#....")
        goal = (3, 2)
        b = NavigationBelief()
        pos = (0, 0)
        moves = 0
        for seq in range(1, 80):
            tiles = {}
            for x, y in (pos, (pos[0] - 1, pos[1]), (pos[0] + 1, pos[1]),
                         (pos[0], pos[1] - 1), (pos[0], pos[1] + 1)):
                if 0 <= y < 4 and 0 <= x < 6:
                    tiles[(x, y)] = ("wall" if world[y][x] == "#" else
                                     "goal" if (x, y) == goal else "floor")
            b.observe(frame(seq=seq, player=pos, tiles=tiles, width=6, height=4),
                      trusted_host=True)
            advice = b.advise(mode="practice", sandbox_approved=True)
            if advice.reason == "goal_reached":
                break
            self.assertIsNotNone(advice.action)
            pos = advice.destination
            self.assertNotEqual(world[pos[1]][pos[0]], "#")
            moves += 1
        else:
            self.fail("Toy grid goal not reached")
        self.assertEqual(pos, goal)
        self.assertLess(moves, 40)

if __name__ == "__main__":
    unittest.main()
