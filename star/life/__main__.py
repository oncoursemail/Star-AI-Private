"""python -m star.life status | moment | diary | gallery | token | serve | widget   (small tools for the owner)."""
from __future__ import annotations

import sys
import time

from . import api, goals, scrapbook, studio
from .store import default_store


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    command = args[0] if args else "status"
    store = default_store()
    if command == "status":
        print(f"moments {len(scrapbook.moments(store, 10000))}, wishes going {len(goals.goals(store, ('open', 'active', 'paused')))}, "
              f"done {len(goals.goals(store, 'done'))}, works {len(studio.works(store, 10000))}")
        due = scrapbook.due(store, time.time())
        print("anniversary today:", due.text if due else "none")
    elif command == "moment":              # moment <kind> <title> <source> [media]: the owner adds something real by hand
        if len(args) < 4:
            print("usage: python -m star.life moment <kind> <title> <source> [media-file]")
            return 2
        made = scrapbook.add_moment(store, args[1], args[2], source=args[3], media=args[4] if len(args) > 4 else "")
        print("saved" if made else "refused (needs a valid kind, a title, a source and a date that is not in the future)")
    elif command == "diary":
        print(goals.diary_text(store, 30) or "nothing yet")
    elif command == "gallery":
        print(studio.gallery_text(store, 40) or "nothing yet")
    elif command == "token":               # prints the PATH of the token file, never the token
        api.read_token()
        print(api.token_path())
    elif command == "serve":
        server = api.serve()
        print("serving on", server.server_address)
        server.serve_forever()
    elif command == "widget":
        from . import widget
        return widget.run()
    else:
        print(__doc__)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
