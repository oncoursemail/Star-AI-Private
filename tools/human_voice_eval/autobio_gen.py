import json, sys, concurrent.futures as cf, urllib.request, time
from common import BRAIN, KEY
import autobio_set, autobio_ctx
from star.agent import FAST_RULES
store = autobio_ctx.make_store()
TAILS = {'off': autobio_ctx.tail(store, False), 'on': autobio_ctx.tail(store, True)}
def msgs(c, arm):
    m = [{'role':'system','content':FAST_RULES}]
    for role, text in c['history']: m.append({'role':role,'content':text})
    m.append({'role':'user','content':c['q'] + '\n\n' + TAILS[arm]})
    return m
def post(body):
    req = urllib.request.Request(BRAIN, data=json.dumps(body).encode(), headers={'Authorization':'Bearer '+KEY,'Content-Type':'application/json'})
    return json.load(urllib.request.urlopen(req, timeout=300))
def gen(job):
    i, arm, rep = job
    c = autobio_set.C[i]
    d = post({'model':'star-voice','messages':msgs(c,arm),'max_tokens':400,'temperature':0.6,'cache_prompt':True,'chat_template_kwargs':{'preserve_thinking':True}})
    return {'i':i,'arm':arm,'rep':rep,'reply':d['choices'][0]['message'].get('content') or ''}
if __name__ == '__main__':
    jobs = [(i,arm,r) for r in range(2) for i in range(len(autobio_set.C)) for arm in ('off','on')]
    with cf.ThreadPoolExecutor(2) as ex: rows = list(ex.map(gen, jobs))
    json.dump(rows, open('autobio_gen.json','w'), indent=1, ensure_ascii=False)
    print('done', len(rows))
