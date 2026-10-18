"""Design checker (star/design_check.py), its evals hook and the design pack's routing. No browser, no model."""
import json
from pathlib import Path

import pytest

from star import design_check as dc
from star import eval_checks as ec
from star import skill_packs

ROOT = Path(__file__).resolve().parent.parent
SUITE = ROOT / "evals" / "design" / "design-20261018.json"
FENCE = "`" * 3

GENERIC_PAGE = f"""<!DOCTYPE html><html><head><style>
body{{font-family:Inter,sans-serif;background:linear-gradient(135deg,#667eea,#764ba2);color:#fff}}
.badge{{font-size:12px;text-transform:uppercase;letter-spacing:0.1em;backdrop-filter:blur(10px)}}
.card{{backdrop-filter:blur(12px);box-shadow:0 8px 32px rgba(0,0,0,0.2);text-align:center;padding:30px;transition:all 0.3s ease-in}}
.card p{{color:#ddd;font-size:15px;padding:13px}}
</style></head><body><span class="badge">New</span><h1>Build <span style="color:#ffd166">faster</span></h1>
<p>Lorem ipsum dolor sit amet</p><a class="btn" href="#">Get Started →</a>
<div class="card"><div class="icon">🚀</div><h3>Fast</h3><p>Feature 1 description goes here.</p></div>
<div class="card"><div class="icon">🔒</div><h3>Secure</h3><p>Feature 2</p></div>
<div class="card"><div class="icon">✨</div><h3>Nice</h3><p>Feature 3</p></div></body></html>"""

QUIET_PAGE = """<!DOCTYPE html><html lang="en"><head><meta name="viewport" content="width=device-width,initial-scale=1"><style>
body{margin:0;font-family:Georgia,serif;background:#f3efe6;color:#1d1a16;font-size:18px;line-height:1.55}
h1{font-size:clamp(40px,7vw,80px);font-weight:700;margin:48px 32px 24px}
p{max-width:60ch;margin:0 32px 16px}
.action{display:inline-block;margin:0 32px;background:#1f4f5a;color:#fff;padding:16px 24px;font-weight:600;transition:transform 140ms cubic-bezier(0.22,1,0.36,1)}
.action:focus-visible{outline:3px solid #1d1a16}
@media (max-width:640px){h1{margin:32px 16px 16px}}
@media (prefers-reduced-motion:reduce){.action{transition:none}}
</style></head><body><h1>Sourdough from the pier.</h1><p>Forty loaves a morning on Water Street.</p>
<a class="action" href="#">Reserve a loaf</a></body></html>"""


def test_generic_page_fails_on_the_named_tells():
    rep = dc.check_html(GENERIC_PAGE)
    ids = {f.id for f in rep.findings}
    for expected in ("A1.violet_gradient", "A3.glass", "A5.emoji", "A10.icon_cards", "A11.placeholder_copy",
                     "A11.arrow_labels", "A11.accent_word", "A11.eyebrow", "M1.transition_all", "M2.ease_in", "A7.spacing_grid"):
        assert expected in ids, expected
    assert not rep.passed() and rep.score < 40


def test_quiet_page_passes_with_a_high_score():
    rep = dc.check_html(QUIET_PAGE)
    assert rep.passed(), rep.summary()
    assert rep.score >= 90
    assert "P1.focus_visible" in {f.id for f in rep.findings}


def test_contrast_maths_matches_wcag():
    assert round(dc.contrast((255, 255, 255), (0, 0, 0)), 1) == 21.0
    assert round(dc.contrast((119, 119, 119), (255, 255, 255)), 2) == 4.48
    assert dc.parse_color("#fff") == (255, 255, 255)
    assert dc.parse_color("rgb(31, 79, 90)") == (31, 79, 90)
    assert dc.parse_color("hsl(0, 100%, 50%)") == (255, 0, 0)


def test_roblox_tree_tells_and_a_clean_tree():
    bad = """local f = Instance.new("Frame")
f.Size = UDim2.new(0, 650, 0, 430)
f.BackgroundColor3 = Color3.fromRGB(120, 80, 220)
local g = Instance.new("UIGradient")
local g2 = Instance.new("UIGradient")
local t = Instance.new("TextLabel")
t.Text = "🛒 Shop"
t.TextSize = 11
t.TextColor3 = Color3.fromRGB(200, 200, 255)
t.BackgroundColor3 = Color3.fromRGB(140, 90, 255)
local b = Instance.new("TextButton")
b.Text = "Button"
b.Size = UDim2.new(0, 150, 0, 35)
b.Position = UDim2.new(0, 23, 0, 77)
local info = TweenInfo.new(0.8, Enum.EasingStyle.Bounce, Enum.EasingDirection.In)"""
    rep = dc.check_roblox_ui(bad)
    ids = {f.id for f in rep.findings}
    for expected in ("A1.violet_gradient", "A2.gradients", "A5.emoji", "A6.tiny_text", "A8.contrast", "A11.placeholder_copy",
                     "A12.offset_only", "A12.touch_target", "M2.ease_in", "M4.bounce"):
        assert expected in ids, expected
    assert not rep.passed()
    good = """local TweenService = game:GetService("TweenService")
local gui = Instance.new("ScreenGui")
local panel = Instance.new("Frame")
panel.Size = UDim2.new(0.6, 0, 0.7, 0)
panel.BackgroundColor3 = Color3.fromRGB(24, 26, 31)
local ratio = Instance.new("UIAspectRatioConstraint")
local layout = Instance.new("UIGridLayout")
layout.CellPadding = UDim2.new(0, 16, 0, 16)
local title = Instance.new("TextLabel")
title.Text = "Gear shop"
title.FontFace = Font.new("rbxasset://fonts/families/GothamSSm.json", Enum.FontWeight.Bold)
title.TextSize = 28
title.TextColor3 = Color3.fromRGB(240, 240, 236)
title.BackgroundTransparency = 1
local b = Instance.new("TextButton")
b.Text = "Grapple hook 300 coins"
b.TextSize = 16
b.TextColor3 = Color3.fromRGB(240, 240, 236)
b.BackgroundColor3 = Color3.fromRGB(40, 43, 50)
b.Size = UDim2.new(0, 160, 0, 96)
b.MouseEnter:Connect(function()
    TweenService:Create(b, TweenInfo.new(0.12, Enum.EasingStyle.Quad, Enum.EasingDirection.Out), {BackgroundColor3 = Color3.fromRGB(52, 56, 64)}):Play()
end)"""
    assert dc.check_roblox_ui(good).passed()


def test_json_layout_tree_is_read_too():
    tree = {"class": "ScreenGui", "children": [
        {"class": "Frame", "props": {"Size": [0.6, 0, 0.7, 0], "BackgroundColor3": [24, 26, 31]}, "children": [
            {"class": "TextLabel", "props": {"Text": "Gear shop", "TextSize": 28, "TextColor3": [240, 240, 236], "BackgroundColor3": [24, 26, 31]}},
            {"class": "TextLabel", "props": {"Text": "Lorem ipsum", "TextSize": 9, "TextColor3": [60, 60, 60], "BackgroundColor3": [24, 26, 31]}}]}]}
    rep = dc.check_roblox_ui(json.dumps(tree))
    ids = {f.id for f in rep.findings}
    assert rep.metrics["instances"] == 4
    assert "A6.tiny_text" in ids and "A11.placeholder_copy" in ids and "A8.contrast" in ids


def test_vfx_budget_rules():
    noisy = """local e = Instance.new("ParticleEmitter")
e.Rate = 600
e.Lifetime = NumberRange.new(2, 25)
e.Size = NumberSequence.new(30)
e.LightEmission = 1
e.Enabled = true
local bloom = Instance.new("BloomEffect")
bloom.Intensity = 3
bloom.Threshold = 0.5"""
    rep = dc.check_vfx(noisy)
    ids = {f.id for f in rep.findings}
    for expected in ("V2.rate", "V3.lifetime", "V4.overdraw", "V6.bloom", "V6.bloom_threshold", "V7.no_layering", "V8.no_cleanup"):
        assert expected in ids, expected
    assert not rep.passed()
    phased = """local Debris = game:GetService("Debris")
local flash = Instance.new("ParticleEmitter")
flash.Rate = 0
flash.Lifetime = NumberRange.new(0.06, 0.1)
flash.Size = NumberSequence.new({NumberSequenceKeypoint.new(0, 1), NumberSequenceKeypoint.new(1, 5)})
flash.Color = ColorSequence.new(Color3.fromRGB(255, 236, 200))
flash.LightEmission = 1
local smoke = Instance.new("ParticleEmitter")
smoke.Rate = 0
smoke.Lifetime = NumberRange.new(1, 1.6)
smoke.Size = NumberSequence.new({NumberSequenceKeypoint.new(0, 2), NumberSequenceKeypoint.new(1, 6)})
smoke.Color = ColorSequence.new(Color3.fromRGB(70, 66, 60))
smoke.LightEmission = 0
flash:Emit(1)
task.wait(0.04)
smoke:Emit(5)
Debris:AddItem(at, 2.5)"""
    assert dc.check_vfx(phased).passed()


def test_extract_reads_fenced_blocks_and_raw_documents():
    parts = dc.extract(f"Here:\n{FENCE}html\n<div>x</div>\n{FENCE}\nand\n{FENCE}css\nbody{{margin:0}}\n{FENCE}\n")
    assert parts["html"] == ["<div>x</div>\n"] and parts["css"] == ["body{margin:0}\n"]
    assert "<style>" in dc.html_document(parts)
    assert dc.extract("<!DOCTYPE html><html></html>")["html"]
    assert dc.extract(f"{FENCE}\nlocal f = Instance.new('Frame')\n{FENCE}")["lua"]
    rep = dc.check_answer("I would use a nice gradient.", "html")
    assert [f.id for f in rep.fails] == ["A0.no_markup"]


def test_evals_hook_scores_the_answer_and_required_words():
    task = {"id": "x", "prompt": "p", "run_mode": "automated",
            "auto": {"code": False, "design": {"kind": "html", "min_score": 70, "require_text": ["Harbor Bakery", "<form"]}}}
    good = ec.score_answer(task, f"{FENCE}html\n{QUIET_PAGE.replace('Sourdough', 'Harbor Bakery sourdough')}\n<form></form>\n{FENCE}", luau_check=None)
    assert good.passed, good.reasons
    bad = ec.score_answer(task, f"{FENCE}html\n{GENERIC_PAGE}\n{FENCE}", luau_check=None)
    assert not bad.passed
    ids = [c.id for c in bad.checks]
    assert "design:score" in ids and "design:text:Harbor_Bakery" in ids
    assert not ec.score_answer(task, "", luau_check=None).passed
    # Tasks without a design block are byte-for-byte unaffected.
    plain = {"id": "y", "prompt": "p", "run_mode": "automated", "auto": {"code": False, "require": [{"id": "w", "re": "hello", "scope": "prose"}]}}
    assert [c.id for c in ec.score_answer(plain, "hello", luau_check=None).checks] == ["require:w"]


@pytest.mark.skipif(not SUITE.is_file(), reason="design suite not generated")
def test_design_suite_loads_references_pass_and_generic_answers_fail():
    from star.eval_runner import validate_tasks
    from star.evals import load_catalog
    tasks = json.loads(SUITE.read_text(encoding="utf-8"))
    assert len(tasks) >= 150
    load_catalog(SUITE)
    assert validate_tasks(tasks, SUITE.parent) == []
    ok = lambda code, strict=False: {"ok": True, "errors": []}   # noqa: E731 - the Luau service is not called here
    ref = SUITE.parent / "reference"
    categories = set()
    for task in tasks:
        categories.add(task["category"])
        good = (ref / f"{task['id']}.md").read_text(encoding="utf-8")
        bad = (ref / f"{task['id']}.bad.md").read_text(encoding="utf-8")
        assert ec.score_answer(task, good, luau_check=ok).passed, (task["id"], ec.score_answer(task, good, luau_check=ok).reasons)
        assert not ec.score_answer(task, bad, luau_check=ok).passed, task["id"]
        assert not ec.score_answer(task, "", luau_check=ok).passed, task["id"]
    assert {"design-web-landing", "design-web-dashboard", "design-web-form", "design-roblox-shop", "design-roblox-hud",
            "design-roblox-menu", "design-roblox-inventory", "design-ui-motion", "design-roblox-vfx"} <= categories


@pytest.fixture
def design_pack_only(monkeypatch):
    monkeypatch.setenv(skill_packs.ENV_VAR, "design-anti-ai-look")
    skill_packs.available.cache_clear()
    yield
    skill_packs.available.cache_clear()


def test_design_pack_ships_in_the_pack_format_and_is_off_by_default():
    pack = next(p for p in skill_packs.available() if p.name == "design-anti-ai-look")
    assert len(pack.body) <= skill_packs.MAX_BODY_CHARS
    assert "## Checklist" in pack.body and "## Sources" in pack.body and "## Motion" in pack.body and "## Game VFX" in pack.body
    assert "design-anti-ai-look" not in skill_packs.DEFAULT_ENABLED
    assert "design-anti-ai-look" not in skill_packs.enabled_names({})
    assert (pack.file.parent / "references" / "layouts.md").is_file()


def test_design_pack_routes_on_design_requests_only(design_pack_only):
    for prompt in ("Design a landing page for a bakery with a modern clean look",
                   "In my Roblox game make a shop UI with a ScreenGui, UIGridLayout and a nice visual style",
                   "Make an explosion VFX with particles for my Roblox game",
                   "Design me a dashboard"):
        assert skill_packs.matching_names(prompt) == ["design-anti-ai-look"], prompt
    for prompt in ("How do I centre a div in my web app UI?", "Write a DataStore save function in Roblox",
                   "What is the capital of France?", "Explain the UI of a spreadsheet"):
        assert skill_packs.matching_names(prompt) == [], prompt
    # Other packs keep their behaviour: a Roblox UI prompt with the Roblox UI pack enabled still gets that pack.
    assert skill_packs.matching_names("In my Roblox game lay out a ScreenGui HUD with UIListLayout and UIPadding",
                                      enabled=["roblox-ui-layout"]) == ["roblox-ui-layout"]
