"""
Format tier definitions -- decided explicitly (2026-08-15) as a video-count
axis, distinct from the older duration/register-based taxonomy already used
by the SQL/AI pipeline in wsda-video-creator (micro/short-video/tutorial/
lesson/course) and by the abandoned engine/format_templates_v2.py scaffold
in wsda-video-engine (same old taxonomy, unrelated to this one). Checked
both for reusable naming before defining this; neither fit this axis, so
this is a new, small vocabulary, kept intentionally narrow rather than
merged with either existing one.

Each tier controls: how many videos a project has, whether videos chain
state via requires_state, and how heavy the opening recap should be --
see LESSON_CONTENT_STANDARD.md's "Grounded in SQL Essential Training"
section (chapter-opener vs. within-chapter recap textures) and
MULTI_VIDEO_PROGRESSION_FINDINGS.md (the requires_state mechanism itself)
for why these specific defaults were chosen.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class FormatTier:
    id: str
    label: str
    video_count_label: str
    min_videos: int
    max_videos: int
    recap_style: str
    chains_state: bool
    description: str


FORMAT_TIERS = {
    "micro": FormatTier(
        id="micro",
        label="Micro",
        video_count_label="1 video",
        min_videos=1,
        max_videos=1,
        recap_style="none",
        chains_state=False,
        description=(
            "Single video, 50 seconds or less. No multi-video progression, "
            "no recap opener, tight and self-contained -- proven end-to-end "
            "only at the single-video-with-no-requires_state shape so far."
        ),
    ),
    "short-form": FormatTier(
        id="short-form",
        label="Short-form",
        video_count_label="2-4 videos",
        min_videos=2,
        max_videos=4,
        recap_style="light",
        chains_state=True,
        description=(
            "A small number of videos, light or no recap between them -- the "
            "within-chapter (XR30 to XR30) transcript texture: same "
            "stakeholder, a new ask, no formal 'in the last video' framing. "
            "This is exactly the shape proven by video_1_1 through video_1_3."
        ),
    ),
    "mid-form": FormatTier(
        id="mid-form",
        label="Mid-form",
        video_count_label="5-10 videos",
        min_videos=5,
        max_videos=10,
        recap_style="chapter-opener",
        chains_state=True,
        description=(
            "A fuller sequence with real recap-then-new-request chapter "
            "openers per LESSON_CONTENT_STANDARD.md's chapter-opener pattern "
            "(hook, explicit recap, new stakeholder request, new tool named, "
            "transition). Not yet proven end-to-end on this project -- video "
            "count and requires_state chain length both go beyond what "
            "video_1_1-1_3 actually tested."
        ),
    ),
    "long-form": FormatTier(
        id="long-form",
        label="Long-form / full course",
        video_count_label="11+ videos",
        min_videos=11,
        max_videos=None,
        recap_style="chapter-opener",
        chains_state=True,
        description=(
            "The complete structure LESSON_CONTENT_STANDARD.md describes as "
            "proven in Walter's own SQL Essential Training course: welcome, "
            "multiple chapters each with opener/lesson(s)/challenge, wrap-up. "
            "Not built or tested at this scale on the Metabase path at all --"
            " generation and requires_state chaining are both extrapolations "
            "past what's actually been proven."
        ),
    ),
}


def get(tier_id: str) -> FormatTier:
    if tier_id not in FORMAT_TIERS:
        raise ValueError(f"unknown format tier {tier_id!r}")
    return FORMAT_TIERS[tier_id]
