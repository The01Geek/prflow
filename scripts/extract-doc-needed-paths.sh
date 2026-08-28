#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2026 Daniel Radman
# SPDX-License-Identifier: MIT
#
# extract-doc-needed-paths.sh — deterministically extract the file paths named
# in an issue body's **Documentation Needed** bullet, one per line.
#
# Reads the issue body on stdin (or from a file path given as $1) and emits the
# recognizable file paths declared in the Documentation Needed block of the
# `## Implementation Notes` section. THREE scope-opening shapes are accepted, per
# the scope note below: (1) a `- **Documentation Needed**` list item (issue #185),
# (2) a bare blank-line-preceded `**Documentation Needed**` bold paragraph (issue
# #309), and (3) a `### Documentation Needed` level-3 heading (issue #380). The direct
# consumer is scripts/read-doc-needed-deliverables.sh, which Phase 4.1 Stage 1
# (pre-flight briefing) and Stage 2 (post-hoc diff gate) each invoke rather than
# re-deriving paths by LLM prose interpretation — so the two passes can never disagree
# about which paths were named (issue #185 Addendum; issue #1554 interposed the helper).
#
# Extraction is intentionally deterministic and scoped:
#   * scope — only the text between the Documentation Needed opener (a `- **…**`
#     list item, a bare blank-line-preceded `**…**` bold paragraph — the shape an
#     LLM-drafted `## Implementation Notes` section, and the real issue #304 body,
#     uses; issue #309 — OR a `### Documentation Needed` level-3 heading, issue
#     #380) and the next peer item: for a list-item opener, a same-indentation
#     label-and-em-dash item closes even when its label is not bold. A top-level
#     bold peer, the next `## ` heading, or (for a
#     heading-opened scope) the next level-3+ heading also closes (or EOF).
#     A `### Documentation Needed` heading only opens inside `## Implementation
#     Notes`; a deeper `#### …` heading or a bullet that merely mentions the label
#     does not open. A bold-emphasis
#     span that only begins a wrapped CONTINUATION line inside the bullet (no
#     `- `, not blank-preceded) does NOT close the scope, so paths on wrapped
#     lines are still captured. Two adjacent-grammar shapes are handled per
#     issue #327: (Shape 1) a top-level bold DELIVERABLE list after the bullet
#     (`- **`docs/a.md`**`) is captured — a backtick-led bold item is a
#     deliverable, not a peer label, and does not close the scope (a
#     non-backticked `- **docs/a.md**` is indistinguishable from a peer label
#     and closes, an accepted run.sh-pinned tradeoff); (Shape 2) a
#     blank-separated PLAIN-PROSE paragraph closes the scope so its tokens do not
#     leak — but ONLY once a deliverable has already been captured, so a PRIMARY
#     prose declaration (a bare opener followed by a prose paragraph that names
#     the path) and INTERVENING prose before the deliverables are still captured
#     (avoiding the fail-open an unconditional close would cause), while a
#     genuinely-TRAILING prose paragraph after the deliverables is dropped. A
#     blank-separated plain sub-list (`- `docs/a.md``) stays in scope. A path
#     mentioned in `## Current Behavior`,
#     `## Technical Context`, or any OTHER bullet is NOT a documentation
#     deliverable and is never emitted.
#   * span / fence markers (issue #644) — a backtick span, a word-adjacent
#     parenthesized `Word(...)` group, and a fenced code block (```` ``` ````/
#     `~~~`) are scope markers, not deliverable text. A backtick span whose whole
#     content is a single bare-path token yields that token; a span of several
#     whitespace-separated bare-path tokens each carrying a recognized extension
#     or naming an in-tree tracked file yields each; ANY other span (a command
#     `bash lib/test/run.sh`, a grant `Bash(x.sh:*)`, a `:`/`*`/`(`-bearing
#     literal) is a command/grant literal — it contributes no tokens and a
#     one-time stderr breadcrumb names the first suppressed span. A `Word(...)`
#     call group outside spans contributes no tokens. Fenced blocks are inert to
#     the ENTIRE pipeline (scope state and tokens alike) — a fenced example is
#     illustration, not a declaration; the single fence tracker lives in Stage A
#     and runs from the top of the body, so the block Stage B receives is
#     fence-free by construction. When the fence-aware pass enters no
#     Documentation Needed scope at all AND a fence actually disrupted parsing
#     (an unbalanced fence still open at EOF, or the section itself swallowed by a
#     straddling fence — a truncated body, a lone stray delimiter, a fence
#     straddling the scope boundary), Stage A re-runs fence-blind (today's
#     semantics) and that result stands, so a mis-fenced body degrades to today's
#     behavior instead of silently emptying; a balanced fenced example that opens
#     no real scope (a phantom scope) does not trip the fallback and stays empty. DISCLOSED
#     drops: an un-backticked bare command word in plain prose still emits its
#     path token (textually indistinguishable from a deliverable mention); and
#     command-shaped spans are a breadcrumbed under-enforcement residual, not a
#     leak-safe property. Indented four-space code blocks are a disclosed
#     non-goal (only the ```` ``` ````/`~~~` GFM fence forms are recognized).
#   * a token counts as a path only if it ends in a recognized documentation/
#     source extension OR names an in-tree tracked regular file (the two-part
#     `[ -f ]` + `git ls-files` rescue for extensionless real files like
#     Makefile/LICENSE — both halves are required; see the inline comment). A bare
#     "contains `/`" test is deliberately NOT sufficient: it wrongly emitted
#     directory tokens (`docs/internal`) and rooted skill-invocation refs
#     (`/claude-md-management`, from colon-splitting) — see issue #254. Rooted
#     (`/…`) tokens are dropped outright, since an in-tree deliverable is always
#     repo-relative. This excludes prose, skill names (`devflow:docs`), and
#     section names — the over-extraction the issue's Counterfactual warns
#     against — by construction, with no LLM judgement.
#   * out-of-tree escapes are dropped before the path test even runs: a rooted
#     (`/…`) token and a parent-dir-escaping (`../…`) token can never name an
#     in-tree deliverable, so both are dropped outright — this also stops a token
#     that carries a recognized extension (`../notes.md`) from reaching the
#     extension branch, which emits on the extension alone (issue #254).
#   * standalone `none` declaration (issue #1663) — a block whose FIRST content
#     token is the recognized declaration promises nothing, so no paths are
#     emitted for it (the reading helper then reports `no-deliverables`). The
#     declaration is examined on the first content token ALONE, wherever it falls:
#     that token must be exactly `none` (case-insensitively) carrying at most one
#     trailing terminator from the closed set comma/period/semicolon/colon, OR
#     `none` standing alone as that first content token (any later block content
#     is then suppressed, per the residual below). It is a whole-token
#     literal comparison, never a leading prefix, so `None of these pages may be
#     skipped:` runs on into a sentence and still extracts its paths, and `none!` /
#     `none)` carry a char outside the terminator set and are not declarations.
#     Content after the first token — the writer's explanatory sentence and any
#     path it names — is deliberately NOT consulted. STATED RESIDUAL: a writer who
#     opens with the declaration and then names a file that genuinely needs editing
#     loses that file's mandatory status; the routine Phase 4.1 documentation pass
#     still runs and still updates what the change warrants, and Stage 1's
#     safety-net workpad note records that the cross-check was skipped, so the case
#     is auditable rather than silent — the accepted cost of a declared empty form.
#
# Output is sorted and de-duplicated; absent section / empty bullet / standalone
# `none` declaration / no path-like tokens all yield empty output and exit 0 (a
# true no-op signal).
set -euo pipefail

body="$(cat "${1:-/dev/stdin}")"

# Recognized documentation/source extensions (an ERE alternation, no anchors).
# SINGLE-SOURCED here: Stage A's `emitted` proxy (passed in via -v extre) and
# Stage B's path test (below) both consume it, so the two can never drift — a
# coupled invariant, kept in one place. Editing this list changes both callers.
doc_ext_alt='md|markdown|sh|json|py|ya?ml|rst|txt|adoc|mdx|toml|cfg|ini'

# Stage A — isolate the **Documentation Needed** bullet block. Scope logic only,
# with ONE minimal token-awareness point: the `emitted` proxy (see its arm below)
# flips once a printed STRUCTURAL line (a list item or bold line) bears a
# recognized-extension path — never a plain-prose line — so a *later* trailing
# prose paragraph can close the scope without ever dropping a primary/intervening
# prose deliverable (the fail-open guard: prose can never arm the close). awk
# state: 0 = outside Implementation Notes; 1 = inside the section but outside the
# bullet; 2 = inside the Documentation Needed bullet. `list_scope` marks a
# list-item opener for the same-level-peer close arm.
#
# Stage A is invoked TWICE-capable via `-v fence_aware` (issue #644): the primary
# fence-AWARE pass tracks fence state (a single tracker, from the top of the body)
# and treats fence delimiter + interior lines as absent — they drive no scope
# transition, never arm `emitted`, are never printed, and never update
# `prev_blank`. If that pass enters NO Documentation Needed scope at all (state
# never reached 2) AND parsing was disturbed by a fence (an unbalanced fence still
# open at EOF, or the section itself was swallowed so state never even reached 1),
# it exits 10 and the shell re-runs Stage A fence-BLIND (today's semantics). So a
# lone stray delimiter, a truncated mid-fence body, or a fence straddling the
# scope boundary degrade to today's behavior instead of silently emptying, while a
# balanced fenced EXAMPLE that opens no real scope (a phantom scope) stays empty.
run_stage_a() {
  printf '%s\n' "$body" | awk -v extre="$doc_ext_alt" -v fence_aware="$1" '
  # clean_spans(line): apply the issue #644 inline-span and Word(...) call-group
  # rules and return the cleaned text — the SAME shape Stage B tokenizes, so
  # arms() (below) arms exactly when Stage B would emit. Backticks are paired
  # left-to-right; a closed span (even index, followed by another backtick) is
  # kept only when its whole content is a single bare-path token, or several
  # bare-path tokens each carrying a recognized extension (EXTENSION-ONLY here —
  # arms() cannot run Stage B'"'"'s `[ -f ]`+git in-tree rescue, an accepted
  # over-emission-direction gap, so a mixed ext/in-tree span is dropped by arms()
  # but kept by Stage B); any other span (a `:`/`*`/`(`-bearing grant or a
  # command word) contributes nothing. Outside spans, a `Word(...)` call group is
  # stripped. SYNC: mirrors the Stage B bash cleaning below — change one, change
  # both.
  function clean_spans(line,   np, parts, i, seg, out, ntok, stoks, j, t, allbare, allext, nnz) {
    np = split(line, parts, "`")
    out = ""
    for (i = 1; i <= np; i++) {
      seg = parts[i]
      if ((i % 2 == 0) && (i <= np - 1)) {
        # a CLOSED backtick span (even index i>=2, followed by a backtick i.e. i<=k=np-1)
        ntok = split(seg, stoks, /[ \t]+/)
        nnz = 0; allbare = 1; allext = 1
        for (j = 1; j <= ntok; j++) {
          t = stoks[j]
          if (t == "") continue
          nnz++
          if (t ~ /[^A-Za-z0-9._\/-]/) allbare = 0
          if (t !~ ("[A-Za-z0-9._-][.](" extre ")$")) allext = 0
        }
        if (nnz == 0) continue                 # empty span
        if (!allbare) continue                 # command/grant/skill literal → drop
        if (nnz == 1) { out = out " " seg " "; continue }   # single bare-path token → keep
        if (allext) out = out " " seg " "      # multi, all extension-bearing → keep (ext-only)
        # else multi with an extensionless token → dropped by arms() (no in-tree rescue)
      } else {
        # outside text (or an unpaired trailing segment): strip Word(...) call
        # groups, keep the rest as tokenizable text.
        gsub(/[A-Za-z_][A-Za-z0-9_]*\([^)]*\)/, " ", seg)
        out = out " " seg " "
      }
    }
    return out
  }
  # arms(line): does this line contain a token STAGE B WOULD EMIT? The `emitted`
  # gate for the Shape 2 close (below) is only fail-open-safe if arming implies a
  # real path was captured, so this MUST mirror the Stage B token predicate: apply
  # the same span/call-group cleaning, split on the same non-path delimiters, apply
  # the same leading-./ and trailing-dot strips, drop the same rooted (/...) and
  # parent-escape (../...) tokens, and require a basename + a recognized extension
  # (extre, single-sourced). A looser test would arm on prose/grant tokens Stage B
  # DROPS, letting the next trailing-prose paragraph close the scope and drop the
  # real deliverable to empty output (the fail-OPEN this whole gate exists to
  # prevent). COUPLED with the Stage B `case` drops + extension test + span
  # cleaning below: change one, change both.
  function arms(line,   cleaned, n, arr, i, t) {
    cleaned = clean_spans(line)
    n = split(cleaned, arr, /[^A-Za-z0-9._\/-]+/)
    for (i = 1; i <= n; i++) {
      t = arr[i]
      sub(/^\.\//, "", t)
      sub(/\.+$/, "", t)
      if (t == "") continue
      if (t ~ /^\//) continue
      if (t ~ /^\.\.\//) continue
      if (t ~ /\/\.\.\//) continue
      if (t ~ ("[A-Za-z0-9._-][.](" extre ")$")) return 1
    }
    return 0
  }
  # decl_candidate(line): the standalone-`none` declaration contract is in the
  # header. This returns the line'"'"'s content with the label and the separator run
  # after it stripped, so is_none_declaration() sees the first content token. The
  # em-dash separator is stripped as a regex LITERAL, never a byte class, so the
  # byte-wise locale cannot decompose it into a stray single-byte match.
  function decl_candidate(line,   s) {
    s = line
    gsub(/`/, "", s)
    sub(/^(- )?\*\*Documentation Needed\*\*/, "", s)
    sub(/^([[:space:]*:.-]|—)+/, "", s)
    return s
  }
  # is_none_declaration(cand): true for the two recognized forms (see the header
  # contract) and nothing else — `none` plus one terminator from `,.;:` at a
  # whitespace-or-end boundary, or `none` standing alone. The terminator/boundary
  # anchor is what keeps a leading prefix like `None of these …` (word `none`
  # followed by more content) and `none!` / `none)` from matching.
  function is_none_declaration(cand) {
    cand = tolower(cand)
    if (cand ~ /^none[,.;:]([[:space:]]|$)/) return 1   # none + one terminator
    if (cand ~ /^none[[:space:]]*$/) return 1           # none standing alone
    return 0
  }
  BEGIN { prev_blank = 1; in_fence = 0 }   # start-of-file is a paragraph boundary
  # Fence tracking (issue #644) — the FIRST thing, before any scope arm, from the
  # top of the body (a fence can open before any scope opener). A GFM fence
  # delimiter line (first non-whitespace chars are 3+ backticks OR 3+ tildes)
  # toggles the state; both the delimiter and every interior line are INERT — no
  # scope transition, no print, no `prev_blank` update (`next` skips the updater),
  # so `prev_blank` is left as it stood before the fence. Only active in the
  # fence-aware pass; the fence-blind fallback pass restores today (no fence rule).
  fence_aware && /^[[:space:]]*(```|~~~)/ { in_fence = !in_fence; next }
  fence_aware && in_fence { next }
  /^## / {
    state = ($0 ~ /^## Implementation Notes[[:space:]]*$/) ? 1 : 0
    if (state == 1) entered_section = 1
    prev_blank = 1           # a heading is a block boundary: the next line begins a new paragraph
    next
  }
  # A level-3-or-deeper Markdown heading (### … and deeper — `###+` is unbounded;
  # Markdown itself caps headings at ######, but the opener anchors to level 3). The
  # `### Documentation Needed` heading is a THIRD scope-opening shape (issue #380):
  # an issue whose `## Implementation Notes` section renders the deliverables under a
  # `### Documentation Needed` SUBHEADING (the real issue #363 body) matched NOTHING
  # under the `- **…**` list / bare-bold-paragraph openers, silently skipping the
  # Phase 4.1 gate — the same fail-open the #309 bare-paragraph widening fixed for a
  # different shape. Only INSIDE Implementation Notes (state>=1), so a
  # `### Documentation Needed` under any OTHER section never opens (heading-outside
  # -Implementation-Notes case). `emitted` is reset on a fresh open (symmetric with
  # the bold openers above) so the Shape 2 trailing-prose close can still tell a
  # captured deliverable from a primary prose declaration. Any OTHER level-3+ heading
  # CLOSES an open scope (2 -> 1) so later-subsection paths never leak — the
  # heading-form analogue of the `## ` and peer-bullet closers. The open-match is
  # anchored to `^###[[:space:]]+…Documentation Needed` (exactly level 3), so a
  # heading that merely deepens (`#### …`) takes the close arm, and a bullet line
  # that only MENTIONS the label in its prose never matches `^###+ ` at all.
  /^###+ / {
    if (state >= 1 && $0 ~ /^###[[:space:]]+\*{0,2}Documentation Needed/) {
      if (state != 2) emitted = 0
      # Reset the declaration latch on EVERY Documentation Needed opener (issue
      # #1663): without this a `none` block silently suppresses a later block
      # deliverable — a fail-open across blocks. Unlike emitted, this is not gated
      # on state!=2, so back-to-back openers (already state 2) still re-examine.
      decl = 0; decl_examined = 0; list_scope = 0
      state = 2
      entered_scope = 1
    } else if (state == 2) {
      state = 1
    }
    prev_blank = 1
    next
  }
  # A bold BULLET opens the Documentation Needed scope (when its label is
  # "Documentation Needed") or, for any other bold bullet, closes it. What counts
  # as a top-level bold bullet is either a "- **" list-marker line OR a bare "**"
  # bold paragraph AT A PARAGRAPH BOUNDARY (preceded by a blank line or the
  # section heading) — the two shapes real issue bodies use. The canonical issue
  # template writes the list form ("- **Documentation Needed** — …"); an
  # LLM-drafted `## Implementation Notes` section commonly renders the same items
  # as bare blank-separated bold PARAGRAPHS ("**Documentation Needed** — …", no
  # "- " prefix — the real issue #304 body is exactly this, and matched NOTHING
  # under the old "- "-required anchor, silently skipping the gate; issue #309,
  # sibling of the #289 class).
  # The `prev_blank` guard is load-bearing, not decoration: a bold-emphasis span
  # that merely BEGINS a wrapped continuation line *inside* an open bullet (no
  # "- ", not blank-preceded — e.g. "**Note.** also update `x.md`") is NOT a
  # bullet. Closing the scope on it would silently drop `x.md` and every path on
  # later wrapped lines — a fail-OPEN that under-enforces the very gate this
  # helper feeds, the recurrence the #309 fix must not introduce. It also keeps
  # the dashed list form (consecutive, blank-separator-free "- **…**" bullets, as
  # in the template) closing correctly via the "- **" arm, which needs no blank
  # line. ACCEPTED tradeoff (#309 review): a blank-line-PRECEDED bold paragraph
  # that the author meant as a continuation of the bullet ("**Also.** update
  # `b.md`" after a blank line) is structurally indistinguishable from a peer
  # bullet ("**Potential Gotchas.** …"), so it closes the scope and its paths
  # are dropped. Closing is the deliberate choice: treating it as continuation
  # would leak every following peer bullet into the gate output (the
  # false-positive direction the issue Gotchas forbid). Pinned by a run.sh
  # fixture so the drop is a documented contract, not a silent surprise.
  # The open-match is still ANCHORED to the bullet LABEL
  # (^(- )?**Documentation Needed**) so a different bullet that merely MENTIONS
  # the label in its prose (e.g. the Potential Gotchas bullet) closes the scope
  # rather than re-opening it. Sub-bullets ("  - x") and non-bold continuation
  # prose do not match and stay within an open scope.
  #
  # SHAPE 1 (issue #327): the [^`] after \*\* excludes a BACKTICK-LED bold item
  # (e.g. "- **`docs/a.md`**", "**`docs/a.md`**") from this scope-controlling arm.
  # Such an item is a listed DELIVERABLE path, not a peer section LABEL
  # ("- **Potential Gotchas**", which opens with a letter), so it must NOT close
  # the scope: a top-level bold DELIVERABLE list after the bullet then stays IN
  # scope and its paths are captured, instead of the first item silently closing
  # the scope to empty output (the fail-open the issue reported). A NON-backticked
  # bold item ("- **docs/a.md**") is structurally identical to a peer label and
  # DOES close — an ACCEPTED, run.sh-pinned tradeoff (leak-safe direction, mirror
  # of the Case 17 drop; deliverable lists in the wild backtick their paths).
  # `emitted` is reset to 0 whenever a FRESH Documentation Needed scope opens
  # (transition into state 2 from a non-2 state) so the Shape 2 close arm below
  # can tell a genuinely-TRAILING prose paragraph (one that follows a captured
  # deliverable) from a PRIMARY prose declaration (the deliverable itself). See
  # the Shape 2 comment.
  state >= 1 && ( /^- \*\*[^`]/ || ( /^\*\*[^`]/ && prev_blank ) ) {
    ns = ($0 ~ /^(- )?\*\*Documentation Needed\*\*/) ? 2 : 1
    if (ns == 2 && state != 2) emitted = 0
    # Reset the declaration latch on EVERY Documentation Needed opener (issue
    # #1663): a `none` block must not suppress a later block deliverable. Not gated
    # on state!=2, so back-to-back openers (already state 2) still re-examine.
    if (ns == 2) { decl = 0; decl_examined = 0; list_scope = ($0 ~ /^- /) }
    if (ns == 2) entered_scope = 1
    entered_section = 1
    state = ns
  }
  # A list-item scope ends at its next same-level plain peer: the label-and-em-dash
  # shape used by issue prose. Items with a backtick before the em dash, indented
  # items, and wrapped lines remain inside the Documentation Needed scope.
  state == 2 && list_scope && /^- [^`]* — / && $0 !~ /^- \*\*Documentation Needed\*\*/ {
    state = 1
    list_scope = 0
  }
  # SHAPE 2 (issue #327): a blank-line-PRECEDED PLAIN-PROSE paragraph (not blank,
  # not a list item, not a bold bullet) inside an open bullet closes the scope so
  # its path-like tokens do not LEAK into the gate as deliverables the docs pass
  # never owed (over-emission) — BUT only once a deliverable has already been
  # captured in this scope (`emitted`). That `emitted` guard is load-bearing: it
  # distinguishes genuinely-TRAILING prose (which follows the deliverables and is
  # safe to drop — the Suggestion-#3 fixture this issue targets) from a PRIMARY
  # prose declaration where the paragraph IS the deliverable ("**Documentation
  # Needed**\n\nUpdate `docs/foo.md`."). Closing unconditionally would empty the
  # output for that primary-prose shape — a fail-OPEN that silently disables the
  # Phase 4.1 gate (the #289/#309/#327 recurrence). Because a fresh scope opens
  # with emitted=0, the FIRST prose paragraph (and any INTERVENING prose before
  # the deliverables are captured) stays in scope and is captured; only prose that
  # arrives AFTER a deliverable was emitted is treated as trailing and dropped.
  # A blank-separated PLAIN sub-list ("- `docs/a.md`", non-bold) is a list
  # CONTINUATION, not prose: the ^[[:space:]]*- guard keeps it in scope. The
  # $0 !~ /^\*\*/ guard is LOAD-BEARING: the bold arm above deliberately skips a
  # BACKTICK-LED bold line (its [^`] class), so a bare "**`docs/a.md`**"
  # deliverable paragraph falls through to here — the guard keeps it IN scope
  # (captured, per Shape 1) instead of this arm mistaking it for prose and closing.
  # A peer/continuation bold paragraph ("**Also.** …") was already demoted to
  # state 1 by the bold arm (Case 17) and never reaches this test. This arm runs
  # AFTER the bold arm and only closes (2 -> 1), so it never re-opens an opener.
  # KNOWN LIMITATION (lookahead-free, leak-safe direction): a deliverable list
  # placed AFTER such a closing prose paragraph is treated as trailing and dropped
  # ("- `docs/a.md`", blank, prose, blank, "- `docs/b.md`" drops docs/b.md). This
  # is the deliberate leak-safe under-emission — keep all deliverables together
  # before any prose paragraph, or in the deliverable list itself. Chosen over the
  # opposite (reopen the scope on a later list) because reopening re-leaks an
  # UNRELATED trailing bullet tokens, the over-emission the #309 Gotchas forbid.
  state == 2 && emitted && prev_blank && $0 !~ /^[[:space:]]*$/ && $0 !~ /^[[:space:]]*-/ && $0 !~ /^\*\*/ {
    state = 1
  }
  # Print an in-scope line and mark the scope as having emitted a deliverable once
  # a printed STRUCTURAL deliverable line — a list item (^[[:space:]]*-) or a bold
  # line (^**) — bears a recognized-extension path token (via arms(), which now
  # applies the same span/call-group cleaning Stage B does, so a grant-only line
  # like "- `Bash(x.sh:*)`" no longer arms; issue #644). The structural-line
  # restriction is the load-bearing fail-open guard: `emitted` must NEVER be armed
  # by a PLAIN-PROSE line, because ordinary intro/context prose routinely carries
  # an extension-bearing substring that is NOT a deliverable, yet a prose line
  # arming emitted would let the NEXT paragraph (often the one that actually names
  # the deliverable) close the scope and DROP it: a fail-OPEN that empties the
  # output, the #289/#309/#327 recurrence. Fence delimiter/interior lines never
  # reach here (the fence rule `next`-skips them), so a fenced heading-shaped or
  # bold-shaped line drives no scope transition and no arm.
  state == 2 {
    # issue #1663 — the standalone `none` declaration. Examine the block'"'"'s FIRST
    # content token (wherever it falls): if it is the recognized declaration, the
    # block promises nothing, so suppress ALL of its output. The reading helper
    # then turns the empty extraction into `no-deliverables` (exit 10), the signal
    # the run already treats as "nothing to cross-check". Runs before any token is
    # classified, so a backticked path anywhere after the declaration cannot defeat
    # it. Placed here rather than as an unconditional close so it expresses a
    # writer'"'"'s declaration, not a second way for content to vanish.
    if (!decl_examined) {
      cand = decl_candidate($0)
      if (cand != "") {
        decl_examined = 1
        if (is_none_declaration(cand)) {
          decl = 1
          print "extract-doc-needed-paths.sh: the Documentation Needed block opens with a standalone none declaration (first content token none); emitting no deliverables for this block" > "/dev/stderr"
        }
      }
    }
    if (decl) { prev_blank = ($0 ~ /^[[:space:]]*$/); next }
    print
    if ( ( $0 ~ /^[[:space:]]*-/ || $0 ~ /^\*\*/ ) && arms($0) ) emitted = 1
  }
  { prev_blank = ($0 ~ /^[[:space:]]*$/) }
  # Fence-blind fallback signal (issue #644): the fence-AWARE pass exits 10 when it
  # entered no Documentation Needed scope AND a fence disturbed parsing (an
  # unbalanced fence still open at EOF, or the section was never even entered so a
  # straddling fence swallowed its opener). The shell then re-runs fence-blind. A
  # phantom scope (a balanced fenced example inside an entered section, no real
  # scope) satisfies neither disjunct, so it stays empty rather than falling back.
  # An UNBALANCED fence (in_fence still open at EOF) that opened AFTER a scope was
  # already entered swallows every later line as fence-interior, so a deliverable
  # written after a stray unclosed ``` is dropped. The fence-blind fallback does NOT
  # cover this (it is gated on !entered_scope), and the leak-safe design keeps the
  # drop (re-running fence-blind here would re-tokenize the malformed fenced content
  # and re-introduce the phantom command tokens #644 exists to suppress). So keep the
  # drop but make it OBSERVABLE with a one-time breadcrumb instead of silent (issue
  # #644 review). A balanced fence (in_fence==0 at EOF) never triggers this.
  END {
    if (fence_aware && in_fence && entered_scope)
      print "extract-doc-needed-paths.sh: an unbalanced (unclosed) fenced block inside the Documentation Needed scope swallowed the lines after it; any deliverable written after the stray fence delimiter was dropped (close the fence or move the deliverable out of it)" > "/dev/stderr"
    exit (fence_aware && !entered_scope && (in_fence || !entered_section)) ? 10 : 0
  }
  '
}

# Primary fence-aware pass; on the exit-10 "entered no scope, fence disturbed
# parsing" signal, re-run fence-blind and let that result stand (issue #644).
# `&& a_rc=0 || a_rc=$?` keeps `set -e` from aborting on the exit-10 signal while
# still capturing the real awk exit code.
block="$(run_stage_a 1)" && a_rc=0 || a_rc=$?
if [ "$a_rc" -eq 10 ]; then
  block="$(run_stage_a 0)" && a_rc=0 || a_rc=$?
fi
if [ "$a_rc" -ne 0 ]; then
  printf '%s\n' "extract-doc-needed-paths.sh: Stage A block scan failed (awk rc=$a_rc)" >&2
  exit "$a_rc"
fi

[ -n "$block" ] || exit 0

# Probe once whether the `git ls-files` half of the extensionless rescue can run
# at all: git absent from PATH, or cwd outside a work tree, both disable it. When
# disabled, an extensionless deliverable that IS a real on-disk file (so `[ -f ]`
# passes) is silently dropped by the rescue below — the same guard-class-2
# tr-dependence failure mode this repo's own review-extension flags. Emit ONE
# stderr breadcrumb naming `git` the first time a token actually hits the
# degraded rescue (not per-token, and not when no extensionless real file is
# affected), so the drop is observable rather than silent.
git_rescue_ok=1
git rev-parse --is-inside-work-tree >/dev/null 2>&1 || git_rescue_ok=0

# Stage B span pre-pass (issue #644) — clean the scoped block BEFORE tokenizing,
# so command/grant literals inside backtick spans and `Word(...)` call groups
# never become phantom deliverables. The cleaning is a TEXT TRANSFORM: each span
# is either passed through (backticks stripped, its tokens survive) or removed
# (replaced by a space); `Word(...)` groups in the surrounding text are removed.
# The existing Stage B tokenizer + per-token predicate below run UNCHANGED over
# the cleaned block, so the extension test, `case` drops, extensionless in-tree
# rescue, and grep-rc>=2 fail-closed path are all preserved.
# SYNC: the span keep/suppress logic mirrors Stage A's clean_spans() (arms()), with
# ONE intended divergence — Stage B runs the `[ -f ]`+git in-tree rescue for
# multi-token spans that arms() cannot (an accepted over-emission-direction gap).
# All string work here is bash builtins (no sed/tr — non-preflight PATH tools a
# SELECTION must not depend on; the only external tools are the preflight-guaranteed
# grep/git already used by the predicate). Uses `printf` builtins, not command
# substitution, so `span_warned` persists across spans in this shell.
span_warned=0
span_degraded_warned=0
CLEANED=""

# span_token_ok TOK — is TOK bare-path-form AND (recognized extension OR in-tree
# tracked regular file)? Used only for the git-available multi-token span keep
# decision (issue #644). Bare builtins + the preflight-guaranteed grep/git.
span_token_ok() {
  local t="$1"
  case "$t" in *[!A-Za-z0-9._/-]*) return 1 ;; esac   # not bare-path-form
  [ -n "$t" ] || return 1
  if printf '%s\n' "$t" | grep -qE ".+\.($doc_ext_alt)\$"; then return 0; fi
  if [ -f "$t" ] && git ls-files --error-unmatch -- "$t" >/dev/null 2>&1; then return 0; fi
  return 1
}

# suppress_span CONTENT — record the first suppressed span with a one-time stderr
# breadcrumb (mirrors the `git unavailable` one-time-breadcrumb precedent), so a
# suppressed span is observable rather than silent. HONEST wording (issue #644
# review): a suppressed multi-token span is NOT necessarily a pure command/grant
# literal — the accepted under-enforcement residual (AC6) also drops a span that
# mixes a real path with a non-path token (`docs/a.md notes`), because the rule
# cannot tell it from a command. The breadcrumb must not assert "a command
# literal" as fact when the span may have carried a deliverable (the repo's
# all-output-channels-honesty guard) — it names both possibilities.
suppress_span() {
  if [ "$span_warned" -eq 0 ]; then
    printf '%s\n' "extract-doc-needed-paths.sh: suppressed a span (a command/grant/skill literal, or a path mixed with non-path tokens — not a set of bare-path deliverables, so no tokens emitted): \`$1\`" >&2
    span_warned=1
  fi
}

# handle_span CONTENT — decide keep/suppress for a paired backtick span and append
# the cleaned text (span content, or a space) to CLEANED.
handle_span() {
  local content="$1"
  local -a toks=()
  # shellcheck disable=SC2162  # default IFS whitespace split is intended
  read -ra toks <<< "$content"
  local ntok=${#toks[@]}
  if [ "$ntok" -eq 0 ]; then CLEANED+=" "; return; fi   # empty span
  local t allbare=1
  for t in "${toks[@]}"; do
    case "$t" in *[!A-Za-z0-9._/-]*) allbare=0; break ;; esac
  done
  if [ "$allbare" -eq 0 ]; then suppress_span "$content"; CLEANED+=" "; return; fi
  if [ "$ntok" -eq 1 ]; then CLEANED+=" ${toks[0]} "; return; fi   # single bare-path token → keep
  if [ "$git_rescue_ok" -eq 1 ]; then
    local allok=1
    for t in "${toks[@]}"; do span_token_ok "$t" || { allok=0; break; }; done
    if [ "$allok" -eq 1 ]; then CLEANED+=" $content "; else suppress_span "$content"; CLEANED+=" "; fi
  else
    # git-unavailable degraded arm: never span-wide suppression — keep the content
    # and let the per-token predicate below emit extension-bearing tokens and drop
    # the extensionless ones (with its own `git unavailable` breadcrumb). Tool or
    # work-tree absence must not escalate into dropping an extension-bearing
    # deliverable (issue #644). But this arm cannot run the command-word check that
    # needs git, so a command span like `bash lib/test/run.sh` KEEPS its
    # extension-bearing `lib/test/run.sh` token (a phantom the git-available path
    # would suppress) — disclosed over-emission in the leak-safe direction. Emit a
    # one-time breadcrumb so that degraded-mode over-emission is observable rather
    # than a silent phantom keep (issue #644 review).
    if [ "$span_degraded_warned" -eq 0 ]; then
      printf '%s\n' "extract-doc-needed-paths.sh: multi-token span kept un-vetted (in-tree/command status unverifiable — git rescue degraded); a command literal in such a span may leak an extension-bearing token this run: \`$content\`" >&2
      span_degraded_warned=1
    fi
    CLEANED+=" $content "
  fi
}

# strip_calls TEXT — remove `Word(...)` call groups (a word immediately followed
# by a parenthesized group, non-greedy to the first `)`) from outside-span text
# and append the rest to CLEANED. Pure-builtin (bash `[[ =~ ]]` + parameter
# substitution) so it depends on no non-preflight PATH tool.
_call_re='[A-Za-z_][A-Za-z0-9_]*\([^)]*\)'
strip_calls() {
  local s="$1" m
  while [[ "$s" =~ $_call_re ]]; do
    m="${BASH_REMATCH[0]}"
    s="${s/"$m"/ }"
  done
  CLEANED+="$s"
}

# Walk the block line by line, splitting each on backticks and pairing spans
# left-to-right. Outside segments (and an unpaired trailing segment after an odd
# backtick — left in place so unbalanced inline spans degrade to today's per-line
# behavior) go through strip_calls; paired spans go through handle_span.
while IFS= read -r line; do
  local_in_span=0
  rest="$line"
  while : ; do
    before="${rest%%\`*}"
    if [ "$before" = "$rest" ]; then
      # no backtick remaining
      if [ "$local_in_span" -eq 1 ]; then strip_calls " $rest"; else strip_calls "$rest"; fi
      break
    fi
    after="${rest#*\`}"
    if [ "$local_in_span" -eq 0 ]; then
      strip_calls "$before"; local_in_span=1
    else
      handle_span "$before"; local_in_span=0
    fi
    rest="$after"
  done
  CLEANED+=$'\n'
done <<< "$block"

# Stage B — pull path-like tokens out of the cleaned block. Split on every
# character that cannot appear in a path token (so backticks, commas, quotes,
# parentheses, and whitespace are delimiters), then keep only tokens that are
# actually paths. `LC_ALL=C sort` makes the output order locale-independent so
# callers and fixtures see one canonical ordering.
#
# Distinguish the grep exit codes instead of swallowing them all with `|| true`:
# rc 1 is the legitimate "no path-like token in the bullet" no-op (exit 0 below),
# but rc >= 2 is a real grep error (e.g. a read failure) that must NOT be
# laundered into an empty-output no-op — that would silently disable the gate the
# same way an upstream failure on the caller side would. Fail closed: propagate
# the non-zero rc so the caller routes to Blocked rather than "no paths named".
grep_rc=0
tokens="$(printf '%s\n' "$CLEANED" | grep -oE '[A-Za-z0-9._/-]+')" || grep_rc=$?
if [ "$grep_rc" -ge 2 ]; then
  printf '%s\n' "extract-doc-needed-paths.sh: token scan failed (grep rc=$grep_rc)" >&2
  exit "$grep_rc"
fi
[ -n "$tokens" ] || exit 0

printf '%s\n' "$tokens" \
  | { git_warned=0; while IFS= read -r tok; do
      tok="${tok#./}"          # strip a leading ./
      # Strip a trailing run of dots the tokenizer glues on at a sentence
      # boundary (the char class includes `.`, so prose like "update
      # CHANGELOG.md." yields the token `CHANGELOG.md.`). A real filename never
      # ends in `.`, so this only ever recovers the intended basename; without it
      # the extension test below rejects `CHANGELOG.md.` and the deliverable is
      # silently dropped — under-enforcing in the gate's own domain.
      tok="${tok%"${tok##*[!.]}"}"
      case "$tok" in
        */) continue ;;        # trailing slash => directory, not a file
        /*) continue ;;        # rooted token: an in-tree deliverable is always
                               # repo-relative, never absolute. Dropping it here
                               # keeps a rooted skill-ref (`/claude-md-management`)
                               # or out-of-tree path (`/etc/hostname`) from ever
                               # reaching the predicate below (issue #254 AC).
        ../*|*/../*) continue ;; # parent-dir escape: an in-tree deliverable never
                               # traverses out of the tree. Drop it here so a token
                               # WITH a recognized extension (`../notes.md`) cannot
                               # reach the extension branch below — that branch emits
                               # on the extension alone and never runs the `[ -f ]` +
                               # git in-tree check, so without this arm an out-of-tree
                               # `../x.md` would be emitted, the very out-of-tree
                               # fail-open the extensionless rescue was hardened against.
        '' ) continue ;;
      esac
      # A token counts as a deliverable file iff it EITHER ends in a recognized
      # doc/source extension (a real filename) OR names an in-tree TRACKED regular
      # file — the rescue for extensionless real files like Makefile/LICENSE. The
      # rescue needs BOTH checks: `[ -f "$tok" ]` rejects directory tokens (a bare
      # `docs`/`docs/internal`, which `-f` reports false for), and
      # `git ls-files --error-unmatch` constrains it to the git work tree. Neither
      # alone suffices: `[ -f ]` tests the whole host filesystem, so a real-on-disk
      # but UNTRACKED relative token (an ad-hoc `notes` file in cwd that is not a
      # repo deliverable) would fail OPEN and be emitted though `git ls-files`
      # rejects it; and `git ls-files` on a bare directory token (`docs`) succeeds
      # by matching the tracked files INSIDE it, so alone it would wrongly emit the
      # directory that `[ -f ]` rejects. Together they keep only in-tree regular
      # files. NOTE: the out-of-tree escapes are NOT this predicate's job —
      # rooted `/…` and parent-escaping `../…` tokens are already dropped by the
      # `case` above, BEFORE the predicate runs, so they never reach here; do not
      # delete those case arms on the assumption this predicate would re-catch them
      # (it would not — the extension branch below emits on the extension alone).
      # The `.+` before the dot excludes a bare extension token (`.md`, `.sh`)
      # that is a syntax reference, not a filename.
      # SYNC: Stage A's arms()/clean_spans() (in the awk above) mirrors THIS token
      # predicate — the span/call-group cleaning plus the rooted/`../` `case` drops
      # and this basename+extension test — so the Shape 2 `emitted` gate only arms
      # when this branch would emit. Change one, change both (the extensionless
      # `[ -f ]`+git rescue below and the multi-token span in-tree rescue are
      # intentionally NOT mirrored — arms() cannot do a filesystem check, an
      # accepted leak-safe gap).
      if printf '%s\n' "$tok" | grep -qE ".+\.($doc_ext_alt)\$"; then
        printf '%s\n' "$tok"
      elif [ -f "$tok" ]; then
        # Extensionless token naming a real on-disk regular file → rescue via git.
        if git ls-files --error-unmatch -- "$tok" >/dev/null 2>&1; then
          printf '%s\n' "$tok"
        elif [ "$git_rescue_ok" -eq 0 ] && [ "$git_warned" -eq 0 ]; then
          # git is unavailable, so this real file was dropped for a tool-absence
          # reason, not because it is untracked — surface it once, per the repo's
          # guard-class-2 (tr-dependence) standard, instead of dropping silently.
          printf '%s\n' "extract-doc-needed-paths.sh: git unavailable (absent from PATH or cwd outside a work tree); the in-tree rescue for extensionless deliverables is degraded — such tokens may be dropped" >&2
          git_warned=1
        fi
      fi
    done; } \
  | LC_ALL=C sort -u
