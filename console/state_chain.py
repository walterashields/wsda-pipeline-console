"""
Reads what a lesson script *produces* (questions it saves, dashboards it
pins to) and what it *requires* (its requires_state block), from the
script text itself -- so a later video's generation prompt and the
project's dependency view can both be built from the same real source
of truth (the scripts), not a separately hand-maintained description
that could drift from what a script actually does.
"""

import yaml


def produced_artifacts(script_text: str) -> list:
    """Scans a lesson script's events for save_question/add_to_dashboard
    actions and returns what this video, if run, would leave behind --
    the same shape a later video's requires_state block would need to
    name to depend on it."""
    card = yaml.safe_load(script_text) or {}
    produced = []
    dashboard_contents = {}

    for event in card.get("events", []):
        if event.get("type") == "save_question":
            produced.append({"type": "question", "name": event["question_name"]})
        elif event.get("type") == "add_to_dashboard":
            name = event["dashboard_name"]
            dashboard_contents.setdefault(name, [])

    # Best-effort: a dashboard "contains" whatever questions were saved
    # earlier in the same script, since that's the only pattern
    # video_1_1-1_3 actually exercise (save, then immediately pin).
    question_names = [p["name"] for p in produced if p["type"] == "question"]
    for name in dashboard_contents:
        produced.append({"type": "dashboard", "name": name, "contains": question_names})

    return produced


def required_state(script_text: str) -> list:
    card = yaml.safe_load(script_text) or {}
    return card.get("requires_state") or []


def project_dependency_chain(project) -> list:
    """For every video in a project that has a generated script, returns
    {video_id, produces, requires, requires_satisfied} -- requires_satisfied
    checks each requires_state entry by name against everything produced
    by an EARLIER video in the same project, so a gap (a video that
    requires_state's something no earlier video in this project actually
    produces) is visible before anything is ever rendered."""
    chain = []
    produced_so_far = {}  # (type, name) -> video_id that produces it

    for v in project.videos:
        entry = {
            "video_id": v["video_id"],
            "status": v["status"],
            "produces": [],
            "requires": [],
        }
        script_path = project.script_path(v["video_id"])
        if script_path.exists():
            text = script_path.read_text()
            entry["produces"] = produced_artifacts(text)
            requires = required_state(text)
            for r in requires:
                satisfied_by = produced_so_far.get((r["type"], r["name"]))
                entry["requires"].append({
                    "type": r["type"],
                    "name": r["name"],
                    "satisfied_by": satisfied_by,
                })
        chain.append(entry)

        for p in entry["produces"]:
            produced_so_far[(p["type"], p["name"])] = v["video_id"]

    return chain
