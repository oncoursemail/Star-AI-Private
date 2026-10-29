"""STAR's system self-model: one live view of her machines, GPUs, models, services, deployed code and own learning.

    collect.py   pulls the existing endpoints (router /mesh/status, brain /models + /metrics, service /health pages,
                 deployed file hashes) into one snapshot; no agents on the GPU machines
    reports.py   what other jobs tell it (eval scores, nightly training, autotuner, upgrade watcher, code/PR/CI)
    brief.py     a short plain-text answer block for STAR's tool and Litha's prompt ("what GPU am I on, why slow")
    service.py   HTTP sibling of the mesh router on 127.0.0.1:8103; the router forwards /mesh/self* here
    code.py      runs on the owner PC (gh is signed in there): open PRs, CI, which commit each service runs
"""
