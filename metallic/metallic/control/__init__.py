"""Metallic Control: the owner's admin dashboard for the Metallic back end (machines, containers, Star AI, forge and
CI, backups, allow-listed admin actions with an audit log). Standard library only, like the rest of `metallic`.

    collector.py  samples the machines through the host gates (server/control/metallic_control_gate.py), the brain's
                  router, the forge API and the PC agent's pushes; derives rates and alerts
    store.py      SQLite time series (raw 5 s for 3 h, 1-minute for 2 days, 10-minute for 8 days), requests, audit
    actions.py    the admin allow-list
    server.py     HTTP API + the built UI (metallic/control-ui), token login, CSRF, optional HTTPS
    pc_agent.py   the Windows PC's reporter (pushes every 10 s, runs the PC's own allow-listed actions)
"""
