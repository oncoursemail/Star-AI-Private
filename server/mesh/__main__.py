"""python -m mesh [config.json]  (PYTHONPATH=server) - run the STAR compute-mesh router."""
import asyncio
import sys

from .router import main

asyncio.run(main(sys.argv[1] if len(sys.argv) > 1 else None))
