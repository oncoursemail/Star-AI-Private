"""python -m mesh.docs [docs.json]  (PYTHONPATH=server) - run the official docs service (:8102)."""
import sys

from .service import main

sys.exit(main(sys.argv[1:]))
