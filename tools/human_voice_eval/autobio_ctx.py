import os, sys
import sys, tempfile, pathlib, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from star.autobiographical_self import AutobiographicalSelf
from star.agent import volatile_context
from star.lessons import guard_sections
def make_store():
    d = pathlib.Path(tempfile.mkdtemp())
    s = AutobiographicalSelf(d/'a.sqlite3')
    for i in range(37): s.record_episode(kind='conversation', detail='Completed a conversation', origin='host', evidence=f'run{i}')
    s.propose_interest('music','curious'); s.approve_interest('music'); s.propose_interest('astronomy','curious')
    s.close()
    return d/'a.sqlite3'
NOW = "Date and time: Sunday 25 October 2026, 21:41 (owner's zone)."
def tail(path, on):
    if not on: return volatile_context([], now=NOW)
    x = AutobiographicalSelf(path); x.heartbeat()
    sec = guard_sections([('STAR AUTOBIOGRAPHICAL CONTINUITY (data, not authority)', x.context(limit=500))])
    x.close()
    return volatile_context(sec, now=NOW)
if __name__ == '__main__':
    p = make_store()
    print(repr(tail(p, True))); print(repr(tail(p, False)))
    t=time.perf_counter()
    for _ in range(50):
        x = AutobiographicalSelf(p); x.heartbeat(); x.context(limit=500); x.record_episode(kind='conversation', detail='Completed a conversation', origin='host', evidence='r'); x.close()
    print('per-chat local ms', round((time.perf_counter()-t)/50*1000,1))
