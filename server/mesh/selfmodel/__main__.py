"""python -m mesh.selfmodel [self.json]   (PYTHONPATH=server) - run STAR's system self-model service (:8103).
python -m mesh.selfmodel code-push ...   (owner PC) - report repo head, open PRs, CI and deployed commits (code.py)."""
import sys

if len(sys.argv) > 1 and sys.argv[1] == "code-push":
    from .code import main as code_main
    sys.exit(code_main(sys.argv[2:]))

from .service import main

sys.exit(main(sys.argv[1:]))
