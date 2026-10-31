"""Real production code (CallSession._generate_and_speak + SentenceChunker + ServerBrain) against the live brain,
fake TTS/speaker. STAR_BRAIN_URL=http://<brain>:8080/v1, key from ~/.star/server_api_key (never printed).
usage: python tools/human_voice_eval/voice_e2e.py <guard on|off> <reps> <out.json> [stress]
  guard off = the code before this change (no plan filter); stress = the six plan-prone prompts in stress.py."""
import sys, json, re
import os
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..', 'tests'))
from common import *
guard, reps, out = sys.argv[1], int(sys.argv[2]), sys.argv[3]
stress = len(sys.argv) > 4 and sys.argv[4] == 'stress'
import star.voice.call as callmod
from star.voice.call import CallConfig, CallSession, _Reply
from star.voice.brain import ServerBrain
from star.voice import persona as P
from voice_fakes import Events, FakeASR, FakeSpeaker, FakeTTS, FakeVAD
if guard == 'off': callmod.leaked_reasoning = lambda s: False
BROAD = re.compile(r"\b(?:the user|user's|his message|i need to|i should|i must|let me (?:think|respond|craft|draft|recall)|i'll keep|i will keep|short warm reaction|full stop|persona|system prompt|instruction|reply to one|we need|respond with|they (?:want|ask|are asking)|first,? i|okay,? (?:so|let'?s)|the question is)", re.I)
import concurrent.futures as cf
def one(job):
    p, rep = job
    events, tts = Events(), FakeTTS(seconds_per_word=0.0001)
    brain = ServerBrain(os.environ['STAR_BRAIN_URL'], KEY, 'star-voice')
    s = CallSession(vad=FakeVAD(), asr=FakeASR({}), brain=brain, tts=tts, speaker=FakeSpeaker(), config=CallConfig(partial_transcripts=False), on_event=events)
    r = _Reply(1)
    msgs = s._context() + [{'role':'user','content':p}]
    s._generate_and_speak(r, msgs)
    brain.close()
    spoken = ' '.join(tts.spoken)
    return {'prompt':p,'rep':rep,'spoken':spoken,'raw':r.raw_text,'dropped':[e.get('retry') for e in events.of('reasoning_dropped')],'flag':bool(BROAD.search(spoken))}
from stress import PROMPTS_STRESS
jobs=[(p,i) for i in range(reps) for p in (PROMPTS_STRESS if stress else PROMPTS)]
with cf.ThreadPoolExecutor(2) as ex: rows=list(ex.map(one, jobs))
json.dump(rows, open(out,'w'), indent=1, ensure_ascii=False)
from collections import Counter
print(guard, 'stress' if stress else 'standard', 'n', len(rows), 'flagged', sum(r['flag'] for r in rows), 'guard fired', sum(bool(r['dropped']) for r in rows),
      'openers', Counter(r['spoken'].split('.')[0][:25] for r in rows).most_common(3))
