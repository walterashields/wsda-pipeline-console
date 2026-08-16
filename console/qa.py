"""
Surfaces wsda-video-engine's QA_CHECKLIST.md against a rendered video --
per the spec's point 6: "surface QA_CHECKLIST.md results per video after
render, both automated check results and a clear prompt for the
human-required checks... given this session's history of automated
checks missing real defects."

The checklist itself is prose (QA_CHECKLIST.md), not machine-readable, so
its 9 items are hand-encoded here as data -- checked directly against
that file's actual current text, not paraphrased from memory, since a
drifted copy would be worse than not having this at all. Items marked
Automated in the source doc get a real check implemented below, run
against the actual rendered files (audit.json, the mp4, live Metabase
API state) -- not a re-statement of "the render exited 0." Items marked
Human or Both keep a human-required component: this module surfaces the
question and the file's own documented history for why it matters, it
does not pretend to answer it.
"""

import subprocess

import requests
import yaml

from console.paths import METABASE_ADMIN_EMAIL, METABASE_ADMIN_PASSWORD, METABASE_BASE_URL

# {id, title, classification, human_prompt} -- transcribed from
# QA_CHECKLIST.md's 9 items (repo root, wsda-video-engine), in order.
# human_prompt is what a reviewer is actually asked to go check, shortened
# from that file's own "Check:" text; automated items are additionally
# handled by run_automated_checks below.
CHECKLIST_ITEMS = [
    {"id": 1, "title": "No dead, unnarrated setup/login time",
     "classification": "Human",
     "human_prompt": "Watch the first ~5 seconds. Does the video open already on the first "
                      "real instructional screen -- no visible login form, setup wizard, or blank loading state?"},
    {"id": 2, "title": "Every notable action carries narration, or silence is deliberate",
     "classification": "Both",
     "human_prompt": "For any event flagged silent below, is it genuinely administrative "
                      "(nothing to teach), not an oversight?"},
    {"id": 3, "title": "Every clicked element is visibly highlighted first",
     "classification": "Both",
     "human_prompt": "Pull a frame at each highlight event's timestamp and confirm the overlay "
                      "is drawn on the actual right element, not just that a highlight exists somewhere."},
    {"id": 4, "title": "Click fires only after highlight, hold, and narration have played",
     "classification": "Automated",
     "human_prompt": None},
    {"id": 5, "title": "Audio is present, audible, and spans the actual full recording",
     "classification": "Automated",
     "human_prompt": None},
    {"id": 6, "title": "Narration explains reasoning, not just mechanics",
     "classification": "Human",
     "human_prompt": "For each narrated step: delete the mechanical description (\"click X\") -- "
                      "is a reason sentence still left? If not, it fails."},
    {"id": 7, "title": "Every value/column named in narration is visible and highlighted",
     "classification": "Human",
     "human_prompt": "Pull a frame at each narrated moment naming a number, column, or field -- "
                      "is that exact thing on screen and highlighted for as long as it's discussed?"},
    {"id": 8, "title": "First-time concepts get more time and deeper narration than repeats",
     "classification": "Both",
     "human_prompt": "For steps marked concept-intro below: does the narration explain what the "
                      "resulting object IS and WHY it matters, not just that the action completed?"},
    {"id": 9, "title": "requires_state artifacts actually match reality after recording",
     "classification": "Automated",
     "human_prompt": None},
]

CONCEPT_INTRO_ACTIONS = {"save_question", "add_to_dashboard"}
SILENT_BY_CONVENTION = {"select_database", "visualize", "open_saved_item", "pause", "clear_highlight", "narrate"}
COMMIT_ACTIONS = {"click_new_question", "select_table", "add_filter", "click_option", "save_question", "add_to_dashboard"}


def _ffprobe_duration(path: str) -> float:
    r = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", path],
        capture_output=True, text=True,
    )
    return float(r.stdout.strip()) if r.returncode == 0 and r.stdout.strip() else 0.0


def _mean_volume_db(path: str, start_s: float, duration_s: float = 5.0) -> float | None:
    r = subprocess.run(
        ["ffmpeg", "-ss", str(max(0, start_s)), "-t", str(duration_s), "-i", path,
         "-af", "volumedetect", "-f", "null", "-"],
        capture_output=True, text=True,
    )
    for line in r.stderr.splitlines():
        if "mean_volume" in line:
            try:
                return float(line.split(":")[1].strip().rstrip(" dB"))
            except (IndexError, ValueError):
                return None
    return None


def _check_sequencing(audit_events: list) -> dict:
    by_id = {e["event_id"]: e for e in audit_events}
    violations = []
    for i, e in enumerate(audit_events):
        if e["event_type"] in COMMIT_ACTIONS:
            if i == 0:
                continue
            prev = audit_events[i - 1]
            if prev["event_type"] == "pause" and e["started_at_ms"] < prev["completed_at_ms"]:
                violations.append(e["event_id"])
    status = "pass" if not violations else "fail"
    detail = "Every commit event fires at/after its preceding pause completes." if not violations \
        else f"Fired early: {', '.join(violations)}"
    return {"id": 4, "status": status, "detail": detail}


def _check_audio(mp4_path: str, audit_events: list) -> dict:
    duration = _ffprobe_duration(mp4_path)
    if duration == 0:
        return {"id": 5, "status": "fail", "detail": f"could not probe {mp4_path}"}
    last_ms = max((e["completed_at_ms"] for e in audit_events), default=0)
    duration_ok = abs(duration - last_ms / 1000) < 5.0
    closing_vol = _mean_volume_db(mp4_path, max(0, duration - 6))
    audio_ok = closing_vol is not None and closing_vol > -50.0
    status = "pass" if duration_ok and audio_ok else "fail"
    detail = (f"mp4 {duration:.1f}s vs audit log {last_ms/1000:.1f}s "
              f"({'matches' if duration_ok else 'MISMATCH'}); "
              f"closing-segment mean volume {closing_vol if closing_vol is not None else 'unreadable'} dB "
              f"({'audible' if audio_ok else 'SILENT/too quiet'})")
    return {"id": 5, "status": status, "detail": detail}


def _check_silent_events(card_events: list) -> dict:
    # Commit-type events (click_new_question, select_table, add_filter,
    # click_option, save_question, add_to_dashboard) are ALWAYS silent by
    # the driver's own established two-event pattern -- their narration
    # lives on the highlight_target(s) event immediately before them, not
    # on the commit itself. Confirmed live (2026-08-15): the first version
    # of this check didn't know that and flagged every commit event in a
    # real render as "unexplained silence," a false positive on exactly
    # the architecture this whole project's driver is built around.
    unexplained = [
        e["id"] for e in card_events
        if e.get("type") not in {"pause"} and not (e.get("narration") or "").strip()
        and e.get("type") not in SILENT_BY_CONVENTION
        and e.get("type") not in COMMIT_ACTIONS
    ]
    status = "pass" if not unexplained else "warn"
    detail = "Every non-pause event either narrates or is silent-by-convention." if not unexplained \
        else f"Silent, not in the known administrative set -- review whether these are genuinely non-teaching: {', '.join(unexplained)}"
    return {"id": 2, "status": status, "detail": detail}


def _check_concept_intro_pacing(card_events: list, audit_events: list) -> dict:
    audit_by_id = {e["event_id"]: e for e in audit_events}
    flagged = []
    for e in card_events:
        if e.get("type") in CONCEPT_INTRO_ACTIONS and e.get("post_hold_ms", 0) < 2000:
            flagged.append(e["id"])
    status = "pass" if not flagged else "warn"
    detail = "save_question/add_to_dashboard events use concept-intro pacing (post_hold_ms >= 2000)." if not flagged \
        else f"These introduce a new concept but use default/short pacing -- confirm that's intentional (a later video repeating the concept doesn't need it): {', '.join(flagged)}"
    return {"id": 8, "status": status, "detail": detail}


def _check_requires_state(card: dict) -> dict:
    requires_state = card.get("requires_state")
    if not requires_state:
        return {"id": 9, "status": "not_applicable", "detail": "no requires_state block on this video"}

    try:
        token = requests.post(
            f"{METABASE_BASE_URL}/api/session",
            json={"username": METABASE_ADMIN_EMAIL, "password": METABASE_ADMIN_PASSWORD}, timeout=10,
        ).json()["id"]
    except Exception as exc:
        return {"id": 9, "status": "fail", "detail": f"could not reach Metabase to verify: {exc}"}
    headers = {"X-Metabase-Session": token}

    problems = []
    for spec in requires_state:
        if spec["type"] == "question":
            cards = requests.get(f"{METABASE_BASE_URL}/api/card", headers=headers, timeout=15).json()
            matches = [c for c in cards if c["name"] == spec["name"] and not c.get("archived")]
            if len(matches) != 1:
                problems.append(f"question {spec['name']!r}: {len(matches)} active copies (expected 1)")
        elif spec["type"] == "dashboard":
            dashboards = requests.get(f"{METABASE_BASE_URL}/api/dashboard", headers=headers, timeout=15).json()
            matches = [d for d in dashboards if d["name"] == spec["name"] and not d.get("archived")]
            if len(matches) != 1:
                problems.append(f"dashboard {spec['name']!r}: {len(matches)} active copies (expected 1)")
                continue
            full = requests.get(f"{METABASE_BASE_URL}/api/dashboard/{matches[0]['id']}", headers=headers, timeout=15).json()
            have = {dc.get("card", {}).get("name") for dc in full.get("dashcards", [])}
            missing = set(spec.get("contains", [])) - have
            if missing:
                problems.append(f"dashboard {spec['name']!r} is missing: {', '.join(missing)}")

    status = "pass" if not problems else "fail"
    detail = "Every requires_state artifact exists in the declared shape." if not problems else "; ".join(problems)
    return {"id": 9, "status": status, "detail": detail}


def run_automated_checks(script_path, audit_json_path, mp4_path) -> list:
    card = yaml.safe_load(script_path.read_text())
    audit = __import__("json").loads(audit_json_path.read_text()) if audit_json_path and audit_json_path.exists() else {"events": []}
    audit_events = audit.get("events", [])
    card_events = card.get("events", [])

    checks = [_check_silent_events(card_events)]
    if audit_events:
        checks.append(_check_sequencing(audit_events))
        if mp4_path and mp4_path.exists():
            checks.append(_check_audio(str(mp4_path), audit_events))
        checks.append(_check_concept_intro_pacing(card_events, audit_events))
    checks.append(_check_requires_state(card))
    return checks
