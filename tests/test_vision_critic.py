import json
import math

import pytest
from PIL import Image

from star import vision_critic as vc


def _img(color=(200, 30, 30), size=(64, 48), blank=False):
    im = Image.new("RGB", size, (40, 40, 40))
    if not blank:
        for x in range(10, 50):
            for y in range(8, 40):
                im.putpixel((x, y), color)
    return im


def _resp(probs: dict[str, float], text: str = ""):
    top = [{"token": t, "logprob": math.log(p)} for t, p in probs.items()]
    return {"choices": [{"message": {"content": text}, "logprobs": {"content": [{"token": "x", "top_logprobs": top}]}}]}


class FakeServer:
    """Answers like a model that prefers the arm whose image is red, but with a bias toward the first image."""

    def __init__(self, first_bias=0.0, answer=None):
        self.bodies = []; self.first_bias = first_bias; self.answer = answer

    def __call__(self, body):
        self.bodies.append(body)
        if self.answer is not None:
            return self.answer
        urls = [c["image_url"]["url"] for c in body["messages"][-1]["content"] if c.get("type") == "image_url"]
        import base64, io
        reds = []
        for u in urls:
            im = Image.open(io.BytesIO(base64.b64decode(u.split(",", 1)[1]))).convert("RGB")
            reds.append(im.getpixel((im.width // 2, im.height // 2))[0] > 150)
        p_first = 0.8 if reds[0] and not reds[1] else 0.2 if reds[1] and not reds[0] else 0.5
        p_first = min(0.99, p_first + self.first_bias)
        return _resp({"A": p_first, " B": 1 - p_first})


def test_prefer_swaps_orders_and_maps_back():
    srv = FakeServer()
    r = vc.prefer([_img((30, 30, 200))], [_img((220, 30, 30))], "a red box", "3d-assets", method="pairwise",
                  transport=srv)
    assert len(srv.bodies) == 2 and r["winner"] == "B" and r["consistent"]
    assert r["p_a"] == pytest.approx(0.2) and r["orders"] == [pytest.approx(0.2), pytest.approx(0.2)]
    body = srv.bodies[0]
    assert body["max_tokens"] == 1 and body["logprobs"] is True and body["temperature"] == 0


def test_position_bias_cancels_and_flags_inconsistent():
    # the model always leans to the first image: one order says A, the other B -> inconsistent, average decides
    srv = FakeServer(first_bias=0.45)
    r = vc.prefer([_img((30, 30, 200))], [_img((220, 30, 30))], "a red box", method="pairwise", transport=srv)
    assert not r["consistent"]
    assert r["winner"] == "B"            # (0.65 -> A) and (0.99 first=B -> A 0.01): mean 0.33 -> B


def test_default_method_is_pairwise():
    srv = FakeServer()
    r = vc.prefer([_img()], [_img((30, 30, 200))], "red", transport=srv)
    assert len(srv.bodies) == 2 and "orders" in r and r["winner"] == "A"


def test_no_swap_single_call():
    srv = FakeServer()
    r = vc.prefer([_img()], [_img((30, 30, 200))], "red", method="pairwise", swap=False, transport=srv)
    assert len(srv.bodies) == 1 and r["winner"] == "A" and r["consistent"]


def test_facts_and_checklist_in_prompt_and_swapped_with_images():
    srv = FakeServer()
    vc.prefer([_img()], [_img(blank=True)], "a red box", "blockbench", facts=("2 floating cubes", "ok"),
              method="pairwise", use_pixel_facts=True, transport=srv)
    t0 = srv.bodies[0]["messages"][-1]["content"][-1]["text"]
    t1 = srv.bodies[1]["messages"][-1]["content"][-1]["text"]
    assert "A: 2 floating cubes" in t0 and "B: ok" in t0
    assert "B: 2 floating cubes" in t1            # swapped presentation carries its facts along
    assert "almost blank" in t0                   # pixel facts mark the empty render
    assert "silhouette" in t0                     # blockbench checklist


def test_letter_probs_text_fallback_and_aliases():
    p = vc._letter_probs({"choices": [{"message": {"content": "B"}}]}, "AB")
    assert p == {"A": 0.0, "B": 1.0}
    assert vc.checklist("roblox-scenes") == vc.CHECKLISTS["roblox-build"]
    assert vc.checklist("shapes-templates") == vc.CHECKLISTS["3d-assets"]
    assert vc.checklist("unknown") == vc.CHECKLISTS["generic"]


def test_side_layout_sends_one_image():
    srv = FakeServer(answer=_resp({"A": 0.7, "B": 0.3}))
    r = vc.prefer([_img(), _img()], [_img()], "x", method="pairwise", layout="side", transport=srv)
    imgs = [c for c in srv.bodies[0]["messages"][-1]["content"] if c.get("type") == "image_url"]
    assert len(imgs) == 1 and r["orders"] == [pytest.approx(0.7), pytest.approx(0.3)] and not r["consistent"]


def test_issues_parses_fenced_and_truncated_json():
    text = '```json\n{"issues": [{"part": "leg", "problem": "floats", "fix": "attach", "severity": 1},' \
           ' {"part": "top", "problem": "not round", "severity": 3}]}\n```'
    srv = FakeServer(answer={"choices": [{"message": {"content": text}}]})
    r = vc.issues([_img()], "a table", "3d-assets", transport=srv)
    assert [i["severity"] for i in r["issues"]] == [3, 1] and r["issues"][1]["fix"] == "attach"
    trunc = '{"issues": [{"part": "a", "problem": "p1", "severity": 2}, {"part": "b", "prob'
    assert vc.parse_issues(trunc) == [{"part": "a", "problem": "p1", "fix": "", "severity": 2}]
    assert vc.parse_issues("no json here") == []


def test_unavailable_host_raises_quickly(monkeypatch):
    monkeypatch.delenv("STAR_VISION_CRITIC_URL", raising=False)
    with pytest.raises(vc.CriticUnavailable):
        vc.http_transport(url="")
    send = vc.http_transport(url="http://127.0.0.1:9", key="k", timeout=2)
    with pytest.raises(vc.CriticUnavailable):
        send({"model": "critic", "messages": []})


def test_tile_and_pixel_facts():
    sheet = vc.tile([_img(), _img(), _img()], max_side=100)
    assert max(sheet.size) <= 100
    f = vc.pixel_facts([_img(blank=True), _img()])
    assert "image 1" in f and "almost blank" in f.split(";")[0] and "almost blank" not in f.split(";")[1]
    json.dumps(vc.prefer.__doc__)


class DigitServer:
    """Scores red renders ~7 and others ~3 as digit log-probabilities."""

    def __init__(self):
        self.bodies = []

    def __call__(self, body):
        import base64, io
        self.bodies.append(body)
        u = [c for c in body["messages"][-1]["content"] if c.get("type") == "image_url"][0]["image_url"]["url"]
        im = Image.open(io.BytesIO(base64.b64decode(u.split(",", 1)[1]))).convert("RGB")
        red = im.getpixel((im.width // 2, im.height // 2))[0] > 150
        return _resp({"7": 0.6, "8": 0.4} if red else {"3": 0.5, "2": 0.25, "x": 0.25})


def test_score_expected_value_over_digits():
    srv = DigitServer()
    r = vc.score([_img()], "a red box", "blockbench", facts="1 floating cube", transport=srv)
    assert r["score"] == pytest.approx(7.4) and r["mass"] == pytest.approx(1.0)
    body = srv.bodies[0]
    assert body["max_tokens"] == 1 and body["logprobs"] and "1 floating cube" in body["messages"][-1]["content"][-1]["text"]
    r = vc.score([_img((30, 30, 200))], "a red box", transport=srv)
    assert r["score"] == pytest.approx((3 * 0.5 + 2 * 0.25) / 0.75, abs=1e-3) and r["mass"] == pytest.approx(0.75)


def test_prefer_score_method_scores_each_arm_once():
    srv = DigitServer()
    r = vc.prefer([_img((30, 30, 200))], [_img()], "a red box", "3d-assets", method="score",
                  facts=("", "seams ok"), transport=srv)
    assert len(srv.bodies) == 2 and r["winner"] == "B" and r["p_a"] < 0.5 and r["scores"][1] == pytest.approx(7.4)
    assert "seams ok" in srv.bodies[1]["messages"][-1]["content"][-1]["text"]
    with pytest.raises(ValueError):
        vc.prefer([_img()], [_img()], "x", method="vote", transport=srv)
