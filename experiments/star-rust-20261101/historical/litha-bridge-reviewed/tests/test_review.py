from __future__ import annotations
import json
import threading
import unittest
from types import SimpleNamespace
from unittest.mock import patch
from litha_bridge import BridgeConfig, ConfigError, GroundedBridge, LemonadeClient, ProviderError, SearchHit, AnythingLLMClient

class ReviewRegressionTests(unittest.TestCase):
    def client(self, **config):
        c = LemonadeClient(BridgeConfig(lemonade_enabled=True, **config))
        self.calls = []
        def request(method, route, **kw):
            self.calls.append((method, route, kw))
            if route == '/models':
                return {'data': [{'id': 'local', 'labels': ['chat']}]}
            return {'choices': [{'message': {'content': 'ok'}}]}
        c.transport = SimpleNamespace(request=request)
        return c

    def test_boolean_flags_are_strict(self):
        for name in ('lemonade_enabled', 'anythingllm_enabled', 'remote_enabled'):
            for value in ('false', 'true', 0, 1, None):
                with self.subTest(name=name, value=value), self.assertRaises(ConfigError):
                    BridgeConfig(**{name: value})

    def test_integer_limits_reject_boolean_and_fraction(self):
        for name in ('max_parallel_chat','max_search_results','max_context_characters','max_prompt_characters'):
            for value in (True, False, 1.5, '4'):
                with self.subTest(name=name,value=value), self.assertRaises(ConfigError):
                    BridgeConfig(**{name: value})

    def test_finite_timeouts_required(self):
        for name in ('timeout_seconds','queue_timeout_seconds'):
            for value in (float('nan'),float('inf'),True,'30',0,-1):
                with self.subTest(name=name,value=value), self.assertRaises(ConfigError):
                    BridgeConfig(**{name:value})

    def test_queue_has_bounded_wait_and_does_not_call_provider(self):
        c=self.client(queue_timeout_seconds=0.01)
        c._chat_slots.acquire()
        done=threading.Event(); errors=[]
        def run():
            try: c.chat('local',[{'role':'user','content':'hello'}])
            except Exception as exc: errors.append(exc)
            finally: done.set()
        worker=threading.Thread(target=run,daemon=True); worker.start()
        try:
            self.assertTrue(done.wait(2), 'admission wait did not time out')
            self.assertEqual(len(errors),1)
            self.assertIsInstance(errors[0],ProviderError)
            self.assertIn('queue wait expired', str(errors[0]))
            self.assertEqual(self.calls,[])
        finally:
            c._chat_slots.release(); worker.join(2)

    def test_slot_released_after_provider_error(self):
        c=self.client(queue_timeout_seconds=0.01)
        c.transport=SimpleNamespace(request=lambda *a,**k: {'data':None})
        with self.assertRaises(ProviderError): c.chat('local',[{'role':'user','content':'hi'}])
        self.assertTrue(c._chat_slots.acquire(blocking=False)); c._chat_slots.release()

    def test_slot_released_after_success(self):
        c=self.client(); c.chat('local',[{'role':'user','content':'hi'}])
        self.assertTrue(c._chat_slots.acquire(blocking=False)); c._chat_slots.release()

    def test_malformed_labels_are_sanitized_errors(self):
        for labels in (None,'chat','not-chat',{},[None],[1]):
            with self.subTest(labels=labels):
                c=self.client()
                c.transport=SimpleNamespace(request=lambda *a,**k: {'data':[{'id':'local','labels':labels}]})
                with self.assertRaisesRegex(ProviderError,'metadata is malformed'):
                    c.chat('local',[{'role':'user','content':'hi'}])

    def test_malformed_recipe_is_sanitized_error(self):
        c=self.client(); c.transport=SimpleNamespace(request=lambda *a,**k:{'data':[{'id':'local','labels':['chat'],'recipe':None}]})
        with self.assertRaises(ProviderError): c.models()

    def test_aggregate_prompt_cap_precedes_network(self):
        c=self.client(max_prompt_characters=200)
        with self.assertRaisesRegex(ConfigError,'Combined messages'):
            c.chat('local',[{'role':'user','content':'x'*110},{'role':'assistant','content':'y'*110}])
        self.assertFalse(self.calls)

    def test_exact_aggregate_cap_is_accepted(self):
        c=self.client(max_prompt_characters=200)
        self.assertEqual(c.chat('local',[{'role':'user','content':'x'*200}]).text,'ok')

    def test_boolean_token_cap_rejected(self):
        c=self.client()
        with self.assertRaises(ConfigError): c.chat('local',[{'role':'user','content':'hi'}],max_tokens=True)
        self.assertFalse(self.calls)

    def test_boolean_search_limit_rejected(self):
        c=AnythingLLMClient(BridgeConfig(anythingllm_enabled=True,anythingllm_api_key='test'))
        with self.assertRaises(ConfigError): c.vector_search('docs','q',top_n=True)

    def test_boolean_score_threshold_rejected(self):
        c=AnythingLLMClient(BridgeConfig(anythingllm_enabled=True,anythingllm_api_key='test'))
        with self.assertRaises(ConfigError): c.vector_search('docs','q',score_threshold=True)

    def test_returned_source_matches_exact_model_excerpt(self):
        hit=SearchHit('x'*5000,'doc','doc.md'); captured=[]
        r=SimpleNamespace(config=BridgeConfig(max_context_characters=1200), vector_search=lambda *a:[hit])
        def chat(model,messages,**kw):
            captured.append(json.loads(messages[1]['content']))
            return SimpleNamespace(text='supported [S1]', model=model)
        a=GroundedBridge(r,SimpleNamespace(chat=chat)).ask('docs','q',model='local')
        self.assertEqual(a.sources[0].text,captured[0]['retrieved_excerpts'][0]['excerpt'])
        self.assertEqual(len(a.sources[0].text),1200)
        self.assertEqual(len(hit.text),5000)

    def test_huge_citation_id_needs_review_instead_of_crashing(self):
        r=SimpleNamespace(config=BridgeConfig(), vector_search=lambda *a:[SearchHit('text','doc','doc')])
        g=SimpleNamespace(chat=lambda *a,**kw:SimpleNamespace(text='[S'+'9'*5000+']',model='local'))
        self.assertEqual(GroundedBridge(r,g).ask('docs','q',model='local').status,'needs_review')

    def test_noncanonical_citation_is_not_accepted(self):
        r=SimpleNamespace(config=BridgeConfig(), vector_search=lambda *a:[SearchHit('text','doc','doc')])
        for text in ('[S01]', '[S١]', '[S0]'):
            with self.subTest(text=text):
                g=SimpleNamespace(chat=lambda *a,**kw:SimpleNamespace(text=text,model='local'))
                self.assertEqual(GroundedBridge(r,g).ask('docs','q',model='local').status,'needs_review')

    def test_new_environment_options(self):
        with patch.dict('os.environ',{'LITHA_QUEUE_TIMEOUT':'0.5','LITHA_MAX_PROMPT_CHARS':'1234'},clear=True):
            cfg=BridgeConfig.from_env()
        self.assertEqual(cfg.queue_timeout_seconds,.5)
        self.assertEqual(cfg.max_prompt_characters,1234)

if __name__ == '__main__': unittest.main()
