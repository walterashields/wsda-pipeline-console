"""
Read-only live Metabase schema lookup -- queried fresh at generation time,
not hardcoded, same discipline as automation/state_seed.py's own table/
field resolution: this project's own history (MULTI_VIDEO_PROGRESSION_
FINDINGS.md) is full of real bugs caused by trusting a remembered/assumed
shape of the data over what the live instance actually has.

Real per-field min/max/avg (numeric) and earliest/latest (datetime)
ranges are included alongside each field name (added 2026-08-16, CRITICAL
fix pass), not just the field's name and type. Root cause of a real,
live defect this addresses directly: a generated script filtered
Orders.Total to $500-$5000 -- a plausible-sounding "high value" range
with no relationship to the real data, which actually tops out at
$159.35. Without a real number to ground against, there's nothing
stopping a plausible-sounding guess; this makes the actual range part of
what the model is generating against, not a fact it has to invent. This
narrows the failure mode but doesn't close it alone -- console/
validator.py is the actual hard gate; this is the mitigation that should
make the gate rarely need to fire in the first place.
"""

import requests

from console.paths import METABASE_ADMIN_EMAIL, METABASE_ADMIN_PASSWORD, METABASE_BASE_URL


def fetch_schema_summary() -> str:
    """Plain-text table/field listing for every database Metabase has,
    formatted to drop straight into a generation prompt. Raises with a
    clear message if Metabase isn't reachable, rather than generating
    against a guessed/stale schema."""
    try:
        token = requests.post(
            f"{METABASE_BASE_URL}/api/session",
            json={"username": METABASE_ADMIN_EMAIL, "password": METABASE_ADMIN_PASSWORD},
            timeout=10,
        ).json()["id"]
    except Exception as exc:
        raise RuntimeError(
            f"Could not reach Metabase at {METABASE_BASE_URL} to read its "
            f"real schema ({exc}). Generation needs this live, not a "
            f"remembered/guessed schema -- start Metabase and retry."
        ) from exc

    headers = {"X-Metabase-Session": token}
    dbs = requests.get(f"{METABASE_BASE_URL}/api/database", headers=headers, timeout=15).json()

    lines = []
    for db in dbs["data"]:
        if db.get("is_sample") is False and db["name"] == "Internal":
            continue
        lines.append(f"Database: {db['name']!r}")
        meta = requests.get(
            f"{METABASE_BASE_URL}/api/database/{db['id']}/metadata",
            headers=headers, timeout=15,
        ).json()
        for table in meta.get("tables", []):
            lines.append(f"  Table {table['name']!r}:")
            for f in table["fields"]:
                lines.append(f"    {f['name']} ({f['base_type'].removeprefix('type/')}){_range_hint(f)}")
    return "\n".join(lines)


def _range_hint(field: dict) -> str:
    """One real-data hint per field, appended to its schema line -- the
    exact number a filter/aggregation choice should be checked against,
    not a fact left for the model to guess or infer from a plausible-
    sounding assumption. See module docstring for the live bug this
    exists to prevent."""
    fp = (field.get("fingerprint") or {})
    numeric = fp.get("type", {}).get("type/Number")
    if numeric:
        return f" -- real range: {numeric['min']:.2f} to {numeric['max']:.2f}, avg {numeric['avg']:.2f}"
    datetime_fp = fp.get("type", {}).get("type/DateTime")
    if datetime_fp:
        earliest = datetime_fp.get("earliest", "?")[:10]
        latest = datetime_fp.get("latest", "?")[:10]
        return f" -- real range: {earliest} to {latest}"
    return ""
