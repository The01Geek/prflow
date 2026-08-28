#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Daniel Radman
# SPDX-License-Identifier: MIT
"""Flag proven-denied command *shapes* in the ```bash fences of a Markdown file.

Why this exists (issue #401). `lib/test/extract-command-heads.py` (issue #363)
validates that every command *head* the review skill invokes is granted by both
cloud allowlists. But the deployed `claude-code-action` matcher denies whole
command *shapes* even when the head is granted — a leading `VAR="…"` assignment, a
shell `>`/`>>` redirect to `/tmp`, a `cat`-headed heredoc write, a leading `cd`,
or an interpreter head (`python3`) the read-only `review` profile never grants.
When the engine emits one of those, the harness refuses it silently, the run burns
budget re-trying variants, and a cloud review can end with no verdict at all
(Devflow Review run 29105381021 on PR #397: 22 denials, engine quit mid-Phase-3).

The denied shapes here are keyed to the empirical matcher probe, whose evidence of
record is `.github/workflows/matcher-probe.yml`'s job-summary table (re-runnable
after any `claude-code-action` / Claude Code CLI upgrade — URLs rot, the workflow
does not). This module is the desk-time drift pin for that class: it turns a review
fence that teaches a denied shape RED before it ships.

Scope boundary (deliberate — mirrors extract-command-heads.py's narrow reach):

* Only ```bash fences are scanned. Inline-backtick prose is out of reach (matching
  it resurrects the false-positive class the head extractor documents), so a
  positive-recipe example written in prose is intentionally invisible here.
* R3 flags a `>`/`>>` redirect only when its target is under `/tmp/` (out of the
  workspace, and the exact shape the probe denied), NOT every `>` redirect: an
  in-workspace `> .prflow/tmp/…` write of a granted head is left to the existing
  head/allowlist pins, matching how the skill already authors run-scoped scratch.
  A `cat`-headed heredoc write (`cat >`/`cat >>` … `<<`) is flagged to ANY target:
  the /tmp arm is probe-denied (row 1, which is /tmp-targeted and so confounded
  like row 7); the in-workspace arm is UNPROVEN either way and is banned as
  discipline in favor of the proven Write-tool/`tee` alternatives — a lint rule,
  not a probe result (mirrors skills/review/SKILL.md's discipline section).
* R1 flags an env-prefix compound (`VAR=v cmd …`) and a computed double-quoted
  literal assignment (`MARKER="…"`), NOT a pure-shell sentinel/counter/status
  capture (`WP=""`, `n=0`, `rc=$?`, `VAR=$'…'`) nor a command-substitution capture
  (`WP=$(cmd)` / `WP="$(cmd)"` — the observed-PERMITTED form the matcher descends
  into, real-run evidence: run 29105381021 seeded its progress comment through
  exactly a `WP=$(vendored-path create …)` call).

Rule table (each keyed to a probe row / run — see .github/workflows/matcher-probe.yml):

  R1  a fence statement whose leading token is a `VAR=value` assignment —
      env-prefix compound (`M=x printf …`, probe row 2) OR a computed
      double-quoted literal (`MARKER="…"`, run 29105381021 denials). The
      `VAR=$(cmd)` / `VAR="$(cmd)"` capture is NOT flagged — observed permitted on
      THIS tier (run 29105381021), which is an observed execution, not a probe row.
  R2  a leading `cd` (probe row 3 — DROPPED as unproven/confounded; treat as denied).
  R3  a `>`/`>>` redirect (stdout or `2>`/`&>` stderr) to a `/tmp/…` target
      (probe rows 1,2,7 — out-of-workspace + `>`-redirect denials), OR a
      `cat`-headed heredoc write (`cat >`/`cat >>` with `<<`) to ANY target
      (/tmp arm probe-denied — row 1; in-workspace arm unproven, banned as
      discipline in favor of the proven `tee` (row 6) / Write-tool (row 9) forms).
  R4  a leading interpreter (`python3`, `python`, `node`) — the read-only
      `review` profile grants no interpreter (run 29105381021 denials).

  (R5 — a command-substitution assignment used as an `if`/`elif` CONDITION,
  issue #857 — was RETIRED once matcher-probe.yml's review Shape 18
  (`if VAR=$(granted-helper …)`) recorded PERMITTED (run 30310938175, review
  `probe` job, 2026-07-27; issue #869). The discipline was probe-answered, so the
  rule no longer exists.)

NON-GOALS (review profile, stated so a limit is never mistaken for coverage):
  * The guard validates each STATEMENT's LEADING TOKEN (and the redirect/heredoc
    shapes above); it does NOT establish that the enclosing CONSTRUCT is a
    permitted shape. A `case … esac` whose every arm's leading token is granted, or an
    `if … fi` whose condition and body are individually clean, passes this guard even
    though the cloud matcher may refuse the compound as a whole (issue #857 — the
    review-seed `case`/`if`/`elif` compound was refused despite each inner statement
    being individually granted). Establishing enclosing-construct permission is a probe
    question (matcher-probe.yml's review rows), not a static one this guard can answer.

CLI:
    extract-command-shapes.py [--profile review|implement|command|no-expansion-redirect] FILE...
        -> one `FILE:LINE  RULE  statement` per denied-shape hit, across every FILE
           (a reviewed surface is a BUNDLE — a skill root plus its phase references,
           issue #529 — and each hit stays attributed to the file it came from);
           exit 1 if any hit, exit 0 when every file is clean. The `review` profile applies R1-R4
           (read-only review allowlist). `--profile implement` applies the implement-
           tier rules (issue #455), keyed to the SEPARATE devflow-implement matcher
           probe (matcher-probe.yml's implement-probe job). `--profile no-expansion-redirect`
           (issue #2082) is tier-independent and flags EXPANSION (a `$VAR`/`${VAR}` parameter
           expansion) and REDIRECT (any shell redirect), used by the suite to prove a rewritten
           fence region carries neither:

  IR1 a `for` loop — any SYNTACTIC spelling of the loop itself, including C-style
      `for ((i=0;…))` — whose do…done span invokes a label helper BY NAME (probe row I4).
  IR2 a `while` / `until` loop whose do…done span invokes a label helper BY NAME (row I5,
      which measured the piped-`while read` spelling; the rule matches the loop keyword in
      COMMAND POSITION, so the unpiped spellings of the same denied shape are caught too).

      IR1/IR2 are matched BY NAME and scoped to a loop the scanner can measure — read the
      NON-GOALS block below before reading either as total coverage (the #480 review): a helper
      reached through a VARIABLE or a FUNCTION wrapper, a loop-equivalent per-item wrapper
      by another head (`xargs -I{}`, `find -exec`), a `select … in` loop, and an opener whose
      `done` is absent from the fence are all NOT flagged, and each is disclosed there.
      "A limit mistaken for coverage is how a guard lies" — that applies to this docstring.
  IR3 a command substitution invoking a label helper — `$(…)`, backtick, or `<(…)`
      process substitution — in ASSIGNMENT, ARGUMENT, or CONDITION position. (Row I6
      measured the ASSIGNMENT spelling; the others are the same shape, unmeasured, and
      flagged deliberately — a guard that knows one spelling of what it forbids is a hole.)
  IR5 a `>`/`>>`/`2>`/`&>` redirect — attached or space-separated — whose target begins
      with `/tmp/` (issue #915). Mirrors the review tier's R3 REDIRECT arm exactly, by
      calling the same module-level `_redirect_violation`, so both profiles share one
      tested target-extraction path. IR5 does NOT inherit R3's `cat`-headed heredoc arm
      (row 12 records a plain heredoc write PERMITTED on this tier). Its arm scope and
      the "a later PERMITTED probe does not retire it" rationale are stated in full in
      the implement-tier NON-GOALS block below.
"""

from __future__ import annotations

import importlib.util
import os
import re
import sys

# Reuse the issue-#363 extractor's fence/quote/heredoc/substitution machinery so
# the two guards can never disagree about what a "statement" is.
_HEADS_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "extract-command-heads.py")
_spec = importlib.util.spec_from_file_location("extract_command_heads", _HEADS_PATH)
# `spec_from_file_location` returns None when it can find no loader for the path's
# suffix, so without this the failure is `AttributeError: 'NoneType' object has no
# attribute 'loader'` at IMPORT — loud but naming nothing. This module is reached at
# import by lib/test/cloud_writer_contract.py, which the pre-agent validator
# (scripts/validate-cloud-writer-contract.py) imports, so that unactionable shape
# would surface there. Guarded here as well as at that caller: guarding only the
# caller leaves this hop, one level down, still able to produce it.
if _spec is None or _spec.loader is None:
    raise ImportError(f"devflow: cannot load sibling helper {_HEADS_PATH}")
_heads = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_heads)

_ASSIGNMENT = _heads._ASSIGNMENT
_HEREDOC = _heads._HEREDOC

_INTERPRETERS = frozenset({"python3", "python", "node"})

# A redirection token: an optional fd/`&` then `>`/`>>`/`>|`, with the target
# either attached (`2>/tmp/f`) or in the next token (`> /tmp/f`).
_REDIR = re.compile(r"^&?[0-9]*(>>|>\||>)(.*)$")

def _strip_line_comment(line: str, quote: str | None = None) -> tuple[str, str | None]:
    """Drop a quote-aware `#` comment from one line. Returns `(cleaned, quote_state_out)`.

    `quote` carries the open-quote state IN from the previous line. A shell string spans
    lines, so a `#`-leading line INSIDE a multi-line double-quoted argument is argument
    text, not a comment — stripping it would hide any capture on it. But carrying state is
    not safe alone either (one unbalanced apostrophe would stop every later comment being
    stripped), so the IMPLEMENT scan (`find_implement_violations`) runs `_preprocess` BOTH
    ways and unions the hits — see `_mask_quoted_lines`, which makes the same trade for the
    loop scan. The review tier (`find_violations`) runs the per-line form only.
    """
    kept: list[str] = []
    prev = ""
    for ch in line:
        if quote:
            kept.append(ch)
            if ch == quote and prev != "\\":
                quote = None
        elif ch in ("'", '"'):
            quote = ch
            kept.append(ch)
        elif ch == "#" and (prev == "" or prev.isspace()):
            break
        else:
            kept.append(ch)
        prev = ch
    return "".join(kept), quote


def _shape_preprocess_lines(block: str) -> list[str]:
    """Comment- and heredoc-clean a fence block, LINE-PRESERVING: exactly one cleaned line per
    input line, so a caller that reports a block-relative line offset (the implement-
    tier loop scan) can clean the source and still attribute a hit to the right line.

    A heredoc BODY line is blanked to `""` rather than dropped — dropping it is what
    makes the joined form unusable for offset attribution. Blanking is equivalent for
    statement splitting (an empty line yields no statement).

    It KEEPS the heredoc OPENER token (`<<'EOF'`) so a `cat > f <<'EOF'` write is still one
    statement — differing from extract-command-heads.py's stripper, which truncates the opener
    at `<<` and so erases the very signal R3's cat-heredoc arm needs.

    BOTH TIERS READ THIS TEXT — the review rules (R1-R4) as well as the implement rules — so a
    change here moves both. The blank-vs-drop line preservation is behavior-preserving; the two
    heredoc rules below are a strict TIGHTENING (a statement that used to be silently swallowed
    is now scanned), never a loosening.

    Two heredoc rules, both fail-CLOSED against a MISSED shape (a preprocessor that blanks what
    it cannot measure silently disarms every rule downstream of it — the worst failure this file
    can have, because it is invisible):

    * The opener is matched on the QUOTE-MASKED line, so a `<<` inside a string
      (`echo "see << EOF for details"`) cannot open a PHANTOM heredoc. The mask deliberately
      leaves a `$( … )` inside double quotes VISIBLE (see `_mask_quoted`), because that interior
      is code: without it the `--body "$(cat <<'EOF' … EOF)"` idiom — the one the guarded fences
      actually write — was not seen as a heredoc at all, its body was never blanked, and the
      issue-body PROSE inside it was scanned as shell (the #480 review).
    * An opener whose terminator never appears in the block is NOT treated as a heredoc
      at all: its tail is scanned as ordinary shell. Blanking to end-of-block on an
      unterminated tag — an elided body, a `…` placeholder, a typo, all routine in the
      DOCUMENTATION fences this lint exists to scan — would blank the rest of the fence
      and let a denied shape below it ship green.

    Fail-closed here means "never hides a denied shape". It does NOT mean "never reports an inert
    one": both rules can over-report (an unterminated-heredoc body is scanned as shell), and that
    is the direction chosen deliberately.
    """
    return _preprocess(block, carry_comments=False)[0]


def _preprocess(block: str, carry_comments: bool = False) -> tuple[list[str], list[int]]:
    """The single heredoc/comment scan. Returns `(cleaned_lines, expanding_body_offsets)`,
    where the second element lists the body lines of an UNQUOTED heredoc.

    Why that second list exists: a heredoc body is blanked because its text is DATA, not
    shell — a `for … done` written in one is inert. But that is only true of the text as
    *commands*. With an UNQUOTED delimiter (`<<EOF`, not `<<'EOF'`) the shell still expands
    command substitutions inside the body, so `$(apply-labels.sh …)` in there is a real,
    executed capture — the I6 denied shape — while a blanked body hides it from every rule.
    IR3 therefore re-scans exactly these lines (see `find_implement_violations`), while the
    loop rules keep ignoring them, which is correct for both.
    """
    raw_lines = block.split("\n")
    n = len(raw_lines)
    out: list[str] = []
    _q: str | None = None
    for _line in raw_lines:
        _cleaned, _q_out = _strip_line_comment(_line, _q if carry_comments else None)
        out.append(_cleaned)
        _q = _q_out
    expanding: list[int] = []
    # Quote state CARRIED across lines, for the second of the two opener probes below. A shell
    # string spans newlines, so a `--body "…"` argument that opens on one line and closes on a
    # later one leaves its middle lines inside the string — and a per-line mask, which restarts
    # with an empty stack on every line, reads that prose as top-level CODE.
    carry_stack: list[list] = []
    i = 0
    while i < n:
        cleaned = out[i]
        # BLANK ONLY ON AGREEMENT between the per-line mask and the carry-state mask. Blanking is
        # the one preprocessing act that DELETES code from the scan, so its false-positive
        # direction is a silent GREEN on every rule downstream (R1-R4, IR1-IR5) — the worst
        # failure this file can have. The two masks are each blind where the other sees, so for
        # blanking the fail-closed combination is their INTERSECTION, not their union (the loop
        # scan, whose miss only hides a loop keyword, correctly unions instead):
        #
        #   * per-line alone: a `<<` inside a MULTI-LINE string is unmasked on the continuation
        #     lines and opens a PHANTOM heredoc whose tag matches a real terminator further down,
        #     blanking every statement between — a denied shape in there shipped GREEN, on both
        #     tiers (the #480 review; the ordinary `gh pr comment --body "…prose…"` shape these
        #     prose-heavy fences are full of).
        #   * carried alone: one unbalanced apostrophe in prose opens a span that never closes and
        #     suppresses every later opener — a real heredoc body would then be scanned as shell.
        #
        # Requiring both to see the SAME opener means a genuine `--body "$(cat <<'EOF'` (balanced
        # at that point in the fence) still blanks its body, while prose inside an open string
        # never opens anything. The residual is an over-report (a string's lines scanned as
        # shell), which is the direction this file elects everywhere else.
        #
        # Masking preserves length, so the probe's offset is valid in `cleaned`; re-search
        # the ORIGINAL there to read the real tag (a quoted tag, `<<'EOF'`, is itself
        # masked, so the probe's own group(2) cannot be trusted).
        per_line = _HEREDOC.search(_mask_quoted(cleaned))
        carried_masked, carry_next = _mask_quoted_stateful(cleaned, carry_stack)
        carried = _HEREDOC.search(carried_masked)
        agree = per_line and carried and per_line.start() == carried.start()
        probe = per_line if agree else None
        match = _HEREDOC.search(cleaned, probe.start()) if probe else None
        if not match:
            carry_stack = carry_next  # not an opener: the string state flows to the next line
            i += 1
            continue
        # An opener consumes the rest of the logical command, so quote state does not carry past
        # it — the body is data and the terminator restarts ordinary parsing.
        carry_stack = []
        tag = match.group(2)
        close = next(
            (j for j in range(i + 1, n) if raw_lines[j].strip() == tag), None
        )
        if close is None:
            i += 1  # unterminated: NOT a heredoc — fail closed, keep scanning the tail
            continue
        if not match.group(1):  # unquoted tag ⇒ the shell EXPANDS substitutions in the body
            expanding.extend(range(i + 1, close))
        for k in range(i + 1, close + 1):  # body + terminator (opener token retained)
            out[k] = ""
        i = close + 1
    return out, expanding


def _statements(block: str) -> list[str]:
    """Every logical statement of a fence block, substitutions descended into."""
    return _statements_from_lines(_shape_preprocess_lines(block))


def _statements_from_lines(clean_lines: list[str]) -> list[str]:
    """`_statements`, from lines a caller already preprocessed (so the implement-tier scan
    can union two different comment-strippings without re-deriving them)."""
    cleaned = _heads._strip_case_patterns("\n".join(clean_lines))
    joined = _heads._join_continuations(cleaned)
    result: list[str] = []
    _collect_statements(joined, result)
    return result


def _collect_statements(text: str, out: list[str]) -> None:
    for statement in _heads._split_statements(text):
        for body in _heads._substitutions(statement):
            _collect_statements(body, out)
        out.append(statement)


def _is_command_token(token: str) -> bool:
    """True when a token is a plausible command head (not an assignment, redirect,
    heredoc opener, separator remnant, or shell syntax word)."""
    if not token or _ASSIGNMENT.match(token):
        return False
    if _REDIR.match(token) or token.startswith(("<<", "<")):
        return False
    norm = _heads._normalize(token)
    return not (not norm or norm in _heads.RESERVED)


# Control words that may legally precede a command (or an assignment-capture) in a
# condition. Stripped before the shape check so `elif WP=$(cmd)` is read as its
# `WP=$(cmd)` capture, not misread as a bare-`elif` head.
_CONTROL_PREFIX = re.compile(r"^(?:if|elif|while|until|!)\s+")


def _leading_substitution_split(value: str):
    """For an assignment value beginning `$(` or `"$(`, find where that leading
    substitution ends and return `(balanced, rest_after_it)`; return None when the
    value does not begin with one. The walk tracks paren depth with single/double
    quote and backslash awareness, so a capture whose inner command carries its own
    quoted arguments is measured by its real closing paren, not the first `)`."""
    v = value.lstrip()
    quoted = v.startswith('"$(')
    if not (v.startswith("$(") or quoted):
        return None
    i = 3 if quoted else 2  # first char inside the substitution
    depth = 1
    in_d = in_s = False
    while i < len(v):
        c = v[i]
        if in_s:
            if c == "'":
                in_s = False
        elif c == "\\":
            i += 1  # skip the escaped char (no escapes exist inside single quotes)
        elif in_d:
            if c == '"':
                in_d = False
        elif c == "'":
            in_s = True
        elif c == '"':
            in_d = True
        elif c == "(":
            depth += 1
        elif c == ")":
            depth -= 1
            if depth == 0:
                i += 1
                if quoted:
                    if i < len(v) and v[i] == '"':
                        i += 1
                    else:  # `"$(…)` never re-closed its quote — not a clean capture
                        return (False, v[i:])
                return (True, v[i:])
        i += 1
    return (False, "")


def _strip_control(raw: str) -> str:
    """Iteratively strip leading control words (`if`/`elif`/`!`/…) so a wrapped
    `VAR=$(cmd)` capture reads as its bare assignment.

    Used by the review-tier `_assignment_violation` ONLY. The implement-tier
    `_label_capture_violation` deliberately does not call it: IR3 scans the substitution
    bodies of the WHOLE statement, so a leading control word is already irrelevant there —
    which is exactly what lets it catch `if [ -n "$(…)" ]` and `export LBL=$(…)` for free."""
    while True:
        stripped = _CONTROL_PREFIX.sub("", raw, count=1)
        if stripped == raw:
            return raw
        raw = stripped.lstrip()


def _assignment_violation(statement: str) -> bool:
    raw = statement.strip()
    # Strip leading control words so `elif WP=$(cmd)` reads as its `WP=$(cmd)` capture.
    raw = _strip_control(raw)
    lead = re.match(r"^([A-Za-z_][A-Za-z0-9_]*=)(.*)$", raw, re.DOTALL)
    if not lead:
        return False
    value_rest = lead.group(2)
    # Substitution-valued assignment: `VAR=$(…)` / `VAR="$(…)"`. A PURE capture (the
    # substitution spans the whole statement) is permitted — the matcher descends into
    # the substitution and matches the inner granted head; real-run evidence: run
    # 29105381021 seeded its progress comment through a `WP=$(vendored-path create …)`
    # call. But the same value followed by a command token — `M=$(x) printf hi` — is
    # the denied leading-`VAR=value` env-prefix shape exactly like a literal value
    # (the pre-fix version exempted EVERY `$(`-value here before checking for a
    # following command — the fail-open the PR #397 review caught). The split is done
    # by a quote-aware balanced scan, NOT the tokenizer, because a capture whose inner
    # command carries its own double quotes (`TELEM="$(… "$WORKPAD_DIR" …)"`) splinters
    # under naive tokenization.
    sub = _leading_substitution_split(value_rest)
    if sub is not None:
        balanced, rest = sub
        if balanced and not rest.strip():
            return False
        if balanced:
            # A chain of further assignments (`M=$(x) N=1 cmd`) is still the same
            # env-prefix compound — skip assignment tokens (each of which may itself
            # carry a substitution value) and judge the first non-assignment token.
            rest_s = rest.lstrip()
            while True:
                chain = re.match(r"^[A-Za-z_][A-Za-z0-9_]*=", rest_s)
                if not chain:
                    break
                tail = rest_s[chain.end():]
                nested = _leading_substitution_split(tail)
                if nested is not None:
                    n_balanced, n_rest = nested
                    if not n_balanced:
                        return True  # fail closed on an unmeasurable chain
                    rest_s = n_rest.lstrip()
                else:
                    parts = tail.split(None, 1)
                    rest_s = parts[1].lstrip() if len(parts) > 1 else ""
            if not rest_s:
                return False  # a chain of captures/assignments with no command
            return _is_command_token(rest_s.split(None, 1)[0])
        # Unbalanced leading substitution inside one statement: a splitting artifact
        # or crafted input. Fail CLOSED — flag rather than exempt what the scan could
        # not measure (a guard that shrugs here re-opens the fail-open).
        return True
    # R1b standalone computed literal: `VAR="…"` whose double-quoted content is
    # non-empty. A bare-word constant (`VAR=critical`), a numeric (`n=0`), a status
    # capture (`rc=$?`), an ANSI-C sentinel (`VAR=$'…'`), and an empty reset
    # (`WP=""` / `IFS=`) are all deliberately NOT this shape.
    if value_rest.startswith('"'):
        after = value_rest[1:]
        inner = after.split('"', 1)[0] if '"' in after else after
        return bool(inner.strip())
    # R1a env-prefix compound with a literal value: a NON-EMPTY assignment value
    # followed by a real command (`M=x printf …`, probe row 2). `IFS= read …` — an
    # EMPTY-valued prefix, the pure-shell field-split idiom — is not this shape and
    # never fires. (Literal values tokenize reliably; the substitution-valued arm was
    # handled above by the balanced scan.)
    tokens = _heads._tokenize(raw)
    if not tokens or not _ASSIGNMENT.match(tokens[0]):
        return False
    first_value = tokens[0].split("=", 1)[1]
    j = 0
    while j < len(tokens) and _ASSIGNMENT.match(tokens[j]):
        j += 1
    following = tokens[j:]
    return bool(first_value) and bool(following) and _is_command_token(following[0])


def _redirect_violation(statement: str) -> bool:
    tokens = _heads._tokenize(statement)
    for idx, tok in enumerate(tokens):
        m = _REDIR.match(tok)
        if not m:
            continue
        target = m.group(2)
        if not target:
            # A space-separated redirect (`> /tmp/f`, `2> /tmp/f`) carries its target in
            # the NEXT token; attached forms (`>/tmp/f`, `2>/tmp/f`, `&>/tmp/f`) already
            # carry it in group(2) above.
            target = tokens[idx + 1] if idx + 1 < len(tokens) else ""
        target = target.strip("'\"")
        if target.startswith("/tmp/"):
            return True
    return False


def _workspace_scratch_redirect(statement: str) -> bool:
    """Whether a redirect targets repo-local `.prflow/tmp/**` on an unmeasured form.

    Two arms, each scoped to what has actually been measured on the implement tier:

    * STDERR (`2>`/`&>`) — no head buys an exemption; every head whose statement carries
      one is flagged. Issue #1721 measured
      `workpad.py acs-resolve … 2>.prflow/tmp/review/<slug>/<run-id>/acs.err` DENIED on
      a cloud run ("Output redirection … was blocked"), so a non-gh head buys no
      exemption here. Do not re-narrow this arm to the gh family: the shipped fences the
      issue rewrote were non-gh stderr captures, and a gh-only rule lets the exact denied
      shape back in with the suite green.
    * STDOUT (`>`/`>>`) — flagged for the gh family only. Probe row 11 measured a non-gh
      repo-relative stdout redirect PERMITTED (`echo … > .prflow/tmp/…`), so a blanket
      stdout ban would forbid a proven form; issue #1514 keeps the unmeasured gh-family
      stdout shapes on the Write-default path, which is why row 19's own gh form
      (`gh issue view … > .prflow/tmp/…`) is flagged rather than exempted.

    Residuals this predicate does not reach: a target spelled through the anchored
    `<scratch-dir>/` form or through a shell variable, and a multi-digit fd word (`02>`).
    """
    head = _heads._head_of(statement)
    if not head:
        return False
    is_gh = _heads._is_gh_head(head[0])
    tokens = _heads._tokenize(statement)
    for idx, tok in enumerate(tokens):
        match = _REDIR.match(tok)
        if not match:
            continue
        # An `&>`/`2>`-style token carries its fd (or `&`) before the operator; a bare
        # `>`/`>>` carries none. Anything that writes fd 2 is the stderr arm.
        prefix = tok[: match.start(1)]
        is_stderr = prefix.startswith("&") or prefix == "2"
        if not (is_stderr or is_gh):
            continue
        target = match.group(2) or (tokens[idx + 1] if idx + 1 < len(tokens) else "")
        target = target.strip("'\"")
        if target.startswith(".prflow/tmp/") or "/.prflow/tmp/" in target:
            return True
    return False


def _cat_heredoc_violation(statement: str) -> bool:
    head = _heads._head_of(statement)
    if not head or head[0] != "cat":
        return False
    tokens = _heads._tokenize(statement)
    has_redirect = any(_REDIR.match(t) for t in tokens)
    has_heredoc = any(t.startswith("<<") for t in tokens)
    return has_redirect and has_heredoc


# (R5 — a command-substitution assignment used as an `if`/`elif` CONDITION,
# issue #857 — was RETIRED in issue #869 once matcher-probe.yml's review Shape 18
# (`if VAR=$(granted-helper …)`) recorded PERMITTED (run 30310938175, review
# `probe` job, 2026-07-27): the shape the discipline guarded against is
# cloud-permitted, so the rule and its finder no longer exist.)


# The two profiles' rule-id sets, exported so a consumer that must enumerate the
# tables (lib/test/cloud_writer_contract.py's AC4 shape-conformance guard, issue
# #678) reads them from here rather than mirroring the ids into a second list that
# silently goes stale when a rule is added. The `#678 AC8` control loop in
# lib/test/test_python_scripts.py drives one planted violation per id listed here
# and asserts the owning finder emits it, so listing an id no finder emits turns
# the suite RED; its companion `a planted control exists for every rule id`
# assertion turns the reverse drift RED — a rule added to a finder and to these
# sets without a control.
def _leading_cd(statement: str) -> bool:
    """A statement whose command HEAD is `cd` — review R2 and implement IR4 are the
    same underlying "no leading `cd`" rule, so both call this one predicate rather
    than each inlining the head test (which would let the two profiles' notion of a
    leading `cd` drift). `cd` in argument position, and a `cd`-prefixed head like
    `cdparanoia`, do not match."""
    head = _heads._head_of(statement)
    return bool(head and head[0] == "cd")


def _interpreter_violation(statement: str) -> bool:
    """R4's arm predicate: an interpreter head."""
    head = _heads._head_of(statement)
    return bool(head and head[0] in _INTERPRETERS)


# ── The review profile's ONE arm table (issue #805) ───────────────────────────
# Every review-profile enumeration below is DERIVED from this table — the rule-id set,
# the arm set, the rule-granularity classifier, and the arm-granularity classifier the
# scripts/pretooluse-shape-guard.py deny set resolves through. They were four hand-
# maintained mirrors: `classify()` and `classify_arms()` carried byte-for-byte duplicate
# predicate chains with nothing asserting they agreed, and `REVIEW_ARMS` was a re-typed
# literal with no derivation from `REVIEW_RULES`. An `R5` added to one of the four then
# passed the whole suite while the guard's only runtime classifier stayed blind to it.
# Rows are (arm id, rule id, predicate) in EMISSION ORDER — both classifiers walk this
# tuple in order, so the returned sequences cannot drift apart either.
#
# ARM vs RULE granularity: R3 is the one rule with two arms. Its `/tmp`-target redirect
# arm (`R3-tmp`) is probe-denied, so a runtime deny is warranted; its in-workspace
# `cat`-heredoc arm (`R3-heredoc`) is banned only as authoring discipline, and a runtime
# deny there would cost the engine a shape the harness permits. `classify()` collapses
# both onto `R3`; `classify_arms()` keeps them apart. The arm identifiers are the JOIN KEY
# between the guard's remediation table and the permitted alternatives
# docs/internal/cloud-allowlist.md records; every other rule maps one-to-one to an arm of the same
# name.
_REVIEW_ARM_TABLE = (
    ("R1", "R1", _assignment_violation),
    ("R2", "R2", _leading_cd),
    ("R3-tmp", "R3", _redirect_violation),
    ("R3-heredoc", "R3", _cat_heredoc_violation),
    ("R4", "R4", _interpreter_violation),
)

REVIEW_ARMS = frozenset(arm for arm, _rule, _pred in _REVIEW_ARM_TABLE)
REVIEW_RULES = frozenset(rule for _arm, rule, _pred in _REVIEW_ARM_TABLE)
IMPLEMENT_RULES = frozenset({"IR1", "IR2", "IR3", "IR4", "IR5", "IR6"})


def classify(statement: str) -> list[str]:
    """Return the rule ids this statement violates (possibly several)."""
    hits: list[str] = []
    for _arm, rule, pred in _REVIEW_ARM_TABLE:
        if pred(statement) and rule not in hits:
            hits.append(rule)
    return hits


def classify_arms(statement: str) -> list[str]:
    """Return the ARM identifiers this statement matches (possibly several).

    R3 is split into `R3-tmp` (a `/tmp`-target `>`/`>>` redirect — probe-denied) and
    `R3-heredoc` (a `cat`-headed heredoc write — lint discipline, not a probe result).
    R1/R2/R4 each map to an arm of the same name. Derived from the same
    `_REVIEW_ARM_TABLE` as `classify()`, so the two cannot disagree about which
    statements violate what.
    """
    return [arm for arm, _rule, pred in _REVIEW_ARM_TABLE if pred(statement)]


def _fence_line_offsets(text: str) -> list[tuple[int, str]]:
    """Return (1-based line number, block-body) for every ```bash fence."""
    blocks: list[tuple[int, str]] = []
    body: list[str] | None = None
    start = 0
    for lineno, line in enumerate(text.splitlines(), start=1):
        stripped = line.strip()
        if body is None:
            if stripped == "```bash":
                body = []
                start = lineno + 1
            continue
        if stripped == "```":
            blocks.append((start, "\n".join(body)))
            body = None
            continue
        body.append(line)
    return blocks


def _attribute_line(statement: str, start: int, block_line_count: int,
                    lines: list[str]) -> int:
    """Best-effort line attribution: the source line of the statement's first line-
    fragment found verbatim in the fence's source lines, else the fence start. Shared
    by `find_violations` and `find_implement_violations` so the two profiles'
    attribution cannot drift."""
    probe = statement.strip().split("\n", 1)[0][:40]
    for off in range(block_line_count):
        src_idx = start - 1 + off
        if src_idx >= len(lines):
            break
        if probe and probe in lines[src_idx]:
            return start + off
    return start


def find_violations(text: str) -> list[tuple[int, str, str]]:
    """Every (approx line, rule, statement) denied-shape hit in the file's fences."""
    lines = text.splitlines()
    hits: list[tuple[int, str, str]] = []
    for start, block in _fence_line_offsets(text):
        for statement in _statements(block):
            rules = classify(statement)
            if not rules:
                continue
            lineno = _attribute_line(statement, start, len(block.split("\n")), lines)
            for rule in rules:
                hits.append((lineno, rule, statement.strip()))
    return hits


# ── The `no-expansion-redirect` profile (issue #2082) ─────────────────────────
# A profile independent of the three cloud-tier profiles above, used by the suite to
# prove a fence region carries NO `$VAR`/`${VAR}` parameter expansion and NO shell
# redirect — the shapes the cloud matcher denies in the "Contains expansion" /
# redirect classes. The review engine's dirty-tree snapshot/restore fences were
# rewritten to plain granted-helper invocations (issue #2082) precisely so this scan
# reports clean over them; run over the two fence regions it fails against the old
# expansion/redirect-bearing text and passes against the helper-invocation form.
#
# The rule ids are DELIBERATELY outside the `R\d+`/`IR\d+`/`CR\d+` namespaces so the
# #678 AC8 source-reconciliation (which regex-scans this module for those id shapes)
# and cloud_writer_contract.PROFILE_SHAPE_TABLES (keyed on the three cloud tiers) are
# untouched — this profile governs no cloud tier and grants nothing.
_PARAM_EXPANSION_START = frozenset("_?@*#!-0123456789")
_ANY_REDIR = re.compile(r"^&?[0-9]*(?:>>|>\||>|<<-|<<|<)")


def _expansion_violation(statement: str) -> bool:
    """A `$VAR` / `${VAR}` parameter expansion in the statement — NOT a `$(…)` command
    substitution (a different shape). Single-quoted spans are masked first so a literal
    `$` inside `'…'` is not read as an expansion."""
    masked = _mask_single_quoted(statement)
    for match in re.finditer(r"\$", masked):
        nxt = masked[match.start() + 1 : match.start() + 2]
        if nxt == "(":
            continue  # command substitution — not the parameter-expansion shape this flags
        if nxt == "{" or (nxt and (nxt.isalpha() or nxt in _PARAM_EXPANSION_START)):
            return True
    return False


def _any_redirect_violation(statement: str) -> bool:
    """Any shell redirect operator (`>`/`>>`/`>|`/`<`/`<<`, with an optional fd or `&`),
    attached or space-separated, to ANY target — the whole redirect class, not just the
    `/tmp` target R3/IR5 flag."""
    return any(_ANY_REDIR.match(tok) for tok in _heads._tokenize(statement))


def find_expansion_redirect_violations(text: str) -> list[tuple[int, str, str]]:
    """Every (approx line, rule, statement) `EXPANSION`/`REDIRECT` hit in the file's fences."""
    lines = text.splitlines()
    hits: list[tuple[int, str, str]] = []
    for start, block in _fence_line_offsets(text):
        for statement in _statements(block):
            rules: list[str] = []
            if _expansion_violation(statement):
                rules.append("EXPANSION")
            if _any_redirect_violation(statement):
                rules.append("REDIRECT")
            if not rules:
                continue
            lineno = _attribute_line(statement, start, len(block.split("\n")), lines)
            for rule in rules:
                hits.append((lineno, rule, statement.strip()))
    return hits


# ── Implement-tier rules (issue #450 -> #455) ────────────────────────────────
# The read-write `devflow-implement` profile is a SEPARATE allowlist from the
# read-only `review` profile the rules above target, with its OWN empirically
# probed denied shapes (matcher-probe.yml's implement-probe job; evidence of record
# on issues #450/#455). The label helpers ensure-label.sh / apply-labels.sh ARE
# granted as vendored literals, but the matcher denies WRAPPING them in a `for` /
# piped-`while read` loop or a `VAR="$(…)"` output capture (probe rows I4/I5/I6). The
# rules below pin exactly those wrappers AROUND A LABEL HELPER, so the agent-level rework of
# all four label channels (Phase 3.1's provenance apply, 4.0/4.0.5's deferred applies, 4.1's
# docs apply) cannot silently regress.
#
# SCOPE BOUNDARY — and it rests on an INFERENCE, not a measurement. A loop or capture
# of any OTHER command (config-get.sh, gh) is NOT flagged, because the implement skill
# legitimately uses that shape (`DEFERRED_LABELS=$(…config-get.sh …)`) and we infer the
# matcher descends into a non-label `$(…)` and matches the inner granted head. That
# inference is carried over from the REVIEW tier (run 29105381021's `WP=$(vendored-path
# create …)` executed), and this file's own rule is that a shape proven on the review
# tier is UNPROVEN here. No implement-tier row has ever measured a non-label capture,
# and the only capture row that WAS measured — I6 — came back DENIED while confounding
# three properties at once (a label helper AND a `VAR="$(…)"` capture AND an inner
# `2>&1`). So if I6's denial is attributable to the capture SHAPE, the reworked fences'
# own `config-get.sh` read is silently denied too and these rules would not catch it.
# matcher-probe.yml rows 8 (non-label capture) and 9 (redirect-free label capture) are
# the disambiguators; until a dispatch records them, treat the non-label carve-out as a
# stated inference and NOT as probe-proven — and keep the phase-4 fences fail-closed on
# a config read that produces no output (a denied command and an empty value must not
# look the same to the agent).
#
# NON-GOALS (stated, not accidental — a limit mistaken for coverage is how a guard lies):
#  * The rules match the helper by NAME, so a label helper reached through a VARIABLE
#    (`H=…/apply-labels.sh; for n in …; do "$H" "$n"; done`) is not flagged. Inherent to a
#    name-literal desk lint — resolving it needs dataflow — and the skill files never write it.
#    The same limit covers a FUNCTION wrapper (`lbl() { …/apply-labels.sh "$1" X; }; for n in …;
#    do lbl "$n"; done`) — same dataflow gap, same disclosure.
#  * A LOOP-EQUIVALENT per-item wrapper by another head — `… | xargs -I{} …/apply-labels.sh {} X`,
#    `find … -exec …/apply-labels.sh …` — is not flagged either. It has the same "the helper is
#    not the leading token" property the probe measured for I4/I5/I6, and `xargs` IS granted, so
#    whether the matcher permits it is precisely UNMEASURED. Not flagged on no evidence; disclosed
#    rather than silently missing. A probe row would settle it.
#  * `select … in` is not matched (never probed, never written here).
#  * IR5 (issue #915) flags a `/tmp/`-targeted redirect on the strength of row 11's
#    proven-permitted `.prflow/tmp/` ALTERNATIVE, NOT a measured denial of each redirect
#    arm: only the spaced-stdout `> /tmp/f` (row 10) is measured DENIED on this tier, and
#    the attached `2>/tmp/f`/`&>/tmp/f` arms are unmeasured. A later probe returning
#    PERMITTED for one of those arms does NOT narrow or retire IR5 — the rule keeps engine
#    scratch on the one target form measured permitted, so a second permitted form does not
#    make `/tmp` acceptable. IR5 also does NOT inherit R3's cat-heredoc arm (row 12 records
#    a plain heredoc write PERMITTED here), so it calls `_redirect_violation` alone.
#  * IR3's rescan of an UNQUOTED heredoc body is LINE-SCOPED: it re-reads each expanding body
#    line on its own, so a capture whose `$(` opens on one body line and whose helper name sits
#    on the NEXT is not flagged. (A multi-line capture in ordinary code IS caught — the statement
#    splitter joins it; this limit is specific to the heredoc-body rescan.) No fence writes it.
#  * The STATEMENT SPLITTER (shared with the #363 head extractor) reads a `\` inside `'…'` as an
#    escape, but the shell honours no escapes in single quotes. So a line ending `'…\'` leaves the
#    splitter's quote parity open, and a following statement can be absorbed into that phantom
#    string and never scanned. The heredoc-opener MASK no longer has this bug (an escaped `\\`
#    before a quote, and a `\` inside `'…'`, are both handled — pinned), but the splitter does,
#    and fixing it there would move the #363 head lint as well. Disclosed, not silently missed:
#    no fence writes a single-quoted trailing backslash, and the direction is a lost statement
#    (a silent GREEN), so it is the one limit here worth closing next.
#  * The mask's paren-depth counter inside a `$( … )` counts parens, not `case` syntax, so an
#    unbalanced arm-closing `)` there (`"$(case $x in a) echo hi;; esac)"`) closes the frame early
#    and the line's tail reads as top-level code. No fence writes a `case` inside a substitution.
#  * A heredoc opener inside a BACKTICK substitution in double quotes (`--body "` … `cat <<'EOF'`
#    … `"`) is masked, so its body is scanned as shell — an over-report (a false RED), never a
#    hidden denied shape. Only `$( … )` opens a code frame in the mask.
#
# Probe row I1 (the unexpanded `${CLAUDE_SKILL_DIR:-…}` anchor as a leading token) is
# deliberately NOT a rule here: every legitimate helper call keeps the portable
# anchor in source (issue #275) and resolves it to the vendored literal at runtime,
# so a fence-static rule would flag every call site. It is a prose-discipline rule
# (the skill's *Cloud command-shape discipline* + *Cloud helper-invocation form*
# sections), exactly as the unexpanded-anchor case is handled in the review skill.

_LABEL_HELPER = re.compile(r"(?:apply-labels|ensure-label)\.sh\b")


def _substitution_bodies(value: str) -> list[str]:
    """Every command-substitution body in a shell fragment — the `$( … )` form
    (paren-balanced) and the backtick form, which are the same shape spelled two ways.

    The fragment is whatever the caller passes: an assignment's right-hand side, or (as
    IR3 does) a WHOLE statement — which is what lets IR3 see a capture in argument or
    condition position, not only one behind a `VAR=`.

    SINGLE-quoted spans are masked out first: a backtick or `$(` inside `'…'` is literal
    text, not a substitution (`NOTE='runs `once`'`). Double-quoted spans are NOT masked —
    `"$(cmd)"` is a real substitution, and it is the exact form the denied shape uses.
    Masking preserves length, so offsets into `value` stay valid.
    """
    # Mask SINGLE-quoted spans only, double-quote-aware (see `_mask_single_quoted`): inside
    # `"…"` a `$(…)` IS a substitution — it is the denied shape's own spelling — and a `'`
    # there is just an apostrophe, not a quote opener.
    masked = _mask_single_quoted(value)
    bodies: list[str] = []
    i = 0
    n = len(value)
    while i < n:
        # `<(…)` / `>(…)` process substitution: the same denied shape — the label helper is not
        # the leading token of the tool call — and it is exactly how an author told "no `$( )`
        # capture" re-introduces the capture (`mapfile -t X < <(apply-labels.sh …)`,
        # `gh issue comment -F <(apply-labels.sh …)`). Read its body like any substitution.
        if masked[i] in "<>" and masked.startswith("(", i + 1):
            depth = 1
            j = i + 2
            start = j
            while j < n and depth:
                if masked[j] == "(":
                    depth += 1
                elif masked[j] == ")":
                    depth -= 1
                j += 1
            bodies.append(value[start : j - 1] if depth == 0 else value[start:])
            i = j
            continue
        if masked.startswith("$(", i):
            depth = 1
            j = i + 2
            start = j
            while j < n and depth:
                if masked[j] == "(":
                    depth += 1
                elif masked[j] == ")":
                    depth -= 1
                j += 1
            # Unbalanced (`$(` with no close) → take the tail: fail CLOSED, since an
            # unmeasurable capture must not be waved through.
            bodies.append(value[start : j - 1] if depth == 0 else value[start:])
            i = j
        elif masked[i] == "`":
            close = masked.find("`", i + 1)
            bodies.append(value[i + 1 : close] if close != -1 else value[i + 1 :])
            i = (close + 1) if close != -1 else n
        else:
            i += 1
    return bodies


def _label_capture_violation(statement: str) -> bool:
    """IR3: a command substitution that invokes a label helper — `VAR=$(…)`,
    `VAR="$(…)"`, a backtick capture, and equally a capture in ARGUMENT or CONDITION
    position (probe row I6 — the old `LBL_ERR="$(apply-labels.sh … 2>&1)"`).

    Scoped to the whole STATEMENT, not just an assignment's right-hand side. Anchoring
    on `^VAR=` was a fail-open on the most natural regression there is: the removed code
    captured the helper's stderr *in order to put it in a comment body*, so the obvious
    way to re-introduce it is to inline the capture into the argument —
    `gh issue comment -b "$(apply-labels.sh … 2>&1)"` — which is the same denied shape
    with no assignment anywhere. `[ -n "$(ensure-label.sh …)" ]` is the same story.

    The BACKTICK form is likewise the same shape spelled differently. A guard that knows
    only one spelling of what it forbids is a hole an author falls into by accident.

    Scoping (see the rule-block comment above): a capture of a NON-label command is not
    flagged, on the *inference* — not a measurement — that the matcher descends into it.
    """
    # Search the SUBSTITUTION BODIES of the whole statement: the shape is "a capture OF a
    # label helper", so a statement that merely NAMES one outside any substitution — a
    # message string like `MSG="$(date -u) applied via apply-labels.sh"`, or the permitted
    # bare call `apply-labels.sh 1 X` itself — is not this shape and must not be flagged.
    return any(_LABEL_HELPER.search(body) for body in _substitution_bodies(statement))


# A loop keyword only OPENS a loop in COMMAND POSITION — at the start of a statement,
# or right after a separator (`;` `|` `&&` `||` `(` `{`) or a case-arm `)` , a
# negation/wrapper (`!`, `time`),
# or an opening keyword (`do`/`then`/`else`). A bare `\bwhile\b` line match instead fires
# on the word `while` anywhere — including inside a command ARGUMENT (`echo "wait a
# while"`) — and, paired with the span rule below, swallowed every later label call in
# the fence. Callers pass COMMENT-STRIPPED, QUOTE-MASKED lines, so neither a `#` comment
# nor a quoted argument can supply a phantom separator or keyword.
_LOOP_OPENER = re.compile(
    r"(?:^|[;|&({)]|\b(?:do|then|else|time)\b|!)\s*(for|while|until)\b"
)
# `do` / `done` in command position, used to DEPTH-COUNT the span. Counting is what makes
# a NESTED loop safe: taking the first `done` after the opener let an inner one-line loop
# (`for x in a b; do echo; done`) close the OUTER span, so a label call after it fell
# outside and shipped green — a fail-open. `do` never matches inside `done` (the lookahead
# rejects the `n`).
#
# BOTH classes are command-position-anchored (line start or after a separator), NOT a bare
# `\s`. With a bare whitespace lead, an ARGUMENT-position word matched: `echo done` inside a
# loop body decremented the depth to 0, closed the span early, and every label call below it
# in that loop fell outside the scanned range and shipped GREEN — a fail-open. The mirror
# hazard applies to `do` (an argument-position `do` inflates depth, the closing `done` is never
# reached, and the opener is skipped entirely).
#
# `_DONE_TOK`'s trailing class is load-bearing and is the ONLY place `done`-recognition is
# decided. A closing `done` may be followed by a subshell/redirect/pipe close, not just
# whitespace — `(…; done)`, `done>/dev/null`, `done | tee`, `done <labels.txt` are all
# ordinary spellings — and `_loop_violations` SKIPS an opener whose `done` it cannot find.
# So omitting `)`/`<`/`>` here is a FAIL-OPEN: a real label-helper loop closed `done)` is
# silently never scanned, the guard failing open in exactly the direction it exists to
# fail closed.
_DO_TOK = re.compile(r"(?:^\s*|[;|&({]\s*)do(?=$|[;|&\s])")
_DONE_TOK = re.compile(r"(?:^\s*|[;|&({]\s*)done(?=$|[;|&)<>\s])")


def _mask_quoted(line: str) -> str:
    """Replace the CONTENT of quoted spans with `x`, preserving length exactly (callers
    slice the ORIGINAL string using offsets found in the masked one, so any length change
    would silently mis-extract).

    The loop scan is a regex over shell TEXT, so without this a `;`, `(`, or loop keyword
    inside an ordinary argument — `gh issue comment -b "Deferred; while open, do not
    merge"` — reads as a command-position loop opener and starts a phantom span.
    Comment-stripping alone does not cover it: that text is code, just quoted.

    A `$( … )` inside a DOUBLE-quoted span SUSPENDS the string: its interior is CODE, and the
    shell parses it normally — including its own quotes. Both halves of that are load-bearing,
    and getting either wrong is a real defect this masker has already had (the #480 review):

    * Masking the substitution's interior blinded the heredoc-opener probe to the one idiom the
      guarded fences most rely on — `--body "$(cat <<'EOF' … EOF)"`. With the `<<'EOF'` masked
      away no heredoc was detected, the body was never blanked, and the issue-body PROSE inside
      it was scanned as shell, so a follow-up-issue template that merely MENTIONED a label helper
      turned the desk RED pointing at documentation text.
    * Leaving it RAW is worse — a fail-OPEN. Quotes inside the substitution are real quotes, so
      `echo "$(printf '%s' 'usage: cmd << EOF')"` puts a `<<` in a *string*; treating it as code
      opened a PHANTOM heredoc whose tag then matched a real `EOF` line further down, blanking
      every statement between — and a denied shape in there shipped GREEN, on both tiers.

    So the substitution is entered as a code CONTEXT (a stack frame), not as a hole in the mask:
    inside it, `'…'` / `"…"` mask their contents exactly as at top level, nested `$( … )` and
    subshell parens nest, and only the unquoted code is visible. `<<'EOF'` is then seen (the `<<`
    is unquoted code) while `'… << …'` is not (it is a string). The masked TAG is fine: the probe
    only takes an OFFSET from this line and re-reads the real tag from the original.
    """
    return _mask_quoted_stateful(line, [])[0]


def _mask_quoted_stateful(line: str, stack_in: list[list]) -> tuple[str, list[list]]:
    """`_mask_quoted`'s core, with the quote/substitution state threaded IN and OUT.

    A shell string spans newlines, so the heredoc-opener probe needs the state a previous line
    left open (see `_preprocess`, which requires the per-line and carried probes to AGREE before
    it blanks anything). `_mask_quoted` is this with an empty starting state — one implementation,
    so the two can never disagree about what is code and what is string.
    """
    out: list[str] = []
    # Stack of contexts: ("q", <quote char>) for a string span, ("c", <paren depth>) for the
    # interior of a `$( … )`. Empty stack = ordinary top-level code.
    stack: list[list] = [list(frame) for frame in stack_in]
    # ESCAPE STATE, tracked explicitly — NOT as `prev != "\\"`, which is wrong in two directions
    # and each one flips the mask's quote parity away from the shell's, exposing unquoted `<<`
    # text to the heredoc probe and blanking real code (the #480 review):
    #   * a DOUBLED backslash (`echo \\"a << EOF"`) is an escaped backslash — the quote after it
    #     is a REAL quote — but `prev == "\\"` reads it as escaped and never opens the string;
    #   * inside `'…'` the shell honours NO escapes at all, so a trailing `\` there does not
    #     escape the closing quote — but `prev == "\\"` says it does, and the string never closes.
    # Both left a `<<` visible as code, opened a phantom heredoc whose tag matched a real
    # terminator below, and the denied shape in the blanked span shipped GREEN, on both tiers.
    esc = False
    i = 0
    n = len(line)
    while i < n:
        ch = line[i]
        top = stack[-1] if stack else None
        in_string = top is not None and top[0] == "q"
        if esc:  # this character is escaped — never syntax, whatever it is
            out.append("x" if in_string else ch)
            esc = False
            i += 1
            continue
        if in_string:
            quote = top[1]
            if quote == "'":
                # Single quotes are literal through and through: no escapes, no substitutions.
                if ch == "'":
                    stack.pop()
                    out.append(ch)
                else:
                    out.append("x")
            else:
                if ch == "\\":  # escapes ARE honoured inside double quotes
                    esc = True
                    out.append("x")
                elif ch == "$" and i + 1 < n and line[i + 1] == "(":
                    # `$(` inside a double-quoted span opens CODE — the string is suspended.
                    stack.append(["c", 1])
                    out.append(ch)
                    out.append(line[i + 1])
                    i += 2
                    continue
                elif ch == quote:
                    stack.pop()
                    out.append(ch)
                else:
                    out.append("x")  # string content: masked
        else:
            # Top-level code, or the interior of a `$( … )`. Quotes here are real quotes.
            if ch == "\\":
                esc = True
                out.append(ch)
            elif ch in ("'", '"'):
                stack.append(["q", ch])
                out.append(ch)
            elif top is not None and ch == "(":
                top[1] += 1
                out.append(ch)
            elif top is not None and ch == ")":
                top[1] -= 1
                if top[1] <= 0:
                    stack.pop()  # substitution closed — back to the enclosing string
                out.append(ch)
            else:
                out.append(ch)
        i += 1
    return "".join(out), stack


def _mask_quoted_lines(lines: list[str], carry: bool) -> list[str]:
    """Quote-mask a block for the LOOP scan. `carry` selects whether quote state crosses newlines.

    This is a SEPARATE implementation from `_mask_quoted`, deliberately: that one is the
    heredoc-opener probe's masker and leaves the interior of a `$( … )` visible as code, which is
    exactly what a heredoc opener needs. The loop scan wants the opposite — a `;`/`(`/loop keyword
    inside ANY quoted argument must not read as a command-position opener — so it does NOT carry
    that carve-out. Do not "unify" the two: they answer different questions about the same text.

    NEITHER setting is safe alone, which is why `_loop_violations` scans BOTH and unions
    the hits (a loop opener visible under *either* masking is a hit — fail-closed):

    * `carry=False` (per-line): a double-quoted argument that OPENS on one line and CLOSES
      on a later one inverts the closing line's parity — the masker reads the closing `"`
      as an *opening* quote and masks the rest of that line, hiding a loop opener chained
      after it. `phase-4-documentation.md` already writes such arguments
      (`--body "$(cat <<'EOF' … )"`) around the code the removed label loop lived in.
    * `carry=True` (stateful): an UNBALANCED quote — an apostrophe in an ordinary word
      (`echo "the config didn't resolve"` written unquoted, a stray `'` — routine in the
      prose-heavy fences this lint scans) — opens a span that never closes, masking every
      line below it and hiding every loop opener in the rest of the fence.

    Each masking is blind exactly where the other sees, so the union is what actually fails
    closed. The residual cost is a possible spurious RED when a loop keyword AND a label
    helper both sit inside a multi-line quoted string (the per-line pass reads the string's
    later lines as code). That is the safe direction, and no fence writes that shape.
    """
    out: list[str] = []
    quote: str | None = None
    for line in lines:
        if not carry:
            quote = None
        kept: list[str] = []
        prev = ""
        for ch in line:
            if quote:
                if ch == quote and prev != "\\":
                    quote = None
                    kept.append(ch)
                else:
                    kept.append("x")
            elif ch in ("'", '"'):
                quote = ch
                kept.append(ch)
            else:
                kept.append(ch)
            prev = ch
        out.append("".join(kept))
    return out


def _mask_single_quoted(text: str) -> str:
    """Mask the content of `'…'` spans ONLY, tracking double-quote state so a `'` INSIDE a
    double-quoted string is not mistaken for a quote opener.

    This is what `_substitution_bodies` needs, and getting it wrong is a fail-open: with a
    naive single-quote-only scan, an apostrophe inside a double-quoted argument — `gh issue
    comment -b "Doesn't matter: $(apply-labels.sh …)"`, and an English message body
    routinely has one — opens a phantom single-quoted span that never closes, masking the
    `$(` so IR3 never sees the capture. Inside `"…"` a `$(…)` IS a substitution and a `'` is
    just a character; inside `'…'` neither is. Length is preserved (callers slice by offset).
    """
    out: list[str] = []
    in_s = False
    in_d = False
    prev = ""
    for ch in text:
        if in_s:
            if ch == "'":
                in_s = False
                out.append(ch)
            else:
                out.append("x")
        elif in_d:
            out.append(ch)
            if ch == '"' and prev != "\\":
                in_d = False
        elif ch == "'":
            in_s = True
            out.append(ch)
        elif ch == '"':
            in_d = True
            out.append(ch)
        else:
            out.append(ch)
        prev = ch
    return "".join(out)


def _loop_violations(lines: list[str]) -> list[tuple[int, str]]:
    """IR1/IR2: a `for` loop — any spelling, incl. C-style `for ((…))` (IR1) — or a
    `while` / `until` loop (IR2) whose do…done span invokes a label helper (probe rows
    I4/I5). Returns (block-relative line offset of the opener, rule). `lines` MUST be
    comment-stripped/heredoc-blanked
    (`_shape_preprocess_lines`) — scanning raw source made a `#` comment mentioning a
    loop a false hit.

    The span runs from the opener to its OWN closing `done`, INCLUSIVE — `do`/`done` are
    depth-counted, so a NESTED inner loop's `done` cannot close the outer span and hide a
    label call that follows it. A one-line loop (`for f in a b; do …; done`) is closed by
    the `done` on the opener line itself. An opener with NO `done` anywhere in the fence
    is NOT a loop we can measure — it is skipped, never treated as running to end-of-fence
    (that made every later label call in the block a phantom hit of a loop that does not
    exist).
    """
    # SHELL STRUCTURE (loop openers, `done`) is read from the QUOTE-MASKED lines, so a
    # separator or keyword inside a quoted argument cannot fake a loop. The LABEL-HELPER
    # search runs over the UNMASKED lines, because a real denied call routinely sits
    # inside quotes — the removed Phase 4.0 shape was `LBL_ERR="$(… apply-labels.sh …)"`,
    # whose helper name lives inside a double-quoted capture. Masking both would blind
    # IR1/IR2 to precisely the shape they exist to catch. Same length, so offsets align.
    # BOTH maskings are scanned and the hits UNIONED — each is blind exactly where the
    # other sees (see `_mask_quoted_lines`), so only the union fails closed.
    hits_seen: set[tuple[int, str]] = set()
    for masked in (_mask_quoted_lines(lines, carry=True), _mask_quoted_lines(lines, carry=False)):
        for hit in _scan_loops(lines, masked):
            hits_seen.add(hit)
    return sorted(hits_seen)


def _scan_loops(lines: list[str], masked: list[str]) -> list[tuple[int, str]]:
    """One loop scan over one masking of `lines` (see `_loop_violations`, which unions two)."""
    hits: list[tuple[int, str]] = []
    n = len(lines)
    i = 0
    while i < n:
        opener = _LOOP_OPENER.search(masked[i])
        if not opener:
            i += 1
            continue
        rule = "IR1" if opener.group(1) == "for" else "IR2"
        # Walk to the loop's OWN closing `done`, depth-counting `do`/`done` so a nested
        # loop's `done` cannot close this span. On the opener line only the text AFTER the
        # loop keyword counts (a one-line `for …; do …; done` closes on its own line).
        end: int | None = None
        depth = 0
        j = i
        while j < n:
            seg = masked[j][opener.end():] if j == i else masked[j]
            depth += len(_DO_TOK.findall(seg))
            closes = len(_DONE_TOK.findall(seg))
            if closes:
                depth -= closes
                if depth <= 0:
                    end = j
                    break
            j += 1
        if end is None:
            i += 1  # unterminated: not a measurable loop span — do NOT swallow the tail
            continue
        # Search the span's text with `\`-CONTINUATIONS JOINED, not line by line. A helper
        # name split across a continuation (`…/apply\<newline>-labels.sh "$n" X`) is ONE word
        # to the shell but two fragments to a per-line regex, so a line-by-line search found
        # neither and the loop shipped GREEN (the #480 review). Reuse the SAME joiner the statement
        # splitter uses (share the contract — do not re-derive it), so IR1/IR2 and IR3 can
        # never disagree about what text a statement contains.
        span = _heads._join_continuations("\n".join(lines[i:end + 1]))
        if _LABEL_HELPER.search(span):
            hits.append((i, rule))
        i = end + 1
    return hits


def find_implement_violations(text: str) -> list[tuple[int, str, str]]:
    """Every (approx line, rule, statement) implement-tier denied-shape hit."""
    lines = text.splitlines()
    hits: list[tuple[int, str, str]] = []
    for start, block in _fence_line_offsets(text):
        block_lines = block.split("\n")
        seen: set[tuple[int, str, str]] = set()
        # Preprocess BOTH ways and union the hits. The comment stripper has the same
        # per-line-vs-carried quote dilemma the loop mask does: a `#`-leading line INSIDE a
        # multi-line double-quoted argument is argument text (carried is right), but one
        # unbalanced apostrophe would stop every later comment being stripped (per-line is
        # right). Each is blind exactly where the other sees, so only the union fails closed.
        for carry in (False, True):
            clean_lines, expanding = _preprocess(block, carry_comments=carry)
            for statement in _statements_from_lines(clean_lines):
                # IR4 — a leading `cd` (issue #855). The Bash tool's cwd persists
                # across calls and every granted helper literal is repo-relative, so
                # a leading `cd` moves the working directory out from under every
                # later helper. Shares the `_leading_cd` predicate with review R2, so
                # the two profiles' notion of a leading `cd` cannot drift.
                if _leading_cd(statement):
                    lineno = _attribute_line(statement, start, len(block_lines), lines)
                    seen.add((lineno, "IR4", statement.strip()))
                # IR5: a `/tmp/`-targeted redirect (issue #915). Shares R3's
                # `_redirect_violation` target-extraction; the arm scope and its
                # heredoc exclusion are stated once in the NON-GOALS block above.
                if _redirect_violation(statement):
                    lineno = _attribute_line(statement, start, len(block_lines), lines)
                    seen.add((lineno, "IR5", statement.strip()))
                # IR6: do not generalize one head's recorded verdict to another;
                # `_workspace_scratch_redirect` limits this rule to the gh family.
                if _workspace_scratch_redirect(statement):
                    lineno = _attribute_line(statement, start, len(block_lines), lines)
                    seen.add((lineno, "IR6", statement.strip()))
                if not _label_capture_violation(statement):
                    continue
                lineno = _attribute_line(statement, start, len(block_lines), lines)
                seen.add((lineno, "IR3", statement.strip()))
            # IR3 in an UNQUOTED heredoc body: blanked above (its text is data, not
            # commands), but the shell still EXPANDS a `$(…)` there — so a label-helper
            # capture in `gh issue comment -F - <<EOF … $(apply-labels.sh …) … EOF` really
            # executes, and blanking alone would hide the denied shape. Re-scan those lines.
            for off in expanding:
                if _label_capture_violation(block_lines[off]):
                    seen.add((start + off, "IR3", block_lines[off].strip()))
            for off, rule in _loop_violations(clean_lines):
                seen.add((start + off, rule, block_lines[off].strip()))
        hits.extend(sorted(seen))
    return hits


# ── Command-tier rules (issue #1152) ─────────────────────────────────────────
# The `devflow.yml` `command` tier — the manual `/prflow:review-and-fix` /
# `/prflow:pr-description` PR-comment path — is a THIRD cloud allowlist, distinct
# from the read-only `review` profile and the read-write `implement` profile. Its
# HEADS were already scanned (run.sh's whole-bundle head scan against devflow.yml's
# TOOLS), but its SHAPES were not: run.sh linted the review-and-fix bundle under the
# `implement` profile as the closest MEASURED proxy, an inference not a measurement
# (its old `#530` comment said so). This issue converts that inference to a real
# tier: a `--profile command` desk lint plus a `command-probe` matcher job
# (matcher-probe.yml) that measures the tier that actually ships.
#
# INHERITANCE (AC2): the command tier's initial denied-shape content is inherited
# VERBATIM from the read-write `implement` tier, on the recorded assumption that
# `command`-tier denied shapes ⊆ `implement`-tier denied shapes (the same assumption
# the old `#530` proxy comment already rested on). The `command-probe` job is what
# converts that assumption from inference to measurement; a probe result that
# disagrees is a follow-up issue TIGHTENING this rule set, never a silent regression.
#
# WHY A REMAP, NOT A THIRD COPY (AC2): rather than inline a third copy of the loop /
# capture / redirect / leading-`cd` tests, `find_command_violations` DELEGATES to the
# implement scan and remaps its `IR*` ids to `CR*`. This reuses the ENTIRE tested
# implement scan — a fortiori the module-level shared predicates `_redirect_violation`
# and `_leading_cd` the AC names — so the two tiers' notion of a denied redirect and of
# a leading `cd` structurally CANNOT drift, and a future command-only tightening has a
# single clean seam (this finder) to diverge at.
#
# THE ANCHOR IS DELIBERATELY NOT A RULE HERE (AC7), exactly as in the implement table
# above: every legitimate helper call keeps the portable `${CLAUDE_SKILL_DIR:-…}`
# anchor in source (issue #275) and resolves it to the vendored literal at runtime, so
# a fence-static rule would flag every call site. This was RESOLVED in this issue's
# favour when issue #1124 closed (PR #1272, 2026-08-04): its remedy is a *conditional
# call form* plus the narrowly-scoped `lib/test/lint-anchor-fallback-arm.py` (enrolled
# sites only), NOT a shape rule — and that lint owns enrolled-site call form while this
# profile owns fence-static shape discipline, so the command rule set must NOT duplicate
# what `lint-anchor-fallback-arm.py` already covers. The unexpanded anchor's argument-
# position denial (run 30695072336) is measured by the `command-probe` job's
# argument-position rows, not modelled as a static rule.
_IR_TO_CR = {"IR1": "CR1", "IR2": "CR2", "IR3": "CR3", "IR4": "CR4", "IR5": "CR5"}
_COMMAND_RULE_EXCLUSIONS = frozenset({"IR6"})

_command_mapped_rules = frozenset(_IR_TO_CR)
if (_command_mapped_rules & _COMMAND_RULE_EXCLUSIONS
        or _command_mapped_rules | _COMMAND_RULE_EXCLUSIONS != IMPLEMENT_RULES):
    raise RuntimeError(
        "command-tier implement-rule partition is incomplete or overlapping: "
        f"mapped={sorted(_command_mapped_rules)!r}, "
        f"excluded={sorted(_COMMAND_RULE_EXCLUSIONS)!r}, "
        f"implement={sorted(IMPLEMENT_RULES)!r}"
    )

# Exported beside REVIEW_RULES / IMPLEMENT_RULES so a consumer that must enumerate the
# tables (cloud_writer_contract.py's AC4 shape-conformance guard and the `#678 AC8`
# control loop in test_python_scripts.py) reads the command ids from here rather than a
# second list that silently goes stale. Derived from `_IR_TO_CR`'s values so the set
# cannot drift from what `find_command_violations` emits.
COMMAND_RULES = frozenset(_IR_TO_CR.values())


def find_command_violations(text: str) -> list[tuple[int, str, str]]:
    """Every (approx line, rule, statement) command-tier denied-shape hit.

    The command tier inherits only the explicitly mapped implement rules. IR6 is
    implement-evidence-specific and must not become command-tier proof by delegation.
    The mapped loop, capture, /tmp redirect, and leading-cd predicates are reused so
    their established common subset cannot drift."""
    hits = []
    for lineno, rule, statement in find_implement_violations(text):
        if rule in _COMMAND_RULE_EXCLUSIONS:
            continue
        hits.append((lineno, _IR_TO_CR[rule], statement))
    return hits


_USAGE = "usage: extract-command-shapes.py [--profile review|implement|command|no-expansion-redirect] FILE..."


def main(argv: list[str]) -> int:
    args = argv[1:]
    profile = "review"
    if args and args[0] == "--profile":
        if len(args) < 2:
            print(_USAGE, file=sys.stderr)
            return 2
        profile = args[1]
        args = args[2:]
    if len(args) < 1 or profile not in ("review", "implement", "command", "no-expansion-redirect"):
        print(_USAGE, file=sys.stderr)
        return 2
    # The reviewed surface is a bundle (a skill root plus its phase references),
    # so every source is scanned in one call and each hit stays attributed to the
    # file it came from — a moved fence must not escape the scan (issue #529).
    _FINDERS = {
        "review": find_violations,
        "implement": find_implement_violations,
        "command": find_command_violations,
        "no-expansion-redirect": find_expansion_redirect_violations,
    }
    finder = _FINDERS[profile]
    hits: list[tuple[str, int, str, str]] = []
    for path in args:
        with open(path, encoding="utf-8") as handle:
            hits += [(path, *hit) for hit in finder(handle.read())]
    for path, lineno, rule, statement in hits:
        oneline = " ".join(statement.split())
        if len(oneline) > 160:
            oneline = oneline[:157] + "..."
        print(f"{path}:{lineno}  {rule}  {oneline}")
    return 1 if hits else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
