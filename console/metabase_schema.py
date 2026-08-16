"""
Read-only live Metabase schema lookup -- queried fresh at generation time,
not hardcoded, same discipline as automation/state_seed.py's own table/
field resolution: this project's own history (MULTI_VIDEO_PROGRESSION_
FINDINGS.md) is full of real bugs caused by trusting a remembered/assumed
shape of the data over what the live instance actually has.
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
            field_names = ", ".join(
                f"{f['name']} ({f['base_type'].removeprefix('type/')})"
                for f in table["fields"]
            )
            lines.append(f"  Table {table['name']!r}: {field_names}")
    return "\n".join(lines)
