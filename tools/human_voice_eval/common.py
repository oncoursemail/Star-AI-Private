import json, pathlib, sys, time, urllib.request, re
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))  # repo root
BRAIN = os.environ['STAR_BRAIN_URL'].rstrip('/') + '/chat/completions'   # e.g. http://<brain>:8080/v1
KEY = pathlib.Path.home().joinpath('.star/server_api_key').read_text().strip()

def chat(messages, *, model='star-voice', max_tokens=600, temperature=0.6, extra=None, timeout=240):
    body = {'model': model, 'messages': messages, 'max_tokens': max_tokens, 'temperature': temperature,
            'extra_body': None}
    body.pop('extra_body')
    body.update({'cache_prompt': True, 'chat_template_kwargs': {'preserve_thinking': True, 'enable_thinking': False}})
    if extra: body.update(extra)
    req = urllib.request.Request(BRAIN, data=json.dumps(body).encode(), headers={'Authorization': 'Bearer ' + KEY, 'Content-Type': 'application/json'})
    t = time.monotonic()
    d = json.load(urllib.request.urlopen(req, timeout=timeout))
    dt = time.monotonic() - t
    m = d['choices'][0]['message']
    return {'content': m.get('content') or '', 'reasoning': m.get('reasoning_content') or '', 'secs': round(dt, 2),
            'usage': d.get('usage'), 'finish': d['choices'][0].get('finish_reason')}

LIVE = """[Your live status at 21:40 owner-local, from your own systems]
- brain 1: night school running; today 41 tries, 20 passed; conductor night 12: 30 of 186 new practice tasks accepted; knowledge search ok
- brain 2: services up, no reports
- work: 3 items claimed in 6 h (human-voice, eval-power, laptop-embed); 4 PRs merged today; 11 open, 1 with failing checks
- night school 20 answers per active hour; your last chat reply started after 0.8 s (star-voice)"""
CLOCK = "(It is Sunday 25 October 2026, 21:41 in the owner's time zone.)"

PROMPTS = [
 "hey star, how's your evening going?",
 "what did you learn today?",
 "tell me a joke about debugging",
 "i'm tired, been coding since 9am",
 "what are you working on right now?",
 "is night school still running?",
 "thanks for the help earlier, that fix worked",
 "do you prefer tabs or spaces? pick one",
 "what should i have for dinner",
 "did anything break while i was out?",
 "are you actually an AI or something else? be honest",
 "give me a one line pep talk before i push this PR",
 "how fast are you answering lately?",
 "i think my brain 2 setup is slow, thoughts?",
 "what's your favourite part of your own work",
 "ok good night star",
 "can you remind me what we decided about the persona?",
 "why do you like practising luau so much",
 "say something nice about my code",
 "what's the weather like where you are",
]

def build(prompt, system=None):
    from star.discord_bot.brain import system_prompt
    sysmsg = system if system is not None else system_prompt()
    return [{'role': 'system', 'content': sysmsg}, {'role': 'user', 'content': prompt + '\n\n' + CLOCK + '\n\n' + LIVE}]

# broad meta-text detector (superset of persona._REASONING)
META = re.compile(r"\b(?:the user (?:is |wants|asks|said|just|wrote|says|seems)|user wants|they(?:'re| are) asking|"
                  r"i should\b|i need to\b|let me (?:think|respond|answer|check|craft|write|see|figure)|"
                  r"i'll (?:respond|answer|reply|say|keep|go with)|i will (?:respond|answer|reply)|"
                  r"we need to|we should|the (?:owner|user) (?:asks|asked|wants)|my (?:reply|response|answer) (?:should|will|is)|"
                  r"(?:first|okay|ok|so),? (?:the user|i)\b|status (?:block|line)|live status|keep it short|"
                  r"possible (?:reply|response)|draft:|reply:|response:)", re.I)
def meta(text):
    from star.persona import leaked_reasoning
    return bool(META.search(text)) or leaked_reasoning(text) or '<think>' in text.lower()
