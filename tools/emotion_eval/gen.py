"""Generate replies for the 20 scenarios, emotion off vs on, on the live brain (voice persona, star-voice, thinking off).
Run only when brain 1 is free:   STAR_BRAIN_URL=http://<brain>:8080/v1 python tools/emotion_eval/gen.py [reps] [out.json]
`--dry` uses a stub instead of the brain (checks the pipeline). The key is read from ~/.star/server_api_key, never printed."""
import json, os, sys, tempfile, time, urllib.request, pathlib
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import build
from scenarios import S

DRY = '--dry' in sys.argv
args = [a for a in sys.argv[1:] if not a.startswith('--')]
REPS = int(args[0]) if args else 2
OUT = args[1] if len(args) > 1 else 'emotion_gen.json'

def post(messages):
    if DRY:
        return {'choices': [{'message': {'content': 'Okay. Stub reply.'}}], 'usage': {'prompt_tokens': 0}}
    url = os.environ['STAR_BRAIN_URL'].rstrip('/') + '/chat/completions'
    key = pathlib.Path.home().joinpath('.star/server_api_key').read_text().strip()
    body = {'model': 'star-voice', 'messages': messages, 'max_tokens': 220, 'temperature': 0.7, 'top_p': 0.9,
            'cache_prompt': True, 'chat_template_kwargs': {'preserve_thinking': True, 'enable_thinking': False}}
    req = urllib.request.Request(url, data=json.dumps(body).encode(), headers={'Authorization': 'Bearer ' + key, 'Content-Type': 'application/json'})
    return json.load(urllib.request.urlopen(req, timeout=300))

rows = []
with tempfile.TemporaryDirectory() as d:
    for i, sc in enumerate(S):
        t = time.perf_counter()
        state = build.state_for(sc, d)
        local_ms = (time.perf_counter() - t) * 1000
        for rep in range(REPS):
            for arm in ('off', 'on'):
                tone = state['directive'] if arm == 'on' else ''
                t = time.perf_counter()
                reply = post(build.messages(sc, tone))['choices'][0]['message'].get('content') or ''
                rows.append({'i': i, 'name': sc['name'], 'rep': rep, 'arm': arm, 'tone': bool(tone), 'reply': reply,
                             'secs': round(time.perf_counter() - t, 2), 'state_ms': round(local_ms, 1)})
                json.dump(rows, open(OUT, 'w', encoding='utf-8'), indent=1, ensure_ascii=False)
print('done', len(rows), 'replies ->', OUT)
