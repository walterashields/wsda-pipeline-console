#!/usr/bin/env python3
"""
WSDA Pipeline Console -- standalone UI for the Metabase course pipeline.

A fresh, separate app from wsda-video-engine's existing studio.py (port
7010) -- different repo, different purpose, kept independent per the
2026-08-15 decision. This one is format-tier-aware (micro/short-form/
mid-form/long-form, see console/format_tiers.py) and drives the Metabase
automation path specifically (automation/metabase_driver.py,
automation/state_seed.py, requires_state) in the sibling wsda-video-engine
repo, not the SQL/AI pipeline in wsda-video-creator.

Run with: python3 app.py
Opens at: http://localhost:7500
"""

from pathlib import Path

import yaml
from flask import Flask, abort, jsonify, redirect, render_template_string, request, send_file, url_for

from console import format_tiers, generator, projects, qa, render_runner, state_chain, trend_source, validator
from console.paths import OUTPUT_DIR

app = Flask(__name__)

BASE_CSS = """
* { box-sizing: border-box; margin: 0; padding: 0; }
:root {
  --bg: #0f1923; --surface: #1a2535; --surface-2: #212f42; --border: #2a3a50;
  --text: #e8eef5; --text-dim: #6b8299; --green: #06c015; --blue: #4a9eff;
  --yellow: #ffd700; --red: #ff4a4a; --radius: 10px;
  --font: "DM Sans", -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
  --font-mono: "DM Mono", ui-monospace, "SF Mono", Menlo, monospace;
}
body { font-family: var(--font); background:
         radial-gradient(700px 420px at 12% 0%, rgba(6,192,21,.05), transparent 60%),
         radial-gradient(600px 380px at 100% 0%, rgba(74,158,255,.035), transparent 55%),
         var(--bg);
       background-repeat: no-repeat;
       color: var(--text); min-height: 100vh; padding: 40px 20px; }
.container { max-width: 920px; margin: 0 auto; }
a { color: inherit; text-decoration: none; }
.logo { display: flex; align-items: center; gap: 12px; margin-bottom: 28px; }
.logo-mark { width: 36px; height: 36px; border-radius: 9px;
             background: linear-gradient(155deg, var(--green) 0%, #049c10 100%);
             box-shadow: 0 2px 10px -2px rgba(6,192,21,.5), inset 0 1px 0 rgba(255,255,255,.25);
             display: flex; align-items: center; justify-content: center;
             font-family: var(--font-mono); font-weight: 500; font-size: 16px; color: #06130a; }
.logo-text { font-size: 19px; font-weight: 700; letter-spacing: -.01em; }
.logo-sub { font-size: 12px; color: var(--text-dim); margin-top: 1px;
            font-family: var(--font-mono); }
.card { background: var(--surface); border: 1px solid var(--border);
        border-radius: var(--radius); padding: 26px; margin-bottom: 18px;
        box-shadow: 0 1px 0 rgba(255,255,255,.02) inset, 0 8px 24px -12px rgba(0,0,0,.4);
        transition: border-color .15s ease; }
.card-title { font-size: 12px; font-weight: 700; color: var(--text-dim);
              text-transform: uppercase; letter-spacing: .08em; margin-bottom: 16px;
              font-family: var(--font-mono); }
.btn { display: inline-block; background: var(--green); color: #06130a; font-weight: 700;
       border: none; border-radius: 8px; padding: 11px 20px; font-size: 14px;
       cursor: pointer; font-family: var(--font); letter-spacing: -.01em;
       box-shadow: 0 2px 8px -2px rgba(6,192,21,.45);
       transition: transform .12s ease, box-shadow .12s ease, filter .12s ease; }
.btn:hover { transform: translateY(-1px); filter: brightness(1.06);
             box-shadow: 0 4px 14px -3px rgba(6,192,21,.6); }
.btn:active { transform: translateY(0); }
.btn.secondary { background: var(--surface-2); color: var(--text); border: 1px solid var(--border);
                 box-shadow: none; }
.btn.secondary:hover { border-color: #3a5170; background: #263650; }
.btn.small { padding: 6px 12px; font-size: 12px; }
.row { display: flex; gap: 10px; flex-wrap: wrap; align-items: center; }
.chip { border: 1px solid var(--border); border-radius: 8px; padding: 12px 16px;
        cursor: pointer; background: var(--surface-2); flex: 1; min-width: 180px;
        transition: border-color .12s ease, background .12s ease, transform .12s ease; }
.chip:hover { border-color: #3a5170; transform: translateY(-1px); }
.chip.selected { border-color: var(--green); background: #10371a; }
.chip-label { font-weight: 700; font-size: 14px; }
.chip-sub { font-size: 12px; color: var(--text-dim); margin-top: 4px; }
label:not(.chip) { display: block; font-size: 11px; color: var(--text-dim); margin: 14px 0 6px;
        text-transform: uppercase; letter-spacing: .06em; font-family: var(--font-mono); }
input[type=text], input[type=number], select, textarea {
  width: 100%; background: var(--bg); border: 1px solid var(--border); color: var(--text);
  border-radius: 8px; padding: 10px 12px; font-size: 14px; font-family: inherit;
  transition: border-color .12s ease, box-shadow .12s ease; }
input[type=text]:focus, input[type=number]:focus, select:focus, textarea:focus {
  outline: none; border-color: var(--green); box-shadow: 0 0 0 3px rgba(6,192,21,.15); }
textarea { font-family: var(--font-mono); font-size: 13px; line-height: 1.55; }
.status { display: inline-block; padding: 3px 9px; border-radius: 6px; font-size: 11px;
          font-weight: 700; text-transform: uppercase; letter-spacing: .05em;
          font-family: var(--font-mono); }
.status.planned { background: #2a3a50; color: var(--text-dim); }
.status.generating, .status.rendering { background: #3a2f0a; color: var(--yellow); }
.status.generated, .status.rendered { background: #123a1a; color: var(--green); }
.status.qa_pending { background: #123a1a; color: var(--blue); }
.status.approved { background: #06c015; color: #06130a; }
.status.flagged, .status.render_failed, .status.needs_fix { background: #3a1414; color: var(--red); }
.video-row { display: flex; justify-content: space-between; align-items: center;
             padding: 12px 0; border-bottom: 1px solid var(--border); }
.video-row:last-child { border-bottom: none; }
.muted { color: var(--text-dim); font-size: 13px; }
.project-row { display: flex; justify-content: space-between; align-items: center;
               padding: 14px 0; border-bottom: 1px solid var(--border);
               transition: padding-left .12s ease; }
.project-row:hover { padding-left: 4px; }
.project-row:last-child { border-bottom: none; }
.tier-badge { font-size: 11px; padding: 3px 9px; border-radius: 6px; font-family: var(--font-mono);
              background: var(--surface-2); border: 1px solid var(--border); color: var(--text-dim); }
pre, code { font-family: var(--font-mono); }
::selection { background: rgba(6,192,21,.35); }
"""

BASE_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>WSDA Pipeline Console</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=DM+Sans:opsz,wght@9..40,400;9..40,500;9..40,700;9..40,900&family=DM+Mono:wght@400;500&display=swap" rel="stylesheet">
<style>{{ css|safe }}</style>
</head>
<body>
<div class="container">
  <div class="logo">
    <div class="logo-mark">P</div>
    <div>
      <div class="logo-text">WSDA Pipeline Console</div>
      <div class="logo-sub">Metabase course pipeline &middot; format-tier aware</div>
    </div>
  </div>
  {{ content|safe }}
</div>
</body>
</html>"""


def render_page(content: str) -> str:
    return render_template_string(BASE_HTML, css=BASE_CSS, content=content)


@app.route("/")
def home():
    all_projects = projects.list_projects()
    if not all_projects:
        rows = '<p class="muted">No projects yet.</p>'
    else:
        rows = ""
        for p in all_projects:
            tier = format_tiers.get(p.format_tier)
            done = sum(1 for v in p.videos if v["status"] == "approved")
            rows += f"""
            <div class="project-row">
              <div>
                <a href="/projects/{p.slug}"><strong>{p.topic}</strong></a>
                <div class="muted">{len(p.videos)} video(s) &middot; {done} approved</div>
              </div>
              <span class="tier-badge">{tier.label}</span>
            </div>"""

    content = f"""
    <div class="card">
      <div class="card-title">Projects</div>
      {rows}
    </div>
    <a class="btn" href="/new">+ New Project</a>
    """
    return render_page(content)


@app.route("/new")
def new_project_form():
    report = trend_source.latest_ranked_report()
    if report:
        topic_rows = ""
        for t in report["topics"][:10]:
            topic_rows += f"""
            <label class="chip" style="display:block;">
              <input type="radio" name="topic" value="{t['topic']}" style="width:auto;display:inline;margin-right:8px;">
              <span class="chip-label">{t['topic']}</span>
              <span class="chip-sub">score {t.get('score', 0):.2f} &middot; {t.get('rationale', '')[:140]}</span>
            </label>"""
        trend_block = f"""
        <div class="card-title" style="margin-top:22px;">From trend report ({report['date']})</div>
        {topic_rows}
        """
    else:
        trend_block = '<p class="muted" style="margin-top:16px;">No trend report found in data-course-engine yet -- enter a topic manually below.</p>'

    tier_chips = ""
    for tier in format_tiers.FORMAT_TIERS.values():
        tier_chips += f"""
        <label class="chip">
          <input type="radio" name="format_tier" value="{tier.id}" style="width:auto;display:inline;margin-right:6px;">
          <span class="chip-label">{tier.label}</span>
          <span class="chip-sub">{tier.video_count_label}</span>
        </label>"""

    content = f"""
    <form method="POST" action="/projects" class="card">
      <div class="card-title">Topic</div>
      <label>Manual topic / platform</label>
      <input type="text" name="manual_topic" placeholder="e.g. Filtering and pinning a first Metabase question">
      {trend_block}

      <div class="card-title" style="margin-top:22px;">Format tier</div>
      <div class="row">{tier_chips}</div>

      <label>Number of videos</label>
      <input type="number" name="num_videos" value="1" min="1" max="20">

      <div style="margin-top:20px;">
        <button class="btn" type="submit">Create Project</button>
      </div>
    </form>
    """
    return render_page(content)


@app.route("/projects", methods=["POST"])
def create_project():
    topic = request.form.get("topic") or request.form.get("manual_topic") or ""
    topic = topic.strip()
    format_tier = request.form.get("format_tier", "micro")
    num_videos = int(request.form.get("num_videos", 1))
    tier = format_tiers.get(format_tier)
    num_videos = max(tier.min_videos, min(num_videos, tier.max_videos or num_videos))

    source = "trend_report" if request.form.get("topic") else "manual"
    trend_meta = None
    if source == "trend_report":
        report = trend_source.latest_ranked_report()
        if report:
            trend_meta = next(
                (t for t in report["topics"] if t["topic"] == topic), None
            )

    if not topic:
        return redirect(url_for("new_project_form"))

    project = projects.create_project(
        topic=topic,
        format_tier=format_tier,
        num_videos=num_videos,
        source=source,
        trend_meta=trend_meta,
    )
    return redirect(url_for("project_detail", slug=project.slug))


@app.route("/projects/<slug>")
def project_detail(slug):
    project = projects.load_project(slug)
    if project is None:
        return render_page('<p class="muted">Project not found.</p>'), 404

    tier = format_tiers.get(project.format_tier)
    video_rows = ""
    for v in project.videos:
        vid = v["video_id"]
        has_script = project.script_path(vid).exists()
        validation_status = (v.get("validation") or {}).get("status")

        # Fast path (2026-08-17): a script that passed the validation gate
        # cleanly gets a "Quick Review" primary action (a short summary +
        # one-click render, see video_review()) instead of forcing a full
        # raw-YAML read-through every time. Full edit stays one click away,
        # optional rather than the default gate. A script that DIDN'T pass
        # keeps "Edit script" as the only/primary action -- that's exactly
        # the case human judgment is actually needed for, not skippable.
        if has_script and validation_status == "pass":
            action_btn = (
                f'<a class="btn small" href="/projects/{slug}/videos/{vid}/review">Quick Review</a> '
                f'<a class="btn secondary small" href="/projects/{slug}/videos/{vid}/edit">Edit script</a>'
            )
        elif has_script:
            action_btn = f'<a class="btn secondary small" href="/projects/{slug}/videos/{vid}/edit">Edit script</a>'
        else:
            action_btn = f'<a class="btn small" href="/projects/{slug}/videos/{vid}/edit">Generate</a>'

        render_btn = ""
        if has_script and validation_status != "fail":
            render_btn = f"""
            <form method="POST" action="/projects/{slug}/videos/{vid}/render" style="display:inline;">
              <button class="btn secondary small" type="submit">Render</button>
            </form>"""
        elif has_script:
            render_btn = '<span class="muted" style="color:var(--red);">Render blocked -- see script review</span>'
        job_link = ""
        if v.get("job_id"):
            job_link = f'<a class="btn secondary small" href="/jobs/{v["job_id"]}">Job</a>'
        qa_link = ""
        if v["status"] in ("rendered", "qa_pending", "approved", "flagged"):
            qa_link = f'<a class="btn secondary small" href="/projects/{slug}/videos/{vid}/qa">Review / QA</a>'
        video_rows += f"""
        <div class="video-row">
          <div>
            <strong>{vid}</strong>
            <span class="muted">{v.get('title') or '(not generated yet)'}</span>
          </div>
          <div class="row">
            <span class="status {v['status']}">{v['status'].replace('_', ' ')}</span>
            {action_btn}
            {render_btn}
            {job_link}
            {qa_link}
          </div>
        </div>"""

    chain_link = (
        f'<a class="btn secondary small" href="/projects/{slug}/state-chain" style="margin-bottom:14px;display:inline-block;">View requires_state chain &rarr;</a>'
        if len(project.videos) > 1 else ""
    )

    content = f"""
    <div class="card">
      <div class="card-title">{project.topic}</div>
      <p class="muted">{tier.label} &middot; {tier.video_count_label} &middot; source: {project.source}</p>
      <p class="muted" style="margin-top:8px;">{tier.description}</p>
    </div>
    <div class="card">
      <div class="card-title">Videos</div>
      {video_rows}
    </div>
    {chain_link}
    <a class="btn secondary" href="/">&larr; All projects</a>
    """
    return render_page(content)


@app.route("/projects/<slug>/state-chain")
def project_state_chain(slug):
    project = projects.load_project(slug)
    if project is None:
        return render_page('<p class="muted">Project not found.</p>'), 404

    chain = state_chain.project_dependency_chain(project)

    rows = ""
    for entry in chain:
        produces_html = "".join(
            f'<div class="muted">&rarr; produces <strong>{p["type"]}</strong> "{p["name"]}"'
            + (f' (contains: {", ".join(p["contains"])})' if p.get("contains") else "")
            + "</div>"
            for p in entry["produces"]
        ) or '<div class="muted">&rarr; produces nothing declared</div>'

        requires_html = ""
        for r in entry["requires"]:
            if r["satisfied_by"]:
                requires_html += f'<div style="color:var(--green);">&larr; requires {r["type"]} "{r["name"]}" -- satisfied by {r["satisfied_by"]}</div>'
            else:
                requires_html += f'<div style="color:var(--red);">&larr; requires {r["type"]} "{r["name"]}" -- NOT produced by any earlier video in this project</div>'
        if not entry["requires"]:
            requires_html = '<div class="muted">&larr; requires nothing (no requires_state block)</div>'

        script_state = "no script yet" if entry["status"] == "planned" and not entry["produces"] and not entry["requires"] else entry["status"]

        rows += f"""
        <div class="card">
          <div class="card-title">{entry['video_id']} <span class="muted" style="text-transform:none;">({script_state})</span></div>
          {requires_html}
          {produces_html}
        </div>"""

    content = f"""
    <h3 style="margin-bottom:16px;">requires_state chain &middot; {project.topic}</h3>
    <p class="muted" style="margin-bottom:20px;">What each video in this project needs from earlier videos, and what it
    leaves behind for later ones -- read directly from each video's own script (save_question /
    add_to_dashboard events for what it produces, its requires_state block for what it needs), not
    hand-maintained separately.</p>
    {rows}
    <a class="btn secondary" href="/projects/{slug}">&larr; {slug}</a>
    """
    return render_page(content)


def _validation_block(video) -> str:
    v = video.validation or {}
    status = v.get("status")
    if status == "pass":
        return ('<div class="card" style="border-color:var(--green);"><div class="card-title">'
                'Pre-render validation</div><p style="color:var(--green);">&#10003; Every declared '
                'query was run against live Metabase data and returned a real, non-empty result. '
                'Render is allowed.</p></div>')
    if status == "fail":
        rows = "".join(
            f'<div style="color:var(--red); margin-top:6px;">event {c["event_id"]}: {c["detail"]}</div>'
            for c in v.get("checks", []) if c["status"] != "pass"
        )
        return (f'<div class="card" style="border-color:var(--red);"><div class="card-title">'
                f'Pre-render validation -- BLOCKED</div><p style="color:var(--red);">One or more steps in '
                f'this script do not produce a real result against live Metabase data right now -- '
                f'narrating over this would state something false on screen, the exact defect this gate '
                f'exists to catch. Render is disabled until this is fixed.</p>{rows}</div>')
    if status == "unchecked":
        return ('<div class="card" style="border-color:var(--yellow);"><div class="card-title">'
                'Pre-render validation -- unchecked</div><p style="color:var(--yellow);">This script declared '
                'no `validations` entries, so nothing was verified against real data. If this video filters '
                'or aggregates anything, that\'s a gap worth fixing by hand before rendering, not assumed safe.</p></div>')
    return ""


def _narration_summary(script_text: str) -> list:
    """What this video will actually show and say, in order -- the short
    summary the fast-path review reads instead of raw YAML (2026-08-17).
    Pulled directly from the script's own narration fields, not
    hand-summarized, so it can't drift from what will actually render."""
    try:
        card = yaml.safe_load(script_text) or {}
    except yaml.YAMLError:
        return []
    beats = []
    for e in card.get("events", []):
        text = (e.get("narration") or "").strip()
        if text:
            beats.append({"event_id": e["id"], "type": e["type"], "text": text})
    return beats


@app.route("/projects/<slug>/videos/<video_id>/review")
def video_review(slug, video_id):
    project = projects.load_project(slug)
    video = project.video(video_id) if project else None
    if project is None or video is None:
        return render_page('<p class="muted">Not found.</p>'), 404

    script_path = project.script_path(video_id)
    if not script_path.exists():
        return redirect(url_for("edit_video", slug=slug, video_id=video_id))

    # This page's whole reason to exist is standing in for a full YAML
    # read -- only offered when the validation gate actually passed. A
    # script that needs a human's eyes gets sent to the real editor
    # instead, not shown a falsely-reassuring summary.
    if (video.validation or {}).get("status") != "pass":
        return redirect(url_for("edit_video", slug=slug, video_id=video_id))

    text = script_path.read_text()
    beats = _narration_summary(text)
    card = yaml.safe_load(text) or {}
    tier = format_tiers.get(project.format_tier)
    order = next(v["order"] for v in project.videos if v["video_id"] == video_id)

    requires_html = ""
    requires_state = card.get("requires_state") or []
    if requires_state:
        names = ", ".join(f'{r["type"]} "{r["name"]}"' for r in requires_state)
        requires_html = f'<p class="muted" style="margin-top:8px;">Depends on: {names} (seeded automatically before recording)</p>'

    beats_html = "".join(
        f'<div class="video-row"><div><span class="muted">{b["type"]}</span><div>{b["text"]}</div></div></div>'
        for b in beats
    ) or '<p class="muted">No narrated beats found in this script.</p>'

    content = f"""
    <div class="card" style="border-color:var(--green);">
      <div class="card-title">Quick Review &middot; {video_id} ({order} of {len(project.videos)})</div>
      <p style="color:var(--green);">&#10003; Every filter/aggregation this video performs was run against
      real, live Metabase data and returned a genuine result -- this is the fast path, standing in for a full
      script read, not a lower bar.</p>
    </div>
    <div class="card">
      <div class="card-title">{card.get('title', video_id)}</div>
      <p class="muted">{tier.label} &middot; format: {card.get('format', '(default)')}</p>
      {requires_html}
    </div>
    <div class="card">
      <div class="card-title">What this video shows and says, in order</div>
      {beats_html}
    </div>
    <form method="POST" action="/projects/{slug}/videos/{video_id}/render" style="display:inline;">
      <button class="btn" type="submit">Looks good &mdash; Render</button>
    </form>
    <a class="btn secondary" href="/projects/{slug}/videos/{video_id}/edit">Edit full script instead</a>
    <a class="btn secondary" href="/projects/{slug}">&larr; {slug}</a>
    """
    return render_page(content)


@app.route("/projects/<slug>/videos/<video_id>/edit")
def edit_video(slug, video_id):
    project = projects.load_project(slug)
    video = project.video(video_id) if project else None
    if project is None or video is None:
        return render_page('<p class="muted">Not found.</p>'), 404

    script_path = project.script_path(video_id)
    error = request.args.get("error", "")
    error_block = f'<div class="card" style="border-color:var(--red);"><p style="color:var(--red);">{error}</p></div>' if error else ""
    validation_block = _validation_block(video)

    # A flagged video's note is the whole point of re-generating -- pre-fill
    # it here so it demonstrably reaches the prompt rather than depending on
    # Walter noticing and manually re-typing it (the actual root cause of a
    # real bug: a flag note was never wired into regeneration at all, so a
    # regenerated script repeated the exact same mistake it was flagged for).
    prefill_hint = video.workflow_hint or ""
    if video.status == "flagged" and video.notes:
        prefill_hint = video.notes

    if script_path.exists():
        script_text = script_path.read_text()
        content = f"""
        {error_block}
        {validation_block}
        <div class="card">
          <div class="card-title">{video_id} &middot; script</div>
          <form method="POST" action="/projects/{slug}/videos/{video_id}/script">
            <textarea name="script_text" rows="34" spellcheck="false">{script_text}</textarea>
            <div class="row" style="margin-top:14px;">
              <button class="btn" type="submit">Save</button>
              <span class="muted">Raw lesson_script.yml -- saving re-runs the pre-render validation gate automatically.</span>
            </div>
          </form>
        </div>
        <div class="card">
          <div class="card-title">Regenerate</div>
          <form method="POST" action="/projects/{slug}/videos/{video_id}/generate">
            <label>Workflow guidance / feedback to address</label>
            <textarea name="workflow_hint" rows="3" placeholder="e.g. add a second chart to the existing dashboard">{prefill_hint}</textarea>
            <p class="muted" style="margin-top:6px;">{"Pre-filled from this video's flagged note -- edit or clear it, but whatever's here is what the regeneration will be told to address." if video.status == "flagged" and video.notes else ""}</p>
            <div style="margin-top:12px;">
              <button class="btn secondary" type="submit">Regenerate from scratch</button>
            </div>
          </form>
        </div>
        """
    else:
        content = f"""
        {error_block}
        <form method="POST" action="/projects/{slug}/videos/{video_id}/generate" class="card">
          <div class="card-title">Generate {video_id}</div>
          <label>Workflow guidance (optional)</label>
          <input type="text" name="workflow_hint" placeholder="e.g. add a second chart to the existing dashboard">
          <p class="muted" style="margin-top:12px;">Calls the Anthropic API, grounded in LESSON_CONTENT_STANDARD.md, the
          live Metabase schema, and this project's earlier videos, then automatically validates every filter/
          aggregation it produces against real Metabase data before this page shows it to you -- a script whose
          declared checks fail gets one automatic corrected retry.</p>
          <div style="margin-top:16px;">
            <button class="btn" type="submit">Generate script</button>
          </div>
        </form>
        """

    content += f'<a class="btn secondary" href="/projects/{slug}">&larr; {slug}</a>'
    return render_page(content)


@app.route("/projects/<slug>/videos/<video_id>/generate", methods=["POST"])
def generate_video_script(slug, video_id):
    project = projects.load_project(slug)
    video = project.video(video_id) if project else None
    if project is None or video is None:
        return render_page('<p class="muted">Not found.</p>'), 404

    workflow_hint = request.form.get("workflow_hint", "")
    # A flagged video's note is real feedback on a real defect -- always
    # passed to generation regardless of what's in the workflow_hint box,
    # so it can't silently fail to reach the prompt the way it did before
    # this fix (a flagged "this filter returns nothing" note produced an
    # identical broken regeneration, because nothing carried it forward).
    feedback = video.notes if video.status == "flagged" and video.notes else ""

    project.update_video(video_id, status="generating")
    projects.save_project(project)

    try:
        result = generator.generate_lesson_script(project, video_id, workflow_hint, feedback)
    except Exception as exc:
        project.update_video(video_id, status="planned")
        projects.save_project(project)
        return redirect(url_for("edit_video", slug=slug, video_id=video_id, error=str(exc)))

    title = None
    try:
        title = yaml.safe_load(result["text"]).get("title")
    except Exception:
        pass

    validation = result["validation"]
    new_status = "generated" if validation["status"] != "fail" else "needs_fix"
    project.update_video(video_id, status=new_status, title=title, workflow_hint=workflow_hint,
                          validation=validation, notes=None,
                          script_relpath=str(project.script_path(video_id).relative_to(project.dir())))
    projects.save_project(project)

    if validation["status"] == "fail":
        return redirect(url_for("edit_video", slug=slug, video_id=video_id,
                                 error=f"Generated, but the pre-render validation gate blocked it after "
                                       f"{result['attempts']} attempt(s) -- see details below. Fix the "
                                       f"script by hand or regenerate again with different guidance."))
    # Fast path (2026-08-17): a script that passed cleanly goes to the
    # short-summary quick-review page, not straight to a full raw-YAML
    # read-through -- full editing is still one click away from there,
    # just not the forced default. A script that needed a fix (status
    # not "pass" -- unchecked or otherwise) still lands on the full edit
    # page, since that's exactly the case human judgment is for.
    if validation["status"] == "pass":
        return redirect(url_for("video_review", slug=slug, video_id=video_id))
    return redirect(url_for("edit_video", slug=slug, video_id=video_id))


@app.route("/projects/<slug>/videos/<video_id>/script", methods=["POST"])
def save_video_script(slug, video_id):
    project = projects.load_project(slug)
    if project is None or project.video(video_id) is None:
        return render_page('<p class="muted">Not found.</p>'), 404

    text = request.form["script_text"]
    try:
        parsed = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        return redirect(url_for("edit_video", slug=slug, video_id=video_id, error=f"Not valid YAML, not saved: {exc}"))

    script_path = project.script_path(video_id)
    script_path.write_text(text)

    # Hand edits get the same pre-render gate generation does -- this is
    # what actually closes the gap for Problem 3: even if a regeneration's
    # feedback-handling were imperfect, or a human edits a filter value by
    # hand and gets it wrong, this check runs regardless, every time a
    # script's content changes, not just right after generation.
    try:
        validation = validator.validate_script(script_path)
    except Exception as exc:
        validation = {"passed": False, "status": "unchecked", "checks": [], "error": str(exc)}

    new_status = "generated" if validation["status"] != "fail" else "needs_fix"
    project.update_video(video_id, status=new_status, title=(parsed or {}).get("title"), validation=validation)
    projects.save_project(project)
    return redirect(url_for("edit_video", slug=slug, video_id=video_id))


@app.route("/projects/<slug>/videos/<video_id>/render", methods=["POST"])
def render_video(slug, video_id):
    project = projects.load_project(slug)
    if project is None or project.video(video_id) is None:
        return render_page('<p class="muted">Not found.</p>'), 404

    # Authoritative, re-run fresh right now, not trusted from whatever the
    # stored video.validation says -- the one thing this project's own
    # history has repeatedly shown is that a stored "looked fine earlier"
    # signal (an exit code, a log line, a cached status) isn't the same
    # claim as "actually true right now." This is the hard gate itself:
    # a script that fails this is never handed to the render pipeline.
    script_path = project.script_path(video_id)
    try:
        validation = validator.validate_script(script_path)
    except Exception as exc:
        return redirect(url_for("edit_video", slug=slug, video_id=video_id,
                                 error=f"Could not run the pre-render validation gate ({exc}) -- "
                                       f"not starting a render without it."))

    project.update_video(video_id, validation=validation)
    projects.save_project(project)
    if validation["status"] == "fail":
        project.update_video(video_id, status="needs_fix")
        projects.save_project(project)
        return redirect(url_for("edit_video", slug=slug, video_id=video_id,
                                 error="Render blocked: the pre-render validation gate found one or more "
                                       "steps that don't produce a real result against live data right now. "
                                       "See the validation details below."))

    try:
        job_id = render_runner.start_render(project, video_id)
    except Exception as exc:
        return redirect(url_for("edit_video", slug=slug, video_id=video_id, error=str(exc)))
    return redirect(url_for("job_status", job_id=job_id))


@app.route("/jobs/<job_id>")
def job_status(job_id):
    job = render_runner.get_job(job_id)
    if job is None:
        return render_page('<p class="muted">Job not found (console was likely restarted since it ran).</p>'), 404

    content = f"""
    <div class="card">
      <div class="card-title">Render job {job_id} &middot; {job['slug']} / {job['video_id']}</div>
      <p><span class="status {'rendered' if job['status']=='done' else ('render_failed' if job['status']=='failed' else 'rendering')}" id="status-badge">{job['status']}</span>
         <span class="muted" id="phase-label">phase: {job['phase']}</span>
         <span class="muted" id="elapsed-label"></span></p>
      <pre id="log-box" style="background:var(--bg); border:1px solid var(--border); border-radius:8px;
           padding:14px; margin-top:14px; max-height:420px; overflow-y:auto; font-size:12px;
           white-space:pre-wrap; font-family: ui-monospace, monospace;">{chr(10).join(job['log'][-300:])}</pre>
      <div id="result-box" style="margin-top:14px;"></div>
    </div>
    <a class="btn secondary" href="/projects/{job['slug']}">&larr; {job['slug']}</a>

    <script>
    const jobId = {job_id!r};
    const startedAt = {job['started_at']};
    function poll() {{
      fetch(`/api/jobs/${{jobId}}`).then(r => r.json()).then(data => {{
        document.getElementById('status-badge').textContent = data.status;
        document.getElementById('status-badge').className = 'status ' + (data.status === 'done' ? 'rendered' : (data.status === 'failed' ? 'render_failed' : 'rendering'));
        document.getElementById('phase-label').textContent = 'phase: ' + data.phase;
        const elapsed = Math.round((data.finished_at || (Date.now()/1000)) - data.started_at);
        document.getElementById('elapsed-label').textContent = elapsed + 's elapsed';
        const box = document.getElementById('log-box');
        box.textContent = data.log.slice(-300).join('\\n');
        box.scrollTop = box.scrollHeight;
        if (data.status === 'done') {{
          document.getElementById('result-box').innerHTML =
            '<p class="muted">Final video: <code>' + data.result.final_mp4 + '</code></p>';
        }} else if (data.status === 'failed') {{
          document.getElementById('result-box').innerHTML =
            '<p style="color:var(--red);">' + (data.error || 'render failed') + '</p>';
        }}
        if (data.status === 'running') setTimeout(poll, 2000);
      }});
    }}
    poll();
    </script>
    """
    return render_page(content)


@app.route("/projects/<slug>/videos/<video_id>/qa", methods=["GET", "POST"])
def video_qa(slug, video_id):
    project = projects.load_project(slug)
    video = project.video(video_id) if project else None
    if project is None or video is None:
        return render_page('<p class="muted">Not found.</p>'), 404

    if request.method == "POST":
        checked = request.form.getlist("human_checked")
        notes = request.form.get("notes", "")
        action = request.form.get("action")
        stored_qa = video.qa or {}
        stored_qa["human_checked"] = [int(x) for x in checked]
        stored_qa["notes"] = notes
        new_status = "approved" if action == "approve" else ("flagged" if action == "flag" else video.status)
        project.update_video(video_id, qa=stored_qa, status=new_status,
                              notes=notes if action == "flag" else video.notes)
        projects.save_project(project)
        return redirect(url_for("video_qa", slug=slug, video_id=video_id))

    render = video.render or {}
    script_path = project.script_path(video_id)
    automated = []
    if script_path.exists() and render.get("mp4"):
        try:
            automated = qa.run_automated_checks(
                script_path,
                Path(render["audit_json"]) if render.get("audit_json") else None,
                Path(render.get("final_mp4") or render["mp4"]),
            )
        except Exception as exc:
            automated = [{"id": 0, "status": "fail", "detail": f"could not run automated checks: {exc}"}]
    automated_by_id = {c["id"]: c for c in automated}

    stored_qa = video.qa or {}
    checked_ids = set(stored_qa.get("human_checked", []))

    preview_html = ""
    final_mp4 = render.get("final_mp4")
    if final_mp4 and Path(final_mp4).exists():
        preview_html = f"""
        <div class="card">
          <div class="card-title">Preview</div>
          <video controls style="width:100%; border-radius:8px; background:#000;" src="/media/{Path(final_mp4).name}"></video>
        </div>"""

    rows = ""
    for item in qa.CHECKLIST_ITEMS:
        auto = automated_by_id.get(item["id"])
        auto_html = ""
        if item["classification"] in ("Automated", "Both") and auto:
            color = {"pass": "var(--green)", "fail": "var(--red)", "warn": "var(--yellow)", "not_applicable": "var(--text-dim)"}[auto["status"]]
            auto_html = f'<div style="color:{color}; margin-top:4px;">[{auto["status"]}] {auto["detail"]}</div>'
        human_html = ""
        if item["classification"] in ("Human", "Both") and item["human_prompt"]:
            checked_attr = "checked" if item["id"] in checked_ids else ""
            human_html = f"""
            <label style="display:flex; align-items:flex-start; gap:8px; margin-top:8px; cursor:pointer;">
              <input type="checkbox" name="human_checked" value="{item['id']}" {checked_attr} style="width:auto; margin-top:3px;">
              <span class="muted">{item['human_prompt']}</span>
            </label>"""
        rows += f"""
        <div class="card">
          <div class="card-title">{item['id']}. {item['title']} <span class="muted" style="text-transform:none;">({item['classification']})</span></div>
          {auto_html}
          {human_html}
        </div>"""

    content = f"""
    <form method="POST">
      <h3 style="margin-bottom:16px;">QA &middot; {video_id} &middot; {project.topic}</h3>
      {preview_html}
      {rows}
      <div class="card">
        <label>Notes</label>
        <textarea name="notes" rows="3">{stored_qa.get('notes', '')}</textarea>
        <div class="row" style="margin-top:16px;">
          <button class="btn" type="submit" name="action" value="approve">Approve</button>
          <button class="btn secondary" type="submit" name="action" value="flag">Flag for another pass</button>
          <button class="btn secondary" type="submit" name="action" value="save">Save progress</button>
        </div>
      </div>
    </form>
    <a class="btn secondary" href="/projects/{slug}">&larr; {slug}</a>
    """
    return render_page(content)


@app.route("/media/<path:filename>")
def media(filename):
    # Serves rendered videos straight out of wsda-video-engine's own
    # output/ dir for in-browser preview -- filename only (no directory
    # components), resolved against OUTPUT_DIR and re-checked to still be
    # inside it, so a crafted "../../" can't walk this out to an
    # arbitrary path on disk.
    path = (OUTPUT_DIR / filename).resolve()
    if not str(path).startswith(str(OUTPUT_DIR.resolve())) or not path.exists():
        abort(404)
    return send_file(path)


@app.route("/api/jobs/<job_id>")
def api_job_status(job_id):
    job = render_runner.get_job(job_id)
    if job is None:
        return jsonify({"error": "not found"}), 404
    return jsonify(job)


if __name__ == "__main__":
    app.run(port=7500, debug=True)
