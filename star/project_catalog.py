"""Owner-confirmed product identities; repository names are refreshable metadata.

These labels never grant GitHub permissions, select a deployment target, or rename
local data. Keep the product identity separate from repository paths and redirects.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class ProjectIdentity:
    name: str
    purpose: str
    repository_id: int
    expected_full_name: str
    aliases: tuple[str, ...] = ()


PROJECTS = (
    ProjectIdentity("Metallic-RC", "Our own Rec Room", 1420186760,
                    "oncoursemail/Metallic-RC", ("Metallic",)),
    ProjectIdentity("Metallic-MC", "Minecraft", 1424831109,
                    "oncoursemail/Metallic-MC"),
    ProjectIdentity("Metallic-RB", "Roblox Rec Room", 1408973704,
                    "oncoursemail/Metallic-RB"),
    ProjectIdentity("Metallic-PX", "Progress", 1410841343,
                    "oncoursemail/Metallic-PX"),
    ProjectIdentity("STAR development", "Private STAR source and development", 1412474221,
                    "oncoursemail/Star-AI-Private"),
    ProjectIdentity("STAR distribution", "Public STAR distribution", 1424898960,
                    "oncoursemail/Star-AI"),
)


def project_catalog() -> dict:
    return {
        "schema_version": "star-project-identities-v1",
        "confirmed_on": "2026-10-19",
        "domain": {"name": "metallic.club", "owner_reported_purchased": True,
                   "dns_verified": False, "deployment_verified": False},
        "projects": [asdict(project) for project in PROJECTS],
        "identity_rule": "Match repository_id; refresh the current full_name from GitHub.",
        "grants_permissions": False,
    }


def project_for_repository(repository_id: int) -> dict | None:
    if type(repository_id) is not int or repository_id <= 0:
        raise ValueError("Repository ID must be a positive integer")
    return next((asdict(project) for project in PROJECTS if project.repository_id == repository_id), None)
