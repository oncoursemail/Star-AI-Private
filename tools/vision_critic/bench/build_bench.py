"""Build the offline vision-critic benchmark from the 10-29 blind Opus judging.

Output: bench/pairs.json + bench/img/<pair>_<A|B>_<n>.jpg (images exactly as the judges saw them, cropped per arm).
Each pair: id, domain, group (brief id, for the split), brief, A/B image lists, votes (+1 = judge preferred A,
-1 = B, 0 = tie, per judge), clear (>= 2 judges strictly agree and none disagree), pref ('A'/'B'/None).
"""
import json, random, itertools
from pathlib import Path
from PIL import Image

import os
DOCS = Path(os.environ.get("VC_DOCS", Path.home() / "Documents" / "starai" / "docs" / "agents"))  # judging artifacts
SCR = Path(os.environ.get("VC_WORK", Path(__file__).parent))  # work dir: src/eval1 = blockbench eval1_outputs.tgz unpacked
UIVFX = Path(os.environ.get("VC_UIVFX", SCR.parent / "uivfx"))  # ui-vfx lane scratch: judging/ + keys/
OUT = SCR / "bench"; IMG = OUT / "img"; IMG.mkdir(parents=True, exist_ok=True)
MAXW = 1280
pairs = []


def save(im, name):
    im = im.convert("RGB")
    if im.width > MAXW:
        im = im.resize((MAXW, round(im.height * MAXW / im.width)), Image.LANCZOS)
    p = IMG / name; im.save(p, quality=90); return str(p.relative_to(OUT)).replace("\\", "/")


def add(pid, domain, group, brief, imgsA, imgsB, votes):
    pos = sum(v > 0 for v in votes); neg = sum(v < 0 for v in votes)
    clear = (pos >= 2 and neg == 0) or (neg >= 2 and pos == 0)
    pref = ("A" if pos > neg else "B") if clear else None
    a = [save(im, f"{pid}_A_{i}.jpg") for i, im in enumerate(imgsA)]
    b = [save(im, f"{pid}_B_{i}.jpg") for i, im in enumerate(imgsB)]
    pairs.append(dict(id=pid, domain=domain, group=group, brief=brief, A=a, B=b, votes=votes, clear=clear, pref=pref))


sgn = lambda x: (x > 0) - (x < 0)

# blockbench: round0 vs round1, 3 judges, A/B as in key.json
src = SCR / "src" / "eval1"
J = json.loads((DOCS / "blockbench/judges.json").read_text()); K = json.loads((DOCS / "blockbench/key.json").read_text())
for bid, k in K.items():
    rep = json.loads((src / bid / "report.json").read_text())
    def views(lab):
        return [Image.open(next((src / bid / k[lab]).glob("*_views.png")))]
    votes = [sgn(J[j][bid]["A"] - J[j][bid]["B"]) for j in J if bid in J[j]]
    add(f"bb-{bid}", "blockbench", f"bb-{bid}", rep["brief"], views("A"), views("B"), votes)

# 3d-assets: judge rounds 1 and 2 (same briefs; split by brief so both rounds land on one side), overall score
for rnd, js in ((1, (1, 2, 3)), (2, (4, 5, 6))):
    jd = DOCS / f"3d-assets/judge{rnd}"
    briefs = json.loads((jd / "briefs.json").read_text())
    scores = [json.loads((jd / f"scores_j{i}.json").read_text())["scores"] for i in js]
    for bid, b in briefs.items():
        labs = b["labels"]; sheet = Image.open(jd / f"{bid}.jpg"); w = sheet.width // len(labs)
        crops = {L: sheet.crop((i * w, 48, (i + 1) * w, sheet.height)) for i, L in enumerate(labs)}
        brief = f"{b['brief']} (style: {b['style']}, category: {b['category']})"
        for x, y in itertools.combinations(labs, 2):
            votes = [sgn(s[bid][x]["overall"] - s[bid][y]["overall"]) for s in scores]
            add(f"3d{rnd}-{bid}-{x}{y}", "3d-assets", f"3d-{bid}", brief, [crops[x]], [crops[y]], votes)

# roblox-build: 3 judges [A, B] overall; judge sheet = BUILD A (top half) / BUILD B (bottom half), 30 px label bars
rb = DOCS / "roblox-build/eval"
S = json.loads((rb / "judge-scores.json").read_text())
briefs = {}
for line in (rb / "judge/packets.txt").read_text(encoding="utf-8").splitlines():
    if line[:1] == "P" and ":" in line:
        pid, rest = line.split(":", 1); briefs[pid.strip()] = rest.strip()
for pid in json.loads((rb / "judge-key.json").read_text()):
    sheet = Image.open(rb / "judge" / f"{pid}.jpg"); h = sheet.height // 2
    A = sheet.crop((0, 30, sheet.width, h)); B = sheet.crop((0, h + 30, sheet.width, sheet.height))
    votes = [sgn(S[j][pid][0] - S[j][pid][1]) for j in S]
    add(f"rb-{pid}", "roblox-build", f"rb-{pid}", briefs[pid], [A], [B], votes)

# ui-vfx: 2 judges per domain, explicit pref field
uj = [json.loads(p.read_text()) for p in sorted((UIVFX / "judging").glob("judge*.json"))]
for dom, sub in (("ui", "ui"), ("lighting", "lighting"), ("vfx", "vfx")):
    for bdir in sorted((DOCS / "ui-vfx" / sub).iterdir()):
        bid = bdir.name; votes = []
        for j in uj:
            r = j.get(dom, {}).get(bid)
            if r:
                votes.append({"A": 1, "B": -1}.get(r.get("pref"), 0))
        if not votes:
            continue
        if dom == "lighting":
            ia = [Image.open(bdir / "A_1.jpg"), Image.open(bdir / "A_2.jpg")]; ib = [Image.open(bdir / "B_1.jpg"), Image.open(bdir / "B_2.jpg")]
        else:
            ia = [Image.open(bdir / "A.jpg")]; ib = [Image.open(bdir / "B.jpg")]
        add(f"{dom}-{bid}", f"ui-vfx:{dom}", f"{dom}-{bid}", (bdir / "brief.txt").read_text(encoding="utf-8").strip(), ia, ib, votes)

# split by group: ~40% dev / 60% test, stratified per domain, fixed seed
rng = random.Random(1029)
groups = {}
for p in pairs:
    groups.setdefault(p["domain"], set()).add(p["group"])
dev = set()
for dom, gs in groups.items():
    gs = sorted(gs); rng.shuffle(gs); dev |= set(gs[: round(len(gs) * 0.4)])
for p in pairs:
    p["split"] = "dev" if p["group"] in dev else "test"
(OUT / "pairs.json").write_text(json.dumps(pairs, indent=1), encoding="utf-8")
from collections import Counter
c = Counter((p["domain"], p["split"], p["clear"]) for p in pairs)
for dom in sorted(groups):
    print(f"{dom:18s} total {sum(v for (d,_,_),v in c.items() if d==dom):3d} | clear dev {c[(dom,'dev',True)]:2d} test {c[(dom,'test',True)]:2d}")
cl = [p for p in pairs if p["clear"]]
print("clear total", len(cl), "dev", sum(p['split']=='dev' for p in cl), "test", sum(p['split']=='test' for p in cl),
      "| pref A share", round(sum(p['pref']=='A' for p in cl)/len(cl), 2))
