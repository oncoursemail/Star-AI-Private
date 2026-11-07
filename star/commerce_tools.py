"""Model-facing commerce tools (opt-in via the `commerce_enabled` setting).

STAR may research and draft freely. The only real-world step is a *proposal*: a draft
row that waits in the Business tab until the owner approves it. These tools cannot
approve or run anything. The commerce package is imported lazily because its art
scanner needs Pillow, which desktop startup must not load.
"""
from __future__ import annotations

from pathlib import Path
import re
from typing import Any

_KINDS = ["list_product", "change_price", "place_order", "spend_money", "post_public",
          "message_customer", "account_change"]
COMMERCE_TOOLS = (
    {"name": "star_commerce_overview",
     "description": "Read the owner's local Business workspace: businesses, product candidates, open monitoring findings and actions waiting for owner approval. Read only.",
     "inputSchema": {"type": "object", "properties": {}, "required": [], "additionalProperties": False}},
    {"name": "star_commerce_draft_candidate",
     "description": "Save a draft product or service idea in the local Business workspace. Local only: nothing is listed or sent.",
     "inputSchema": {"type": "object", "properties": {
         "channel": {"type": "string", "enum": ["etsy", "shopify", "fiverr", "payhip", "gumroad", "printify"]},
         "title": {"type": "string", "minLength": 1, "maxLength": 120},
         "concept": {"type": "string", "minLength": 1, "maxLength": 3000}},
         "required": ["channel", "title", "concept"], "additionalProperties": False}},
    {"name": "star_commerce_propose_action",
     "description": ("Draft a real-world commerce action (listing, price change, order, spend, public post, customer message, "
                     "account change) for the owner to approve. This only records the draft; it does NOT run. The owner "
                     "approves it in the Business tab."),
     "inputSchema": {"type": "object", "properties": {
         "kind": {"type": "string", "enum": _KINDS},
         "title": {"type": "string", "minLength": 1, "maxLength": 160},
         "details": {"type": "object"},
         "amount_cents": {"type": "integer", "minimum": 0},
         "business_id": {"type": "string", "minLength": 1, "maxLength": 64}},
         "required": ["kind", "title", "details"], "additionalProperties": False}},
)
COMMERCE_TOOL_NAMES = frozenset(tool["name"] for tool in COMMERCE_TOOLS)
COMMERCE_TRIGGER = re.compile(
    r"\b(etsy|shopify|fiverr|payhip|gumroad|printify|dropship\w*|e-?commerce|storefront|my\s+(?:shop|store|business)|"
    r"online\s+(?:shop|store|business)|product\s+listings?|listings?\s+for|merch|marketplace|supplier|autods|"
    r"customer\s+(?:message|email|inquir\w+)|side\s+hustle)\b", re.I)


def call_commerce_tool(name: str, args: dict[str, Any], *, project: str, home: Path) -> dict[str, Any]:
    from .commerce.workspace import handle_commerce
    if name == "star_commerce_overview":
        board = handle_commerce("commerceBoard", {}, project=project, home=home)
        return {
            "project": board["project"], "counts": board["counts"],
            "businesses": [{"id": b["id"], "name": b["name"], "channel": b["channel"], "paused": b.get("paused")}
                           for b in board.get("businesses", [])],
            "candidates": [{"id": i["id"], "channel": i["channel"], "title": i["title"], "status": i["status"],
                            "open_notes": i["review"]["blockers"]} for i in board["ideas"][:25]],
            "waiting_for_owner_approval": [{"id": a["id"], "kind": a["kind"], "title": a["title"]}
                                           for a in board["approvals"] if a["status"] == "pending"],
        }
    if name == "star_commerce_draft_candidate":
        before = {i["id"] for i in handle_commerce("commerceBoard", {}, project=project, home=home)["ideas"]}
        board = handle_commerce("commerceCreate", args, project=project, home=home)
        made = next(i for i in board["ideas"] if i["id"] not in before)
        return {"id": made["id"], "title": made["title"], "status": made["status"], "listed": False}
    if name == "star_commerce_propose_action":
        from .commerce.approvals import propose
        from .commerce.workspace import commerce_connection
        with commerce_connection(home) as conn, conn:
            row = propose(conn, project, args["kind"], args["title"], args["details"],
                          business_id=args.get("business_id"), amount_cents=args.get("amount_cents"))
        return {"id": row["id"], "status": row["status"], "ran": False,
                "next": "Waiting for the owner to approve it in the Business tab."}
    raise PermissionError("Unknown commerce tool")
