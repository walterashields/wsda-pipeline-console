"""
Pre-render data-validation gate (added 2026-08-16, CRITICAL fix pass).

The problem this exists for, found live in Walter's own first real use of
this console: a generated script filtered Orders.Total to a $500-$5000
range, framed in narration as "these are the orders that need review."
Metabase's real Orders.Total data tops out at $159.35 -- that filter
returns zero rows, always. The recording still played out the narration
as if results were showing, over an empty table. That's not a delivery
gap (LESSON_CONTENT_STANDARD.md rule 5 already covers narration
referencing something not visible) -- it's the system stating something
false, in Walter's own teaching voice, about data it never actually
checked. Confirmed by reproducing it directly: POSTing that exact filter
to Metabase's own /api/dataset returns 0 rows, immediately, no
ambiguity.

This module runs BEFORE any render is offered, not after one completes
(that distinction is the whole point -- see QA_CHECKLIST.md item 10).
For every `validations` entry a generated script declares, it builds the
same MBQL query the video's own workflow implies (console/mbql.py) and
runs it live, for real, against whatever Metabase actually has right
now -- the same discipline every other real-state check on this project
has used (QA_CHECKLIST.md item 9, the silent-duplicate-dashboard bug,
the field-normalization bug). A script with no validations entries at
all (nothing declared, or a video whose commit actions don't produce
query results at all, e.g. a save/dashboard-only step) is not treated as
having passed anything -- see NO_VALIDATIONS_STATUS below.
"""

import requests
import yaml

from console import mbql
from console.paths import METABASE_ADMIN_EMAIL, METABASE_ADMIN_PASSWORD, METABASE_BASE_URL

# A script with a data-producing step (a filter/aggregation-driven
# highlight_targets + add_filter or click_option pair) but NO
# `validations` entry describing it is not the same as a script that
# validated cleanly -- it's a script this gate can't vouch for at all.
# Surfaced as its own status, not silently folded into "passed", so a
# human reviewer sees the difference between "checked, real data" and
# "nothing to check here."
NO_VALIDATIONS_STATUS = "unchecked"


def _login_headers():
    try:
        token = requests.post(
            f"{METABASE_BASE_URL}/api/session",
            json={"username": METABASE_ADMIN_EMAIL, "password": METABASE_ADMIN_PASSWORD},
            timeout=10,
        ).json()["id"]
    except Exception as exc:
        raise RuntimeError(f"could not reach Metabase at {METABASE_BASE_URL} to validate: {exc}") from exc
    return {"X-Metabase-Session": token}


def _run_one(headers, v: dict) -> dict:
    query_spec = v["query"]
    expect = v.get("expect", {})
    min_rows = expect.get("min_rows", 1)
    allow_zero = expect.get("allow_zero", False)

    try:
        db_id, table_id, fields = mbql.resolve_table_and_fields(
            METABASE_BASE_URL, headers, query_spec["database"], query_spec["table"]
        )
        query_spec = {**query_spec, "_table_id": table_id}
        payload = mbql.build_query(query_spec, db_id, fields)
        resp = requests.post(f"{METABASE_BASE_URL}/api/dataset", headers=headers, json=payload, timeout=30)
        resp.raise_for_status()
        data = resp.json()
    except Exception as exc:
        return {"event_id": v.get("event_id"), "status": "fail", "row_count": None,
                "detail": f"query failed: {exc}", "query": query_spec}

    rows = data.get("data", {}).get("rows", [])
    row_count = len(rows)

    if row_count < min_rows:
        detail = (f"returned {row_count} row(s), need at least {min_rows} -- "
                  f"the narration for this step claims a real, meaningful result, "
                  f"but this query returns {'nothing' if row_count == 0 else 'too little'} "
                  f"against live data right now")
        return {"event_id": v.get("event_id"), "status": "fail", "row_count": row_count,
                "detail": detail, "query": query_spec}

    # An aggregation with no breakout always returns exactly 1 row
    # (min_rows: 1 passes trivially) even when the aggregate VALUE
    # itself is zero or null -- "1 row, value 0" is just as false a
    # narration claim as "0 rows" when the narration implies a
    # meaningful count/sum. Checked separately, only when the query is a
    # pure aggregation (no breakout, no filter beyond what's already
    # applied), since a filtered row-listing's "meaningfulness" is fully
    # covered by min_rows already.
    if "aggregation" in query_spec and "breakout" not in query_spec and not allow_zero:
        agg_value = rows[0][-1] if rows and rows[0] else None
        if agg_value in (0, 0.0, None):
            return {"event_id": v.get("event_id"), "status": "fail", "row_count": row_count,
                    "detail": f"aggregation result is {agg_value!r} -- a zero/empty aggregate is as "
                              f"misleading as an empty filter if narration implies a real count/sum",
                    "query": query_spec}

    return {"event_id": v.get("event_id"), "status": "pass", "row_count": row_count,
            "detail": f"returned {row_count} row(s), matches a real, non-trivial result", "query": query_spec}


def _requires_state_checks(headers, requires_state: list) -> list:
    """requires_state's own filter/aggregation specs are just as real a
    claim as an in-video one: automation/state_seed.py builds and creates
    that exact query if a question with that name doesn't already exist.
    Found live (2026-08-16): a regenerated video_1_2 declared
    requires_state for "Orders Needing Review" with the OLD, already-
    disproven filter range (500-5000 in the original bug, drifted to a
    still-wrong 50-1000 in one regeneration) even after video_1_1's own
    in-video filter had been corrected -- the two aren't automatically
    kept in sync, and requires_state was outside what the original gate
    checked at all. If seeded fresh (video_1_1 never actually run first),
    that would silently recreate the exact same empty-result defect one
    level removed, undetected by validations checks on video_1_2's own
    steps alone.

    Only checked when the named artifact doesn't already exist live --
    if it does, state_seed.py reuses the real thing regardless of what
    this script's requires_state says about it, so the spec here is only
    load-bearing (and only worth checking) when nothing already exists
    under that name."""
    checks = []
    for spec in requires_state:
        if spec.get("type") != "question" or not ("filter" in spec or "aggregation" in spec):
            continue
        try:
            cards = requests.get(f"{METABASE_BASE_URL}/api/card", headers=headers, timeout=15).json()
            already_exists = any(c["name"] == spec["name"] and not c.get("archived") for c in cards)
        except Exception as exc:
            checks.append({"event_id": f"requires_state:{spec['name']}", "status": "fail",
                            "row_count": None, "detail": f"could not check: {exc}", "query": spec})
            continue
        if already_exists:
            continue
        query_spec = {"database": spec["database"], "table": spec["table"]}
        if "filter" in spec:
            query_spec["filter"] = spec["filter"]
        if "aggregation" in spec:
            query_spec["aggregation"] = spec["aggregation"]
        if "breakout" in spec:
            query_spec["breakout"] = spec["breakout"]
        result = _run_one(headers, {"event_id": f"requires_state:{spec['name']}", "query": query_spec})
        checks.append(result)
    return checks


def validate_script(script_path) -> dict:
    """Returns {"passed": bool, "status": "pass"|"fail"|"unchecked", "checks": [...]}.
    `passed` is only True when every declared validation actually ran and
    passed -- a script with zero `validations` entries AND no filter/
    aggregation-bearing requires_state entries is `unchecked`, not
    `passed`, so it's never mistaken for having been verified."""
    card = yaml.safe_load(script_path.read_text()) or {}
    validations = card.get("validations") or []
    requires_state = card.get("requires_state") or []
    requires_state_with_data = [
        s for s in requires_state if s.get("type") == "question" and ("filter" in s or "aggregation" in s)
    ]

    if not validations and not requires_state_with_data:
        return {"passed": False, "status": NO_VALIDATIONS_STATUS, "checks": []}

    headers = _login_headers()
    checks = [_run_one(headers, v) for v in validations]
    checks += _requires_state_checks(headers, requires_state)

    all_pass = all(c["status"] == "pass" for c in checks)
    return {"passed": all_pass, "status": "pass" if all_pass else "fail", "checks": checks}
