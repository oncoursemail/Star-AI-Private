import json, random
import autobio_set
rows = json.load(open('autobio_gen.json'))
by = {}
for r in rows: by[(r['i'], r['rep'], r['arm'])] = r['reply'].strip()
rng = random.Random(20261025)
items, key = [], {}
n = 0
for rep in range(2):
    for i, c in enumerate(autobio_set.C):
        n += 1
        flip = rng.random() < 0.5
        a, b = (by[(i,rep,'on')], by[(i,rep,'off')]) if flip else (by[(i,rep,'off')], by[(i,rep,'on')])
        key[n] = {'A': 'on' if flip else 'off', 'B': 'off' if flip else 'on', 'i': i, 'rep': rep}
        hist = ' / '.join(('You: ' if role=='user' else 'STAR: ') + t for role, t in c['history'])
        items.append(f"#{n}\nEARLIER: {hist}\nQUESTION: {c['q']}\nMUST RESPECT: {c['fact']}\n[A] {a}\n[B] {b}\n")
open('autobio_blind.txt','w',encoding='utf-8').write('\n'.join(items))
json.dump(key, open('autobio_key.json','w'))
print(n, 'pairs written')
