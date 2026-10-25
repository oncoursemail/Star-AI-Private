"""Opener variety of the voice persona, with the real CallSession path against the live brain (fake TTS/speaker).
usage: python tools/human_voice_eval/opener_eval.py <arm> <reps> <out.json> [threads]
  arm base      = production prompt and request (the prompt's own example phrases)
  arm described = varied_openers prompt (no example phrases), no per-turn note
  arm hint      = varied_openers prompt + the per-turn note (CallConfig.varied_openers, as shipped)
Each job is its own call at turn number = job index, so the note rotates the way it does on a call.
Prints and stores: distinct-opener rate, most common opener and its share, leaks (broad regex + persona.leaked_reasoning on
what was spoken), guard fired, check_reply problems, mean words, share of replies with a 2-5 word opener ending in a stop."""
import sys, json, re, os
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..', 'tests'))
from common import *
arm, reps, out = sys.argv[1], int(sys.argv[2]), sys.argv[3]
threads = int(sys.argv[4]) if len(sys.argv) > 4 else 2
import star.voice.call as callmod
from star.voice.call import CallConfig, CallSession, _Reply
from star.voice.brain import ServerBrain
from star.persona import check_reply
from voice_fakes import Events, FakeASR, FakeSpeaker, FakeTTS, FakeVAD
if arm == 'described': callmod.opener_hint = lambda *a, **k: ''
BROAD = re.compile(r"\b(?:the user|user's|his message|i need to|i should|i must|let me (?:think|respond|craft|draft|recall)|i'll keep|i will keep|short warm reaction|full stop|persona|system prompt|instruction|reply to one|we need|respond with|they (?:want|ask|are asking)|first,? i|okay,? (?:so|let'?s)|the question is|open with|just said)", re.I)
import concurrent.futures as cf
def one(job):
    idx, p, rep = job
    events, tts = Events(), FakeTTS(seconds_per_word=0.0001)
    brain = ServerBrain(os.environ['STAR_BRAIN_URL'], KEY, 'star-voice')
    s = CallSession(vad=FakeVAD(), asr=FakeASR({}), brain=brain, tts=tts, speaker=FakeSpeaker(),
                    config=CallConfig(partial_transcripts=False, varied_openers=arm != 'base'), on_event=events)
    r = _Reply(idx + 1)
    r.user_text = p
    s._generate_and_speak(r, s._turn_messages(r))
    brain.close()
    spoken = ' '.join(tts.spoken)
    return {'idx': idx, 'prompt': p, 'rep': rep, 'spoken': spoken, 'dropped': [e.get('retry') for e in events.of('reasoning_dropped')],
            'flag': bool(BROAD.search(spoken)) or meta(spoken), 'problems': check_reply(spoken, prompt=p)}
jobs, i = [], 0
for rep in range(reps):
    for p in PROMPTS:
        jobs.append((i, p, rep)); i += 1
with cf.ThreadPoolExecutor(threads) as ex: rows = list(ex.map(one, jobs))
def opener(t):
    first = re.split(r'(?<=[.!?])\s', t.strip(), 1)[0]
    return ' '.join(re.findall(r"[a-z']+", first.lower()))
for r in rows: r['opener'] = opener(r['spoken'])
from collections import Counter
c = Counter(r['opener'] for r in rows)
n = len(rows)
good = sum(1 for r in rows if 1 <= len(r['opener'].split()) <= 5 and re.match(r'.*[.!?]', r['spoken'].strip().split('\n')[0]))
summary = {'arm': arm, 'n': n, 'distinct': len(c), 'distinct_rate': round(len(c) / n, 3), 'top': c.most_common(5),
           'top_share': round(c.most_common(1)[0][1] / n, 3), 'leaks': sum(r['flag'] for r in rows),
           'guard_fired': sum(bool(r['dropped']) for r in rows), 'problems': sum(bool(r['problems']) for r in rows),
           'mean_words': round(sum(len(r['spoken'].split()) for r in rows) / n, 1), 'short_opener_share': round(good / n, 3)}
json.dump({'summary': summary, 'rows': rows}, open(out, 'w'), indent=1, ensure_ascii=False)
print(json.dumps(summary, ensure_ascii=False))
