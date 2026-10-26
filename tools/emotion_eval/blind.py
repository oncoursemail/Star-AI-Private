"""Pair the off/on replies in a seeded random A/B order. Writes emotion_blind.txt (what the judge reads: no arm labels)
and emotion_key.json (do NOT open before scoring). Scenarios with no tone note are identical prompts in both arms; they
are still paired (a control: any score gap there is sampling noise)."""
import json, random, sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from scenarios import S
rows = json.load(open(sys.argv[1] if len(sys.argv) > 1 else 'emotion_gen.json', encoding='utf-8'))
by = {(r['i'], r['rep'], r['arm']): r['reply'].strip() for r in rows}
reps = sorted({r['rep'] for r in rows})
rng = random.Random(20261026)
items, key, n = [], {}, 0
for rep in reps:
    for i, sc in enumerate(S):
        n += 1
        flip = rng.random() < 0.5
        a, b = (by[(i, rep, 'on')], by[(i, rep, 'off')]) if flip else (by[(i, rep, 'off')], by[(i, rep, 'on')])
        key[n] = {'A': 'on' if flip else 'off', 'B': 'off' if flip else 'on', 'i': i, 'rep': rep, 'control': not any(r['tone'] for r in rows if r['i'] == i and r['arm'] == 'on')}
        hist = ' / '.join(('Owner: ' if r == 'user' else 'STAR: ') + t for r, t in sc['hist']) or '(start of chat)'
        items.append(f"#{n}\nEARLIER: {hist}\nWHAT HAPPENED: {sc['name'].replace('_', ' ')}\nOWNER SAYS: {sc['user']}\n[A] {a}\n[B] {b}\n")
open('emotion_blind.txt', 'w', encoding='utf-8').write('\n'.join(items))
json.dump(key, open('emotion_key.json', 'w'))
print(n, 'pairs written')
