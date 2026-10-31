"""Read blind scores and report. scores.json: {"1": [A_natural, A_consistent, A_appropriate, B_natural, B_consistent,
B_appropriate], ...} with 1-5 each, written by the judge from emotion_blind.txt before the key is opened.
Reports per arm means, pairs won (sum of the three), a two-sided sign test, and the same for the control pairs."""
import json, math, statistics as st, sys
scores = json.load(open(sys.argv[1] if len(sys.argv) > 1 else 'scores.json'))
key = json.load(open('emotion_key.json'))
arms = {'on': [[], [], []], 'off': [[], [], []]}
wins = {'on': 0, 'off': 0, 'tie': 0}
cwins = {'on': 0, 'off': 0, 'tie': 0}
for n, v in scores.items():
    k = key[n]
    for side, part in (('A', v[:3]), ('B', v[3:])):
        for d in range(3):
            arms[k[side]][d].append(part[d])
    sa, sb = sum(v[:3]), sum(v[3:])
    bucket = cwins if k['control'] else wins
    bucket['tie' if sa == sb else (k['A'] if sa > sb else k['B'])] += 1
for arm in ('on', 'off'):
    print(arm, 'natural %.2f consistent %.2f appropriate %.2f' % tuple(st.mean(x) for x in arms[arm]))
def sign(w, l):
    n = w + l
    return 1.0 if n == 0 else min(1.0, 2 * sum(math.comb(n, i) for i in range(max(w, l), n + 1)) / 2 ** n)
print('pairs with a tone note:', wins, 'sign test p =', round(sign(wins['on'], wins['off']), 3))
print('control pairs (identical prompt):', cwins)
