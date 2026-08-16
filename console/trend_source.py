"""
Reads the trend engine's ranked topic report from the sibling
data-course-engine repo (data/processed/ranked_*.json) -- read-only, no
import of that repo's code, just its output file, same boundary as every
other sibling-repo integration in this console.
"""

import json
from pathlib import Path

from console.paths import DATA_COURSE_ENGINE


def latest_ranked_report() -> dict | None:
    """Returns {"date": "...", "topics": [...]} for the most recent
    ranked_*.json, or None if the trend engine hasn't produced one yet."""
    processed_dir = DATA_COURSE_ENGINE / "data" / "processed"
    if not processed_dir.is_dir():
        return None

    reports = sorted(processed_dir.glob("ranked_*.json"))
    if not reports:
        return None

    latest = reports[-1]
    date = latest.stem.removeprefix("ranked_")
    with open(latest) as f:
        topics = json.load(f)

    # Highest score first -- the report itself doesn't guarantee ordering.
    topics = sorted(topics, key=lambda t: t.get("score", 0), reverse=True)
    return {"date": date, "path": str(latest), "topics": topics}
