"""Exercise Litha's actual verifier/repair/HTTP paths; synthetic source, no model or code execution."""
from __future__ import annotations

import asyncio
import http.client
import json
import sys
import tempfile
import threading
import unittest
import warnings
from http.server import ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "server"))
from mesh import router  # noqa: E402
from mesh.verify import core, eval_litha, json_code, python_code, service, source_limits  # noqa: E402
from mesh.verify.apidump import ApiIndex  # noqa: E402
sys.path.remove(str(ROOT / "server"))


class LanguageChecks(unittest.TestCase):
    def setUp(self):
        self.verifier = core.Verifier(ApiIndex({}))

    def test_python_fences_aliases_and_explicit_source_are_checked(self):
        for label in ("python", "py", "python3"):
            with self.subTest(label=label):
                result = self.verifier.verify(f"Example:\n```{label}\ndef square(x):\n    return x*x\n```\n")
                self.assertTrue(result["ok"])
                self.assertEqual([(row["language"], row["checked"]) for row in result["blocks"]], [("python", True)])
                self.assertTrue(self.verifier.verify("x = 1", label)["blocks"][0]["checked"])

    def test_python_syntax_and_answer_line_coordinates(self):
        result = self.verifier.verify("Explanation\n\n```python\nx = 1\ndef broken(:\n    pass\n```\n")
        self.assertFalse(result["ok"])
        self.assertTrue(result["needs_fix"])
        issue = result["blocks"][0]["problems"][0]
        self.assertEqual((issue["kind"], issue["line"], issue["answer_line"]), ("syntax", 2, 5))
        self.assertGreater(issue["column"], 0)
        self.assertIsNone(issue["name"])

    def test_python_compiler_checks_context_beyond_ast_parsing(self):
        for source in ("return 1", "break", "await work()", "nonlocal missing"):
            with self.subTest(source=source):
                issues, checked = python_code.check_python(source)
                self.assertTrue(checked)
                self.assertEqual(issues[0]["severity"], "error")

    def test_python_is_never_executed_and_imports_are_not_resolved(self):
        with tempfile.TemporaryDirectory(prefix="litha-no-exec-") as folder:
            sentinel = Path(folder) / "must-not-exist.txt"
            source = f"from pathlib import Path\nPath({str(sentinel)!r}).write_text('wrong')\nimport module_that_does_not_exist\n1 / 0\n"
            self.assertEqual(python_code.check_python(source), ([], True))
            self.assertFalse(sentinel.exists())
        self.assertEqual(python_code.check_python("def f(x: MissingType):\n    return unknown_name\n"), ([], True))

    def test_valid_python_warning_does_not_become_syntax_failure(self):
        with warnings.catch_warnings(record=True):
            warnings.simplefilter("always")
            self.assertEqual(python_code.check_python("same = 1 is 1"), ([], True))

    def test_source_limits_and_unicode_fail_without_compiler_or_model(self):
        for source in ("x" * (source_limits.MAX_SOURCE_BYTES + 1), "雪" * 22000, "\ud800"):
            with self.subTest(chars=len(source)), patch("builtins.compile", side_effect=AssertionError("must not compile")):
                issues, checked = python_code.check_python(source)
                self.assertFalse(checked)
                self.assertEqual(issues[0]["severity"], "error")
                self.assertIsNone(issues[0]["line"])
        calls = []
        report = self.verifier.fix("x" * (source_limits.MAX_SOURCE_BYTES + 1), lambda _msgs: calls.append(True), "python")
        self.assertFalse(report["ok"])
        self.assertTrue(report["verify"]["needs_fix"])
        self.assertFalse(report["verify"]["blocks"][0]["checked"])
        self.assertEqual((calls, report["rounds"]), ([], 0))

    def test_complexity_failures_are_not_reported_as_passes_or_model_repairs(self):
        for error in (RecursionError, MemoryError, OverflowError):
            with self.subTest(error=error.__name__), patch("builtins.compile", side_effect=error):
                issues, checked = python_code.check_python("x = 1")
                self.assertFalse(checked)
                self.assertEqual(issues[0]["kind"], "source_limit")
        self.assertFalse(python_code.check_python("(" * 300 + "1" + ")" * 300)[1])

    def test_general_json_accepts_all_top_level_value_kinds(self):
        for source in ('{"tick": ["game:tick"]}', '[1,"text",true,null]', '"text"', "42", "true", "null"):
            with self.subTest(source=source):
                self.assertEqual(json_code.check_json(source), ([], True))
                result = self.verifier.verify(f"```json\n{source}\n```\n")
                self.assertTrue(result["ok"])
                self.assertTrue(result["blocks"][0]["checked"])

    def test_json_errors_have_actual_line_and_column(self):
        result = self.verifier.verify('```json\n{\n  "a": 1,\n}\n```\n')
        issue = result["blocks"][0]["problems"][0]
        self.assertFalse(result["ok"])
        self.assertEqual((issue["kind"], issue["line"], issue["column"], issue["answer_line"]), ("syntax", 3, 1, 4))
        self.assertIsNone(issue["name"])

    def test_duplicate_decoded_keys_warn_without_placeholder_demotion(self):
        for source in ('{"x":1,"x":2}', '{"x":1,"\\u0078":2}', '{"X_POS":1,"X_POS":2}', '{"a":{"nested":1,"nested":2}}'):
            with self.subTest(source=source):
                result = self.verifier.verify(source, "json")
                self.assertTrue(result["ok"])
                self.assertTrue(result["needs_fix"])
                issue = result["blocks"][0]["problems"][0]
                self.assertEqual((issue["kind"], issue["severity"]), ("json_duplicate_key", "warning"))
                self.assertIsNone(issue["name"])
                self.assertIsNone(issue["line"])
        self.assertEqual(json_code.check_json('[{"x":1},{"x":2}]'), ([], True))

    def test_json_nonfinite_extensions_fail_but_numeric_lexemes_are_not_converted(self):
        for source in ("NaN", "Infinity", "-Infinity", '{"x":NaN}'):
            with self.subTest(source=source):
                issues, checked = json_code.check_json(source)
                self.assertTrue(checked)
                self.assertEqual(issues[0]["kind"], "syntax")
                self.assertIsNone(issues[0]["line"])
        for source in ('"NaN"', "1e9999", "9" * 5000):
            self.assertEqual(json_code.check_json(source), ([], True))

    def test_json_depth_limits_ignore_brackets_and_escapes_inside_strings(self):
        self.assertEqual(json_code.check_json(json.dumps({"text": '["' * 1000})), ([], True))
        self.assertEqual(json_code.check_json("[" * 128 + "0" + "]" * 128), ([], True))
        issues, checked = json_code.check_json("[" * 129 + "0" + "]" * 129)
        self.assertFalse(checked)
        self.assertEqual(issues[0]["kind"], "source_limit")
        with patch.object(json_code.json, "loads", side_effect=AssertionError("must not parse")):
            self.assertFalse(json_code.check_json("x" * 65537)[1])

    def test_json_duplicate_problem_count_and_messages_are_bounded(self):
        source = "{" + ",".join(f'"key{i}":1,"key{i}":2' for i in range(40)) + "}"
        issues, checked = json_code.check_json(source)
        self.assertTrue(checked)
        self.assertEqual(len(issues), json_code.MAX_DUPLICATES)
        self.assertTrue(all(len(issue["message"]) <= 240 for issue in issues))

    def test_minecraft_pack_semantics_and_unchecked_java_are_preserved(self):
        result = self.verifier.verify('pack.mcmeta:\n```json\n{"pack":{"description":"demo"}}\n```\n')
        self.assertFalse(result["ok"])
        self.assertTrue(any(row["kind"] == "mc_datapack" for row in result["blocks"][0]["problems"]))
        malformed = self.verifier.verify('pack.mcmeta:\n```json\n{"pack_format":NaN}\n```\n')
        self.assertEqual(malformed["blocks"][0]["problems"][0]["kind"], "syntax")
        tick = self.verifier.verify('pack.mcmeta is separate.\n```json\n{"values":["demo:tick"]}\n```\n')
        self.assertTrue(tick["ok"])
        self.assertTrue(tick["blocks"][0]["checked"])
        self.assertFalse(self.verifier.verify('```java\nclass A {}\n```\n')["blocks"][0]["checked"])

    def test_existing_report_consumers_count_new_syntax_failures_without_harness_changes(self):
        for source, language in (("return 1", "python"), ('{"a":}', "json"), ("NaN", "json")):
            with self.subTest(language=language):
                stats = eval_litha.stats(self.verifier.verify(source, language))
                self.assertEqual(stats["syntax"], 1)
                self.assertFalse(stats["ok"])

    def test_pack_detection_uses_root_members_and_each_fences_own_filename(self):
        for source in ('{}', '{"note":"demo","pack":{"description":"demo"}}'):
            with self.subTest(source=source):
                self.assertFalse(self.verifier.verify(f'pack.mcmeta:\n```json\n{source}\n```\n')["ok"])
        answer = ('pack.mcmeta:\n```json\n{"pack":{"description":"demo","pack_format":48}}\n```\n'
                  'tick.json:\n```json\n{"values":["demo:tick"]}\n```\n')
        result = self.verifier.verify(answer)
        self.assertTrue(result["ok"])
        self.assertEqual([row["checked"] for row in result["blocks"]], [True, True])
        self.assertTrue(self.verifier.verify('{"note":{"pack":{}}}', "json")["ok"])
        self.assertTrue(self.verifier.verify('{"label":"pack_format"}', "json")["ok"])
        self.assertFalse(self.verifier.verify('{"note":1,"pack":{}}', "json")["ok"])

    def test_pack_fix_keeps_local_filename_context(self):
        answer = 'pack.mcmeta:\n```json\n{}\n```\n'
        calls = []

        def model(messages):
            calls.append(messages)
            return '```json\n{"pack":{"pack_format":48,"description":"demo"}}\n```'

        result = self.verifier.fix(answer, model)
        self.assertTrue(result["ok"])
        self.assertEqual(len(calls), 1)

    def test_actual_repair_loop_fixes_python_and_json_then_rechecks(self):
        for source, language, replacement in (("def broken(:\n    pass\n", "python", "def fixed():\n    pass\n"),
                                               ('{"a":1,}', "json", '{"a":1}')):
            calls = []

            def model(messages):
                calls.append(messages)
                return f"```{language}\n{replacement}\n```"

            result = self.verifier.fix(source, model, language)
            self.assertTrue(result["ok"])
            self.assertEqual(result["rounds"], 1)
            self.assertEqual(len(calls), 1)
            self.assertIn("Problems:", calls[0][-1]["content"])
            self.assertFalse(result["verify"]["needs_fix"])
            self.assertTrue(result["verify"]["blocks"][0]["checked"])

    def test_actual_http_handler_verifies_and_repairs_with_injected_model(self):
        model_calls = []

        class Keys:
            @staticmethod
            def check(token):
                return token == "synthetic-litha-key"

        def factory(_cfg, auth):
            self.assertEqual(auth, "Bearer synthetic-litha-key")

            def model(messages):
                model_calls.append(messages)
                return '```python\ndef fixed():\n    return 1\n```'

            return model

        cfg = dict(service.DEFAULTS)
        server = ThreadingHTTPServer(("127.0.0.1", 0), service.make_handler(cfg, self.verifier, Keys(), factory))
        server.daemon_threads = True
        worker = threading.Thread(target=server.serve_forever, daemon=True)
        worker.start()
        try:
            for path in ("/mesh/verify", "/mesh/verify?fix=1"):
                connection = http.client.HTTPConnection("127.0.0.1", server.server_address[1], timeout=5)
                try:
                    connection.request("POST", path, json.dumps({"code": "def broken(:\n    pass", "language": "python"}),
                                       {"Content-Type": "application/json", "Authorization": "Bearer synthetic-litha-key"})
                    response = connection.getresponse()
                    self.assertEqual(response.status, 200)
                    result = json.loads(response.read())
                    if "fix=1" in path:
                        self.assertTrue(result["ok"])
                        self.assertIn("def fixed", result["answer"])
                    else:
                        self.assertFalse(result["ok"])
                        self.assertTrue(result["blocks"][0]["checked"])
                finally:
                    connection.close()
            self.assertEqual(len(model_calls), 1)
        finally:
            server.shutdown()
            server.server_close()
            worker.join(3)

    def test_existing_router_cache_admission_rejects_new_language_errors(self):
        mesh = object.__new__(router.Router)
        mesh.cfg = {"verify_url": "http://127.0.0.1:9"}
        mesh.keys = SimpleNamespace(first=lambda: "synthetic-litha-key")

        async def upstream(_url, _method, body, _headers, **_kwargs):
            report = self.verifier.verify(json.loads(body)["answer"])

            async def response_body():
                return json.dumps(report).encode()

            return SimpleNamespace(status=200, body=response_body, close=lambda: None)

        with patch.object(router, "open_upstream", new=upstream):
            for answer, expected in (("```python\nreturn 1\n```\n", False),
                                     ("```python\ndef f():\n    return 1\n```\n", True),
                                     ('```json\n{"a":}\n```\n', False),
                                     ('```json\n{"a":1,"a":2}\n```\n', False),
                                     ('```json\n{"a":1}\n```\n', True)):
                with self.subTest(answer=answer):
                    self.assertIs(asyncio.run(mesh.verify_ok(answer)), expected)


if __name__ == "__main__":
    unittest.main(verbosity=2)
