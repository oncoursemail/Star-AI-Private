"""Added latency of the tone note: wall time, prompt tokens and prompt-eval ms with the note vs without, one request at a
time on a quiet brain 1 (run under:  ./star.cmd lock run --owner claude --holder emotion-timing --server 1 -- python ...).
The engine itself (SQLite, no model call) is timed locally and printed first."""
import json, os, pathlib, statistics as st, sys, tempfile, time, urllib.request
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import build
from scenarios import S

def post(messages):
    url = os.environ['STAR_BRAIN_URL'].rstrip('/') + '/chat/completions'
    key = pathlib.Path.home().joinpath('.star/server_api_key').read_text().strip()
    body = {'model': 'star-voice', 'messages': messages, 'max_tokens': 1, 'temperature': 0.0, 'cache_prompt': True,
            'chat_template_kwargs': {'preserve_thinking': True, 'enable_thinking': False}}
    req = urllib.request.Request(url, data=json.dumps(body).encode(), headers={'Authorization': 'Bearer ' + key, 'Content-Type': 'application/json'})
    return json.load(urllib.request.urlopen(req, timeout=300))

with tempfile.TemporaryDirectory() as d:
    states = [build.state_for(sc, d) for sc in S]
    from star import emotion
    eng = emotion.EmotionEngine(os.path.join(d, 'cost.sqlite3'))
    t = time.perf_counter()
    for _ in range(100):
        eng.on_message('thanks, great job'); eng.on_event('voice_turn'); eng.snapshot()
    print('engine per turn (on_message + voice_turn + snapshot): %.1f ms' % ((time.perf_counter() - t) * 10))
    out = {'off': [], 'on': []}
    for i, (sc, state) in enumerate(zip(S, states)):
        if not state['directive']:
            continue
        for arm in (('off', 'on') if i % 2 == 0 else ('on', 'off')):
            m = build.messages(sc, state['directive'] if arm == 'on' else '')
            m[-1]['content'] += f'\n(It is {21 + i % 3}:{41 + i % 17}:{i % 60:02d}.)'      # a fresh tail every request
            post(build.messages(sc, ''))                                                 # prime the shared prefix
            t = time.perf_counter(); r = post(m); wall = time.perf_counter() - t
            tm = r.get('timings', {})
            out[arm].append({'wall_ms': round(wall * 1000), 'prompt_ms': tm.get('prompt_ms') or 0, 'prompt_tokens': r['usage']['prompt_tokens']})
for arm in ('off', 'on'):
    r = out[arm]
    print(arm, 'n', len(r), 'median wall ms', st.median(x['wall_ms'] for x in r), 'median prompt_ms', st.median(x['prompt_ms'] for x in r),
          'median prompt tokens', st.median(x['prompt_tokens'] for x in r))
json.dump(out, open('emotion_timing.json', 'w'), indent=1)
