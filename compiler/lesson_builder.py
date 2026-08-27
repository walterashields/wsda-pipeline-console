#!/usr/bin/env python3
"""
compiler/lesson_builder.py

Lesson-first script generation, validation, action derivation, and graph
construction. This is the Path A orchestrator: it generates a narration script
before any screen action is taken, validates it against the SQL Essentials
standard, derives deterministic UI actions, executes them through the discovery
harness, and builds an ExecutionGraph from the resulting recorded clips.
"""

from __future__ import annotations

import json
import os
import re
import sqlite3
import subprocess
import sys
import uuid
from pathlib import Path
from typing import Any, Dict, List, Literal, Optional, Tuple

import anthropic

from .discovery import APP_NAME, DiscoveryRecipes, EndStateDiscovery
from .graph_store import GraphStore
from .lesson_standard import LessonStandard
from .narrator import (
    ScriptBeat,
    _contains_action_word,
    _contains_filler,
    _contains_result_phrase,
    _contains_state_setup_phrase,
    _extract_numbers,
    _format_action_sql,
)
from .schemas import ActionEdge, DiscoveryResult, ExecutionGraph, NarrationBeat, ScreenState
from .sql_formatter import format_sql_query

MODEL = os.environ.get("NARRATOR_MODEL", "claude-sonnet-5")

_APP_FRIENDLY_NAMES = {
    "db_browser_sqlite": "DB Browser for SQLite",
    "metabase": "Metabase",
    "excel": "Excel",
    "power_bi": "Power BI",
    "mysql_workbench": "MySQL Workbench",
}


def _friendly_app_name(application: str) -> str:
    return _APP_FRIENDLY_NAMES.get(application, application.replace("_", " ").title())


class LessonBuilder:
    """
    Generates a narration script from a VideoManifest, derives the concrete
    UI action sequence, executes it through the discovery harness, and builds
    an ExecutionGraph from the recorded demo-beat clips.
    """

    def __init__(self, content_standard_path: str = "LESSON_CONTENT_STANDARD.md"):
        self.client = anthropic.Anthropic()
        self.lesson_standard = LessonStandard(content_standard_path)

    # ------------------------------------------------------------------
    # Standard ingestion
    # ------------------------------------------------------------------

    def ingest_standard(self) -> dict:
        """
        Extract the lesson content standard into a structured dict for prompts
        and quality gates.
        """
        text = self.lesson_standard.raw_text
        return {
            "structure_pattern": self._extract_section(text, "The five rules", "Three more rules"),
            "voice": self._extract_section(text, "Sentence-level style", "Grounded in SQL Essential Training"),
            "pacing": self._extract_section(text, "Corollary: no click is fast", "The five rules"),
            "sql_style": self._extract_section(text, "SQL Query Formatting Standard", "## General Rules"),
            "validation_habit": self._extract_section(text, "### 8. Every explanation closes", "## Grounded"),
        }

    @staticmethod
    def _extract_section(text: str, start_marker: str, end_marker: str) -> str:
        """Return the text between two markdown headings, trimmed."""
        start = text.find(start_marker)
        if start == -1:
            return ""
        end = text.find(end_marker, start + len(start_marker))
        if end == -1:
            end = len(text)
        return re.sub(r"\n{2,}", "\n", text[start:end]).strip()

    # ------------------------------------------------------------------
    # Deterministic script generation helpers
    # ------------------------------------------------------------------

    _FORBIDDEN_VOICE_PATTERNS = [
        r"\byou'll\b",
        r"\byou need to\b",
        r"\byou need\b",
        r"\byour\b",
        r"\bimportant to note\b",
        r"\bbefore you\b",
        r"\bif you skip\b",
        r"\bif you\b",
        r"\bit is important\b",
        r"\bit's important\b",
        r"\bin order to\b",
        r"\bas you can see\b",
        r"\bbasically\b",
        r"\bessentially\b",
        r"\bvery\b",
        r"\breally\b",
        r"\bjust\b",
        r"\bsimply\b",
        r"\bunderstand\b",
        r"\bunderstanding\b",
        r"\blearn\b",
        r"\blearning\b",
        r"\bgrasp\b",
        r"\bcomprehend\b",
        r"\bconcept\b",
        r"\babstract\b",
        r"\bthe fact that\b",
        r"\bthis is because\b",
        r"\bwhich means\b",
        r"\btherefore\b",
    ]

    _SECOND_PERSON_PATTERN = re.compile(r"\byou\b|\byour\b|\byou'll\b|\byou're\b", re.IGNORECASE)

    @staticmethod
    def _word_count(text: str) -> int:
        return len(text.split())

    @staticmethod
    def _truncate(text: str, max_words: int) -> str:
        words = text.split()
        if len(words) <= max_words:
            return text
        return " ".join(words[:max_words]).rstrip(",.;:")

    @staticmethod
    def _db_facts(db_path: Optional[str], table_name: str) -> Dict[str, Any]:
        """Return row count and column list for a table."""
        facts = {"row_count": 0, "columns": []}
        if not db_path or not Path(db_path).exists():
            return facts
        try:
            with sqlite3.connect(db_path) as conn:
                cur = conn.cursor()
                cur.execute(f"SELECT COUNT(*) FROM {table_name}")
                facts["row_count"] = cur.fetchone()[0]
                cur.execute(f"PRAGMA table_info({table_name})")
                facts["columns"] = [row[1] for row in cur.fetchall()]
        except Exception as exc:
            print(f"Warning: could not read DB facts for {table_name}: {exc}", file=sys.stderr)
        return facts

    @staticmethod
    def _top_value(db_path: Optional[str], table_name: str, column: str, direction: str) -> str:
        """Return the top value after sorting a column."""
        if not db_path or not Path(db_path).exists():
            return ""
        try:
            with sqlite3.connect(db_path) as conn:
                cur = conn.cursor()
                order = "ASC" if direction == "asc" else "DESC"
                cur.execute(f"SELECT {column} FROM {table_name} ORDER BY {column} {order} LIMIT 1")
                row = cur.fetchone()
                return str(row[0]) if row and row[0] is not None else ""
        except Exception as exc:
            print(f"Warning: could not read top value: {exc}", file=sys.stderr)
            return ""

    @staticmethod
    def _filtered_count(db_path: Optional[str], table_name: str, column: str, value: str) -> int:
        """Return the number of rows matching a filter value."""
        if not db_path or not Path(db_path).exists():
            return 0
        try:
            with sqlite3.connect(db_path) as conn:
                cur = conn.cursor()
                cur.execute(f"SELECT COUNT(*) FROM {table_name} WHERE {column} = ?", (value,))
                return cur.fetchone()[0]
        except Exception as exc:
            print(f"Warning: could not read filtered count: {exc}", file=sys.stderr)
            return 0

    @staticmethod
    def _first_value(db_path: Optional[str], table: str, column: str, context: str = "") -> str:
        """Return a representative non-null value from a column."""
        if not db_path or not Path(db_path).exists():
            return ""
        try:
            with sqlite3.connect(db_path) as conn:
                cur = conn.cursor()
                cur.execute(
                    f"SELECT DISTINCT {column} FROM {table} WHERE {column} IS NOT NULL LIMIT 1"
                )
                row = cur.fetchone()
                return str(row[0]) if row and row[0] is not None else ""
        except Exception as exc:
            print(f"Warning: could not read first value ({context}, db={db_path}, table={table}, col={column}): {exc}", file=sys.stderr)
            return ""

    @staticmethod
    def _table_exists(db_path: Optional[str], table: str) -> bool:
        if not db_path or not Path(db_path).exists():
            return False
        try:
            with sqlite3.connect(db_path) as conn:
                cur = conn.cursor()
                cur.execute(
                    "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)
                )
                return cur.fetchone() is not None
        except Exception:
            return False

    @staticmethod
    def _column_exists(db_path: Optional[str], table: str, column: str) -> bool:
        if not db_path or not Path(db_path).exists():
            return False
        try:
            with sqlite3.connect(db_path) as conn:
                cur = conn.cursor()
                cur.execute(f"PRAGMA table_info({table})")
                cols = [row[1] for row in cur.fetchall()]
                return column.lower() in (c.lower() for c in cols)
        except Exception:
            return False

    @staticmethod
    def _table_for_column(db_path: Optional[str], column: str) -> Optional[str]:
        """Return the name of a table that contains the given column."""
        if not db_path or not Path(db_path).exists():
            return None
        try:
            with sqlite3.connect(db_path) as conn:
                cur = conn.cursor()
                cur.execute("SELECT name FROM sqlite_master WHERE type='table'")
                for (table,) in cur.fetchall():
                    try:
                        cur.execute(f"PRAGMA table_info({table})")
                        cols = [row[1] for row in cur.fetchall()]
                        if column.lower() in (c.lower() for c in cols):
                            return table
                    except Exception:
                        continue
        except Exception as exc:
            print(f"Warning: could not find table for column {column}: {exc}", file=sys.stderr)
        return None

    @staticmethod
    def _pick_substitute_column(target_column: Optional[str], table: str, columns: List[str]) -> Optional[str]:
        """Choose a real column to substitute for an ungrounded target_column.

        Prefers categorical/text-sounding columns, then falls back to the first
        column. Returns the canonical-cased column name from the schema.
        """
        if not columns:
            return None
        lowered_cols = {c.lower(): c for c in columns}
        if target_column and target_column.lower() in lowered_cols:
            return lowered_cols[target_column.lower()]
        for pattern in ("status", "region", "country", "name", "type", "category", "state", "city", "role"):
            if pattern in lowered_cols:
                return lowered_cols[pattern]
        return columns[0]

    def _parse_objective(self, objective: str, db_path: Optional[str] = None, default_table: str = "Orders") -> Optional[Dict[str, Any]]:
        """Map a discovery objective to a recipe type and parameters."""
        lowered = objective.lower()

        # Browse table: open/browse/show/display the X table
        browse_match = re.search(
            r"(?:open|browse|show|display)\s+(?:the\s+)?(\w+)\s+(?:table)", lowered,
        )
        if browse_match:
            return {"type": "browse_table", "table": browse_match.group(1).capitalize()}

        # Sort: sort the X table by Y [direction] or sort by the Y column/header.
        sort_match = re.search(
            r"sort\s+(?:(?:the\s+)?(\w+)\s+(?:table\s+)?)?by\s+(?:the\s+)?(\w+)(?:\s+(?:column|header))?",
            lowered,
        )
        if sort_match:
            direction = "desc" if any(w in lowered for w in ("descending", "desc", "largest", "biggest", "highest")) else "asc"
            return {
                "type": "sort_column",
                "table": (sort_match.group(1) or default_table).capitalize(),
                "column": sort_match.group(2).capitalize(),
                "direction": direction,
            }

        # Sort via column-header click: "Click the X column header in the Y table ..."
        header_sort_match = re.search(
            r"(?:click|clicking)\s+(?:the\s+)?(\w+)\s+(?:column\s+)?header\s+(?:in\s+(?:the\s+)?)?(\w+)",
            lowered,
        )
        if header_sort_match:
            direction = "desc" if any(w in lowered for w in ("descending", "desc", "largest", "biggest", "highest", "second time", "again")) else "asc"
            return {
                "type": "sort_column",
                "table": header_sort_match.group(2).capitalize(),
                "column": header_sort_match.group(1).capitalize(),
                "direction": direction,
            }

        # Filter with explicit value: filter X by typing Y into the Z column filter box
        filter_value_match = re.search(
            r"filter\s+(?:the\s+)?(\w+)\s+(?:table\s+)?(?:by\s+(?:typing|entering)\s+)['\"]?(.+?)['\"]?\s+(?:into|in)\s+(?:the\s+)?(\w+)\s+(?:column\s+)?filter",
            lowered,
        )
        if filter_value_match:
            value = filter_value_match.group(2).strip().strip("'\"")
            return {
                "type": "filter_column",
                "table": filter_value_match.group(1).capitalize(),
                "column": filter_value_match.group(3).capitalize(),
                "value": value,
            }

        # Filter via type-into-filter-box: "Type X into the Y filter box under the Z table"
        filter_box_match = re.search(
            r"(?:type|enter)\s+['\"]?(.+?)['\"]?\s+(?:into|in)\s+(?:the\s+)?(\w+)\s+(?:column\s+)?filter\s+(?:box\s+)?(?:under|in)\s+(?:the\s+)?(\w+)",
            lowered,
        )
        if filter_box_match:
            value = filter_box_match.group(1).strip().strip("'\"")
            return {
                "type": "filter_column",
                "table": filter_box_match.group(3).capitalize(),
                "column": filter_box_match.group(2).capitalize(),
                "value": value,
            }

        # Filter without explicit value: filter [the X table] by/using/with the Y column filter box
        filter_col_match = re.search(
            r"filter\s+(?:(?:the\s+)?(\w+)\s+(?:table\s+)?)?(?:by|using|with)\s+(?:the\s+)?(\w+)(?:\s+(?:column))?(?:\s+(?:filter\s+box))?(?:\s+(?:for\s+an\s+exact\s+text\s+match))?",
            lowered,
        )
        if filter_col_match:
            table = (filter_col_match.group(1) or default_table).capitalize()
            column = filter_col_match.group(2).capitalize()
            if not self._table_exists(db_path, table):
                table = default_table
            value = self._first_value(db_path, table, column, context=f"filter {objective[:60]}") or ""
            return {
                "type": "filter_column",
                "table": table,
                "column": column,
                "value": value,
            }

        # Execute query: try to extract the literal SELECT statement first.
        if any(phrase in lowered for phrase in ("execute sql", "select ", "run a query", "query in the execute sql", "join query")):
            table_match = re.search(r"(?:on|from)\s+(?:the\s+)?(\w+)\s+(?:table)?", lowered)
            table = table_match.group(1).capitalize() if table_match else "Orders"

            # Capture a SELECT ... clause up to a stopping word, but keep going
            # through "FROM table" so simple star queries stay complete.
            query_match = re.search(
                r"(SELECT\s+.+?(?:\s+FROM\s+\w+)?)(?:\s+(?:query|in the execute sql|in the|on the|and view|and see)|$)",
                objective,
                re.IGNORECASE,
            )
            if query_match:
                query = query_match.group(1).strip()
                query = re.sub(r"[;.]+$", "", query)
                # Reject placeholder captures like "SELECT query with a WHERE clause".
                looks_valid = (
                    re.search(r"\bFROM\b", query, re.IGNORECASE)
                    or re.search(r"\b(COUNT|SUM|AVG|MIN|MAX)\s*\(", query, re.IGNORECASE)
                )
                if looks_valid:
                    # Aggregates like COUNT(*) still need a source table.
                    if re.search(r"\b(COUNT|SUM|AVG|MIN|MAX)\s*\(", query, re.IGNORECASE) and not re.search(r"\bFROM\b", query, re.IGNORECASE):
                        query = f"{query}\nFROM {table}"
                    return {"type": "execute_query", "query": query}

            if "count" in lowered:
                return {"type": "execute_query", "query": f"SELECT\n    COUNT(*)\nFROM {table}"}

            if "where" in lowered:
                col_match = re.search(
                    r"where\s+clause\s+(?:on\s+(?:the\s+)?)?(?:\w+\s+table\s+)?(\w+)(?:\s+column)?",
                    lowered,
                    re.IGNORECASE,
                )
                column = col_match.group(1).capitalize() if col_match else "status"
                if not self._table_exists(db_path, table):
                    table = default_table
                # Make sure the chosen table actually has the target column.
                if db_path and not self._column_exists(db_path, table, column):
                    table = self._table_for_column(db_path, column) or table
                value_match = re.search(r"equal\s+to\s+['\"]?([\w-]+)", lowered, re.IGNORECASE)
                value = (value_match.group(1).strip() if value_match else self._first_value(db_path, table, column, context=f"where {objective[:60]}")) or ""
                value = value.replace("'", "''")
                return {
                    "type": "execute_query",
                    "query": f"SELECT\n    *\nFROM {table}\nWHERE {column} = '{value}'",
                }

            if "join" in lowered or ("top" in lowered and "spend" in lowered):
                join_table = "Customers" if table.lower() == "orders" else table
                return {
                    "type": "execute_query",
                    "query": (
                        f"SELECT\n"
                        f"    c.name,\n"
                        f"    SUM(o.amount) AS total_spend\n"
                        f"FROM {table.lower()} o\n"
                        f"JOIN {join_table.lower()} c ON o.customer_id = c.customer_id\n"
                        f"GROUP BY c.name\n"
                        f"ORDER BY total_spend DESC"
                    ),
                }

            return {"type": "execute_query", "query": f"SELECT\n    *\nFROM {table}"}

        return None

    @staticmethod
    def _verbalize_sql(query: str) -> str:
        """Convert a SQL query fragment to a single-line spoken form for narration."""
        spoken = query.strip()
        # Collapse whitespace and newlines to single spaces.
        spoken = re.sub(r"\s+", " ", spoken)
        spoken = re.sub(r"\bSELECT\b", "SELECT", spoken, flags=re.IGNORECASE)
        spoken = re.sub(r"\bFROM\b", "FROM", spoken, flags=re.IGNORECASE)
        spoken = re.sub(r"\bWHERE\b", "WHERE", spoken, flags=re.IGNORECASE)
        spoken = re.sub(r"\bORDER BY\b", "ORDER BY", spoken, flags=re.IGNORECASE)
        spoken = re.sub(r"\bGROUP BY\b", "GROUP BY", spoken, flags=re.IGNORECASE)
        spoken = re.sub(r"\bCOUNT\b", "COUNT", spoken, flags=re.IGNORECASE)
        spoken = re.sub(r"\bSUM\b", "SUM", spoken, flags=re.IGNORECASE)
        spoken = re.sub(r"\bAS\b", "AS", spoken, flags=re.IGNORECASE)
        spoken = re.sub(r"\bJOIN\b", "JOIN", spoken, flags=re.IGNORECASE)
        spoken = re.sub(r"\bINNER\b", "INNER", spoken, flags=re.IGNORECASE)
        spoken = re.sub(r"\bLEFT\b", "LEFT", spoken, flags=re.IGNORECASE)
        spoken = re.sub(r"\bRIGHT\b", "RIGHT", spoken, flags=re.IGNORECASE)
        spoken = re.sub(r"\bON\b", "ON", spoken, flags=re.IGNORECASE)
        spoken = re.sub(r"\*", "star", spoken)
        # Keep COUNT star natural (remove parentheses around the star substitution).
        spoken = re.sub(r"\(\s*star\s*\)", " star", spoken)
        return spoken.strip()

    @staticmethod
    def _wait_action() -> Dict[str, Any]:
        return {"type": "wait", "duration": 1.5}

    @staticmethod
    def _click_action(detail: str) -> Dict[str, Any]:
        return {"type": "click", "detail": detail}

    @staticmethod
    def _type_action(text: str, target: Optional[str] = None) -> Dict[str, Any]:
        action: Dict[str, Any] = {"type": "type", "detail": text}
        if target:
            action["target"] = target
        return action

    @staticmethod
    def _key_action(key: str) -> Dict[str, Any]:
        return {"type": "key", "detail": key}

    @staticmethod
    def _verify_action(detail: str) -> Dict[str, Any]:
        return {"type": "verify", "detail": detail}

    @staticmethod
    def _sequence_action(actions: List[Dict[str, Any]], logical_unit: bool = False) -> Dict[str, Any]:
        action: Dict[str, Any] = {"type": "sequence", "actions": actions}
        if logical_unit:
            # A logical_unit sequence represents one conceptual demo interaction
            # (e.g. "open the Orders table" or "type a value and press Return").
            # It is kept as a single demo beat in the C1 arc.
            action["logical_unit"] = True
        return action

    # ------------------------------------------------------------------
    # C1: full teaching-arc text helpers (grounded in EnvironmentMap)
    # ------------------------------------------------------------------

    def _generate_hook(self, video: Any, table: str, column: Optional[str]) -> str:
        """Return an opening beat (<=45 words) stating the lesson + payoff."""
        objective = video.learning_objective or getattr(video, "discovery_objective", "")
        lowered = objective.lower()
        column_phrase = f" by {column}" if column else ""
        if "sort" in lowered and "filter" in lowered:
            return (
                f"In this lesson, we open the {table} table, sort{column_phrase}, and filter to explore the data interactively."
            )
        if "sort" in lowered:
            return (
                f"In this lesson, we sort the {table} table{column_phrase} to find the largest and smallest values instantly."
            )
        if "filter" in lowered:
            return (
                f"In this lesson, we filter the {table} table to focus on one group of rows without deleting data."
            )
        if "query" in lowered or "select" in lowered:
            return (
                f"In this lesson, we run a SELECT query in the Execute SQL tab to ask precise questions of the {table} table."
            )
        return (
            f"In this lesson, we open the {table} table in the Browse Data tab and inspect its rows and columns."
        )

    def _generate_concept(
        self,
        video: Any,
        table: str,
        columns: List[str],
        row_count: int,
        rows_word: str,
    ) -> str:
        """Return a concept beat (<=40 words) describing what is on screen."""
        objective = video.learning_objective or getattr(video, "discovery_objective", "")
        lowered = objective.lower()
        cols_text = ", ".join(columns) if columns else "the columns"
        if "sort" in lowered:
            return (
                f"The {table} table shows {row_count} {rows_word} with columns {cols_text}. "
                f"Sorting reorders the rows without changing the stored data."
            )
        if "filter" in lowered:
            return (
                f"The {table} table shows {row_count} {rows_word} with columns {cols_text}. "
                f"Filtering hides rows that do not match our value."
            )
        if "query" in lowered or "select" in lowered:
            return (
                f"The {table} table holds {row_count} {rows_word} with columns {cols_text}. "
                f"A SELECT query asks the database for specific rows."
            )
        return (
            f"The {table} table shows {row_count} {rows_word} and {len(columns)} columns: {cols_text}. "
            f"Browse Data displays this structure without changing anything."
        )

    def _generate_recap(self, video: Any, table: str, column: Optional[str]) -> str:
        """Return a close/recap beat (<=45 words)."""
        objective = video.learning_objective or getattr(video, "discovery_objective", "")
        lowered = objective.lower()
        column_phrase = f" by {column}" if column else ""
        if "sort" in lowered and "filter" in lowered:
            return (
                f"We opened, sorted{column_phrase}, and filtered the {table} table. We can now explore any table interactively."
            )
        if "sort" in lowered:
            return (
                f"We sorted the {table} table{column_phrase} and saw the rows reorder. We can now sort any numeric column."
            )
        if "filter" in lowered:
            return (
                f"We filtered the {table} table and saw only matching rows. We can now filter by any column."
            )
        if "query" in lowered or "select" in lowered:
            return (
                f"We ran a SELECT query against the {table} table. We can now write our own queries."
            )
        return (
            f"We opened the {table} table and confirmed its structure. We can now browse any table in the database."
        )

    @staticmethod
    def _parse_demo_to_action(text: str) -> List[Dict[str, Any]]:
        """
        Parse a demo-beat narration sentence into vision-agent action dicts.

        Used as a fallback when a demo beat does not already have an action.
        Examples:
          "We click the Browse Data tab and the table view opens."
            -> [{"type": "click", "detail": "Browse Data tab"}]
          "We type SELECT star FROM Orders and the query appears."
            -> [{"type": "type", "detail": "SELECT * FROM Orders"}]
          "We press F5 and the results grid populates."
            -> [{"type": "key", "detail": "F5"}]
        """
        actions: List[Dict[str, Any]] = []
        lowered = text.lower()

        # Explicit high-level action verbs.
        if re.search(r"\b(apply|activate)\s+(?:the\s+)?filter", lowered):
            actions.append({"type": "click", "detail": "filter box"})
        if re.search(r"\brun\s+(?:the\s+)?quer", lowered) or re.search(
            r"\bexecute\s+(?:the\s+)?quer", lowered
        ):
            actions.append({"type": "key", "detail": "f5"})

        # Sort: "sort X by Y" or "click the Y column header".
        sort_match = re.search(
            r"\bsort\s+(?:the\s+)?\w+\s+(?:table\s+)?by\s+(?:the\s+)?(\w+)", lowered
        )
        if sort_match:
            actions.append({"type": "click", "detail": f"{sort_match.group(1)} column header"})
        header_match = re.search(r"\bclick\s+(?:the\s+)?(\w+)\s+(?:column\s+)?header", lowered)
        if header_match:
            actions.append({"type": "click", "detail": f"{header_match.group(1)} column header"})

        # Find type actions.
        for match in re.finditer(r"\btype\s+(.+?)(?=\s+(?:into|in|and|then|,)\s|\s*$)", lowered):
            detail = match.group(1).strip().rstrip(",.;:")
            # Convert spoken "star" back to the SQL asterisk.
            detail = detail.replace("star", "*")
            actions.append({"type": "type", "detail": detail})

        # Find key actions.
        for match in re.finditer(r"\bpress(?:es)?\s+([a-z0-9_+]+)", lowered, re.IGNORECASE):
            actions.append({"type": "key", "detail": match.group(1)})

        # Find click actions.
        for match in re.finditer(
            r"\bclick(?:s)?\s+(?:the\s+)?(.+?)(?=\s+(?:and|then|,)\s|\s*$)", lowered
        ):
            detail = match.group(1).strip().rstrip(",.;:")
            actions.append({"type": "click", "detail": detail})

        if len(actions) > 1:
            return [{"type": "sequence", "actions": actions}]
        return actions

    @staticmethod
    def _normalize_action(action_spec: Dict[str, Any]) -> Dict[str, Any]:
        """
        Convert legacy recipe action specs and coordinate-based actions into the
        vision-agent action format (click/type/key/verify/wait/sequence).
        """
        if not isinstance(action_spec, dict):
            return {"type": "wait", "duration": 1.5}

        action_type = action_spec.get("type")

        if action_type == "browse_table":
            table = action_spec.get("table", "Orders")
            return {
                "type": "sequence",
                "actions": [
                    {"type": "click", "detail": "Browse Data tab"},
                    {"type": "click", "detail": f"{table} table in the table dropdown"},
                ],
            }

        if action_type == "sort_column":
            table = action_spec.get("table", "Orders")
            column = action_spec.get("column", "amount")
            direction = action_spec.get("direction", "asc")
            seq: List[Dict[str, Any]] = [
                {"type": "click", "detail": "Browse Data tab"},
                {"type": "click", "detail": f"{table} table in the table dropdown"},
            ]
            if direction == "desc":
                seq.append({"type": "click", "detail": f"{column} column header"})
            seq.append({"type": "click", "detail": f"{column} column header"})
            return {"type": "sequence", "actions": seq}

        if action_type == "filter_column":
            table = action_spec.get("table", "Orders")
            column = action_spec.get("column", "region")
            value = action_spec.get("value", "")
            return {
                "type": "sequence",
                "actions": [
                    {"type": "click", "detail": "Browse Data tab"},
                    {"type": "click", "detail": f"{table} table in the table dropdown"},
                    {"type": "click", "detail": f"{column} filter box"},
                    {"type": "type", "detail": str(value), "target": f"{column} filter box"},
                    {"type": "key", "detail": "Return"},
                ],
            }

        if action_type == "execute_query":
            query = action_spec.get("query", "SELECT * FROM Orders")
            return {
                "type": "sequence",
                "actions": [
                    {"type": "click", "detail": "Execute SQL tab"},
                    {"type": "click", "detail": "SQL editor text area"},
                    {"type": "type", "detail": query, "target": "SQL editor text area"},
                    {"type": "key", "detail": "F5"},
                ],
            }

        # Coordinate-based click/type/key actions from older manifests.
        if action_type == "click":
            detail = action_spec.get("description") or action_spec.get("detail") or "UI element"
            target = action_spec.get("target")
            if not isinstance(target, dict):
                target = {}
            return {"type": "click", "detail": detail, "target": target}

        if action_type == "type":
            detail = action_spec.get("detail") or action_spec.get("text") or ""
            target = action_spec.get("target")
            if isinstance(target, dict):
                # Keep legacy coordinate dictionaries for the graph edge, but add
                # a human description for the vision agent if it is missing.
                if not target.get("description"):
                    target = {**target, "description": action_spec.get("description", "input field")}
            elif isinstance(target, str):
                # Vision-agent format uses a string target; keep it.
                pass
            else:
                target = action_spec.get("description", "input field")
            return {"type": "type", "detail": detail, "target": target}

        if action_type == "key":
            detail = action_spec.get("detail") or action_spec.get("text") or "Return"
            return {"type": "key", "detail": detail}

        if action_type == "wait":
            return {"type": "wait", "duration": action_spec.get("duration", 1.5)}

        # Already in vision-agent format.
        return action_spec

    # ------------------------------------------------------------------
    # C1: demo-unit helpers
    # ------------------------------------------------------------------

    def _demo_action_from_description(
        self,
        description: str,
        table: str,
        column: Optional[str],
        direction: str,
        filter_value: str,
        query: str,
        browse_data_already_active: bool,
        target_table_already_open: bool,
    ) -> Tuple[str, Optional[Dict[str, Any]]]:
        """
        Convert a demo-plan action_description into narration text and a
        vision-agent action dict. Returns (text, action); text may be empty
        if the step is redundant given the observed UI state.

        C2: demo descriptions may name their own target column/value; extract
        them so the demo_plan can vary actions without relying on the top-level
        discovery objective.
        """
        lowered = description.lower()

        # Extract a target column from the demo description if the global column
        # is not set or does not match the wording.
        demo_column = column
        header_match = re.search(r"(\w+)\s+(?:column\s+)?header", lowered)
        filter_box_match = re.search(r"(\w+)\s+(?:column\s+)?filter\s*(?:box)?", lowered)
        if header_match:
            demo_column = header_match.group(1).capitalize()
        elif filter_box_match:
            demo_column = filter_box_match.group(1).capitalize()

        # Extract a literal filter value from the original description (preserve case).
        demo_filter_value = filter_value
        literal_value_match = re.search(
            r"type\s+['\"]?([\w-]+)['\"]?", description, re.IGNORECASE
        )
        if literal_value_match:
            demo_filter_value = literal_value_match.group(1)

        # Logical-unit demos: one conceptual interaction that may need several
        # physical steps. They stay as a single demo beat in the C1 arc.
        if "open" in lowered and table.lower() in lowered:
            actions: List[Dict[str, Any]] = []
            texts: List[str] = []
            if not browse_data_already_active:
                actions.append(self._click_action("Browse Data tab"))
                texts.append("We click the Browse Data tab")
            if not target_table_already_open:
                actions.append(self._click_action(f"{table} table in the table dropdown"))
                texts.append(f"and select the {table} table")
            if not actions:
                return f"The {table} table is already open.", self._wait_action()
            if len(actions) == 1:
                return " ".join(texts).strip() + ".", actions[0]
            seq = self._sequence_action(actions, logical_unit=True)
            return " ".join(texts).strip() + ".", seq

        if "browse data" in lowered or "browse data tab" in lowered:
            if browse_data_already_active:
                return "", None
            return "We click the Browse Data tab.", self._click_action("Browse Data tab")

        if "select" in lowered and table.lower() in lowered and "dropdown" in lowered:
            if target_table_already_open:
                return "", None
            return f"We select the {table} table.", self._click_action(f"{table} table in the table dropdown")

        if "column header" in lowered and demo_column:
            if "twice" in lowered or "second time" in lowered or "again" in lowered:
                return f"We click the {demo_column} column header again.", self._click_action(f"{demo_column} column header")
            return f"We click the {demo_column} column header.", self._click_action(f"{demo_column} column header")

        if "filter box" in lowered and demo_column:
            # If the description also includes a value to type, make it one filter unit.
            if demo_filter_value and ("type" in lowered or "enter" in lowered):
                return (
                    f"We click the {demo_column} filter box and type {demo_filter_value}.",
                    self._sequence_action([
                        self._click_action(f"{demo_column} filter box"),
                        self._type_action(str(demo_filter_value), target=f"{demo_column} filter box"),
                        self._key_action("Return"),
                    ], logical_unit=True),
                )
            return f"We click the {demo_column} filter box.", self._click_action(f"{demo_column} filter box")

        # Standalone type-and-submit unit (e.g. "Type a value and press Return").
        if ("type" in lowered or "enter" in lowered) and demo_filter_value and demo_column:
            return (
                f"We type {demo_filter_value} and press Return.",
                self._sequence_action([
                    self._type_action(str(demo_filter_value), target=f"{demo_column} filter box"),
                    self._key_action("Return"),
                ], logical_unit=True),
            )

        if "return" in lowered or "press return" in lowered:
            return "We press Return.", self._key_action("Return")

        if "execute sql" in lowered or "sql" in lowered:
            return (
                "We open Execute SQL, type the query, and run it.",
                self._sequence_action([
                    self._click_action("Execute SQL tab"),
                    self._click_action("SQL editor text area"),
                    self._type_action(query, target="SQL editor text area"),
                    self._key_action("F5"),
                ]),
            )

        # Generic fallback.
        return f"We {description.lower()}.", self._wait_action()

    def _generate_explain(
        self,
        description: str,
        table: str,
        column: Optional[str],
        direction: str,
        filter_value: str,
        columns: List[str],
        row_count: int,
        rows_word: str,
    ) -> str:
        """Return an explain beat (<=50 words) referencing the visible result."""
        lowered = description.lower()
        direction_text = "ascending" if direction == "asc" else "descending"

        # C2: demo descriptions may name their own target column.
        demo_column = column
        header_match = re.search(r"(\w+)\s+(?:column\s+)?header", lowered)
        filter_box_match = re.search(r"(\w+)\s+(?:column\s+)?filter\s*(?:box)?", lowered)
        if header_match:
            demo_column = header_match.group(1).capitalize()
        elif filter_box_match:
            demo_column = filter_box_match.group(1).capitalize()

        demo_filter_value = filter_value
        literal_value_match = re.search(
            r"type\s+['\"]?([\w-]+)['\"]?", description, re.IGNORECASE
        )
        if literal_value_match:
            demo_filter_value = literal_value_match.group(1)

        if "browse data" in lowered:
            return (
                f"The data grid is now visible. We can select a table here and view its rows without writing SQL."
            )

        if "select" in lowered and table.lower() in lowered:
            return (
                f"The {table} grid is loaded. Each row is a record, and the headers name the columns."
            )

        if "column header" in lowered and demo_column:
            return (
                f"The rows now reorder by {demo_column} in {direction_text} order. "
                f"The stored data is unchanged; only the view is sorted."
            )

        # A filter unit that already typed a value describes the result, not the box.
        if ("type" in lowered or "enter" in lowered) and demo_filter_value and demo_column:
            return (
                f"The grid now shows only rows where {demo_column} matches {demo_filter_value}. "
                f"The status bar reflects the filtered count."
            )

        if "filter box" in lowered and demo_column:
            return (
                f"The {demo_column} filter box is active. We will type a value and the grid will show only matching rows."
            )

        if "execute sql" in lowered or "sql" in lowered or "query" in lowered:
            return (
                f"The results grid shows the query output. The database returns exactly the requested rows and columns."
            )

        return (
            f"The screen now reflects the action. The stored data in the {table} table remains unchanged."
        )

    def _generate_validation(
        self,
        description: str,
        table: str,
        column: Optional[str],
        direction: str,
        filter_value: str,
        columns: List[str],
        row_count: int,
        rows_word: str,
    ) -> str:
        """Return a validation beat (<=40 words) confirming visible state without re-listing facts."""
        lowered = description.lower()
        direction_text = "ascending" if direction == "asc" else "descending"

        # C2: demo descriptions may name their own target column/value.
        demo_column = column
        header_match = re.search(r"(\w+)\s+(?:column\s+)?header", lowered)
        filter_box_match = re.search(r"(\w+)\s+(?:column\s+)?filter\s*(?:box)?", lowered)
        if header_match:
            demo_column = header_match.group(1).capitalize()
        elif filter_box_match:
            demo_column = filter_box_match.group(1).capitalize()

        demo_filter_value = filter_value
        literal_value_match = re.search(
            r"type\s+['\"]?([\w-]+)['\"]?", description, re.IGNORECASE
        )
        if literal_value_match:
            demo_filter_value = literal_value_match.group(1)

        if "browse data" in lowered:
            return (
                f"We see the Browse Data tab is active and the data grid is visible."
            )

        if "select" in lowered and table.lower() in lowered:
            return (
                f"We see the {table} grid is loaded and matches the schema."
            )

        if "column header" in lowered and demo_column:
            return (
                f"We see the {table} table is sorted by {demo_column} in {direction_text} order."
            )

        if "filter" in lowered and demo_filter_value and demo_column:
            return (
                f"We see the {table} table filtered by {demo_column}. The status bar shows the matching count."
            )

        if "execute sql" in lowered or "query" in lowered:
            return (
                f"We see the Execute SQL tab shows a populated results grid."
            )

        return (
            f"We see the {table} table displays the expected result."
        )

    def _build_script_beats(
        self,
        video: Any,
        parsed: Dict[str, Any],
        env_map: Optional[Dict[str, Any]] = None,
    ) -> List[ScriptBeat]:
        """Build a full SQL Essentials-style teaching arc from a parsed objective.

        Arc: hook -> concept -> [demo -> explain -> validate]* -> recap.
        All numbers and names come from the EnvironmentMap or direct DB facts.
        """
        exercise = video.exercise_artifact or {}
        db_path = exercise.get("db_path")
        table = parsed.get("table", exercise.get("table_name", "Orders"))
        column = parsed.get("column")
        direction = parsed.get("direction", "asc")
        filter_value = parsed.get("value", "")
        query = parsed.get("query", "SELECT * FROM Orders")

        facts = self._db_facts(db_path, table)
        row_count = facts.get("row_count", 0)
        columns = facts.get("columns", [])

        # Ground against the scout pass when available.
        env_tables: List[str] = []
        env_columns: Dict[str, List[str]] = {}
        env_row_counts: Dict[str, int] = {}
        env_default_table: Optional[str] = None
        env_active_tab: Optional[str] = None
        if env_map:
            env_tables = env_map.get("tables", []) or []
            env_columns = env_map.get("columns", {}) or {}
            env_row_counts = env_map.get("row_counts", {}) or {}
            ui = env_map.get("ui") or {}
            env_default_table = ui.get("browse_data_default_table")
            env_active_tab = ui.get("active_tab")
            if table in env_row_counts:
                row_count = env_row_counts[table]
            if table in env_columns:
                columns = env_columns[table]

        rows_word = "rows" if row_count != 1 else "row"
        browse_data_already_active = env_active_tab and "browse data" in env_active_tab.lower()
        target_table_already_open = env_default_table and env_default_table.lower() == table.lower()

        # Ground the parsed column against the actual table schema.
        # Provisional demo_plan/objectives may reference columns that do not
        # exist (e.g. "Region" on a table that only has "status"). Substitute a
        # real column so filter/sort demos are retained and narration stays
        # grounded.
        if column and columns:
            canonical = {c.lower(): c for c in columns}
            if column.lower() not in canonical:
                substitute = self._pick_substitute_column(column, table, columns)
                if substitute:
                    print(
                        f"Info: substituting missing column '{column}' with '{substitute}' in {video.video_id}",
                        file=sys.stderr,
                    )
                    column = substitute
            else:
                column = canonical[column.lower()]
            # Refresh any filter value from the actual substituted column.
            if parsed.get("type") == "filter_column":
                filter_value = self._first_value(
                    db_path, table, column, context=f"filter {video.video_id}"
                ) or ""

        # Reconcile demo_plan against the EnvironmentMap.
        demo_plan = list(getattr(video, "demo_plan", []) or [])
        reconciled_demos: List[Dict[str, Any]] = []
        env_tables_lower = {t.lower() for t in env_tables}
        columns_lower = {c.lower() for c in columns}
        for demo in demo_plan:
            desc = demo.get("action_description", "")
            lowered = desc.lower()
            grounded = True
            # Drop demos that reference tables not present in the environment.
            for t in env_tables:
                if t.lower() in lowered and t.lower() not in env_tables_lower:
                    grounded = False
                    break
            # Drop demos that reference columns not present in the target table.
            if grounded and column and column.lower() in lowered:
                if column.lower() not in columns_lower:
                    grounded = False
            if not grounded:
                print(
                    f"Warning: dropping ungrounded demo from {video.video_id}: {desc}",
                    file=sys.stderr,
                )
                continue
            reconciled_demos.append(demo)

        # Fallback if the manifest demo_plan is empty or all demos were dropped.
        if not reconciled_demos:
            reconciled_demos = [
                {
                    "action_description": video.discovery_objective,
                    "expected_observable_result": video.discovery_objective,
                }
            ]

        beats: List[ScriptBeat] = []

        # Hook (opening)
        beats.append(
            ScriptBeat(
                beat_id="beat_001",
                kind="opening",
                text=self._generate_hook(video, table, column),
                action=self._wait_action(),
            )
        )

        # Concept (no action, spoken over initial stable state)
        beats.append(
            ScriptBeat(
                beat_id="beat_002",
                kind="concept",
                text=self._generate_concept(video, table, columns, row_count, rows_word),
                action=None,
            )
        )

        # Demo units.
        demo_idx = 3
        for demo in reconciled_demos:
            demo_text, demo_action = self._demo_action_from_description(
                demo.get("action_description", ""),
                table,
                column,
                direction,
                filter_value,
                query,
                browse_data_already_active,
                target_table_already_open,
            )
            if not demo_text or not demo_action:
                continue
            beats.append(
                ScriptBeat(
                    beat_id=f"beat_{demo_idx:03d}",
                    kind="demo",
                    text=demo_text,
                    action=demo_action,
                )
            )
            demo_idx += 1

            # Explain (concept/state beat over the settled result state)
            beats.append(
                ScriptBeat(
                    beat_id=f"beat_{demo_idx:03d}",
                    kind="explain",
                    text=self._generate_explain(
                        demo.get("action_description", ""),
                        table,
                        column,
                        direction,
                        filter_value,
                        columns,
                        row_count,
                        rows_word,
                    ),
                    action=None,
                )
            )
            demo_idx += 1

            # Validate
            beats.append(
                ScriptBeat(
                    beat_id=f"beat_{demo_idx:03d}",
                    kind="validation",
                    text=self._generate_validation(
                        demo.get("action_description", ""),
                        table,
                        column,
                        direction,
                        filter_value,
                        columns,
                        row_count,
                        rows_word,
                    ),
                    action=self._verify_action(
                        demo.get(
                            "expected_observable_result",
                            f"the {table} table shows the expected result",
                        )
                    ),
                )
            )
            demo_idx += 1

        # Recap (close)
        beats.append(
            ScriptBeat(
                beat_id=f"beat_{demo_idx:03d}",
                kind="close",
                text=self._generate_recap(video, table, column),
                action=self._wait_action(),
            )
        )

        # Renumber sequentially.
        for i, beat in enumerate(beats, start=1):
            beat.beat_id = f"beat_{i:03d}"

        return beats

    # ------------------------------------------------------------------
    # C2: anti-repetition helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _sentence_overlap(a: str, b: str) -> float:
        """Return Jaccard word overlap between two sentences (0..1)."""
        words_a = set(re.findall(r"\b\w+\b", a.lower()))
        words_b = set(re.findall(r"\b\w+\b", b.lower()))
        if not words_a or not words_b:
            return 0.0
        intersection = words_a & words_b
        union = words_a | words_b
        return len(intersection) / len(union)

    @staticmethod
    def _normalize_sentence(sentence: str) -> str:
        """Lowercase, strip punctuation, collapse whitespace."""
        sentence = sentence.lower()
        sentence = re.sub(r"[^\w\s]", " ", sentence)
        sentence = re.sub(r"\s+", " ", sentence).strip()
        return sentence

    def _strip_repetitive_sentences(self, beats: List[ScriptBeat]) -> List[ScriptBeat]:
        """Drop later sentences that are verbatim or near-verbatim repeats."""
        used_sentences: List[str] = []
        for beat in beats:
            if not beat.text:
                continue
            # Split on sentence terminators.
            raw_sentences = re.split(r"(?<=[.!?])\s+", beat.text.strip())
            kept: List[str] = []
            for raw in raw_sentences:
                if not raw.strip():
                    continue
                norm = self._normalize_sentence(raw)
                if not norm:
                    continue
                # Check against previously used sentences.
                duplicate = False
                for used in used_sentences:
                    if norm == used or self._sentence_overlap(norm, used) > 0.6:
                        duplicate = True
                        break
                if duplicate:
                    continue
                kept.append(raw)
                used_sentences.append(norm)
            if kept:
                beat.text = " ".join(kept)
            else:
                # If every sentence was a repeat, reduce to a neutral confirmation.
                beat.text = "We confirm the result on screen."
        return beats

    def _enforce_word_limits(
        self, beats: List[ScriptBeat], video: Any
    ) -> List[ScriptBeat]:
        """C2: cap each beat to its per-kind maximum. No padding, no floor."""
        limits = {
            "opening": (5, 45),
            "concept": (5, 40),
            "explain": (5, 50),
            "demo": (5, 20),
            "validation": (5, 40),
            "close": (5, 45),
            "state": (5, 40),
            "recap": (5, 45),
            "preview": (5, 30),
        }

        # Hard cap each beat to its maximum.
        for beat in beats:
            _, hi = limits.get(beat.kind, (5, 40))
            beat.text = self._truncate(beat.text, hi)

        # C2: mechanical anti-repetition pass.
        beats = self._strip_repetitive_sentences(beats)

        # Log final word counts per kind.
        total = sum(self._word_count(b.text) for b in beats)
        by_kind: Dict[str, int] = {}
        for beat in beats:
            by_kind[beat.kind] = by_kind.get(beat.kind, 0) + self._word_count(beat.text)
        print(
            f"Script word counts: total={total}, by_kind={by_kind}",
            file=sys.stderr,
        )

        return beats

    # ------------------------------------------------------------------
    # Script generation
    # ------------------------------------------------------------------

    def generate_script(
        self,
        video: Any,
        fix_errors: Optional[List[str]] = None,
        max_attempts: int = 1,
        env_map: Optional[Dict[str, Any]] = None,
    ) -> List[ScriptBeat]:
        """
        Generate a SQL Essentials-quality narration script for the video.

        Known objectives are rendered deterministically from templates. Unknown
        objectives fall back to an LLM prompt. The validator emits warnings for
        most issues and only hard-fails on empty/missing beats. At most one
        regeneration attempt is made; after that the best-effort script is used.
        """
        exercise = video.exercise_artifact or {}
        db_path = exercise.get("db_path")
        default_table = (video.exercise_artifact or {}).get("table_name", "Orders")
        parsed = self._parse_objective(video.discovery_objective, db_path, default_table=default_table)
        beats: List[ScriptBeat] = []

        if parsed:
            beats = self._build_script_beats(video, parsed, env_map=env_map)
        else:
            if not os.environ.get("ANTHROPIC_API_KEY"):
                print("Error: ANTHROPIC_API_KEY environment variable is not set.", file=sys.stderr)
                return []
            for attempt in range(max_attempts):
                prompt = self._build_script_prompt(video, fix_errors=fix_errors, env_map=env_map)
                response = self.client.messages.create(
                    model=MODEL,
                    max_tokens=2048,
                    messages=[{"role": "user", "content": prompt}],
                )
                text_parts = [block.text for block in response.content if block.type == "text"]
                raw_text = "\n".join(text_parts).strip()
                script_data = self._parse_script_json(raw_text)
                if not script_data:
                    print(f"Warning: could not parse script JSON (attempt {attempt + 1}); retrying.", file=sys.stderr)
                    continue
                beats = [
                    ScriptBeat(
                        beat_id=item.get("beat_id") or f"beat_{i:03d}",
                        kind=item.get("kind", "state"),
                        text=item.get("text", "").strip(),
                        action=item.get("action"),
                        visual_check=item.get("visual_check"),
                    )
                    for i, item in enumerate(script_data, start=1)
                ]
                beats = self._validate_script_beats(beats, video)
                ok, errors, warnings = self.validate_script(beats, video)
                for warning in warnings:
                    print(f"Warning: {warning}", file=sys.stderr)
                if ok:
                    break
                print(f"Script quality gate failed (attempt {attempt + 1}); regenerating.", file=sys.stderr)
                fix_errors = errors

        beats = self._validate_script_beats(beats, video)
        beats = self._enforce_word_limits(beats, video)
        ok, errors, warnings = self.validate_script(beats, video)
        for warning in warnings:
            print(f"Warning: {warning}", file=sys.stderr)
        if not ok:
            print(f"Warning: returning script despite hard failures: {errors}", file=sys.stderr)
        return beats

    @staticmethod
    def _parse_script_json(raw_text: str) -> List[Dict[str, Any]]:
        """Extract a JSON array of beats from the LLM response."""
        script_data: List[Dict[str, Any]] = []
        fenced = re.search(r"```(?:json)?\s*(\[.*\])\s*```", raw_text, re.DOTALL)
        if fenced:
            try:
                script_data = json.loads(fenced.group(1))
            except json.JSONDecodeError:
                pass

        if not script_data:
            try:
                script_data = json.loads(raw_text)
            except json.JSONDecodeError:
                return []

        if not isinstance(script_data, list):
            script_data = script_data.get("script", [])

        return script_data

    def _build_script_prompt(
        self,
        video: Any,
        fix_errors: Optional[List[str]] = None,
        env_map: Optional[Dict[str, Any]] = None,
    ) -> str:
        exercise = video.exercise_artifact or {}
        db_path = exercise.get("db_path", "")
        table_name = exercise.get("table_name", "")
        fix_section = ""
        if fix_errors:
            fix_section = (
                "\n\nThe previous script failed quality review with these errors. "
                "Fix them and return a corrected JSON array with no explanation:\n"
                + "\n".join(f"- {e}" for e in fix_errors)
            )

        env_section = ""
        if env_map:
            env_section = (
                "\n\nOBSERVED ENVIRONMENT (from a scout pass; treat as ground truth):\n"
                f"- Application: {env_map.get('application', video.application)}\n"
                f"- Tables in database: {', '.join(env_map.get('tables', []) or [])}\n"
            )
            row_counts = env_map.get("row_counts", {}) or {}
            if row_counts:
                env_section += "- Exact row counts: " + ", ".join(
                    f"{t}={row_counts.get(t, '?')}" for t in env_map.get("tables", [])
                ) + "\n"
            columns = env_map.get("columns", {}) or {}
            if columns:
                env_section += "- Columns per table:\n"
                for t in env_map.get("tables", []):
                    env_section += f"  - {t}: {', '.join(columns.get(t, []))}\n"
            ui = env_map.get("ui") or {}
            env_section += (
                f"- Active tab on launch: {ui.get('active_tab')}\n"
                f"- Available tabs: {', '.join(ui.get('available_tabs', []) or [])}\n"
                f"- Browse Data default table: {ui.get('browse_data_default_table')}\n"
                f"- Notable UI state: {ui.get('notable', 'none')}\n"
            )

        return f"""You are writing narration for a short software-training video in the style of SQL Essentials.

Course context
- Topic: {getattr(video, 'title', '')}
- Tool: DB Browser for SQLite
- Learning objective: {video.learning_objective}
- Discovery objective: {video.discovery_objective}
- Running example: {table_name} table in {db_path}
{env_section}
STRICT RULES (zero exceptions):
1. Follow this exact arc: opening -> concept -> (demo -> concept -> validation)* -> close.
2. opening (hook): 30-45 words. State what this lesson teaches and one concrete payoff.
3. concept: 50-90 words, no action. Explain the core idea over a stable screen state.
4. demo: 5-20 words, exactly ONE atomic action, spoken WHILE the action happens. Start with "We ".
5. concept (explain): 40-70 words, no action. Explain the "why/what this means" over the SETTLED RESULT of the previous demo.
6. validation: 20-40 words. Cite only observable facts from the EnvironmentMap (exact table names, column names, row counts).
7. close (recap): 30-45 words. Summarize what we did and what the learner can do now.
8. Total script: 350-650 words (≈2-4.5 minutes at 2.5 words per second).
9. Voice: first person plural, present tense. "We click...", "We type...", "We see..."
10. NEVER use: you'll, you need to, it's important to, before you, if you skip, understand, learn, abstract.
11. Do NOT generate actions already satisfied by the observed default state.
12. Only state numbers/names present in the EnvironmentMap. Never invent quantities, table names, or column names.
13. SQL keywords in narration stay uppercase: SELECT, FROM, WHERE. Use "star" for *.

Return ONLY a JSON array of beats. concept/explain beats have NO action. demo beats MUST have an action.
[
  {{"beat_id": "beat_001", "kind": "opening", "text": "In this lesson, we will open the Orders table in DB Browser for SQLite. Seeing the raw rows and columns is the first step before sorting, filtering, or writing any query.", "action": {{"type": "wait", "duration": 1.5}}}},
  {{"beat_id": "beat_002", "kind": "concept", "text": "A database table stores information in rows and columns. Each row in the Orders table is one record, and each column is one attribute. The Orders table has columns id, region, order_date, and amount, with several rows of data. Opening the table in the Browse Data tab lets us inspect this structure without changing anything, which is the safest way to understand the data."}},
  {{"beat_id": "beat_003", "kind": "demo", "text": "We click the Browse Data tab.", "action": {{"type": "click", "detail": "Browse Data tab"}}}},
  {{"beat_id": "beat_004", "kind": "concept", "text": "The Browse Data tab switches the view from the database structure to the data grid. This grid is where we view and interact with table rows visually instead of writing SQL. Once the tab is active, the Orders table can be selected and its rows become visible."}},
  {{"beat_id": "beat_005", "kind": "validation", "text": "The Browse Data tab is active and the data grid area is visible, ready to show table rows."}},
  {{"beat_id": "beat_006", "kind": "demo", "text": "We select the Orders table.", "action": {{"type": "click", "detail": "Orders table in the table dropdown"}}}},
  {{"beat_id": "beat_007", "kind": "concept", "text": "Selecting the Orders table loads its rows into the grid. The column headers now show id, region, order_date, and amount, and every row represents one order. We can now inspect the data directly and confirm the table structure before moving on."}},
  {{"beat_id": "beat_008", "kind": "validation", "text": "The grid shows the Orders table with all rows and columns id, region, order_date, and amount visible."}},
  {{"beat_id": "beat_009", "kind": "close", "text": "We have opened the Orders table and confirmed its structure. You can now browse any table in the database to see its raw rows and columns before analyzing it.", "action": {{"type": "wait", "duration": 1.5}}}}
]
{fix_section}
"""

    @staticmethod
    def _validate_script_beats(beats: List[ScriptBeat], video: Any) -> List[ScriptBeat]:
        """Normalize actions, split multi-step demo beats, and drop invalid beats."""
        valid_kinds = {"opening", "concept", "explain", "demo", "validation", "close", "recap", "preview", "state"}
        supported_actions = {
            "browse_table", "sort_column", "filter_column", "execute_query",
            "click", "type", "key", "wait", "verify", "sequence",
        }
        cleaned: List[ScriptBeat] = []
        for beat in beats:
            if beat.kind not in valid_kinds:
                print(f"Warning: dropping script beat with unknown kind {beat.kind!r}", file=sys.stderr)
                continue
            if not beat.text or not beat.text.strip():
                print(f"Warning: {beat.beat_id} has empty text; skipping.", file=sys.stderr)
                continue
            if beat.kind == "demo" and beat.action:
                action_type = beat.action.get("type")
                if action_type not in supported_actions:
                    print(
                        f"Warning: demo beat {beat.beat_id} uses unsupported action {action_type!r}; skipping.",
                        file=sys.stderr,
                    )
                    continue
                beat.action = _format_action_sql(beat.action)
                beat.action = LessonBuilder._normalize_action(beat.action)
            cleaned.append(beat)

        cleaned = LessonBuilder._split_atomic_demo_beats(cleaned)
        return cleaned

    @staticmethod
    def _split_atomic_demo_beats(beats: List[ScriptBeat]) -> List[ScriptBeat]:
        """Split any demo beat whose action contains >1 UI step into atomic demo beats."""
        result: List[ScriptBeat] = []
        for beat in beats:
            if beat.kind != "demo" or not beat.action:
                result.append(beat)
                continue

            sub_actions = LessonBuilder._atomic_sub_actions(beat.action)
            if len(sub_actions) <= 1:
                result.append(beat)
                continue
            # C1 arc: logical demo units (open table, type+Return, etc.) stay as
            # one conceptual demo beat even though they contain multiple physical
            # steps. Splitting them would create consecutive demo beats and break
            # the demo -> concept -> validation pattern.
            if beat.action.get("logical_unit"):
                result.append(beat)
                continue

            texts = LessonBuilder._split_demo_text(beat.text, len(sub_actions))
            for i, (sub_action, sub_text) in enumerate(zip(sub_actions, texts), start=1):
                suffix = f"_{chr(ord('a') + i - 1)}"
                result.append(
                    ScriptBeat(
                        beat_id=f"{beat.beat_id}{suffix}",
                        kind="demo",
                        text=sub_text,
                        action=LessonBuilder._normalize_action(sub_action),
                    )
                )
        return result

    @staticmethod
    def _atomic_sub_actions(action: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Return a flat list of atomic UI actions from an action spec."""
        action_type = action.get("type")
        if action_type == "sequence":
            return [
                sub
                for sub in (action.get("actions") or [])
                if sub
            ]
        return [action]

    @staticmethod
    def _split_demo_text(text: str, n_parts: int) -> List[str]:
        """Split a demo narration into one phrase per atomic action."""
        text = text.strip().rstrip(".")
        # Try splitting on common conjunctions that join two action clauses.
        separators = [" and ", ", then ", ", and then ", "; "]
        lowered = text.lower()
        for sep in separators:
            if sep in lowered:
                raw_parts = [p.strip() for p in text.split(sep, n_parts - 1)]
                if len(raw_parts) == n_parts:
                    fixed: List[str] = []
                    for part in raw_parts:
                        part = part.rstrip(",.;:")
                        if not part.lower().startswith("we "):
                            # Fragment like "select Customers" -> "We select Customers."
                            part = f"We {part[0].lower()}{part[1:]}"
                        if part and not part.endswith("."):
                            part += "."
                        fixed.append(part)
                    return fixed

        # Fallback: generate concise narration for each implied action.
        words = text.split()
        chunk_size = max(1, len(words) // n_parts)
        parts: List[str] = []
        for i in range(n_parts):
            start = i * chunk_size
            end = len(words) if i == n_parts - 1 else (i + 1) * chunk_size
            chunk = " ".join(words[start:end]).rstrip(",.;:")
            if chunk and not chunk.lower().startswith("we "):
                chunk = f"We {chunk[0].lower()}{chunk[1:]}"
            if chunk and not chunk.endswith("."):
                chunk += "."
            parts.append(chunk)
        return parts

    def validate_script(
        self, beats: List[ScriptBeat], video: Any
    ) -> tuple[bool, List[str], List[str]]:
        """
        C1 quality gate. Returns (ok, hard_errors, warnings).

        Hard failures: empty script, missing required kinds, no demo beats, or
        beats that severely violate the teaching arc.
        """
        errors: List[str] = []
        warnings: List[str] = []

        if not beats:
            errors.append("Script is empty.")
            return False, errors, warnings

        kinds = [b.kind for b in beats]
        required = {"opening", "concept", "demo", "validation", "close"}
        # explain beats are post-demo concept beats; concept can be satisfied by either.
        present_concepts = {"concept", "explain"} & set(kinds)
        missing = required - set(kinds)
        if missing and not (missing == {"concept"} and present_concepts):
            errors.append(f"Missing required beat kinds: {sorted(missing)}")

        # Arc ordering: opening -> concept -> (demo -> explain -> validation)* -> close
        progression_ok = True
        if kinds[0] != "opening":
            progression_ok = False
            warnings.append("Script should start with an opening beat.")
        if len(kinds) > 1 and kinds[1] not in {"concept", "explain"}:
            progression_ok = False
            warnings.append("The second beat should be a concept beat.")
        if kinds[-1] != "close":
            progression_ok = False
            warnings.append("Script should end with a close/recap beat.")

        # Validate the repeating demo -> explain -> validation units.
        middle = kinds[2:-1]
        unit_pattern = re.compile(r"^(demo explain validation)( demo explain validation)*$")
        if middle and not unit_pattern.match(" ".join(middle)):
            progression_ok = False
            warnings.append(
                "Middle beats must follow repeating demo -> explain -> validation units."
            )

        if not progression_ok:
            warnings.append("Expected arc: opening -> concept -> (demo -> explain -> validation)* -> close.")

        demo_count = sum(1 for b in beats if b.kind == "demo")
        action_count = sum(1 for b in beats if b.kind == "demo" and b.action)
        if demo_count == 0:
            errors.append("Script must have at least one demo beat.")
        if action_count == 0:
            warnings.append("Demo beats lack concrete actions; discovery may not reach the objective.")

        # C2: no total word budget; report total for information only.
        total_words = sum(self._word_count(b.text) for b in beats)

        # Per-kind word ranges (C2).
        limits = {
            "opening": (5, 45),
            "concept": (5, 40),
            "explain": (5, 50),
            "demo": (5, 20),
            "validation": (5, 40),
            "close": (5, 45),
            "state": (5, 40),
            "recap": (5, 45),
            "preview": (5, 30),
        }
        for beat in beats:
            wc = self._word_count(beat.text)
            lo, hi = limits.get(beat.kind, (5, 90))
            if not (lo <= wc <= hi):
                warnings.append(f"{beat.beat_id} ({beat.kind}) has {wc} words; expected {lo}-{hi}.")

            lowered = beat.text.lower()
            for pattern in self._FORBIDDEN_VOICE_PATTERNS:
                if re.search(pattern, lowered):
                    warnings.append(f"{beat.beat_id} contains filler phrase matching /{pattern}/.")
                    break

            if self._SECOND_PERSON_PATTERN.search(beat.text):
                warnings.append(f"{beat.beat_id} uses second-person voice; prefer 'we'.")

            if not beat.text.startswith("We ") and beat.kind in {"demo", "validation", "close"}:
                warnings.append(f"{beat.beat_id} should start with 'We '.")

            if beat.kind == "opening" and not re.search(
                r"^(in this lesson,\s+)?(we\s+will|we\s+sort|we\s+filter|we\s+open|we\s+run|this\s+lesson\s+shows|we\s+are\s+going)", lowered
            ):
                warnings.append(f"{beat.beat_id} opening should state the objective clearly.")

            if beat.kind == "close" and not re.search(r"^we\s+(have|opened|sorted|filtered|ran)", lowered):
                warnings.append(f"{beat.beat_id} close should recap the skill.")

            if beat.kind == "validation" and _contains_action_word(beat.text):
                warnings.append(f"{beat.beat_id} (validation) describes an action; prefer a visible fact.")

            if beat.kind == "demo":
                action_words = {"click", "type", "press", "enter", "select", "choose", "hit", "tap", "open", "run", "sort", "filter"}
                if not any(w in lowered for w in action_words):
                    warnings.append(f"{beat.beat_id} (demo) does not describe an action.")

        return not errors, errors, warnings
    # ------------------------------------------------------------------
    # Action derivation
    # ------------------------------------------------------------------

    def derive_actions(
        self, beats: List[ScriptBeat], db_path: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """
        Convert script demo beats into concrete UI actions the discovery harness
        can execute. Recipe-friendly actions are expanded by DiscoveryRecipes;
        generic click/type/key actions pass through.
        """
        actions, _ = self._derive_actions_with_mapping(beats, db_path)
        return actions

    def _derive_actions_with_mapping(
        self, beats: List[ScriptBeat], db_path: Optional[str] = None
    ) -> Tuple[List[Dict[str, Any]], List[Optional[ScriptBeat]]]:
        """
        Like derive_actions, but also returns a parallel list mapping each
        concrete action back to its source demo beat (or None).
        """
        actions: List[Dict[str, Any]] = []
        beat_for_action: List[Optional[ScriptBeat]] = []
        for beat in beats:
            if beat.kind != "demo" or not beat.action:
                continue
            derived = self._derive_single_action(beat.action, db_path)
            actions.extend(derived)
            beat_for_action.extend([beat] * len(derived))
        return actions, beat_for_action

    @staticmethod
    def _derive_single_action(
        action_spec: Dict[str, Any], db_path: Optional[str]
    ) -> List[Dict[str, Any]]:
        action_type = action_spec.get("type")

        if action_type == "browse_table":
            return DiscoveryRecipes.browse_table(action_spec.get("table", "Orders"), db_path)

        if action_type == "sort_column":
            return DiscoveryRecipes.sort_column(
                action_spec.get("table", "Orders"),
                action_spec.get("column", "amount"),
                action_spec.get("direction", "asc"),
            )

        if action_type == "filter_column":
            return DiscoveryRecipes.filter_column(
                action_spec.get("table", "Orders"),
                action_spec.get("column", "region"),
                action_spec.get("value", ""),
            )

        if action_type == "execute_query":
            query = action_spec.get("query", "SELECT * FROM Orders")
            return DiscoveryRecipes.execute_query(query)

        if action_type == "click":
            return [
                {
                    "action": "click",
                    "target": action_spec.get("target", {"x": 0.5, "y": 0.5}),
                    "description": action_spec.get("description", "Click"),
                    "animate": True,
                }
            ]

        if action_type == "type":
            target = action_spec.get("target", {"x": 0.5, "y": 0.5})
            return [
                {
                    "action": "click",
                    "target": target,
                    "description": action_spec.get("description", "Focus input"),
                    "animate": True,
                },
                {
                    "action": "type",
                    "target": target,
                    "text": action_spec.get("text", ""),
                    "description": action_spec.get("description", "Type value"),
                    "click_first": False,
                },
            ]

        if action_type == "key":
            return [
                {
                    "action": "key",
                    "text": action_spec.get("text", "Return"),
                    "description": action_spec.get("description", "Press key"),
                }
            ]

        if action_type == "wait":
            return [
                {
                    "action": "wait",
                    "duration": action_spec.get("duration", 1.0),
                    "description": action_spec.get("description", "Wait"),
                }
            ]

        print(f"Warning: unsupported action type {action_type!r}", file=sys.stderr)
        return []

    # ------------------------------------------------------------------
    # Script execution
    # ------------------------------------------------------------------

    def execute_script(
        self,
        beats: List[ScriptBeat],
        discovery: EndStateDiscovery,
        db_path: Optional[str] = None,
    ) -> DiscoveryResult:
        """
        Run the vision-agent script beats through the discovery harness.

        The harness records one video clip per beat (opening, demo, validation,
        close) and stores the path in ``beat.video_clip_path``.
        """
        # Back-fill demo actions using the text parser for any beat that is
        # missing an action specification, normalising multi-action parses to a
        # single sequence action dict.
        for beat in beats:
            if beat.kind == "demo" and not beat.action:
                parsed = self._parse_demo_to_action(beat.text)
                if len(parsed) == 1:
                    beat.action = parsed[0]
                elif len(parsed) > 1:
                    beat.action = {"type": "sequence", "actions": parsed}

        result = discovery.execute_script(
            beats=beats,
            visual_summary=discovery.objective,
            save_all_screenshots=True,
        )

        # ADAPT narration for validation/concept beats that conflict with observed facts.
        self._adapt_beats_to_observed_state(beats)

        return result

    def _adapt_beats_to_observed_state(self, beats: List[ScriptBeat]) -> None:
        """Rewrite beats whose claims conflict with observed facts or footage."""
        previous_observed: Optional[Dict[str, Any]] = None
        for beat in beats:
            if not beat.observed_state:
                continue

            if beat.kind in ("validation", "concept"):
                if self._beat_conflicts_with_observed_state(beat):
                    self._rewrite_beat_from_observed(beat, "state")
            elif beat.kind == "demo":
                if previous_observed and self._observed_state_unchanged(
                    previous_observed, beat.observed_state
                ):
                    self._rewrite_beat_from_observed(
                        beat,
                        "state",
                        extra_instruction=(
                            "The screen did not visibly change during this beat. "
                            "Rewrite the narration to describe the existing state instead of claiming an action happened."
                        ),
                    )

            previous_observed = beat.observed_state

    def _rewrite_beat_from_observed(
        self,
        beat: ScriptBeat,
        target_kind: str,
        extra_instruction: str = "",
    ) -> None:
        """Use a text-only LLM call to rewrite a beat from observed facts."""
        observed = beat.observed_state
        prompt = (
            "Rewrite this narration beat to describe ONLY the stable observed state. "
            "Do not invent numbers, column names, or table names. "
            "Do NOT mention dropdowns, menus, modals, popups, or anything transient that is open. "
            "Describe only what is persistently visible in the main window. "
            "Keep first person plural, present tense, and the original intent. "
            + extra_instruction
            + "\n\n"
            f"Original beat: {beat.text}\n"
            f"Observed facts:\n"
            f"- Active tab: {observed.get('active_tab')}\n"
            f"- Visible table: {observed.get('visible_table')}\n"
            f"- Row range text: {observed.get('row_range_text')}\n"
            f"- Column headers: {', '.join(observed.get('column_headers', []) or [])}\n"
            f"- Summary: {observed.get('summary')}\n"
        )
        try:
            response = self.client.messages.create(
                model=MODEL,
                max_tokens=256,
                messages=[{"role": "user", "content": prompt}],
            )
            text_parts = [block.text for block in response.content if block.type == "text"]
            rewritten = "\n".join(text_parts).strip().strip('"')
            if rewritten:
                print(
                    f"  Adapted {beat.beat_id}: '{beat.text[:50]}...' -> '{rewritten[:50]}...'",
                    file=sys.stderr,
                )
                beat.text = rewritten
                beat.kind = target_kind  # type: ignore[assignment]
                # Drop the recorded clip for a converted state beat so the renderer
                # holds a clean still frame instead of footage of the dismissed artifact.
                beat.video_clip_path = None
        except Exception as exc:
            print(f"Warning: could not adapt {beat.beat_id}: {exc}", file=sys.stderr)

    @staticmethod
    def _observed_state_unchanged(
        prev: Dict[str, Any], curr: Dict[str, Any]
    ) -> bool:
        """Return True if the UI state did not visibly change between observations."""
        keys = ["active_tab", "visible_table", "row_range_text"]
        for key in keys:
            if prev.get(key) != curr.get(key):
                return False
        prev_headers = set(prev.get("column_headers") or [])
        curr_headers = set(curr.get("column_headers") or [])
        if prev_headers != curr_headers:
            return False
        return True

    @staticmethod
    def _beat_conflicts_with_observed_state(beat: ScriptBeat) -> bool:
        """Detect obvious mismatches between beat text and observed state."""
        observed = beat.observed_state
        if not observed:
            return False
        text = beat.text.lower()
        headers = [h.lower() for h in (observed.get("column_headers") or [])]
        visible_table = (observed.get("visible_table") or "").lower()

        # Mentioned table not visible?
        for table in ["customers", "orders"]:
            if table in text and visible_table and table != visible_table:
                return True

        # Mentioned column not in the observed headers?
        text_words = set(__import__("re").findall(r"\b[a-z_]+\b", text))
        for word in text_words:
            if len(word) <= 3:
                continue
            if word in {"table", "rows", "grid", "columns", "browse", "data", "status"}:
                continue
            if word not in headers and any(h in word or word in h for h in headers):
                # Partial match to an observed header is OK.
                continue
            # If the word looks like a column name (contains underscore) and isn't observed.
            if "_" in word and word not in headers:
                return True

        # Numbers in text that don't appear in row_range_text?
        row_range = observed.get("row_range_text") or ""
        try:
            text_numbers = {int(n) for n in _extract_numbers(beat.text)}
            observed_numbers = {int(n) for n in _extract_numbers(row_range)}
        except Exception:
            text_numbers = set()
            observed_numbers = set()
        # If beat states a count that isn't in the observed range text, flag it.
        for num in text_numbers:
            if num >= 10 and num not in observed_numbers:
                return True

        return False

    # ------------------------------------------------------------------
    # Graph construction
    # ------------------------------------------------------------------

    def build_graph(
        self,
        video: Any,
        beats: List[ScriptBeat],
        discovery_result: DiscoveryResult,
    ) -> ExecutionGraph:
        """
        Build an ExecutionGraph from the script beats and the discovery result.

        Demo beats become edges whose video_path is the recorded clip for that
        beat. Non-demo beats attach to the surrounding states.
        """
        if not discovery_result.success or not discovery_result.locked_state:
            raise ValueError("DiscoveryResult must be successful to build a graph.")

        graph_id = f"{video.video_id}_{uuid.uuid4().hex[:8]}"
        application = video.application
        output_dir = Path(discovery_result.locked_state.screenshot_path).parent

        demo_beats = [b for b in beats if b.kind == "demo"]
        if not demo_beats:
            raise ValueError("Cannot build graph: script has no demo beats.")

        # Build states from frame extracts of demo-beat clips.
        states: List[ScreenState] = []
        start_screenshot = self._extract_first_frame(
            demo_beats[0].video_clip_path, output_dir / f"{graph_id}_start.png"
        )
        start_state = ScreenState(
            state_id="state_000",
            screenshot_path=str(start_screenshot.resolve()),
            timestamp=0.0,
            application=application,  # type: ignore[arg-type]
            platform_snapshot={},
            visual_summary="Start state",
        )

        prev_state = start_state
        edges: List[ActionEdge] = []

        for i, beat in enumerate(demo_beats, start=1):
            if not beat.video_clip_path:
                raise ValueError(f"Demo beat {beat.beat_id} has no recorded clip.")

            end_screenshot = self._extract_last_frame(
                beat.video_clip_path, output_dir / f"{graph_id}_state_{i:03d}.png"
            )
            state_id = f"state_{i:03d}"
            state = ScreenState(
                state_id=state_id,
                screenshot_path=str(end_screenshot.resolve()),
                timestamp=0.0,
                application=application,  # type: ignore[arg-type]
                platform_snapshot={},
                visual_summary=f"After {beat.beat_id}",
            )
            states.append(state)

            action_type: Literal["click", "type", "select", "scroll", "hotkey", "wait", "api_seed"] = "click"
            payload: Optional[str] = None
            target: Dict[str, Any] = {}
            if beat.action:
                raw_type = beat.action.get("type")
                if raw_type == "execute_query":
                    action_type = "type"
                    payload = beat.action.get("query")
                    target = {"x": 0.5, "y": 0.45, "w": 700, "h": 300}
                elif raw_type == "type":
                    action_type = "type"
                    # Vision-agent beats store the text in ``detail``; older recipe
                    # beats store it in ``text``.  Support both.
                    payload = beat.action.get("detail") or beat.action.get("text")
                    target = beat.action.get("target", {})
                elif raw_type == "click":
                    action_type = "click"
                    target = beat.action.get("target", {})
                elif raw_type == "key":
                    action_type = "hotkey"
                    payload = beat.action.get("detail") or beat.action.get("text")
                elif raw_type == "sequence":
                    # A sequence edge represents a multi-step demo beat; the renderer
                    # uses the recorded clip, so the edge action is a generic click.
                    action_type = "click"
                elif raw_type == "wait":
                    action_type = "wait"
                else:
                    target = beat.action.get("target", {})

            # ActionEdge.target must be a dict; vision-agent strings are descriptive.
            if isinstance(target, str):
                target = {"description": target}
            elif not isinstance(target, dict):
                target = {}

            edges.append(
                ActionEdge(
                    edge_id=f"edge_{i:03d}",
                    from_state_id=prev_state.state_id,
                    to_state_id=state.state_id,
                    action_type=action_type,
                    target=target,
                    payload=payload,
                    expected_duration=2.0,
                    video_path=beat.video_clip_path,
                )
            )
            prev_state = state

        end_state = discovery_result.locked_state
        end_state.state_id = f"state_{len(states) + 1:03d}"

        # Connect the last demo state to the locked end state if they differ.
        if prev_state.state_id != end_state.state_id:
            edges.append(
                ActionEdge(
                    edge_id=f"edge_{len(edges) + 1:03d}",
                    from_state_id=prev_state.state_id,
                    to_state_id=end_state.state_id,
                    action_type="wait",
                    target={},
                    payload=None,
                    expected_duration=1.0,
                    video_path=None,
                )
            )

        narration_beats = self._overlay_beats(beats, start_state, states, end_state, edges)

        graph = ExecutionGraph(
            graph_id=graph_id,
            learning_objective=video.learning_objective,
            application=application,
            start_state=start_state,
            end_state=end_state,
            states=states,
            edges=edges,
            narration_beats=narration_beats,
            generation_cost_usd=round(
                sum(log.get("cost_usd", 0.0) for log in discovery_result.attempt_logs), 6
            ),
            reliability_score=discovery_result.reliability_score,
        )

        store = GraphStore()
        store.save(graph)
        return graph

    @staticmethod
    def _extract_first_frame(video_path: Optional[str], out_path: Path) -> Path:
        """Extract the first frame of a video clip to a PNG."""
        if not video_path or not Path(video_path).exists():
            return LessonBuilder._blank_image(out_path)
        try:
            subprocess.run(
                [
                    "ffmpeg", "-y", "-i", video_path,
                    "-ss", "0", "-vframes", "1",
                    "-pix_fmt", "rgb24", str(out_path),
                ],
                check=True, capture_output=True, timeout=60,
            )
            return out_path
        except Exception as exc:
            print(f"Warning: could not extract first frame from {video_path}: {exc}", file=sys.stderr)
            return LessonBuilder._blank_image(out_path)

    @staticmethod
    def _extract_last_frame(video_path: Optional[str], out_path: Path) -> Path:
        """Extract the last frame of a video clip to a PNG."""
        if not video_path or not Path(video_path).exists():
            return LessonBuilder._blank_image(out_path)
        try:
            subprocess.run(
                [
                    "ffmpeg", "-y", "-sseof", "-0.5", "-i", video_path,
                    "-vframes", "1", "-pix_fmt", "rgb24", str(out_path),
                ],
                check=True, capture_output=True, timeout=60,
            )
            return out_path
        except Exception as exc:
            print(f"Warning: could not extract last frame from {video_path}: {exc}", file=sys.stderr)
            return LessonBuilder._blank_image(out_path)

    @staticmethod
    def _blank_image(out_path: Path) -> Path:
        """Create a small black placeholder PNG."""
        try:
            from PIL import Image
            img = Image.new("RGB", (1280, 720), color=(0, 0, 0))
            img.save(out_path)
        except Exception:
            # Absolute fallback: write a 1x1 transparent PNG header.
            out_path.write_bytes(
                b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x02\x00\x00\x00\x90wS\xde\x00\x00\x00\x0cIDATx\x9cc\xf8\x0f\x00\x00\x01\x01\x00\x05\x18\xd8N\x00\x00\x00\x00IEND\xaeB`\x82"
            )
        return out_path

    @staticmethod
    def _overlay_beats(
        beats: List[ScriptBeat],
        start_state: ScreenState,
        intermediate_states: List[ScreenState],
        end_state: ScreenState,
        edges: List[ActionEdge],
    ) -> List[NarrationBeat]:
        """
        Map script beats to graph states and edges.

        Demo beats consume edges in order. Non-demo state beats attach to the
        current state; multiple consecutive state beats can share a state.
        """
        states = [start_state] + intermediate_states + [end_state]
        edge_idx = 0
        state_idx = 0
        narration_beats: List[NarrationBeat] = []

        for beat in beats:
            if beat.kind == "demo":
                if edge_idx >= len(edges):
                    beat.attaches_to = "state"
                    beat.target_id = end_state.state_id
                    state_idx = len(states) - 1
                else:
                    beat.attaches_to = "edge"
                    beat.target_id = edges[edge_idx].edge_id
                    to_id = edges[edge_idx].to_state_id
                    edge_idx += 1
                    for i, s in enumerate(states):
                        if s.state_id == to_id:
                            state_idx = i
                            break
            else:
                beat.attaches_to = "state"
                beat.target_id = states[min(state_idx, len(states) - 1)].state_id

            narration_beats.append(
                NarrationBeat(
                    beat_id=beat.beat_id,
                    attaches_to=beat.attaches_to,  # type: ignore[arg-type]
                    target_id=beat.target_id or "",
                    text=beat.text,
                    word_count=len(beat.text.split()),
                    start_time=0.0,
                    end_time=0.0,
                    observed_state=beat.observed_state,
                )
            )

        return narration_beats