import argparse, json, sys, time, threading
from pathlib import Path
from types import SimpleNamespace
parser=argparse.ArgumentParser(); parser.add_argument('--source', type=Path, required=True)
args=parser.parse_args(); sys.path.insert(0, str(args.source.resolve()))
from litha_bridge import BridgeConfig,LemonadeClient,GroundedBridge,SearchHit
results={}
class Retriever:
 config=BridgeConfig(max_context_characters=1200)
 def vector_search(self,*args): return [SearchHit('x'*5000,'source','source.md')]
class Generator:
 def chat(self,model,messages,**kwargs):
  self.payload=json.loads(messages[1]['content'])
  return SimpleNamespace(text='Answer [S1]',model=model)
g=Generator(); ans=GroundedBridge(Retriever(),g).ask('docs','question',model='local')
results['source_trace']={'sent_excerpt_characters':len(g.payload['retrieved_excerpts'][0]['excerpt']),'returned_source_characters':len(ans.sources[0].text)}
c=LemonadeClient(BridgeConfig(lemonade_enabled=True, timeout_seconds=0.2))
def fake(method,route,**kwargs):
 if route=='/models': return {'data':[{'id':'local','labels':['chat']}]}
 return {'choices':[{'message':{'content':'ok'}}]}
c.transport=SimpleNamespace(request=fake)
c._chat_slots.acquire(); done=threading.Event()
def run():
 try: c.chat('local',[{'role':'user','content':'hi'}])
 finally: done.set()
t=threading.Thread(target=run,daemon=True); t.start(); time.sleep(.3)
results['queue']={'socket_timeout_seconds':0.2,'still_waiting_after_seconds':0.3,'still_waiting':not done.is_set()}
c._chat_slots.release(); t.join(2)
c.transport=SimpleNamespace(request=lambda *a,**k:{'data':[{'id':'local','labels':None}]})
try: c.chat('local',[{'role':'user','content':'hi'}]); result='accepted'
except Exception as e: result=type(e).__name__
results['malformed_labels_result']=result
results['non_boolean_false_string_accepted']=bool(BridgeConfig(lemonade_enabled='false').lemonade_enabled)
print(json.dumps(results,indent=2))
