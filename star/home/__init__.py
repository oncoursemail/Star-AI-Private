"""STAR Home: STAR's own Windows PC (issue #613; owner 2026-10-26).

control.py   the data folder, the owner's global stop and the append-only action log
host.py      the executor that runs STAR's actions on that PC (shell, winget, files, screen, mouse, keyboard, apps)
life.py      her interests (weights she changes), goals, verified activity history and the novelty scheduler
activities.py the activity registry; other packages plug in with register_home_activities(registry)
brain.py     a bounded tool-calling loop against the brain's OpenAI-compatible HTTP API
__main__.py  `python -m star.home run|once|status|stop|resume|interests|weight|log`

Install on the PC with installer/star-home/setup.cmd. Notes: docs/agents/star-home-20261026.md.
"""
