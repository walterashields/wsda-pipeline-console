"""
Project data model: one project = one topic taken through a format tier,
producing 1..N videos. Stored as plain JSON on disk under data/projects/ --
no database, matching the "keep it simple, local tool for Walter" scope.

Each video's lesson_script.yml (generated or hand-edited) lives alongside
its project.json, not inside wsda-video-engine's courses/ tree --
automation/metabase_driver.py takes an arbitrary script path as its argv,
so nothing requires generated scripts to live under the sibling repo.
"""

import json
import re
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from console.paths import PROJECTS_DIR, ensure_data_dirs

# Video lifecycle, in order. A video can also land on "render_failed" or
# "flagged" as a side branch from "rendering" / "qa_pending" respectively.
STATUSES = [
    "planned",
    "generating",
    "generated",
    "rendering",
    "render_failed",
    "rendered",
    "qa_pending",
    "approved",
    "flagged",
]


def slugify(text: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return slug[:60] or "project"


@dataclass
class VideoRecord:
    video_id: str
    order: int
    status: str = "planned"
    title: Optional[str] = None
    workflow_hint: Optional[str] = None
    script_relpath: Optional[str] = None
    job_id: Optional[str] = None
    render: dict = field(default_factory=dict)
    qa: dict = field(default_factory=dict)
    notes: Optional[str] = None


@dataclass
class Project:
    slug: str
    topic: str
    platform: str
    format_tier: str
    source: str
    created_at: str
    trend_meta: Optional[dict] = None
    videos: list = field(default_factory=list)

    def dir(self) -> Path:
        return PROJECTS_DIR / self.slug

    def video(self, video_id: str) -> Optional[VideoRecord]:
        for v in self.videos:
            if v["video_id"] == video_id:
                return VideoRecord(**v)
        return None

    def video_dir(self, video_id: str) -> Path:
        return self.dir() / video_id

    def script_path(self, video_id: str) -> Path:
        return self.video_dir(video_id) / "lesson_script.yml"

    def update_video(self, video_id: str, **fields) -> None:
        for v in self.videos:
            if v["video_id"] == video_id:
                v.update(fields)
                return
        raise ValueError(f"no video {video_id!r} on project {self.slug!r}")


def create_project(
    topic: str,
    format_tier: str,
    num_videos: int,
    platform: str = "Metabase",
    source: str = "manual",
    trend_meta: Optional[dict] = None,
) -> Project:
    ensure_data_dirs()

    base_slug = slugify(topic)
    slug = base_slug
    n = 2
    while (PROJECTS_DIR / slug).exists():
        slug = f"{base_slug}-{n}"
        n += 1

    videos = [
        asdict(VideoRecord(video_id=f"video_1_{i+1}", order=i + 1))
        for i in range(num_videos)
    ]

    project = Project(
        slug=slug,
        topic=topic,
        platform=platform,
        format_tier=format_tier,
        source=source,
        created_at=datetime.now(timezone.utc).isoformat(),
        trend_meta=trend_meta,
        videos=videos,
    )
    project.dir().mkdir(parents=True, exist_ok=True)
    save_project(project)
    return project


def save_project(project: Project) -> None:
    project.dir().mkdir(parents=True, exist_ok=True)
    with open(project.dir() / "project.json", "w") as f:
        json.dump(asdict(project), f, indent=2)


def load_project(slug: str) -> Optional[Project]:
    path = PROJECTS_DIR / slug / "project.json"
    if not path.exists():
        return None
    with open(path) as f:
        data = json.load(f)
    return Project(**data)


def list_projects() -> list:
    ensure_data_dirs()
    projects = []
    for d in sorted(PROJECTS_DIR.iterdir()):
        if (d / "project.json").exists():
            p = load_project(d.name)
            if p:
                projects.append(p)
    projects.sort(key=lambda p: p.created_at, reverse=True)
    return projects
