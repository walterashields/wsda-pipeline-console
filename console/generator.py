"""
LLM-based lesson_script.yml generation -- the riskiest, most novel piece of
this console (explicit user call, 2026-08-15: "real LLM auto-generation...
this is also the riskiest piece: nothing like it exists yet, and this
session's own history shows real lesson-authoring took live UI
exploration, not just prompting"). Grounded as tightly as this project's
own accumulated knowledge allows:

  - LESSON_CONTENT_STANDARD.md, read live, in full, not summarized
  - the driver's real event/action/locator vocabulary
    (automation/metabase_driver.py) -- hand-transcribed here rather than
    pasting the whole module, but checked against it directly, not
    remembered/guessed, since a wrong verb or locator kind produces a
    script that simply won't run
  - the requires_state schema (automation/state_seed.py)
  - two of the three proven scripts (video_1_1: the simplest end-to-end
    shape; video_1_3: multi-video state chaining + a chart question) as
    few-shot grounding
  - the live Metabase schema, fetched fresh (console/metabase_schema.py)
  - what earlier videos in the same project actually produce, read from
    their own scripts (console/state_chain.py), not hand-redescribed

Generated output is a DRAFT for human review in the console's editor, not
something committed straight to a render -- this module does not trigger
recording. Real UI selectors (exact button text, test-ids) are the part
most likely to be wrong in a first draft, since the model has no way to
verify them against the live DOM the way every hand-authored script on
this project was checked; the review step exists specifically to catch
that before a render is attempted.
"""

import os
import re

import anthropic

from console import metabase_schema, state_chain
from console.paths import EXAMPLE_SCRIPTS, LESSON_CONTENT_STANDARD

MODEL = os.environ.get("CONSOLE_MODEL", "claude-sonnet-5")

ACTION_VOCABULARY = """
Event types the driver (automation/metabase_driver.py) actually
implements -- use ONLY these `type` values, nothing invented:

  narrate            -- pure narration beat, no click, no highlight.
  pause              -- {duration: <seconds, float>}. Narration audio for
                         the PRECEDING narrated event plays during this
                         pause, never before it, so every narrate/
                         highlight_target(s) event must be immediately
                         followed by its own pause event.
  highlight_target    -- {locator: {...}, narration?, pre_actions?,
                          lead_ms?}. Locates one element, draws an overlay,
                          does NOT click. Held up through the pause that
                          follows, cleared by the commit event after that.
  highlight_targets    -- plural: {locators: [{...}, ...], narration?,
                          pre_actions?, lead_ms?}. Highlights several
                          elements at once, for narration naming more than
                          one thing in the same breath.
  highlight_section     -- {selector_text: "...", narration}. Same overlay
                          mechanism, for "why this matters" narration over
                          something already on screen, no click involved.
                          Must be followed by a clear_highlight event
                          (there is no commit action to piggyback the
                          clear onto).
  clear_highlight        -- removes any current overlay(s). No fields.
  click_new_question       -- clicks New > Question in the app bar. Use
                          right after a highlight_target on
                          {"kind": "app_bar_button", "name": "New"}.
  select_database           -- {database: "<name>"}. Silent/administrative
                          by convention (per LESSON_CONTENT_STANDARD.md,
                          picking which database is not a teaching
                          moment) -- no highlight_target needed before it.
  select_table                -- {table: "<name>"}. Commit for a preceding
                          highlight_target on {"kind": "text", "value":
                          "<table name>"}.
  add_filter                    -- commit for a filter opened/filled via a
                          preceding highlight_target(s)'s pre_actions (see
                          pre_actions below) -- this event only clicks the
                          final "Add filter" submit button, it does not
                          open the picker or type values itself.
  click_option                   -- {locator: {...}}. Generic single-click
                          commit: clicks the SAME locator a preceding
                          highlight_target already pointed at, to finalize
                          a selection from an already-open picker (e.g.
                          Summarize's function/column lists, a chart-type
                          picker, a "Done" button on a filter-mapping
                          panel). Use this for any commit that isn't one
                          of the other named actions below.
  visualize                       -- clicks "Visualize". Silent/
                          administrative by convention.
  show_result                      -- closing narration beat, no click.
  save_question                     -- {question_name: "<name>"}. Must be
                          preceded by a highlight_target on
                          {"kind": "test_id", "value": "qb-save-button"}.
                          This is a first-time-concept step the FIRST time
                          it appears in a project -- set
                          lead_ms: 3000 / post_hold_ms: 3000 on its
                          highlight_target/commit pair the first time a
                          project ever saves a question; default pacing is
                          fine on a later video that already taught this.
  add_to_dashboard                   -- {dashboard_name: "<name>"}. Must
                          be preceded by a highlight_target. Same
                          first-time-concept pacing rule as save_question.
                          Handles three real UI branches automatically
                          (named target already exists / "New dashboard" /
                          already auto-merged) -- the script only needs to
                          name the dashboard, not branch on which case
                          applies.
  open_saved_item                     -- {name: "<question or dashboard
                          name>"}. Opens an existing saved item via
                          search+Enter. Use this (not click_new_question)
                          when a video's first real step is continuing
                          work on something requires_state already seeded,
                          rather than building something new. Silent/
                          administrative by convention, same as
                          select_database.

Locator kinds (`locator: {"kind": ..., "value": ...}` unless noted):
  app_bar_button   -- {"kind": "app_bar_button", "name": "New"}
  text             -- exact visible text anywhere on the page. Accepts an
                      optional "index" (0-based) when the exact same text
                      legitimately appears more than once on screen at
                      once (e.g. the same field name mapped on two cards).
  test_id          -- Metabase's data-testid attribute. Known stable ids:
                      "qb-save-button" (the Save button in the query
                      editor), "save-question-button" (Save inside the
                      save dialog -- handled internally by save_question,
                      don't reference directly).
  placeholder      -- an input's placeholder text, e.g. "Min", "Max".
  button           -- {"kind": "button", "value": "Done"}, role=button
                      with that exact accessible name.
  label            -- aria-label match, for icon-only controls with no
                      visible text (e.g. a pencil/edit icon, "Search").

pre_actions (on highlight_target/highlight_targets only): a list of small
setup steps run BEFORE the highlight is drawn, so data that doesn't exist
on screen until some interaction happens (a filter's typed min/max, a
picker's opened options) is already visible and highlighted during its
own narrated pause, per LESSON_CONTENT_STANDARD.md's data-capture rule.
Each step is either:
  {"click": {"kind": ..., "value": ...}, "wait_ms": 400}
  {"fill": {"kind": ..., "value": ...}, "text": "50", "wait_ms": 200}

Pacing: `lead_ms` (on highlight_target/highlight_targets/highlight_section)
overrides the default 1500ms hold before the pause starts. `post_hold_ms`
(on any commit action) overrides the default 700ms hold after the click.
Use 3000 for both on a step introducing a brand-new concept for the FIRST
time in a project (per LESSON_CONTENT_STANDARD.md's first-time-concept
corollary) -- do not mark a repeated action type as concept-intro just
because it's early in this particular video.

Pause duration formula (seconds), matching every existing script:
  duration = (word_count_of_preceding_narration / 145) * 60 + buffer
  buffer = 8.0 for a long/reasoning-heavy narration line (outcome
           statements, first-time-concept explanations, closing beats),
           2.0 for a short one-sentence action line.
A silent (unnarrated) action's pause is a fixed 1.0s settle time.

HARD CONSTRAINT, more important than the formula above: narration/qa.py
enforces a real per-format maximum pause duration and will not extend a
pause past it (confirmed live, 2026-08-15 -- a script whose narration
doesn't fit even after this cap is hit does not converge no matter how
many times it's auto-fixed and re-recorded; the narration itself has to
be shorter, not the pause longer). The exact cap for THIS video's format
is given in the user prompt as `max_pause_s` -- every single narration
line's word count must produce a pause, by the formula above, that stays
UNDER that cap, with real margin (aim for at most ~70% of the cap so
edge-tts's real synthesized clip length, which runs slightly longer than
the word-count estimate, still fits). This is the single most common way
a first-draft generated script fails in practice -- treat it as a hard
per-line budget, not a rough guideline.
"""

REQUIRES_STATE_SCHEMA = """
requires_state (top-level key, list, OMIT entirely if this video needs no
prior state -- e.g. it's the first video in a project): declares state
this video depends on, seeded via Metabase's real API before recording
starts, NOT by assuming a prior video actually ran. Each entry:

  - type: "question"
    name: "<exact name, must match what an earlier video's save_question
            produces, or what you're about to build fresh in this
            video if type is not depended on>"
    database: "<database name, e.g. Sample Database>"
    table: "<table name>"
    display: "table" | "bar" | ...
    filter:                      # optional, "between" is the only
      field: "<field name>"      # operator implemented
      operator: "between"
      min: <number>
      max: <number>
    aggregation:                 # optional, "sum" is the only function
      function: "sum"            # implemented
      field: "<field name>"
    breakout:                    # optional
      field: "<field name>"
      granularity: "month" | "day" | "year" | ...

  - type: "dashboard"
    name: "<exact name>"
    contains: ["<question name>", ...]   # every question that must
                                          # already be pinned to it

Field names in requires_state use the human-readable form shown in
Metabase's UI (e.g. "Created At"), not the raw column name (CREATED_AT)
-- the seeding code normalizes this itself.
"""


def _read_examples() -> str:
    blocks = []
    for path in EXAMPLE_SCRIPTS:
        if path.exists():
            blocks.append(f"--- EXAMPLE: {path.parent.name}/lesson_script.yml ---\n{path.read_text()}")
    return "\n\n".join(blocks)


def _build_system_prompt() -> str:
    standard = LESSON_CONTENT_STANDARD.read_text()
    schema = metabase_schema.fetch_schema_summary()
    examples = _read_examples()

    return f"""You write lesson_script.yml files for a Metabase instructional
video pipeline. These are consumed literally by a Playwright driver
(automation/metabase_driver.py) that records a real browser session
against a real Metabase instance -- your output must be valid,
runnable YAML matching the exact schema below, not a description or an
approximation of one.

=== CONTENT STANDARD (every rule is a hard requirement) ===
{standard}

=== EVENT/ACTION/LOCATOR VOCABULARY ===
{ACTION_VOCABULARY}

=== requires_state SCHEMA ===
{REQUIRES_STATE_SCHEMA}

=== LIVE METABASE SCHEMA (query against this, not a guessed schema) ===
{schema}

=== PROVEN WORKED EXAMPLES ===
{examples}

=== OUTPUT FORMAT ===
Output ONLY the lesson_script.yml content -- valid YAML, starting with
`lesson_id:`. No markdown code fences, no commentary before or after.
Include a header comment block (like the examples) briefly explaining
the workflow chosen and why, and (if requires_state is present) which
earlier video's output it depends on and why.

Be honest in what you generate: exact on-screen button text and
test-ids you cannot verify against the live DOM are the likeliest thing
to be wrong in a first draft. Prefer locator kinds and exact strings
used in the worked examples above wherever the workflow is similar
enough to reuse them; where it genuinely isn't (e.g. a new picker/dialog
neither example exercises), still write your best real guess at the
actual visible text Metabase would show, not a placeholder -- this
script will be reviewed and, if needed, corrected against the live app
before it's ever rendered, not run blind.
"""


def _prior_context(project) -> str:
    chain = state_chain.project_dependency_chain(project)
    if not chain or all(not c["produces"] for c in chain):
        return "This is the first video in this project. No prior state exists."

    lines = ["Earlier videos in this project and what they produce (available for this video to depend on via requires_state):"]
    for c in chain:
        if c["produces"]:
            produced_desc = "; ".join(
                f"{p['type']} {p['name']!r}" + (f" (contains: {p['contains']})" if p.get("contains") else "")
                for p in c["produces"]
            )
            lines.append(f"  - {c['video_id']}: produces {produced_desc}")
    return "\n".join(lines)


def _build_user_prompt(project, video_id: str, tier, workflow_hint: str) -> str:
    order = next(v["order"] for v in project.videos if v["video_id"] == video_id)
    total = len(project.videos)

    # word_count/145*60 <= max_pause_s*0.85 margin, essentially no room for
    # the 2.0-8.0s buffer convention at a tight cap -- floored rather than
    # left to go arbitrarily small, since a handful of words can still be
    # a real, if terse, sentence, but the formula alone would suggest an
    # unusably tiny number for the tightest tier (micro, 2.5s: ~5 words).
    max_words_per_line = max(8, int(tier.max_pause_s * 0.85 * 145 / 60))
    tight_cap = tier.max_pause_s < 5.0

    return f"""Generate lesson_script.yml for video {order} of {total} in a
project on the topic: "{project.topic}".

Format tier: {tier.label} ({tier.video_count_label}). Recap style for
this tier: {tier.recap_style}. {tier.description}

This tier's real pause cap (max_pause_s) is {tier.max_pause_s}s -- per the
HARD CONSTRAINT above, no single narration line should need more than
roughly {max_words_per_line} words to stay safely under that cap (the
2.0s/8.0s buffer convention doesn't fit inside a cap this tight -- use
little to no buffer instead of chasing that formula literally). If the
topic genuinely needs more explanation than that per beat, split it
across more events/pauses rather than writing one long narration line.
{"This cap is tight enough that the right response is FEWER narrated events with short, real sentences, not many events each awkwardly truncated -- prefer 3-5 total narrated beats over the ~8-10 a lesson-format script would use, and let more steps stay silent/administrative (per the content standard's own carve-out for genuinely non-teaching clicks) rather than forcing reasoning into a line that can't fit it." if tight_cap else ""}
Set the top-level `format: "{tier.pipeline_format}"` field in the output
YAML -- this is what narration/qa.py actually reads to know which cap
applies; omitting it silently defaults to a different, looser cap that
does not match this tier.

This video's position: {order} of {total} in the sequence.
{"This is the FIRST video -- no requires_state, no recap of a prior video." if order == 1 else "This is NOT the first video -- its opening narration should recap what's genuinely true from earlier videos in this project (see LESSON_CONTENT_STANDARD.md's chapter-opener vs. within-chapter recap textures), and its requires_state should declare whatever real prior state this video's workflow actually needs, using the exact names produced below."}

{_prior_context(project)}

Workflow guidance from the author: {workflow_hint or "(none given -- use your judgment for a natural, scenario-grounded next step given the topic and this video's position in the sequence)"}

lesson_id must be "{project.slug.replace('-', '_')}_{video_id}".
course must be "{project.slug}".
target must match every existing script's target block exactly:
  base_url: "http://localhost:3000"
  admin_email: "admin@wsda.local"
  admin_password: "WsdaDemo123!"
  admin_first_name: "WSDA"
  admin_last_name: "Admin"
  site_name: "WSDA Metabase Demo"
"""


def generate_lesson_script(project, video_id: str, workflow_hint: str = "") -> str:
    if not os.environ.get("ANTHROPIC_API_KEY"):
        raise RuntimeError(
            "ANTHROPIC_API_KEY is not set. Script generation calls the "
            "Anthropic API directly (this console is not running inside "
            "Claude Code) -- set it in the environment and retry."
        )

    from console import format_tiers
    tier = format_tiers.get(project.format_tier)

    client = anthropic.Anthropic()
    system_prompt = _build_system_prompt()
    user_prompt = _build_user_prompt(project, video_id, tier, workflow_hint)

    # Extended thinking is on by default for this model and, left
    # unbounded, consumed nearly the entire max_tokens budget on its own
    # (confirmed live: 7893 of 8000 output tokens went to thinking, the
    # actual YAML got cut off mid-file at 291 characters). Disabled
    # explicitly -- this is a constrained-format generation task, not one
    # that benefits from visible reasoning, and thinking competing with
    # the actual output for the same token budget is a real failure mode
    # here, not a hypothetical one.
    response = client.messages.create(
        model=MODEL,
        max_tokens=12000,
        thinking={"type": "disabled"},
        system=system_prompt,
        messages=[{"role": "user", "content": user_prompt}],
    )
    text = "".join(block.text for block in response.content if block.type == "text")

    # Strip a markdown fence if the model added one despite instructions,
    # rather than failing generation over a cosmetic formatting slip.
    fenced = re.match(r"^```(?:ya?ml)?\s*\n(.*)\n```\s*$", text.strip(), re.DOTALL)
    if fenced:
        text = fenced.group(1)

    script_path = project.script_path(video_id)
    script_path.parent.mkdir(parents=True, exist_ok=True)
    script_path.write_text(text)
    return text
