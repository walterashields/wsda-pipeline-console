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
    name to depend on it.

    A script that fails to parse (confirmed live, 2026-08-16: a
    generation that left invalid YAML on disk, e.g. a leftover markdown
    fence) is treated as producing nothing, not raised -- this function
    is called for EVERY video in a project while building context for
    generating or regenerating any ONE of them, including the video
    currently being (re)generated itself. A parse error on one video's
    on-disk file used to take down the ability to generate or regenerate
    ANY video in the project, including itself, which is a worse failure
    than just not knowing what a broken script produces."""
    try:
        card = yaml.safe_load(script_text) or {}
    except yaml.YAMLError:
        return []
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
    try:
        card = yaml.safe_load(script_text) or {}
    except yaml.YAMLError:
        return []
    return card.get("requires_state") or []


def project_dependency_chain(project) -> list:
    """For every video in a project that has a generated script, returns
    {video_id, produces, requires, requires_satisfied} -- requires_satisfied
    checks each requires_state entry by name against everything produced
    by an EARLIER video in the same project, so a gap (a video that
    requires_state's something no earlier video in this project actually
    produces) is visible before anything is ever rendered."""
    chain = []
    produced_so_far = {}  # (type, name) -> video_id that first produces it
    dashboard_cards_so_far = {}  # dashboard name -> accumulated question names

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

        # A dashboard's real "contains" set accumulates across every video
        # that pins to it (state_seed.py's dashboard seeding adds missing
        # cards rather than replacing them) -- shown here as the running
        # total, not just what THIS video's own script saved, so the view
        # doesn't undersell a dashboard a later video adds a second chart
        # to.
        for p in entry["produces"]:
            produced_so_far[(p["type"], p["name"])] = v["video_id"]
            if p["type"] == "dashboard":
                accumulated = dashboard_cards_so_far.setdefault(p["name"], [])
                for card_name in p.get("contains", []):
                    if card_name not in accumulated:
                        accumulated.append(card_name)
                p["contains"] = list(accumulated)

    return chain
