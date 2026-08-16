# WSDA Pipeline Console

A standalone, local UI for running the Metabase course pipeline end to
end -- topic selection, format-tier-aware lesson script generation,
review/editing, render triggering, QA checklist surfacing, and
review/approve -- without hand-typing instructions into Claude Code for
routine runs.

A separate, independent repo from both `wsda-video-engine` (the Metabase
automation this console drives) and `wsda-video-creator` / data-course-
engine (the trend engine this console reads topic suggestions from).
Decided explicitly 2026-08-15: different repo, different purpose, kept
independent of `wsda-video-engine`'s existing `studio.py` (port 7010),
which this console does not touch or replace.

## Requires

- The two sibling repos checked out alongside this one:
  `../wsda-video-engine` and `../wsda-video-creator`.
- A running local Metabase instance (`http://localhost:3000`, same demo
  credentials `automation/state_seed.py` already uses).
- `ANTHROPIC_API_KEY` in the environment, for script generation.

## Run

```
pip install -r requirements.txt
python3 app.py
```

Opens at `http://localhost:7500`.

## Format tiers

See `console/format_tiers.py`. A video-count axis (micro: 1 video,
short-form: 2-4, mid-form: 5-10, long-form: 11+), decided as its own,
narrow vocabulary -- checked `LESSON_CONTENT_STANDARD.md` and the older
duration-based taxonomy already used by the SQL/AI pipeline first, and
found neither one fit this axis, so this is new rather than reused.

## Status

Built incrementally, commit by commit -- see git log for what's actually
working versus still in progress. Only `micro` and `short-form` are
proven end to end on the underlying Metabase automation (video_1_1
through video_1_3); `mid-form` and `long-form` are this console's own
extrapolation past what's actually been tested, flagged as such in
`console/format_tiers.py`.
