"""
Sibling-repo locations and Metabase target config this console orchestrates
against. A separate, independent repo from both siblings (per the explicit
2026-08-15 decision this console was built under) -- it reads and triggers
work in them via subprocess/file I/O, it does not import their code or
duplicate their logic.
"""

from pathlib import Path

CONSOLE_ROOT = Path(__file__).resolve().parent.parent

# Siblings, same parent directory as this repo.
WSDA_VIDEO_ENGINE = CONSOLE_ROOT.parent / "wsda-video-engine"
DATA_COURSE_ENGINE = CONSOLE_ROOT.parent / "wsda-video-creator"

# Local data this console owns: generated projects, their lesson scripts,
# and everything derived from them. Not part of either sibling repo.
DATA_DIR = CONSOLE_ROOT / "data"
PROJECTS_DIR = DATA_DIR / "projects"

# Reused verbatim across every session on this PoC so far (metabase_driver.py,
# state_seed.py, all three lesson_script.yml files) -- not re-derived here,
# just pointed at.
METABASE_BASE_URL = "http://localhost:3000"
METABASE_ADMIN_EMAIL = "admin@wsda.local"
METABASE_ADMIN_PASSWORD = "WsdaDemo123!"

LESSON_CONTENT_STANDARD = WSDA_VIDEO_ENGINE / "LESSON_CONTENT_STANDARD.md"
QA_CHECKLIST = WSDA_VIDEO_ENGINE / "QA_CHECKLIST.md"
METABASE_DRIVER = WSDA_VIDEO_ENGINE / "automation" / "metabase_driver.py"
AUDIT_NARRATOR = WSDA_VIDEO_ENGINE / "narration" / "audit_narrator.py"
OUTPUT_DIR = WSDA_VIDEO_ENGINE / "output"

# Existing example lesson scripts, used as few-shot grounding for generation
# -- not because they're the only valid shape, but because they're the only
# scripts on this project that are actually proven to record and render
# correctly end to end.
EXAMPLE_SCRIPTS = [
    WSDA_VIDEO_ENGINE / "courses" / "metabase_poc" / "video_1_1" / "lesson_script.yml",
    WSDA_VIDEO_ENGINE / "courses" / "metabase_poc" / "video_1_3" / "lesson_script.yml",
]


def ensure_data_dirs() -> None:
    PROJECTS_DIR.mkdir(parents=True, exist_ok=True)
