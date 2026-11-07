"""Broad, source-first learning curriculum for STAR's general knowledge.

A research map, NOT a knowledge download, remote search result, or model fine-tune.
Connects the existing consented web-research and reviewed knowledge tools to a
reproducible study plan with provenance, comparison and transfer tests.
"""
from __future__ import annotations

from dataclasses import dataclass
import re


@dataclass(frozen=True)
class Domain:
    id: str
    label: str
    keywords: tuple[str, ...]
    source: str
    url: str
    method: str
    transfer: str


DOMAINS = (
    Domain("mathematics", "Mathematics & logic",
           ("mathematics", "math", "algebra", "calculus", "geometry", "statistics", "proof", "probability"),
           "OpenStax Math", "https://openstax.org/subjects/math",
           "Derive the result and check it against a worked problem.",
           "Solve a related problem with different numbers and explain why the method transfers."),
    Domain("physics", "Physics & mechanics",
           ("physics", "motion", "force", "energy", "gravity", "collision", "velocity", "mechanics"),
           "OpenStax Physics", "https://openstax.org/subjects/science",
           "Describe the model, dimensions, assumptions and a reproducible measurement.",
           "Predict an unfamiliar collision or animation and compare it with a sandbox simulation."),
    Domain("biology", "Biology & living systems",
           ("biology", "cell", "organism", "evolution", "genetics", "ecology", "animal", "anatomy"),
           "NIH NCBI Bookshelf", "https://www.ncbi.nlm.nih.gov/books/",
           "Distinguish primary evidence, textbook explanation and speculation.",
           "Explain how an environmental change affects an unfamiliar ecosystem."),
    Domain("earth", "Earth science & geography",
           ("geography", "climate", "weather", "geology", "volcano", "planet", "ocean", "earth"),
           "NOAA Education", "https://www.noaa.gov/education",
           "Check location, time range, units and original measurement source.",
           "Explain a comparable pattern in a different geographical region."),
    Domain("history", "History & society",
           ("history", "civilization", "historical", "war", "ancient", "empire", "culture", "archive"),
           "Library of Congress", "https://www.loc.gov/",
           "Separate primary sources from interpretation; check dates and competing accounts.",
           "Compare explanations for an unfamiliar event without assuming a single cause."),
    Domain("computing", "Computer science & systems",
           ("computer", "programming", "algorithm", "software", "code", "operating", "network", "database", "ai"),
           "MIT OpenCourseWare", "https://ocw.mit.edu/",
           "Run a minimal reproducible program and inspect worst-case and failure behavior.",
           "Adapt an algorithm to a different data size or platform."),
    Domain("engineering", "Engineering & safety",
           ("engineering", "electrical", "electronics", "mechanical", "robot", "control", "hardware", "material"),
           "NIST", "https://www.nist.gov/",
           "Identify standards, measurement uncertainty and realistic operating constraints.",
           "Design a failure-resistant alternative and list how to validate it."),
    Domain("economics", "Economics & data literacy",
           ("economics", "economy", "prices", "trade", "inflation", "business", "finance", "market"),
           "FRED", "https://fred.stlouisfed.org/",
           "Check definitions, units, vintage, time period and causal claims.",
           "Analyze a different data series without mistaking correlation for causation."),
    Domain("health", "Health & human physiology",
           ("health", "medicine", "medical", "nutrition", "immune", "physiology", "disease"),
           "MedlinePlus", "https://medlineplus.gov/",
           "Distinguish population evidence from individual medical advice; check source review dates.",
           "Identify what evidence would change a claim and when a clinician is needed."),
    Domain("visualarts", "Art, design & animation",
           ("art", "animation", "vfx", "visual", "shading", "design", "color", "rigging", "render", "blender"),
           "Blender Manual", "https://docs.blender.org/manual/en/latest/",
           "Reproduce a technique in an original small scene and measure performance.",
           "Transfer the same motion principle to a different character or visual style."),
    Domain("gamedev", "Game design & interaction",
           ("game", "gaming", "roblox", "studio", "level", "playtest", "fps", "npc", "physics"),
           "Roblox Creator Hub", "https://create.roblox.com/docs",
           "Inspect official engine behavior, implement in a disposable test place and run a measured playtest.",
           "Rebuild the mechanism as an original feature in a new genre with testable results."),
    Domain("language", "Languages & communication",
           ("language", "linguistic", "grammar", "speech", "translation", "writing", "literature"),
           "MIT OpenCourseWare", "https://ocw.mit.edu/",
           "Compare context-sensitive meanings and verify examples with reviewed material.",
           "Explain the same concept precisely for a novice and for an expert."),
    Domain("astronomy", "Astronomy & space",
           ("astronomy", "space", "solar", "star", "galaxy", "orbit", "rocket", "universe"),
           "NASA Science", "https://science.nasa.gov/",
           "Verify objects, distances, dates and observations from primary missions.",
           "Predict how a change in orbital conditions would affect a simulation."),
)

_ID = re.compile(r"[a-z][a-z0-9_-]{1,30}\Z")


def plan(question: str, *, max_domains: int = 4) -> dict:
    """Return bounded domain/source/test suggestions; nothing fetched or saved."""
    if type(question) is not str or not 3 <= len(question.strip()) <= 500:
        raise ValueError("Supply a specific research topic of 3-500 characters")
    if type(max_domains) is not int or not 1 <= max_domains <= 8:
        raise ValueError("max_domains must be 1-8")
    text = question.casefold()
    words = set(re.findall(r"[a-z]{2,}", text))
    scored = []
    for entry in DOMAINS:
        score = sum(3 if word in words else 0 for word in entry.keywords)
        if entry.id in words:
            score += 5
        scored.append((score, entry))
    ranked = sorted(scored, key=lambda item: (-item[0], item[1].id))
    selected = ([item[1] for item in ranked if item[0] > 0][:max_domains]
                or [entry for entry in DOMAINS
                    if entry.id in ("mathematics", "physics", "history", "computing", "gamedev", "biology", "earth", "visualarts")][:max_domains])
    tasks = []
    for domain in selected:
        tasks.append({
            "domain": domain.id, "label": domain.label, "source_name": domain.source,
            "source_url": domain.url, "source_status": "suggested_not_retrieved",
            "research_query": f"{question.strip()[:250]} site:{domain.url.split('/')[2]}",
            "learn": domain.method,
            "transfer_test": domain.transfer,
            "checkpoints": [
                "Find a current, properly licensed or authorized source and record title, URL, author and date.",
                "Extract an exact claim and its supporting passage; keep the source and interpretation separate.",
                "Seek an independent corroboration or counterexample and state uncertainty.",
                "Perform a question-answer or executable test without providing its answer in the prompt.",
                "Store only reviewed evidence as accepted knowledge; keep model summaries as candidates.",
            ],
        })
    return {
        "topic": question.strip(), "domain_count": len(tasks), "tasks": tasks,
        "status": "research_plan_only",
        "not_fetched": True, "model_parameters_updated": False,
        "note": "This plan supplies source candidates and falsifiable learning tasks. "
                "STAR must still retrieve permitted sources, test answers and obtain human "
                "review before adding trusted facts.",
    }
