# Accessibility audit — Follow It (`/` ticket page, `/lab` dashboard)

Method: real Chrome 155 headless, driven over raw CDP from Node (`Input.dispatchKeyEvent` /
`Input.dispatchMouseEvent`, `Accessibility.getPartialAXTree`, `Runtime.evaluate` on
`document.activeElement` and `getComputedStyle`). Server run locally with `POW_BITS=12`
against a scratch DB. No files were edited except this one.

**Tooling caveat, stated up front:** CDP's synthetic `Input.dispatchKeyEvent` for `Enter`
does **not** trigger a native `click` on a focused `<button>`, even though the dispatched
`keydown`/`keyup` are `isTrusted`. I verified this is a CDP/headless quirk, not an app bug,
by reproducing it on a bare `data:` page with a plain `<button>` and a `click` listener —
`Enter` → 0 clicks, `Space` → 1 click, on totally vanilla markup. Real keyboards don't go
through this path, and both keys are spec'd to activate a button, so I used **Space** to
activate buttons for the rest of this audit and do not count the `Enter` gap against the app.

## KEYBOARD-ONLY RESULT: PASS

Full run, fresh page load, keyboard only (Tab / Space), `POW_BITS=12`:

| # | Key | Focus before → after | Notes |
|---|---|---|---|
| 1-4 | Tab×4 | body → skip-link → brand → "Ticket demo" → "Agent lab ↗" | nav before the stage |
| 5 | Tab | → `button#skip` ("Skip the game") | reached in exactly 5 tabs |
| 6 | Space | click fires on `#skip` | confirmed via injected listener (`__skipClicked===1`) |
| — | (auto) | PoW solves in-worker, no input needed | `reserve.disabled` flips to `false` |
| — | (auto) | focus **lands on `button#reserve` automatically** | app code: `if (hadFocus) el.reserve.focus()` in `ticket.js` — no extra Tab needed |
| 7 | Space | click fires on `#reserve` (`__reserveClicked===1`) | |
| — | (auto) | focus moves to `div#confirm` (`tabindex="-1"`) | reservation `res_dT6iDDAINiqh` returned, confirm panel shown |

Focus was never dropped to `<body>` at any observed step, and the whole fallback route
(Skip → PoW → Reserve → confirm) is reachable and completable with Tab/Space alone. This
is the one item the project plan calls out explicitly, and it works.

One nuance worth recording for future changes: `ticket.js:263` only re-focuses `#reserve`
automatically when the control that had focus before `startPow()` was `#skip`, `#retry`, or
`#verify-again` (`hadFocus` check). That's exactly the keyboard-relevant set today, so it's
fine — just don't widen the fallback-trigger surface without widening that check too.

## Findings, severity-ordered

### 1. [SHOULD-FIX] Live-region (`#status`) toggles `display:none`/`block`, risking dropped announcements
- **File:** `web/static/style.css:36`
- **Observed:** `.status { ... } .status:empty{display:none}`. Measured with
  `getComputedStyle(...).display`: textContent `''` → `display: none` (and the node is
  reported `"ignored": true, "ignoredReasons":[{"name":"notRendered"}]` by
  `Accessibility.getPartialAXTree`); setting any text → `display: block`. The element is the
  same DOM node throughout (never replaced — good), but it is removed from the render/AX
  tree whenever `say('')` runs (e.g. `ticket.js:142`, `ticket.js:267`) and reinserted when
  text is set again.
- **Why it matters:** many screen readers key live-region announcements off a mutation to a
  node that is *already* in the accessibility tree. A node flipping from "not rendered" to
  "rendered with text" in the same tick is often treated as an insertion, not a mutation, and
  several AT/browser combinations do not announce it. Since the Skip → PoW transition goes
  through exactly this empty→non-empty flip (`say('')` at page load → `say('Checking your
  browser...')` on Skip), the "Checking your browser" announcement is the one most at risk of
  being silently dropped for screen-reader users on the keyboard-only path this project cares
  about most.
- **Proposed fix (1-line CSS deletion, no JS change):**
  ```diff
  - .status { color: var(--muted); font-size: 13px; margin-top: 12px; }.status:empty{display:none}
  + .status { color: var(--muted); font-size: 13px; margin-top: 12px; min-height: 1.6em; }
  ```
  Keeping a `min-height` avoids a layout jump when the text is empty; dropping the
  `:empty{display:none}` keeps the node permanently present and rendered (zero height text
  node is harmless either way) so later mutations are reliably seen as mutations.

### 2. [SHOULD-FIX] Same `display:none`-on-empty pattern on the lab key-error message
- **File:** `web/static/lab.css:10` (inline in the long rule list)
- **Observed:** `<span id="keymsg" ... role="status">` (`web/static/lab.html:10`) paired with
  `.keymsg:empty{display:none}`. Identical mechanism to finding 1: `badKey()` in `lab.js`
  (lines ~162-169) sets `$("keymsg").textContent = msg` after it was previously cleared to
  `''`, so the same empty→non-empty flip happens for the "lab key rejected" message.
- **Proposed fix:**
  ```diff
  - .keymsg{width:100%;font-size:12px;color:var(--red)}.keymsg:empty{display:none}
  + .keymsg{width:100%;font-size:12px;color:var(--red);min-height:1.4em}
  ```

### 3. [SHOULD-FIX] The comet-failure reason is shown but never announced
- **File:** `web/static/ticket.js:235-238`, `web/static/ticket.js:72`
- **Observed:** When a comet attempt scores too low, `failToPow()` runs:
  ```js
  function failToPow() {
    showResult("<p>That didn't work, so we'll check your browser instead.</p>");
    startPow('failed', true);
  }
  ```
  `showResult()` writes into `#result` (`web/static/index.html:78`), a plain
  `<div id="result" class="result" hidden>` with **no `role` and no `aria-live`**. I drove a
  real (non-skip) comet attempt that scored a fail and captured the final DOM state:
  `result.textContent === "That didn't work, so we'll check your browser instead."` while
  `status.textContent === "Done. You can reserve now."` — i.e. the only text that ever passes
  through the live region for this path is the generic "Checking your browser" /
  "Done" messages. A screen-reader user never hears *why* they were bounced to the fallback;
  a sighted user does, because `#result` is visually on-screen. This is a straightforward
  "visible-but-not-announced" gap.
- **Proposed fix (minimal — reuse the existing live region instead of adding a second one):**
  ```diff
  function failToPow() {
    showResult("<p>That didn't work, so we'll check your browser instead.</p>");
  +  say("That didn't work, so we'll check your browser instead.");
    startPow('failed', true);
  }
  ```
  `startPow()` immediately overwrites `say()` with "Checking your browser…", so this adds one
  more announced step without changing the visible UI at all.

### 4. [NICE-TO-HAVE] `/lab` text is small for across-the-room viewing
- **File:** `web/static/lab.css:13` (`.log`), `web/static/lab.css:15` (`table`, `th`, `td:first-child`, `.evidence-note`)
- **Measured computed `font-size` at 1280×720 and 1024×768** (both render fine, no
  horizontal overflow, panels stay side-by-side as designed — see finding 6 below for the
  layout check):
  - `.log` → **11px**
  - table header `th` → **9px**
  - `td:first-child` (variant id) → **10px**
  - `.evidence-note` → **10px**
- **Why it matters:** the task explicitly calls out judges viewing the dashboard "from across
  a room." 9–11px absolute text is hard to read at distance even on a sharp display, and
  there's no `rem`/viewport scaling to compensate on a bigger screen.
- **Proposed fix (bump the two smallest, lowest-risk since both have `overflow-x:auto`/`overflow-wrap:anywhere` safety nets already):**
  ```diff
  - .log{height:270px;overflow-y:auto;padding-right:6px;font:11px/1.8 var(--mono)}
  + .log{height:270px;overflow-y:auto;padding-right:6px;font:13px/1.8 var(--mono)}
  ```
  ```diff
  - .cmp{overflow-x:auto}table{border-collapse:collapse;width:100%;font-size:11px;line-height:1.7}th{text-align:left;font-size:9px;...}
  + .cmp{overflow-x:auto}table{border-collapse:collapse;width:100%;font-size:13px;line-height:1.7}th{text-align:left;font-size:11px;...}
  ```
  Not a blocker — nothing overflows or becomes illegible, it's just small.

### 5. [NIT] Primary button label contrast is right at the 4.5:1 line
- **File:** `web/static/design-system.css:4` (`--accent: #c84c08`), used as `.btn-primary`
  background with white (`--accent-ink`) text in `web/static/style.css:32`.
- **Measured (WCAG relative-luminance formula, computed by hand from the hex values):**
  white-on-`#c84c08` = **4.67:1**. Passes the 4.5:1 normal-text threshold, but with very
  little margin — any future darkening of the accent toward orange/lighter, or any
  anti-aliasing/sub-pixel loss on some displays, could tip it under.
- Every other pair I measured passed comfortably: body text on page background 14.7:1, muted
  text on white/panel 5.2–5.7:1, dashboard log colors (`.line.red` `#a63b42`, `.line.blue`
  `#255da1`, `.line.gate` `#825714`) on white 6.3–6.7:1, `reserve-msg`/`toast`/badge color
  pairs 5.9–7.7:1. **No contrast blockers found anywhere in the app.**
- **No code change proposed** — flagging only so nobody nudges `--accent` lighter without
  rechecking this one pair.

## Checklist items that came back clean (no findings)

- **Visible focus (item 3):** every interactive control I tabbed to — nav links, `#skip`,
  `#reserve`, the tester-mode checkboxes, and the visually-hidden radio inputs in `.seg`
  (`web/static/index.html:52-55`) — showed a real focus ring. Global rule
  `design-system.css:12` (`:focus-visible{outline:3px solid var(--focus);outline-offset:4px}`)
  covers ordinary controls; for the `.seg` radios (input has `opacity:0`, `position:absolute`)
  the sibling `<span>` gets its own ring via `style.css:44`
  (`.seg input:focus-visible+span{outline:3px solid var(--focus);outline-offset:2px}`) — I
  confirmed this resolves on the focused radio's sibling span:
  `outline: solid 3px rgb(23,104,202)`, `outline-offset: 2px`. Nothing relies on a
  browser-default outline that's been stripped elsewhere.
- **Color is never the only signal (item 5):** `/lab` verdict cells render `"✔ " + verdict`
  or `"✘ " + verdict` text (`web/static/lab.js:207`), not color alone; every log line is
  prefixed with the agent's icon+name (`web/static/lab.js:38`), so color is reinforcement,
  not the message.
- **Tester mode labelling (item 6):** at `/?tester=1`, Tab lands on, in order: consent
  checkbox → one stop for the `device` radio group (correct native behavior — arrow keys,
  not Tab, move between radios in a group) → non-dominant checkbox → Skip button. All three
  controls resolved an accessible name from their wrapping `<label>` (`"We keep this movement
  trace for 72 hours..."`, `"Mouse"`, `"I'm using my non-dominant hand."`) with no `for`/`id`
  needed — the implicit wrapping-label association works correctly. No unlabelled control.
- **`/lab` layout at 1280×720 and 1024×768 (item 7, layout half):** `document.documentElement
  .scrollWidth` equals `window.innerWidth` at both sizes (no horizontal overflow); the
  3-panel grid stays 2-column (`.panels` computed `grid-template-columns`, e.g. `702px
  425px` at 1280 and `558px 338px` at 1024) because both sizes are above the
  `@media(max-width:1000px)` single-column breakpoint in `lab.css:19` — that's the intended
  behavior at these sizes, not a bug.
- **Wrong roles (item 8):** scanned every `role=` attribute in `index.html` and `lab.html`
  (`status`, `alert`, `log`, `img`). Every one matches its actual content/behavior — no
  misapplied roles found. The only live-region problem is the CSS-driven
  render/derender described in findings 1–2, not a wrong `role`.
- **Canvas accessible name (item 8, extra check):** the comet `<canvas>` has no implicit
  ARIA role, but Chrome still exposes it with `role: Canvas` and a computed accessible name
  equal to its `aria-label` (confirmed via `Accessibility.getPartialAXTree`) — the "put your
  finger on the comet... skip below" instructions do reach assistive tech.

## Summary

- **Keyboard-only fallback route (Skip → PoW → Reserve): PASS.** Reachable and completable
  with Tab/Space alone; focus is actively managed to `#reserve` then `#confirm` and is never
  dropped to `<body>`.
- Findings: **0 blockers**, **3 should-fix** (live-region display:none pattern on `#status`
  and `#keymsg`; unannounced comet-failure reason), **2 nice-to-have/nit** (small `/lab` text
  at distance; one contrast pair with thin margin — currently passing, not failing).
- Only `reviews/a11y-audit.md` was created/edited. No file under `web/static/` was touched,
  no commits were made, and nothing on port 5432 was touched (server ran against
  `ag_a11y` on port 54330 only).
