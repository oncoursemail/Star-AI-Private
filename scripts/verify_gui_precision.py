"""Check desktop click planning without native input or changing gameplay profiles."""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from star.computer.hands import Hands
from star.play.humanlike import HumanProfile


class Clock:
    def __init__(self): self.t = 10.0
    def now(self): return self.t
    def sleep(self, delay): self.t += delay


class Sink:
    def __init__(self): self.pos, self.downs = (100, 100), []
    def position(self): return self.pos
    def move_to(self, x, y): self.pos = (x, y)
    def button(self, button, down):
        if down: self.downs.append(self.pos)
    def key(self, key, down): pass


def main():
    for seed in range(200):
        clock, sink = Clock(), Sink()
        hands = Hands(sink, seed=seed, clock=clock.now, sleep=clock.sleep)
        hands.click(500, 300, width=4)
        assert sink.downs == [(500, 300)], (seed, sink.downs)
    clock, sink = Clock(), Sink()
    explicit = HumanProfile(miss_p=1.0)
    hands = Hands(sink, profile=explicit, seed=3, clock=clock.now, sleep=clock.sleep)
    hands.click(500, 300, width=100)
    assert hands.profile is explicit and sink.downs != [(500, 300)]
    assert HumanProfile().miss_p == .04
    print('200 simulated GUI clicks land on their requested points; explicit/game profiles preserved. No native input.')


if __name__ == '__main__': main()
