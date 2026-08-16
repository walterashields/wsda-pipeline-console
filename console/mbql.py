"""
Minimal, pure MBQL (Metabase Query Language) query-building helpers --
resolve a database/table/field by human-readable name, build a `between`
filter, a `sum` aggregation, a breakout. Deliberately a small, self-
contained duplicate of the same logic in wsda-video-engine's
automation/state_seed.py, not an import of it: this console's own
architecture (console/paths.py) commits to reading/triggering that
sibling repo via subprocess and its HTTP API, never importing its code,
so the two stay independently deployable. The duplicated surface here is
intentionally tiny (four pure functions, no side effects) precisely so
that boundary doesn't cost much -- if state_seed.py's filter/aggregation
support grows, this module needs the same growth, by design, not by
accident.
"""

import requests


def normalize_field_name(name: str) -> str:
    return name.lower().replace("_", " ")


def resolve_table_and_fields(base_url, headers, database_name, table_name):
    dbs = requests.get(f"{base_url}/api/database", headers=headers, timeout=15).json()
    db = next((d for d in dbs["data"] if d["name"] == database_name), None)
    if db is None:
        raise ValueError(f"database {database_name!r} not found")

    meta = requests.get(f"{base_url}/api/database/{db['id']}/metadata", headers=headers, timeout=15).json()
    table = next((t for t in meta["tables"] if t["name"].lower() == table_name.lower()), None)
    if table is None:
        raise ValueError(f"table {table_name!r} not found in database {database_name!r}")

    fields = {normalize_field_name(f["name"]): f["id"] for f in table["fields"]}
    return db["id"], table["id"], fields


def build_filter_mbql(spec, fields):
    operator = spec["operator"]
    field_id = fields[normalize_field_name(spec["field"])]
    if operator == "between":
        return ["between", ["field", field_id, None], spec["min"], spec["max"]]
    raise ValueError(f"unsupported filter operator {operator!r}")


def build_aggregation_mbql(spec, fields):
    # Confirmed live (2026-08-16): `count` needs no field at all -- a bare
    # ["count"] MBQL clause -- but this function used to look up
    # spec["field"] unconditionally before checking the function type,
    # raising a plain KeyError on the very first real `count` spec a
    # generated script produced. Checked field-less functions first, not
    # patched around the crash, since the same shape of bug (assuming a
    # key exists before checking whether this branch even needs it) could
    # recur for any future field-less function.
    function = spec["function"]
    if function == "count":
        return ["count"]
    field_id = fields[normalize_field_name(spec["field"])]
    if function == "sum":
        return ["sum", ["field", field_id, None]]
    raise ValueError(f"unsupported aggregation function {function!r}")


def build_breakout_mbql(spec, fields):
    field_id = fields[normalize_field_name(spec["field"])]
    options = {"temporal-unit": spec["granularity"]} if "granularity" in spec else None
    return ["field", field_id, options]


def build_query(spec, db_id, fields) -> dict:
    query = {"source-table": spec["_table_id"]}
    if "filter" in spec:
        query["filter"] = build_filter_mbql(spec["filter"], fields)
    if "aggregation" in spec:
        query["aggregation"] = [build_aggregation_mbql(spec["aggregation"], fields)]
    if "breakout" in spec:
        query["breakout"] = [build_breakout_mbql(spec["breakout"], fields)]
    return {"database": db_id, "type": "query", "query": query}
