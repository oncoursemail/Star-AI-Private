"""python -m mesh.verify [verify.json]  (PYTHONPATH=server) - run the Litha code verifier (:8101)."""
import sys

from .service import main

sys.exit(main(sys.argv[1:]))
