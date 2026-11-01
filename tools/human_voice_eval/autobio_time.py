# run under: star lock run ... -- python autobio_time.py   (quiet brain 1, one request at a time)
import json, time
import autobio_set, autobio_ctx
from autobio_gen import msgs, post, TAILS
out=[]
for i,c in enumerate(autobio_set.C[:12]):
    order = ('off','on') if i%2==0 else ('on','off')
    base = {'model':'star-voice','max_tokens':1,'temperature':0.0,'cache_prompt':True,'chat_template_kwargs':{'preserve_thinking':True}}
    post({**base,'messages':msgs(c,'off')})            # primes the shared prefix (system + history)
    for arm in order:
        # a fresh clock value per request, like a real turn, so the tail is never already cached
        m = msgs(c,arm); m[-1]['content'] = m[-1]['content'].replace('21:41', f'21:{41+ (i%9)}:{len(out)%60:02d}')
        t=time.perf_counter(); d=post({**base,'messages':m}); wall=time.perf_counter()-t
        tm=d.get('timings',{})
        out.append({'i':i,'arm':arm,'wall_ms':round(wall*1000),'prompt_n':tm.get('prompt_n'),'cache_n':tm.get('cache_n'),'prompt_ms':tm.get('prompt_ms'),'prompt_tokens':d['usage']['prompt_tokens']}); json.dump(out, open('autobio_time.json','w'), indent=1)

import statistics as st
for arm in ('off','on'):
    r=[x for x in out if x['arm']==arm]
    print(arm,'median wall ms',st.median(x['wall_ms'] for x in r),'median prompt_ms',st.median(x['prompt_ms'] or 0 for x in r),'median new tokens',st.median(x['prompt_n'] or 0 for x in r))
