"""Diagnostics that never print API keys, document text, or raw local paths."""
from __future__ import annotations

import argparse
import json

from .clients import AnythingLLMClient, LemonadeClient, ProviderError
from .config import BridgeConfig, ConfigError
from .grounded import GroundedBridge


def main() -> None:
    parser = argparse.ArgumentParser(description="Experimental Litha local inference & knowledge adapters")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("doctor", help="Read provider status without changing model/workspace state")
    answer = sub.add_parser("ask", help="Ground an answer in a preconfigured AnythingLLM workspace")
    answer.add_argument("--workspace", required=True)
    answer.add_argument("--model", required=True, help="Already downloaded Lemonade model id")
    answer.add_argument("question")
    args = parser.parse_args()
    try:
        cfg = BridgeConfig.from_env()
        lemonade = LemonadeClient(cfg)
        anythingllm = AnythingLLMClient(cfg)
        if args.command == "doctor":
            result = {"lemonade_enabled": cfg.lemonade_enabled, "anythingllm_enabled": cfg.anythingllm_enabled}
            if cfg.lemonade_enabled:
                result["lemonade"] = lemonade.health()
                result["installed_models"] = [m["id"] for m in lemonade.models()]
            if cfg.anythingllm_enabled:
                # Do not query a workspace without a user-selected slug.
                result["anythingllm"] = "configured" if cfg.anythingllm_api_key else "missing API key"
            print(json.dumps(result, indent=2))
        else:
            grounded = GroundedBridge(anythingllm, lemonade).ask(args.workspace, args.question, model=args.model)
            print(json.dumps({
                "status": grounded.status, "answer": grounded.text,
                "sources": [{"id": f"S{i+1}", "title": h.title, "reference": h.reference} for i, h in enumerate(grounded.sources)],
                "model": grounded.model,
            }, indent=2, ensure_ascii=False))
    except (ConfigError, ProviderError) as exc:
        parser.exit(status=2, message=f"Bridge error: {exc}\n")


if __name__ == "__main__":
    main()
