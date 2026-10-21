"""Local-first commerce workforce.

No storefront, advertising, payments, private data or external publishing access.
Every output is an *internal* draft until independently reviewed.
"""
from __future__ import annotations

import hashlib
import io
import json
import os
import re
import sqlite3
import urllib.error
from contextlib import contextmanager
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ALLOWED_STEPS = ("produce", "listing", "qa")
BUSINESSES = (
    ("creator-assets", "Creator Asset Studio", "Original gaming and streaming assets", "Shopify / digital downloads"),
    ("service-studio", "Design Service Desk", "Human-reviewed custom client work", "Fiverr / direct inquiries"),
    ("print-studio", "Print & Personalize Lab", "Seller-designed personalized concepts", "Etsy / Printify"),
)
SEED_OFFERS = (
    ("hud-kit", "creator-assets", "Creator HUD Starter Kit", "Original editable game HUD and streaming scene SVGs", 2400, "digital"),
    ("thumbnail-service", "service-studio", "Creator Thumbnail Design Service", "Custom thumbnails made to a buyer-approved brief", 3900, "service"),
    ("personalized-print", "print-studio", "Personalized Milestone Print Concept", "Original seller-designed celebration print; mockup only", 2800, "physical"),
)
SCHEMA = """
PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;
CREATE TABLE IF NOT EXISTS business (
  id TEXT PRIMARY KEY, name TEXT NOT NULL, description TEXT NOT NULL, channel TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS offer (
  id TEXT PRIMARY KEY, business_id TEXT NOT NULL REFERENCES business(id),
  name TEXT NOT NULL, summary TEXT NOT NULL, price_cents INTEGER NOT NULL,
  kind TEXT NOT NULL, state TEXT NOT NULL DEFAULT 'concept',
  artifact TEXT NOT NULL DEFAULT '', sha256 TEXT NOT NULL DEFAULT '',
  listing_json TEXT NOT NULL DEFAULT '{}', qa_json TEXT NOT NULL DEFAULT '{}',
  rights_review TEXT NOT NULL DEFAULT '', updated_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS job (
  id INTEGER PRIMARY KEY AUTOINCREMENT, offer_id TEXT NOT NULL REFERENCES offer(id),
  step TEXT NOT NULL CHECK(step IN ('produce','listing','qa')),
  state TEXT NOT NULL DEFAULT 'queued', dedupe_key TEXT NOT NULL UNIQUE,
  error TEXT NOT NULL DEFAULT '', created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS activity (
  id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT NOT NULL,
  offer_id TEXT, kind TEXT NOT NULL, message TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS expense (
  id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT NOT NULL, business_id TEXT NOT NULL REFERENCES business(id),
  category TEXT NOT NULL, amount_cents INTEGER NOT NULL CHECK(amount_cents >= 0),
  memo TEXT NOT NULL DEFAULT '', source TEXT NOT NULL DEFAULT 'owner_entered');
"""


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _clean(s: Any, maxlen: int = 200) -> str:
    if not isinstance(s, str):
        raise ValueError("Expected a string")
    s = " ".join(s.split())
    if not 1 <= len(s) <= maxlen or any(ord(c) < 32 for c in s):
        raise ValueError("Text length/characters are not valid")
    return s


@contextmanager
def _immediate_transaction(db: sqlite3.Connection):
    """Serialize queue decisions across dashboard and worker processes."""
    db.execute("BEGIN IMMEDIATE")
    try:
        yield
    except BaseException:
        db.rollback()
        raise
    else:
        db.commit()


def init_db(path: str | Path) -> sqlite3.Connection:
    path = Path(path).expanduser().resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(path, timeout=15, isolation_level=None, check_same_thread=False)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA busy_timeout=15000")
    db.executescript(SCHEMA)
    now = utc_now()
    with db:
        db.executemany("INSERT OR IGNORE INTO business VALUES (?,?,?,?)", BUSINESSES)
        db.executemany("""INSERT OR IGNORE INTO offer
           (id,business_id,name,summary,price_cents,kind,updated_at) VALUES (?,?,?,?,?,?,?)""",
           (r + (now,) for r in SEED_OFFERS))
    return db


def audit(db: sqlite3.Connection, offer: str | None, kind: str, message: str) -> None:
    db.execute("INSERT INTO activity(ts,offer_id,kind,message) VALUES (?,?,?,?)",
               (utc_now(),offer,kind,message[:300]))


def snapshot(db: sqlite3.Connection) -> dict[str, Any]:
    businesses = [dict(r) for r in db.execute("SELECT * FROM business ORDER BY rowid")]
    offers = [dict(r) for r in db.execute("SELECT * FROM offer ORDER BY rowid")]
    jobs = [dict(r) for r in db.execute("SELECT * FROM job ORDER BY id DESC LIMIT 30")]
    for o in offers:
        o["listing"] = json.loads(o.pop("listing_json"))
        o["qa"] = json.loads(o.pop("qa_json"))
        o["artifact_ready"] = bool(o.pop("artifact"))
    activity = [dict(r) for r in db.execute("SELECT * FROM activity ORDER BY id DESC LIMIT 35")]
    expenses = db.execute("SELECT COALESCE(SUM(amount_cents),0) FROM expense").fetchone()[0]
    return {"mode":"local_draft_only", "marketplaces_connected":0,
            "verified_orders":0,"verified_gross_cents":0,"cleared_payouts_cents":0,
            "owner_entered_expenses_cents":expenses,
            "businesses":businesses, "offers":offers,"jobs":jobs,"activity":activity,
            "ai_mode": bool(os.environ.get("STAR_COMMERCE_LLM_URL"))}


def queue_pipeline(db: sqlite3.Connection, offer_id: str) -> list[int]:
    if not db.execute("SELECT 1 FROM offer WHERE id=?", (offer_id,)).fetchone():
        raise ValueError("Unknown offer")
    # A new run number is computed in transaction so repeated clicks do not create duplicates.
    with _immediate_transaction(db):
        queued = db.execute("SELECT 1 FROM job WHERE offer_id=? AND state IN ('queued','running')",
                            (offer_id,)).fetchone()
        if queued:
            raise ValueError("This offer already has an active pipeline")
        revision = db.execute("SELECT COALESCE(MAX(id),0)+1 FROM job WHERE offer_id=?",(offer_id,)).fetchone()[0]
        created = []
        for step in ALLOWED_STEPS:
            cur = db.execute("INSERT INTO job(offer_id,step,state,dedupe_key,created_at,updated_at) VALUES (?,?,?,?,?,?)",
                             (offer_id,step,"queued",f"{offer_id}:{revision}:{step}",utc_now(),utc_now()))
            job_id = cur.lastrowid
            if job_id is None:
                raise RuntimeError("Inserted job has no row ID")
            created.append(job_id)
        db.execute("UPDATE offer SET state='producing',qa_json='{}',rights_review='',updated_at=? WHERE id=?",
                   (utc_now(),offer_id))
        audit(db,offer_id,"pipeline","Queued three internal production stages. No marketplace actions.")
    return created


def _safe_base(db: sqlite3.Connection) -> Path:
    base = Path(db.execute("PRAGMA database_list").fetchone()[2]).parent / "artifacts"
    base.mkdir(parents=True,exist_ok=True)
    return base.resolve()


def _svgs(name: str) -> dict[str, str]:
    # Hand-authored geometries, not replicas of any game/brand artwork.
    return {
      "scene-frame.svg": '''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1920 1080">
<defs><linearGradient id="t" x1="0" y1="0" x2="1" y2="1"><stop stop-color="#D7B692"/><stop offset="1" stop-color="#E4E7DC"/></linearGradient></defs>
<g fill="none" stroke="url(#t)" stroke-width="3"><path d="M66 217V92h158 M1696 92h158v125 M66 856v131h158 M1696 987h158V856"/>
<path opacity=".35" d="M100 143H510 M1410 143h410 M100 939h342 M1478 939h342"/></g>
<circle cx="960" cy="87" r="7" fill="#E4E7DC"/><path d="M920 87h-40 M1000 87h40" stroke="#D7B692" stroke-width="2"/>
</svg>''',
      "status-panel.svg": '''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 600 260">
<defs><linearGradient id="a"><stop stop-color="#242D2D"/><stop offset="1" stop-color="#364141"/></linearGradient></defs>
<path d="M0 29L32 0H552L600 48V260H0Z" fill="url(#a)"/><path d="M1 70H599" stroke="#8B9C92" opacity=".4"/>
<g fill="#D4DCD5" font-family="Arial,sans-serif"><text x="32" y="46" font-size="21" letter-spacing="4">STATUS / 01</text><text x="38" y="128" font-size="31">READY</text></g>
<path d="M40 170H556" stroke="#6B7A73" stroke-width="13"/><path d="M40 170H412" stroke="#C8AC89" stroke-width="13"/>
<path d="M40 221H556" stroke="#6B7A73" stroke-width="13"/><path d="M40 221H522" stroke="#9FB8A7" stroke-width="13"/>
</svg>''',
      "minimap-shell.svg": '''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 520 520">
<path d="M24 0H496L520 24V496L496 520H24L0 496V24Z" fill="#1E2929" fill-opacity=".8" stroke="#D4B79A" stroke-width="3"/>
<g stroke="#D4B79A" opacity=".4" fill="none" stroke-width="2"><path d="M104 0V520 M208 0V520 M312 0V520 M416 0V520 M0 104H520 M0 208H520 M0 312H520 M0 416H520"/></g>
<g fill="none" stroke="#D4B79A" stroke-width="15"><path d="M110 115H210V227H292V380H400"/></g>
<path d="M260 220L289 288L260 277L231 288Z" fill="#E7E6DE"/>
</svg>''',
      "action-chip.svg": '''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 440 120">
<path d="M1 1H403L439 36V119H1Z" fill="#283636" stroke="#C7AA8B" stroke-width="2"/>
<path d="M54 37l24 24-24 24-24-24z" fill="none" stroke="#E0C6A6" stroke-width="4"/>
<text x="112" y="72" fill="#E6E9E2" font-family="Arial,sans-serif" font-size="28" letter-spacing="3">ACTION 01</text>
</svg>''',
      "ticker.svg": '''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1160 100">
<path d="M0 0h1126l34 34v66H0Z" fill="#252F30" fill-opacity=".92"/>
<path d="M0 99h1160" stroke="#CBAE8B" stroke-width="2"/>
<circle cx="46" cy="51" r="10" fill="#A7BAA9"/>
<text x="85" y="60" font-family="Arial,sans-serif" fill="#E5E8E0" font-size="24" letter-spacing="5">NEW CHAPTER / WELCOME</text>
</svg>''',
      "crosshair.svg": '''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 200 200">
<g fill="none" stroke="#E5E7DE" stroke-width="5"><path d="M100 11v55 M100 134v55 M11 100h55 M134 100h55"/></g><circle cx="100" cy="100" r="17" fill="none" stroke="#D4B79A" stroke-width="5"/>
</svg>'''
    }


def produce_asset(db: sqlite3.Connection, offer: dict[str, Any]) -> tuple[str, str]:
    # Original SVG *starter* files only. Physical and client services get a concept brief.
    root = _safe_base(db)
    dest = root / f"{offer['id']}.zip"
    files = _svgs(offer["name"]) if offer["kind"] == "digital" else {}
    readme = (
        f"{offer['name']}\n\n{offer['summary']}\n\n"
        "INTERNAL CONCEPT / NOT FOR DISTRIBUTION BEFORE RIGHTS + HUMAN QA.\n"
        "Original template assets; edit the artwork, typography, positioning and customer details.\n"
        "No trademark, platform affiliation, performance or marketplace approval is claimed.\n"
        "For personalized or client services, obtain a real buyer brief first.\n"
    )
    files["README.txt"] = readme
    files["offer-metadata.json"] = json.dumps({"title":offer["name"],"price_cents":offer["price_cents"],
             "status":"internal_draft","marketplace_published":False},indent=2)
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer,"w",compression=zipfile.ZIP_DEFLATED,compresslevel=7) as z:
        for fname,body in files.items():
            zi = zipfile.ZipInfo(fname,date_time=(2026,1,1,0,0,0))
            zi.compress_type = zipfile.ZIP_DEFLATED
            z.writestr(zi,body.encode("utf-8"))
    content = buffer.getvalue()
    if len(content) > 8_000_000:
        raise ValueError("Generated asset is too large")
    temp = dest.with_suffix(".tmp")
    temp.write_bytes(content)
    temp.replace(dest)
    digest=hashlib.sha256(content).hexdigest()
    return dest.name,digest


def _offline_listing(offer: dict[str, Any]) -> dict[str, Any]:
    return {"title":offer["name"],"description":(
        f"{offer['summary']}. This is an original design concept, prepared for human review. "
        "Please verify the finished deliverables, applicable licenses, product images, "
        "buyer requirements and production terms before publication."),
        "tags":["original creator design","customizable","digital art"] if offer["kind"]=="digital" else
               ["custom design","seller original","made to order"],
        "ai_disclosure_required":True,
        "source":"deterministic_offline_draft","approved":False}


def _optional_local_brain(offer: dict[str, Any], fallback: dict[str, Any]) -> dict[str, Any]:
    """Only loopback OpenAI-compatible models; fail closed to deterministic drafts."""
    value=os.environ.get("STAR_COMMERCE_LLM_URL","").strip()
    if not value:
        return fallback
    from urllib.parse import urlparse
    url=urlparse(value)
    if url.scheme != "http" or url.hostname not in ("localhost","127.0.0.1","::1"):
        raise ValueError("STAR_COMMERCE_LLM_URL must use HTTP loopback only")
    if not url.path.endswith("/chat/completions"):
        raise ValueError("Expected an OpenAI-compatible /chat/completions endpoint")
    payload = json.dumps({"model":os.environ.get("STAR_COMMERCE_MODEL","local"),
              "temperature":0.2,"max_tokens":400,"messages":[
              {"role":"system","content":"Write original, factual commercial listing text. Return only valid JSON: {title, description, tags}. Never assert sales, certifications, ownership verification, or unprovided specifics. No trademarks. This is a draft."},
              {"role":"user","content":json.dumps({k:offer[k] for k in ("name","summary","kind")})}] }).encode()
    try:
        req=urllib.request.Request(value,payload,headers={"Content-Type":"application/json"},method="POST")
        # Do not follow redirects to hosted providers or arbitrary public URLs.
        class _NoRedirect(urllib.request.HTTPRedirectHandler):
            def redirect_request(self, request, fp, code, msg, headers, newurl):
                raise ValueError("Local model endpoint redirects are forbidden")
        with urllib.request.build_opener(_NoRedirect()).open(req,timeout=10) as r:
            if r.status!=200 or int(r.headers.get("Content-Length","0") or "0")>40000:
                raise ValueError("Unexpected response")
            body=r.read(40001)
        if len(body)>40000: raise ValueError("Model output exceeded limit")
        candidate=json.loads(json.loads(body)["choices"][0]["message"]["content"])
        title=_clean(candidate["title"],90)
        description=_clean(candidate["description"],1000)
        tags=candidate.get("tags",[])
        if not isinstance(tags,list) or len(tags)>13: raise ValueError("Bad tags")
        tags=[_clean(t,28) for t in tags]
        return {"title":title,"description":description,"tags":tags,
                "ai_disclosure_required":True,"source":"local_model_unverified","approved":False}
    except (urllib.error.URLError, KeyError, IndexError, TypeError, json.JSONDecodeError, ValueError):
        return {**fallback,"warning":"Local model unavailable or invalid; used offline draft"}


def verify_asset(db: sqlite3.Connection, offer: dict[str, Any]) -> dict[str, Any]:
    # Mechanical tests are NOT human originality/design/marketplace approval.
    root=_safe_base(db)
    file=offer["artifact"]
    if not file or file!=f"{offer['id']}.zip":
        raise ValueError("No generated artifact found")
    path=root/file
    if not path.is_file() or path.stat().st_size>8_000_000:
        raise ValueError("Missing or oversized artifact")
    data=path.read_bytes()
    if hashlib.sha256(data).hexdigest()!=offer["sha256"]:
        raise ValueError("Artifact checksum mismatch")
    names=[]
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        for member in z.infolist():
            if (member.filename.startswith("/") or ".." in Path(member.filename).parts
                or member.file_size>1_000_000): raise ValueError("Unsafe archive member")
            if member.filename.endswith(".svg"):
                root_el=ET.fromstring(z.read(member))
                if not root_el.tag.endswith("svg"): raise ValueError("Invalid SVG")
            names.append(member.filename)
    if "README.txt" not in names or "offer-metadata.json" not in names:
        raise ValueError("Required documentation missing")
    if offer["kind"]=="digital" and len([n for n in names if n.endswith(".svg")])<5:
        raise ValueError("Not enough original digital example files")
    return {"checks":"passed_mechanical_tests", "archive_files":len(names),
            "sha256":offer["sha256"],"human_rights_review":False,
            "human_visual_qa":False,"buyer_customization_review":False,
            "commercial_ready":False}


def run_next(db: sqlite3.Connection) -> dict[str, Any] | None:
    # Transactions lease one runnable job; downstream steps require previous success.
    with db:
        row=db.execute("""SELECT j.* FROM job j WHERE j.state='queued'
          AND NOT EXISTS (SELECT 1 FROM job earlier WHERE earlier.offer_id=j.offer_id
          AND earlier.id < j.id AND earlier.id >
          COALESCE((SELECT MAX(id) FROM job newer WHERE newer.offer_id=j.offer_id AND newer.step='qa' AND newer.id<j.id),0)
          AND earlier.state!='completed') ORDER BY j.id LIMIT 1""").fetchone()
        if row is None: return None
        job=dict(row)
        claimed=db.execute("UPDATE job SET state='running',updated_at=? WHERE id=? AND state='queued'",(utc_now(),job["id"]))
        if claimed.rowcount != 1:
            return None
    try:
        offer_row=db.execute("SELECT * FROM offer WHERE id=?",(job["offer_id"],)).fetchone()
        if offer_row is None: raise ValueError("Offer missing")
        offer=dict(offer_row)
        if job["step"]=="produce":
            filename,digest=produce_asset(db,offer)
            with db:
                db.execute("UPDATE offer SET artifact=?,sha256=?,updated_at=? WHERE id=?",
                           (filename,digest,utc_now(),offer["id"]))
        elif job["step"]=="listing":
            listing=_optional_local_brain(offer,_offline_listing(offer))
            with db:
                db.execute("UPDATE offer SET listing_json=?,updated_at=? WHERE id=?",
                           (json.dumps(listing),utc_now(),offer["id"]))
        elif job["step"]=="qa":
            qa=verify_asset(db,offer)
            with db:
                db.execute("UPDATE offer SET qa_json=?,state='awaiting_owner_review',updated_at=? WHERE id=?",
                           (json.dumps(qa),utc_now(),offer["id"]))
        else: raise ValueError("Unrecognized step")
        with db:
            db.execute("UPDATE job SET state='completed',updated_at=? WHERE id=?",(utc_now(),job["id"]))
            audit(db,offer["id"],job["step"],f"Completed {job['step']} internally; no marketplace action.")
        return {"id":job["id"],"step":job["step"],"state":"completed"}
    except Exception as exc:
        with db:
            db.execute("UPDATE job SET state='failed',error=?,updated_at=? WHERE id=?",
                       (str(exc)[:400],utc_now(),job["id"]))
            db.execute("UPDATE offer SET state='blocked',updated_at=? WHERE id=?",(utc_now(),job["offer_id"]))
            db.execute("UPDATE job SET state='cancelled',error='Upstream stage failed',updated_at=? WHERE offer_id=? AND id>? AND state='queued'",
                       (utc_now(),job["offer_id"],job["id"]))
            audit(db,job["offer_id"],"failed",f"{job['step']} failed: {str(exc)[:150]}")
        return {"id":job["id"],"step":job["step"],"state":"failed","error":str(exc)[:200]}


def run_all(db: sqlite3.Connection,limit: int=30) -> list[dict[str, Any]]:
    if limit<1 or limit>100: raise ValueError("Limit out of range")
    out=[]
    for _ in range(limit):
        next_one=run_next(db)
        if next_one is None: break
        out.append(next_one)
    return out


def review_offer(db: sqlite3.Connection, offer_id: str, rights_evidence: str) -> None:
    rights_evidence=_clean(rights_evidence,300)
    offer=db.execute("SELECT * FROM offer WHERE id=?",(offer_id,)).fetchone()
    if not offer or offer["state"]!="awaiting_owner_review":
        raise ValueError("Offer is not ready for owner review")
    qa=json.loads(offer["qa_json"])
    if qa.get("checks")!="passed_mechanical_tests":
        raise ValueError("Mechanical QA has not passed")
    with db:
        db.execute("UPDATE offer SET rights_review=?,state='internally_approved',updated_at=? WHERE id=?",
                   (rights_evidence,utc_now(),offer_id))
        audit(db,offer_id,"owner_review","Owner entered rights/quality evidence. Marketplace publication remains disabled.")


def record_expense(db: sqlite3.Connection,business_id: str, category: str, amount_cents: int, memo: str="") -> None:
    if not isinstance(amount_cents,int) or isinstance(amount_cents,bool) or not 0 <= amount_cents <= 10_000_000:
        raise ValueError("Amount must be integer cents from 0 to 10000000")
    category=_clean(category,45)
    if memo: memo=_clean(memo,180)
    if not db.execute("SELECT 1 FROM business WHERE id=?",(business_id,)).fetchone():
        raise ValueError("Unknown business")
    with db:
        db.execute("INSERT INTO expense(ts,business_id,category,amount_cents,memo) VALUES (?,?,?,?,?)",
                   (utc_now(),business_id,category,amount_cents,memo))
        audit(db,None,"expense",f"Owner-recorded {category} expense ${amount_cents/100:.2f}; not a verified invoice.")


def artifact_path(db: sqlite3.Connection, offer_id: str) -> Path:
    row=db.execute("SELECT artifact FROM offer WHERE id=?",(offer_id,)).fetchone()
    if not row or row["artifact"]!=f"{offer_id}.zip" or not re.fullmatch(r"[a-z0-9-]+",offer_id):
        raise FileNotFoundError(offer_id)
    path=_safe_base(db)/row["artifact"]
    if not path.is_file(): raise FileNotFoundError(offer_id)
    return path
