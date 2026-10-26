"""Turn a scenario into the engine state and the two message lists (off / on), exactly as the voice call builds them."""
import os, sys, tempfile
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from star import emotion
from star.emotion import EmotionEngine
from star.voice.persona import system_message
from scenarios import S, HOUR


class Clock:
    now = 1_800_000_000.0
    def __call__(self): return self.now


def state_for(sc, directory):
    clock = Clock()
    engine = EmotionEngine(os.path.join(directory, sc['name'] + '.sqlite3'), clock=clock)
    person = sc.get('person')
    engine.on_event('owner_message', person=person)
    if sc.get('bond'):      # an established friend, set directly (not 40 scripted chats that would leave pride and joy behind)
        engine._transaction(lambda state, now: state['bonds'].update({person: [sc['bond'], now]}))
    clock.now += 600
    for step in sc['events']:
        if step[0] == 'wait':
            clock.now += step[1] * HOUR
        elif step[0] == 'msg':
            clock.now += 30; engine.on_message(step[1], person=person)
        else:
            clock.now += 30; engine.on_event(step[1], person=person, **step[2])
    return engine.snapshot(person, sc.get('adult'))


def messages(sc, tone):
    m = [system_message()]
    m += [{'role': r, 'content': t} for r, t in sc['hist']]
    content = sc['user'] + (f"\n\n{emotion.note_line(tone)}" if tone else '')
    m.append({'role': 'user', 'content': content})
    return m


if __name__ == '__main__':      # offline check: what each scenario would add (no brain needed)
    with tempfile.TemporaryDirectory() as d:
        for sc in S:
            st = state_for(sc, d)
            print(f"{sc['name']:34} dominant={st['dominant']}  avatar={st['avatar']['face']}  bond={st['bond']}\n   {st['directive'] or '(no note: identical prompt in both arms)'}")
