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
import yaml

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

ATOMIC ACTION DISCIPLINE (added 2026-08-17, real quality gap found by
comparing generated scripts against the proven examples line by line):
video_1_1 and video_1_3 above are not just style references, they are
structural templates for GRANULARITY. Every real generated script
checked against them showed the same three concrete defects -- fix
these directly, don't just aim for a vague sense of "tighter":

  1. Narration-only beats with nothing new to look at. A generated
     script inserted a second scene-setting `narrate` event
     ("That's a SQL question underneath: which rows match a
     condition...") floating with no highlight, no action, nothing on
     screen changing -- pure abstract commentary. If a sentence doesn't
     accompany something new and concrete appearing/changing on screen,
     it doesn't get its own event -- fold it into the adjacent real
     beat or cut it. See the HARD RULE below: this defect specifically
     recurred even after a first attempt at instructing against it, so
     it now has its own non-negotiable, mechanically-checkable limit,
     not just guidance to weigh against other considerations.
  2. Redundant restatement. A generated script highlighted the same
     filter logic twice (once as "why BETWEEN matters", again later as
     "every row here really does fall in that range") with no new
     information or action between them -- two events making
     essentially the same point. Every narrated beat must say something
     the learner doesn't already know from the beat before it. If two
     beats would say the same thing, there's only one beat, not two.
  3. Narration not tightly bound to the one action it accompanies.
     Compare "Here are the actual matching rows. Total shows each
     order's amount, User ID shows who placed it." (two columns named,
     matches highlight_targets highlighting both -- correct, this is
     what the plural event exists for) against a beat that explains a
     concept in general terms disconnected from the specific click that
     follows it. Every highlight/commit pair's narration explains
     THAT SPECIFIC ACTION -- what's being clicked/typed and why THIS
     ONE STEP matters -- not a broader lesson wrapped around it.

HARD RULE, mechanically checkable, not a soft preference (added
2026-08-17 after a first, softer version of this instruction still let
a generated script split its opening across two `narrate` events
despite being told not to -- this version is the fix for that specific
failure, not a restatement of it): **before finalizing your event list,
count the `narrate`-type events that appear before the first non-
narrate event. That count must be exactly 1.** Likewise, count the
narration-only events at the very end of the script (after the last
commit action, typically the `show_result` beat) -- that count must
also be exactly 1. If your draft has 2 or more consecutive narrate
events at the start or end, that is a failure of this rule, full stop
-- go back and MERGE them into a single narrate event before writing
anything else, even if the merged line runs a little longer (it still
must obey the pause-cap word budget below; trim content rather than
split it into a second event). This applies ONLY to the pure `narrate`
type (no highlight, no click) -- it does NOT limit how many real
highlight/commit action pairs the lesson has in between; those are
exactly as numerous as the real action sequence from Step A requires.

This rule is NOT only about the very start/end of the script (extended
2026-08-17 after the scaled test found the same defect recurring mid-
script): a real generation inserted an extra `narrate` beat BETWEEN a
highlight_target's own pause and its own commit action (highlight ->
pause -> narrate -> pause -> commit) -- structurally the identical
defect, just not at the edges. The actual, general invariant: every
`highlight_target`/`highlight_targets` event's pause must be followed
IMMEDIATELY by that same beat's own commit action (click_new_question,
select_table, add_filter, click_option, save_question,
add_to_dashboard) -- or by `clear_highlight` for an explanatory-only
highlight with no click (the same pattern highlight_section uses).
NOTHING else -- no extra narrate beat, no second highlight -- may sit
between a highlight's pause and its own resolution. If you find
yourself wanting to add a sentence there, it belongs IN that beat's own
narration, not as a new event.

Also, a highlight_target/highlight_targets event must always actually
GET a resolution: if you draw a highlight, either click something as a
result (a real commit event, immediately after its pause) or clear it
as a pure explanation (clear_highlight, immediately after its pause).
A generated script drew a highlight for "New dashboard" AFTER
add_to_dashboard had already run and completed its own entire flow
internally (per that action's own description above -- it handles
naming/creating/selecting the dashboard by itself, it does not need or
expect a separate highlight+click for that step) -- an orphaned
highlight with nothing real to resolve it, narrating a decision that
was already made and finished a step earlier. Before finalizing, check
every highlight_target/highlight_targets event has exactly one real
resolution immediately after its pause, not zero and not a stray extra
one for a step an action already handles internally.

Work in this ORDER, not narration-first-then-fit-actions-after:
  Step A. Decompose the requested workflow into the smallest real
          sequence of actions available in the vocabulary above that
          accomplishes it -- list them conceptually before writing any
          narration. One real UI action (one commit event, or one
          purely-explanatory highlight_section) per step.
  Step B. For each action, write exactly one short, specific narration
          line that explains THAT action and nothing else -- the way
          turn-by-turn directions work: this click, this reason, then
          the next one. Never combine two steps' worth of explanation
          into one line, and never add a narration beat that isn't
          anchored to something concrete on screen.
  Step C. If the workflow genuinely needs a UI action with no matching
          entry in the vocabulary above, do not paper over the gap with
          vague narration or a stretched use of click_option to fake
          something the driver doesn't actually implement. Say so
          plainly in the header comment (e.g. "this workflow would
          benefit from an X action the driver doesn't have yet; used Y
          instead / scoped the lesson to avoid needing it") so the gap
          is visible to the human reviewer, not silently hidden.

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

VALIDATIONS_SCHEMA = """
validations (top-level key, list, REQUIRED whenever this video's workflow
filters, aggregates, or otherwise produces a specific data result that
the narration then describes -- added 2026-08-16, CRITICAL fix pass):

This is a hard gate, not optional metadata. A real defect shipped
because a generated script filtered Orders.Total to a range (500-5000)
that returns ZERO rows against live data, and the narration described
the (empty) result as if it were showing real orders -- the recording
played out a false claim in Walter's own teaching voice over a blank
table. console/validator.py runs every entry below against Metabase's
real /api/dataset endpoint BEFORE a render is ever offered, and blocks
the script if any of them fail. A data-producing step with no matching
validations entry is not assumed safe -- it's flagged to the human
reviewer as literally unchecked. So: every filter/aggregation this
script performs must have a corresponding entry here, describing the
SAME query in structured form (reusing requires_state's filter/
aggregation/breakout shape) so it can actually be run and checked, not
just narrated.

  - event_id: "<the commit event id this validates, e.g. the add_filter
              or click_option event that finalizes the filter/summarize
              step>"
    query:
      database: "<database name>"
      table: "<table name>"
      filter:                        # optional, same shape as requires_state
        field: "<field name>"
        operator: "between"
        min: <number>
        max: <number>
      aggregation:                   # optional
        function: "sum" | "count"
        field: "<field name, omit for count>"
      breakout:                      # optional
        field: "<field name>"
        granularity: "month" | ...
    expect:
      min_rows: 1                    # default 1 if omitted -- raise this
                                      # if the narration specifically
                                      # claims a larger, specific count

console/validator.py ALSO checks requires_state's own filter/aggregation
specs the same way, not just this section's entries -- found live that a
regenerated video declared requires_state depending on an earlier
video's saved question using a stale, already-disproven filter range,
inconsistent with what that earlier video's own (corrected) script
actually uses now. If this video's requires_state names a question this
project's own earlier video produces, use that earlier video's ACTUAL
current filter/aggregation values (given above in "Earlier videos... and
what they produce" is a name/type summary, not the values -- if in
doubt, keep this video's own workflow independent of the exact prior
filter values rather than guessing or drifting from them).

Ground every filter/aggregation value against the REAL per-field ranges
given in the live schema below (e.g. "real range: 8.94 to 159.35") --
choosing a plausible-sounding round number (500, 5000, 1000000) with no
relationship to those real numbers is exactly how the live defect above
happened. A "high value" or "needs review" framing has to be a real
subset of the actual data, not just a bigger-sounding number.
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

PRIORITY OF GROUNDING SOURCES, HIGHEST FIRST -- when anything below
seems to pull in different directions, this order decides it:
  1. LESSON_CONTENT_STANDARD.md (below) and the proven worked examples
     (video_1_1, video_1_3, further down) -- Walter's own proven voice,
     structure, and granularity. This is the dominant source for HOW
     every beat is written and paced, not one input among several.
  2. The live Metabase schema (below) -- real data, non-negotiable for
     any filter/aggregation value, per the validations section.
  3. General instructional-writing instinct -- only fills gaps the two
     sources above don't cover (e.g. how to phrase a brand-new UI
     picker neither example exercises). Never overrides rule 1's
     granularity/voice, and never a reason to add a beat, a hedge, or a
     restatement rule 1 wouldn't include.

=== CONTENT STANDARD (every rule is a hard requirement) ===
{standard}

=== EVENT/ACTION/LOCATOR VOCABULARY ===
{ACTION_VOCABULARY}

=== requires_state SCHEMA ===
{REQUIRES_STATE_SCHEMA}

=== validations SCHEMA (hard gate, read this carefully) ===
{VALIDATIONS_SCHEMA}

=== LIVE METABASE SCHEMA (query against this, not a guessed schema; use
the real per-field ranges shown for every filter/aggregation value you
choose) ===
{schema}

=== PROVEN WORKED EXAMPLES -- STRUCTURE AND MECHANICS ONLY ===
Read these for event sequencing, locator kinds, pre_actions patterns,
pause-duration formula, and first-time-concept pacing -- NOT for their
scenario. Confirmed live (2026-08-16) that copying too closely here is a
real failure mode, not a hypothetical one: a generated "SQL (general)"
lesson reused this exact table (Orders), this exact filter field
(Total), and a barely-reskinned version of the same "flag orders for
review" framing and saved-question name, instead of generating content
actually appropriate to its own topic. Do NOT reuse:
  - the specific scenario (manager/support wanting a filtered list)
  - the specific table chosen (Orders), unless THIS topic genuinely
    calls for it -- Sample Database also has ACCOUNTS, FEEDBACK,
    INVOICES, PEOPLE, PRODUCTS, REVIEWS; pick whichever one the actual
    topic and workflow guidance below point to
  - the specific field/filter range or aggregation these examples use
  - the specific saved-question/dashboard names
Do reuse the mechanical shape: highlight-then-commit event pairs,
pre_actions revealing typed values before they're narrated, the pause
formula, requires_state chaining between videos, and how first-time
concepts get longer holds. The test of a good generation here is: could
someone tell this was written FROM these examples, not just a copy OF
one of them, retargeted at a different topic with its own real data
grounding.
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


def _build_user_prompt(project, video_id: str, tier, workflow_hint: str, feedback: str = "") -> str:
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

{f'''=== FEEDBACK ON A PRIOR ATTEMPT -- ADDRESS THIS DIRECTLY, NOT OPTIONAL ===
{feedback}
This is either a human reviewer's note on a flagged render, or a
pre-render validation failure from the LAST attempt at this exact video.
Either way, the regenerated script below must demonstrably address it --
a regeneration that repeats the same mistake (e.g. the same out-of-range
filter, the same unaddressed complaint) is itself a failure of this
step, confirmed as a real defect on this project (a flagged note about a
broken filter range produced the identical broken filter range on
regeneration, because the note was never actually passed into the
prompt before this fix). If the feedback names a specific wrong value,
use the real per-field ranges in the live schema above to pick a
genuinely correct one, don't just adjust it slightly.
''' if feedback else ""}

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


MAX_GENERATION_ATTEMPTS = 2  # one shot plus one feedback-informed retry


def _call_model(system_prompt: str, user_prompt: str) -> str:
    client = anthropic.Anthropic()
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

    # Strip a markdown fence if the model added one despite instructions
    # not to -- confirmed live (2026-08-16) this isn't hypothetical: one
    # generation prepended a full paragraph of reasoning before a ```yaml
    # fence, which an earlier version of this regex (anchored to require
    # the ENTIRE response to be just the fence, nothing before it) didn't
    # match at all, so the literal prose-plus-fence-markers text got
    # written to disk as "the script" -- invalid YAML that broke the
    # validation gate itself (a real, load-bearing consequence, not a
    # cosmetic one: script_path.read_text() -> yaml.safe_load() raised
    # immediately). Fixed by searching for a fenced block ANYWHERE in the
    # response and extracting just its contents, rather than requiring
    # the fence to be the whole response.
    fenced = re.search(r"```(?:ya?ml)?\s*\n(.*?)\n```", text, re.DOTALL)
    if fenced:
        text = fenced.group(1)
    return text.strip() + "\n"


COMMIT_TYPES = {"click_new_question", "select_table", "add_filter", "click_option",
                 "save_question", "add_to_dashboard"}


def _highlight_resolution_violations(card_events: list) -> list:
    """Deterministic structural backstop (added 2026-08-17), same
    priority and same pattern as _missing_validations_coverage: a prompt
    instruction alone ("nothing may sit between a highlight's pause and
    its commit") isn't something to just trust the model on every time,
    any more than the validations requirement was. automation/
    metabase_driver.py's own documented behavior establishes ONE
    invariant every highlight_target/highlight_targets event must
    satisfy: its own pause is immediately followed by EITHER its
    matching commit action (COMMIT_TYPES) or clear_highlight (the
    explanatory-only pattern, same as highlight_section). Both real
    defects the scaled test found are this SAME invariant broken two
    different ways, not two separate bugs: (1) an extra narrate+pause
    beat inserted between a highlight's pause and its own commit (the
    commit is still there, just displaced), and (2) a highlight with NO
    commit anywhere after it at all (add_to_dashboard already resolves
    its own dashboard-naming step internally; a script highlighted
    "New dashboard" again afterward with nothing left to click). Both
    silently produce narration describing an action that either fires
    somewhere other than where it's being described, or never fires --
    the same class of "not what's actually on screen" defect the data-
    validation gate exists to catch, just for actions instead of
    numbers. highlight_section is intentionally excluded: that type is
    documented as always resolved by clear_highlight, a different,
    already-correct pattern."""
    violations = []
    for i, event in enumerate(card_events):
        if event.get("type") not in ("highlight_target", "highlight_targets"):
            continue
        eid = event.get("id")
        nxt = card_events[i + 1] if i + 1 < len(card_events) else None
        if not nxt or nxt.get("type") != "pause":
            violations.append(f"{eid}: not immediately followed by its own pause")
            continue
        nxt2 = card_events[i + 2] if i + 2 < len(card_events) else None
        found = nxt2.get("type") if nxt2 else "(end of script)"
        is_valid_resolution = found in COMMIT_TYPES or found == "clear_highlight"
        if not nxt2 or not is_valid_resolution:
            violations.append(
                f"{eid}: its pause is not immediately followed by a matching commit action or "
                f"clear_highlight (found {found!r} instead) -- either something was inserted "
                f"between the highlight and its resolution, or this highlight has no resolution at all"
            )
    return violations


def _filter_fill_event_ids(card_events: list) -> list:
    """Returns the commit event_ids that submit a typed min/max filter --
    the one reliable, consistently-used structural marker every real
    filter step in this project's scripts shares (a highlight event's
    pre_actions filling placeholders literally named "Min"/"Max",
    followed by the commit event that submits them). Deliberately
    narrow, not a claim of total coverage: this does not detect a fresh
    Summarize/aggregation performed within a video's own events (no
    fill steps involved there, no comparably reliable marker found yet)
    -- it closes the specific, real gap that actually shipped (a typed
    Total-between-X-and-Y filter with no matching validations entry),
    not every theoretical one."""
    flagged = []
    for i, event in enumerate(card_events):
        pre_actions = event.get("pre_actions") or []
        has_min_max_fill = any(
            "fill" in step and step["fill"].get("value") in ("Min", "Max")
            for step in pre_actions
        )
        if not has_min_max_fill:
            continue
        # The commit event is NOT the very next event -- every script in
        # this project follows highlight_target(s) -> pause -> commit
        # (the pause is what carries the narration audio), confirmed
        # live: an earlier version of this function assumed i+1 was the
        # commit and flagged the PAUSE event's id instead every single
        # time, on real generated output, not a hypothetical. Skip over
        # pause events (and any clear_highlight) to find the real commit.
        for j in range(i + 1, len(card_events)):
            if card_events[j].get("type") not in ("pause", "clear_highlight"):
                flagged.append(card_events[j].get("id"))
                break
    return flagged


def _missing_validations_coverage(text: str) -> list:
    """Deterministic structural backstop (added 2026-08-17), not a second
    place to hope the model remembers: confirmed live that the prompt's
    "validations is REQUIRED whenever this video filters" instruction
    doesn't hold 100% of the time on its own -- root-caused to the
    proven worked examples (video_1_1, video_1_3) predating the
    validation-gate fix pass and not having a validations block
    themselves, directly undermining the instruction once those
    examples were elevated to "dominant grounding source" (fixed
    separately, in wsda-video-engine, by adding video_1_1's real
    validations block -- but this check exists so the pipeline doesn't
    depend on that alone holding either). Returns event_ids of filter
    steps with no matching validations entry."""
    try:
        card = yaml.safe_load(text) or {}
    except yaml.YAMLError:
        return []
    filter_ids = set(_filter_fill_event_ids(card.get("events", [])))
    validated_ids = {v.get("event_id") for v in (card.get("validations") or [])}
    return sorted(filter_ids - validated_ids)


def _validation_feedback(result: dict) -> str:
    lines = ["The pre-render validation gate ran your last attempt's declared "
             "validations against LIVE Metabase data and found real problems:"]
    for c in result["checks"]:
        if c["status"] != "pass":
            lines.append(f"  - event {c['event_id']}: {c['detail']} (query: {c['query']})")
    lines.append("Fix these specific steps using real data ranges from the live schema below "
                  "-- do not just narrow the same wrong range slightly, pick values that actually "
                  "produce the described result against real data.")
    return "\n".join(lines)


def generate_lesson_script(project, video_id: str, workflow_hint: str = "", feedback: str = "") -> dict:
    """Returns {"text": str, "validation": {...}, "attempts": int}. The
    pre-render validation gate (console/validator.py) runs automatically
    as part of this call, per the 2026-08-16 CRITICAL fix pass -- a
    script whose declared validations fail against live data gets ONE
    automatic regeneration attempt with the specific failure fed back
    into the prompt, not silently returned as if it were fine. Callers
    (app.py) must check result["validation"]["passed"] before treating a
    generated script as ready for review/render -- this function does not
    raise on a validation failure after retries, since "generated but
    flagged as unvalidated" is a real, useful state for the reviewer to
    see, not an exceptional one."""
    if not os.environ.get("ANTHROPIC_API_KEY"):
        raise RuntimeError(
            "ANTHROPIC_API_KEY is not set. Script generation calls the "
            "Anthropic API directly (this console is not running inside "
            "Claude Code) -- set it in the environment and retry."
        )

    from console import format_tiers, validator
    tier = format_tiers.get(project.format_tier)
    system_prompt = _build_system_prompt()
    script_path = project.script_path(video_id)
    script_path.parent.mkdir(parents=True, exist_ok=True)

    current_feedback = feedback
    text = ""
    validation = {"passed": False, "status": "unchecked", "checks": []}

    for attempt in range(1, MAX_GENERATION_ATTEMPTS + 1):
        user_prompt = _build_user_prompt(project, video_id, tier, workflow_hint, current_feedback)
        text = _call_model(system_prompt, user_prompt)

        # Confirmed live (2026-08-16): a generation can produce invalid
        # YAML (a stray markdown fence or commentary the extraction regex
        # didn't fully strip) -- this is a generation-quality problem,
        # the same category as a failed data validation, not a reason to
        # give up on the whole attempt loop after one try. Checked BEFORE
        # writing to disk or calling the real-data validator, so a
        # syntactically broken script is never what gets left behind.
        try:
            yaml.safe_load(text)
        except yaml.YAMLError as exc:
            validation = {"passed": False, "status": "fail", "checks": [],
                          "error": f"generated output is not valid YAML: {exc}"}
            if attempt < MAX_GENERATION_ATTEMPTS:
                current_feedback = (f"Your last attempt did not produce valid YAML "
                                     f"(parse error: {exc}). Output ONLY the lesson_script.yml "
                                     f"content, no markdown code fences, no commentary before or "
                                     f"after it, starting directly with `lesson_id:`.")
                continue
            break

        # Structural backstop for the validations-block requirement,
        # checked in the same category and same place as the YAML-
        # validity check above -- deterministic, not relying on the
        # model remembering an instruction that's demonstrably not 100%
        # reliable on its own (see _missing_validations_coverage's
        # docstring). Checked before writing to disk, same as the YAML
        # check, so an incomplete script is never what a human reviewer
        # or the fast-path Quick Review page sees without this having
        # tried to fix it first.
        missing = _missing_validations_coverage(text)
        if missing:
            validation = {"passed": False, "status": "fail", "checks": [],
                          "error": f"filter step(s) {missing} have no matching validations entry"}
            if attempt < MAX_GENERATION_ATTEMPTS:
                current_feedback = (
                    f"Your last attempt filtered data in event(s) {', '.join(missing)} but declared no "
                    f"validations entry for it/them. Every filter/aggregation step needs a validations "
                    f"entry describing that exact query (see the validations SCHEMA) -- add it, using "
                    f"real per-field ranges from the live schema below, not a placeholder.")
                continue
            break

        # Structural backstop for highlight/commit resolution, same
        # category, priority, and pattern as the validations check right
        # above -- see _highlight_resolution_violations' docstring. Two
        # real defects found via the scaled test (a floating narrate
        # beat displacing a commit; an orphaned highlight with no commit
        # at all) are both this same invariant broken two ways.
        highlight_issues = _highlight_resolution_violations(
            yaml.safe_load(text).get("events", [])
        )
        if highlight_issues:
            validation = {"passed": False, "status": "fail", "checks": [],
                          "error": f"highlight/commit resolution problems: {highlight_issues}"}
            if attempt < MAX_GENERATION_ATTEMPTS:
                current_feedback = (
                    "Your last attempt has highlight_target/highlight_targets event(s) whose pause "
                    "isn't immediately followed by their own commit action or clear_highlight:\n  - "
                    + "\n  - ".join(highlight_issues) +
                    "\nRemove whatever is displacing the resolution (e.g. an extra narrate beat) or "
                    "give an orphaned highlight a real commit -- or remove it entirely if the step it "
                    "was meant to show is already handled internally by a preceding action "
                    "(e.g. add_to_dashboard resolves its own dashboard-naming step, it needs no "
                    "separate highlight+click after it)."
                )
                continue
            break

        script_path.write_text(text)

        try:
            validation = validator.validate_script(script_path)
        except Exception as exc:
            # Metabase unreachable or similar -- don't claim a pass we
            # never actually checked, but don't burn a retry on
            # infrastructure being down either.
            validation = {"passed": False, "status": "unchecked", "checks": [],
                          "error": f"validation could not run: {exc}"}
            break

        if validation["status"] == "pass":
            break
        if validation["status"] == "unchecked":
            # No validations declared at all -- not a data-correctness
            # failure to retry against, just an authoring gap. Surfaced
            # to the reviewer as-is rather than looping.
            break
        if attempt < MAX_GENERATION_ATTEMPTS:
            current_feedback = _validation_feedback(validation)

    return {"text": text, "validation": validation, "attempts": attempt}
