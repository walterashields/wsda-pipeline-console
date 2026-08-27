# WSDA Delivery Style Guide

These rules govern narration for every WSDA training video. The script generation
prompt includes this file verbatim.

## 1. Narration follows the action

- Describe each action AS it happens, not before and not after a long delay.
- Use spatial pointers so the viewer knows where to look:
  - "the icon at the top left"
  - "the dropdown above the grid"
  - "the status bar at the bottom of the window"
- Keep demo beats under 20 words so the narration finishes while the motion is
  still on screen.

## 2. Before/after observation ritual

- Before acting, direct attention to the current state:
  - "Look at the result pane as it stands."
- After acting, describe what visibly changed:
  - "The rows now reorder by customer_id."
  - "The status bar now shows 6 of 6."

## 3. Explanations must be about the current frame

- Every "why" explanation must reference something visible right now.
- Good: "Notice the second column — Country — now has a filter icon. That tells us the filter is active."
- Bad: "Sorting is useful in many situations..." over a static or unrelated frame.

## 4. Frame each video as a concrete scenario

- Open with a real task, not an abstract topic.
- Good: "We've been asked for a list of customers with emails, so let's open the Customer table."
- Bad: "In this video we will learn about tables."

## 5. Rhetorical transitions are encouraged

- Use short questions to move between sections:
  - "So how do we start? Well — we open the Browse Data tab."
- Do not overuse them; one or two per video is enough.

## 6. State each fact once per video

- Each datum (row count, full column list, table name + attribute) is stated
  once, in the beat where it first becomes visible.
- Later beats may reference it without restating:
  - "the columns we saw earlier"
  - "the same 20 rows"
- Practices may be reinforced ACROSS videos ("the same best practice as before"),
  but never restated as new within one video.

## 7. Validation beats must add a new checkable observation

- A validation beat is not a rewrite of the previous beat.
- It must cite something specific that can be checked on screen:
  - a status-bar count
  - a sort indicator on a column header
  - a filter value in a filter box
  - a newly visible row set
- If a validation beat merely echoes the previous two beats, it is merged or
  dropped.

## 8. Voice and tone

- First-person plural, present tense.
- No filler words ("so", "just", "really", "basically") and no hedging.
- Plain, direct language that a working analyst would use.

## 9. Close with a preview

- End each video by looking ahead:
  - "Next, we'll combine this table with Invoice data to see customer spending."
