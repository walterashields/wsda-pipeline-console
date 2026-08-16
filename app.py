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

import yaml
from flask import Flask, redirect, render_template_string, request, url_for

from console import format_tiers, generator, projects, state_chain, trend_source

app = Flask(__name__)

BASE_CSS = """
* { box-sizing: border-box; margin: 0; padding: 0; }
:root {
  --bg: #0f1923; --surface: #1a2535; --surface-2: #212f42; --border: #2a3a50;
  --text: #e8eef5; --text-dim: #6b8299; --green: #06c015; --blue: #4a9eff;
  --yellow: #ffd700; --red: #ff4a4a; --radius: 10px;
  --font: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
}
body { font-family: var(--font); background: var(--bg); color: var(--text);
       min-height: 100vh; padding: 40px 20px; }
.container { max-width: 920px; margin: 0 auto; }
a { color: inherit; text-decoration: none; }
.logo { display: flex; align-items: center; gap: 12px; margin-bottom: 28px; }
.logo-mark { width: 36px; height: 36px; background: var(--green); border-radius: 8px;
             display: flex; align-items: center; justify-content: center;
             font-weight: 900; font-size: 16px; color: #000; }
.logo-text { font-size: 19px; font-weight: 700; }
.logo-sub { font-size: 12px; color: var(--text-dim); margin-top: 1px; }
.card { background: var(--surface); border: 1px solid var(--border);
        border-radius: var(--radius); padding: 26px; margin-bottom: 18px; }
.card-title { font-size: 12px; font-weight: 700; color: var(--text-dim);
              text-transform: uppercase; letter-spacing: .06em; margin-bottom: 16px; }
.btn { display: inline-block; background: var(--green); color: #000; font-weight: 700;
       border: none; border-radius: 8px; padding: 11px 20px; font-size: 14px;
       cursor: pointer; }
.btn.secondary { background: var(--surface-2); color: var(--text); border: 1px solid var(--border); }
.btn.small { padding: 6px 12px; font-size: 12px; }
.row { display: flex; gap: 10px; flex-wrap: wrap; align-items: center; }
.chip { border: 1px solid var(--border); border-radius: 8px; padding: 12px 16px;
        cursor: pointer; background: var(--surface-2); flex: 1; min-width: 180px; }
.chip.selected { border-color: var(--green); background: #10371a; }
.chip-label { font-weight: 700; font-size: 14px; }
.chip-sub { font-size: 12px; color: var(--text-dim); margin-top: 4px; }
label { display: block; font-size: 12px; color: var(--text-dim); margin: 14px 0 6px; }
input[type=text], input[type=number], select, textarea {
  width: 100%; background: var(--bg); border: 1px solid var(--border); color: var(--text);
  border-radius: 8px; padding: 10px 12px; font-size: 14px; font-family: inherit; }
textarea { font-family: ui-monospace, monospace; font-size: 13px; line-height: 1.5; }
.status { display: inline-block; padding: 3px 9px; border-radius: 6px; font-size: 11px;
          font-weight: 700; text-transform: uppercase; letter-spacing: .04em; }
.status.planned { background: #2a3a50; color: var(--text-dim); }
.status.generating, .status.rendering { background: #3a2f0a; color: var(--yellow); }
.status.generated, .status.rendered { background: #123a1a; color: var(--green); }
.status.qa_pending { background: #123a1a; color: var(--blue); }
.status.approved { background: #06c015; color: #000; }
.status.flagged, .status.render_failed { background: #3a1414; color: var(--red); }
.video-row { display: flex; justify-content: space-between; align-items: center;
             padding: 12px 0; border-bottom: 1px solid var(--border); }
.video-row:last-child { border-bottom: none; }
.muted { color: var(--text-dim); font-size: 13px; }
.project-row { display: flex; justify-content: space-between; align-items: center;
               padding: 14px 0; border-bottom: 1px solid var(--border); }
.project-row:last-child { border-bottom: none; }
.tier-badge { font-size: 11px; padding: 3px 9px; border-radius: 6px;
              background: var(--surface-2); border: 1px solid var(--border); color: var(--text-dim); }
"""

BASE_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>WSDA Pipeline Console</title>
<style>{{ css }}</style>
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
        action_btn = (
            f'<a class="btn secondary small" href="/projects/{slug}/videos/{vid}/edit">Edit script</a>'
            if has_script else
            f'<a class="btn small" href="/projects/{slug}/videos/{vid}/edit">Generate</a>'
        )
        video_rows += f"""
        <div class="video-row">
          <div>
            <strong>{vid}</strong>
            <span class="muted">{v.get('title') or '(not generated yet)'}</span>
          </div>
          <div class="row">
            <span class="status {v['status']}">{v['status'].replace('_', ' ')}</span>
            {action_btn}
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


@app.route("/projects/<slug>/videos/<video_id>/edit")
def edit_video(slug, video_id):
    project = projects.load_project(slug)
    if project is None or project.video(video_id) is None:
        return render_page('<p class="muted">Not found.</p>'), 404

    script_path = project.script_path(video_id)
    error = request.args.get("error", "")
    error_block = f'<div class="card" style="border-color:var(--red);"><p style="color:var(--red);">{error}</p></div>' if error else ""

    if script_path.exists():
        script_text = script_path.read_text()
        content = f"""
        {error_block}
        <div class="card">
          <div class="card-title">{video_id} &middot; script</div>
          <form method="POST" action="/projects/{slug}/videos/{video_id}/script">
            <textarea name="script_text" rows="34" spellcheck="false">{script_text}</textarea>
            <div class="row" style="margin-top:14px;">
              <button class="btn" type="submit">Save</button>
              <span class="muted">Raw lesson_script.yml -- edits are saved as-is, no validation beyond YAML parsing before render.</span>
            </div>
          </form>
        </div>
        <div class="card">
          <div class="card-title">Regenerate</div>
          <form method="POST" action="/projects/{slug}/videos/{video_id}/generate">
            <label>Workflow guidance (optional)</label>
            <input type="text" name="workflow_hint" placeholder="e.g. add a second chart to the existing dashboard">
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
          live Metabase schema, and this project's earlier videos. Produces a draft
          for review here, not a script that renders automatically.</p>
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
    if project is None or project.video(video_id) is None:
        return render_page('<p class="muted">Not found.</p>'), 404

    workflow_hint = request.form.get("workflow_hint", "")
    project.update_video(video_id, status="generating")
    projects.save_project(project)

    try:
        text = generator.generate_lesson_script(project, video_id, workflow_hint)
    except Exception as exc:
        project.update_video(video_id, status="planned")
        projects.save_project(project)
        return redirect(url_for("edit_video", slug=slug, video_id=video_id, error=str(exc)))

    title = None
    try:
        title = yaml.safe_load(text).get("title")
    except Exception:
        pass

    project.update_video(video_id, status="generated", title=title, workflow_hint=workflow_hint,
                          script_relpath=str(project.script_path(video_id).relative_to(project.dir())))
    projects.save_project(project)
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

    project.script_path(video_id).write_text(text)
    project.update_video(video_id, status="generated", title=(parsed or {}).get("title"))
    projects.save_project(project)
    return redirect(url_for("edit_video", slug=slug, video_id=video_id))


if __name__ == "__main__":
    app.run(port=7500, debug=True)
