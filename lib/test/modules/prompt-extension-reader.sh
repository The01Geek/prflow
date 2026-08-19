# SPDX-FileCopyrightText: 2026 Daniel Radman
# SPDX-License-Identifier: MIT
# shellcheck shell=bash
# Sourceable prompt-extension-reader contract module (issue #746 tranche).
# Contract: the caller sets LIB and RESULTS_FILE, defines assert_eq, and sources
# lib/test/module-harness.sh first (which defines the namespaced module pin API:
# devflow_module_pin_count / devflow_module_pin_unique / devflow_module_pin_present).
# This module uses assert_eq alone — it asserts the
# observable behavior of scripts/load-prompt-extension.sh through recorded exit
# codes and captured stdout, so it needs no pin primitive and references NO
# monolith helper. Every path derives from LIB. It allocates no module-level
# fixture root (see the note below); it never invokes the runner or the full-suite
# boundary. The inventory in prompt-extension-reader.inventory.md maps the
# extracted coverage to its former run.sh location. Modules may not self-skip.
# No private fixture root and no EXIT trap here, deliberately: the extracted body
# allocates its two fixture trees with its own `mktemp -d` and removes them on its own
# clean path, exactly as it did inline in lib/test/run.sh. Both callers already allocate
# a boundary-owned scratch root and clean it on every path, so a module-level root would
# only add a second ownership layer over the same directories.


# The helper prints .prflow/prompt-extensions/<skill>.md verbatim (relative to
# CWD) when present, nothing otherwise; it validates the skill-name argument and
# refuses any value containing '/' or '..' before touching the filesystem.
# (issue #84, AC 1–5, AC 8.)
LPE="$LIB/../scripts/load-prompt-extension.sh"
LPE_DIR="$(mktemp -d)"
mkdir -p "$LPE_DIR/.prflow/prompt-extensions"

# AC 1: present → stdout equals the file, exit 0.
printf 'line one\nline two\n' > "$LPE_DIR/.prflow/prompt-extensions/implement.md"
LPE_OUT="$(cd "$LPE_DIR" && bash "$LPE" implement 2>/dev/null)"; LPE_RC=$?
assert_eq "lpe: present → verbatim stdout (newlines trimmed by \$())" \
  "$(printf 'line one\nline two')" "$LPE_OUT"
assert_eq "lpe: present → exit 0" "0" "$LPE_RC"

# AC 4: byte-for-byte verbatim incl. multi-byte UTF-8, NO trailing newline added
# when the file has none. cmp the helper's raw bytes against the source file.
printf 'café 日本語 🎉 no-trailing-newline' > "$LPE_DIR/.prflow/prompt-extensions/review.md"
( cd "$LPE_DIR" && bash "$LPE" review 2>/dev/null ) > "$LPE_DIR/out-utf8.bin"
assert_eq "lpe: UTF-8 verbatim, no trailing newline added (cmp byte-exact)" "yes" \
  "$(cmp -s "$LPE_DIR/.prflow/prompt-extensions/review.md" "$LPE_DIR/out-utf8.bin" && echo yes || echo no)"
# AC 4 (other direction): a file WITH a trailing newline round-trips unchanged.
printf 'has trailing newline\n' > "$LPE_DIR/.prflow/prompt-extensions/docs.md"
( cd "$LPE_DIR" && bash "$LPE" docs 2>/dev/null ) > "$LPE_DIR/out-nl.bin"
assert_eq "lpe: trailing-newline file round-trips byte-for-byte" "yes" \
  "$(cmp -s "$LPE_DIR/.prflow/prompt-extensions/docs.md" "$LPE_DIR/out-nl.bin" && echo yes || echo no)"

# AC 2: absent file → empty stdout, exit 0 (no-op path).
LPE_ABS_OUT="$(cd "$LPE_DIR" && bash "$LPE" pr-description 2>/dev/null)"; LPE_ABS_RC=$?
assert_eq "lpe: absent → empty stdout" "" "$LPE_ABS_OUT"
assert_eq "lpe: absent → exit 0" "0" "$LPE_ABS_RC"

# AC 3: empty file → empty stdout, exit 0.
: > "$LPE_DIR/.prflow/prompt-extensions/create-issue.md"
LPE_EMP_OUT="$(cd "$LPE_DIR" && bash "$LPE" create-issue 2>/dev/null)"; LPE_EMP_RC=$?
assert_eq "lpe: empty file → empty stdout" "" "$LPE_EMP_OUT"
assert_eq "lpe: empty file → exit 0" "0" "$LPE_EMP_RC"

# AC 5: path-traversal — reject '/' and '..' BEFORE any read, exit non-zero,
# print nothing. Sentinels the helper would leak if validation were absent:
#   name '../config'  → .prflow/prompt-extensions/../config.md = .prflow/config.md
printf 'SECRET-OUTSIDE' > "$LPE_DIR/.prflow/config.md"
for bad in "a/b" ".." "../config" "../../etc/passwd" "foo/../bar"; do
  BAD_OUT="$(cd "$LPE_DIR" && bash "$LPE" "$bad" 2>/dev/null)"; BAD_RC=$?
  assert_eq "lpe: reject '$bad' → exit non-zero" "yes" \
    "$([ "$BAD_RC" -ne 0 ] && echo yes || echo no)"
  assert_eq "lpe: reject '$bad' → reads nothing outside (empty stdout)" "" "$BAD_OUT"
done
# Empty skill name → bad arguments, exit non-zero.
EMPTY_NAME_OUT="$(cd "$LPE_DIR" && bash "$LPE" "" 2>/dev/null)"; EMPTY_NAME_RC=$?
assert_eq "lpe: empty skill name → exit non-zero" "yes" \
  "$([ "$EMPTY_NAME_RC" -ne 0 ] && echo yes || echo no)"
assert_eq "lpe: empty skill name → empty stdout" "" "$EMPTY_NAME_OUT"

# Present-but-unreadable file → refused LOUDLY (exit 2 + breadcrumb), never the
# silent empty no-op the calling skill reads as "proceed unchanged" (which would
# drop the consumer's extension). Root bypasses the permission bits, so a chmod 000
# file is still readable there and the guard cannot fire. Rather than SKIP the three
# assertions under root — which would drop the executed count below this module's
# equality floor and turn a root run into a false FAIL (issue #746 review Suggestion) —
# run three assertions in EITHER environment: the non-root arm pins the loud refusal;
# the root arm pins the read-through the bypassed bits actually produce. The count is
# then constant across environments, so the floor is no longer host-sensitive.
printf 'unreadable content' > "$LPE_DIR/.prflow/prompt-extensions/locked.md"
chmod 000 "$LPE_DIR/.prflow/prompt-extensions/locked.md"
if [ "$(id -u)" -ne 0 ] && [ ! -r "$LPE_DIR/.prflow/prompt-extensions/locked.md" ]; then
  LOCK_OUT="$(cd "$LPE_DIR" && bash "$LPE" locked 2>/tmp/devflow-lpe-lock.err)"; LOCK_RC=$?
  assert_eq "lpe: unreadable present file → exit non-zero (not a silent no-op)" "yes" \
    "$([ "$LOCK_RC" -ne 0 ] && echo yes || echo no)"
  assert_eq "lpe: unreadable present file → no content leaked to stdout" "" "$LOCK_OUT"
  assert_eq "lpe: unreadable present file → breadcrumb says 'not readable'" "yes" \
    "$(grep -qF 'not readable' /tmp/devflow-lpe-lock.err && echo yes || echo no)"
else
  # Root (or any host where the bits do not deny): the file is readable, so the helper
  # reads it through and emits it at exit 0 — the guard is bypassed, not triggered.
  # Assert exactly that, so the arm still contributes its three assertions to the floor.
  LOCK_OUT="$(cd "$LPE_DIR" && bash "$LPE" locked 2>/tmp/devflow-lpe-lock.err)"; LOCK_RC=$?
  assert_eq "lpe: unreadable-bits file under root → read through at exit 0 (bits bypassed)" "yes" \
    "$([ "$LOCK_RC" -eq 0 ] && echo yes || echo no)"
  assert_eq "lpe: unreadable-bits file under root → content emitted" "yes" \
    "$(printf '%s' "$LOCK_OUT" | grep -qF 'unreadable content' && echo yes || echo no)"
  assert_eq "lpe: unreadable-bits file under root → no 'not readable' breadcrumb (guard bypassed)" "yes" \
    "$(grep -qF 'not readable' /tmp/devflow-lpe-lock.err && echo no || echo yes)"
fi
chmod 644 "$LPE_DIR/.prflow/prompt-extensions/locked.md"   # restore so rm -rf can clean up

# Broken symlink (present link, missing target) → refused LOUDLY (exit 2 +
# breadcrumb), not the silent no-op a bare `-f` test would yield — same silent-drop
# class as the unreadable guard, for an unresolvable link.
ln -s "./this-target-does-not-exist.md" "$LPE_DIR/.prflow/prompt-extensions/broken.md"
BROKEN_OUT="$(cd "$LPE_DIR" && bash "$LPE" broken 2>/tmp/devflow-lpe-broken.err)"; BROKEN_RC=$?
assert_eq "lpe: broken symlink (missing target) → exit non-zero (not silent no-op)" "yes" \
  "$([ "$BROKEN_RC" -ne 0 ] && echo yes || echo no)"
assert_eq "lpe: broken symlink → empty stdout" "" "$BROKEN_OUT"
assert_eq "lpe: broken symlink → breadcrumb names the missing target" "yes" \
  "$(grep -qF 'missing target' /tmp/devflow-lpe-broken.err && echo yes || echo no)"
rm -f "$LPE_DIR/.prflow/prompt-extensions/broken.md"

# Present-but-not-a-regular-file → refused LOUDLY, not a silent no-op: a directory
# at <skill>.md (a fat-fingered `mkdir`) and a symlink resolving to a directory both
# have -f false and would otherwise drop the extension silently (same class).
mkdir "$LPE_DIR/.prflow/prompt-extensions/adir.md"
(cd "$LPE_DIR" && bash "$LPE" adir >/dev/null 2>/tmp/devflow-lpe-adir.err); ADIR_RC=$?
assert_eq "lpe: directory at <skill>.md → exit non-zero (not silent no-op)" "yes" \
  "$([ "$ADIR_RC" -ne 0 ] && echo yes || echo no)"
assert_eq "lpe: directory at <skill>.md → breadcrumb 'not a regular file'" "yes" \
  "$(grep -qF 'not a regular file' /tmp/devflow-lpe-adir.err && echo yes || echo no)"
mkdir "$LPE_DIR/realdir"
ln -s "../../realdir" "$LPE_DIR/.prflow/prompt-extensions/dirlink.md"
DIRLINK_OUT="$(cd "$LPE_DIR" && bash "$LPE" dirlink 2>/tmp/devflow-lpe-dirlink.err)"; DIRLINK_RC=$?
assert_eq "lpe: symlink resolving to a directory → exit non-zero (not silent no-op)" "yes" \
  "$([ "$DIRLINK_RC" -ne 0 ] && echo yes || echo no)"
assert_eq "lpe: symlink-to-directory → empty stdout" "" "$DIRLINK_OUT"
# Pin WHICH guard fired (the non-regular guard, not the broken-symlink one) so a
# future refactor can't silently reroute this shape through the wrong branch.
assert_eq "lpe: symlink-to-directory → breadcrumb 'not a regular file'" "yes" \
  "$(grep -qF 'not a regular file' /tmp/devflow-lpe-dirlink.err && echo yes || echo no)"
rm -rf "$LPE_DIR/.prflow/prompt-extensions/adir.md" "$LPE_DIR/.prflow/prompt-extensions/dirlink.md" "$LPE_DIR/realdir"

# Intended symlink behavior (pins a DECISION, not an accident): the name guard
# constrains the model-supplied NAME, not the resolved target. A symlink the repo
# owner commits inside the consumer-owned extensions dir IS followed by `cat` — the
# directory's contents are trusted by design. This documents that AC 5's "reads no
# file outside" is a name-confinement guarantee, not symlink-target confinement.
printf 'TARGET-OF-SYMLINK' > "$LPE_DIR/symlink-target.txt"
ln -s "../../symlink-target.txt" "$LPE_DIR/.prflow/prompt-extensions/linked.md"
LINK_OUT="$(cd "$LPE_DIR" && bash "$LPE" linked 2>/dev/null)"; LINK_RC=$?
assert_eq "lpe: symlinked extension inside the dir is followed (consumer-owned, by design)" \
  "TARGET-OF-SYMLINK" "$LINK_OUT"
assert_eq "lpe: symlinked extension → exit 0" "0" "$LINK_RC"

# AC 8: read-only + idempotent — identical output on re-run, source file unchanged.
printf 'idem\n' > "$LPE_DIR/.prflow/prompt-extensions/init.md"
LPE_IDEM1="$(cd "$LPE_DIR" && bash "$LPE" init 2>/dev/null)"
LPE_CKSUM_BEFORE="$(cksum "$LPE_DIR/.prflow/prompt-extensions/init.md")"
LPE_IDEM2="$(cd "$LPE_DIR" && bash "$LPE" init 2>/dev/null)"
LPE_CKSUM_AFTER="$(cksum "$LPE_DIR/.prflow/prompt-extensions/init.md")"
assert_eq "lpe: idempotent — identical output on re-run" "$LPE_IDEM1" "$LPE_IDEM2"
assert_eq "lpe: read-only — source file unchanged after run" \
  "$LPE_CKSUM_BEFORE" "$LPE_CKSUM_AFTER"

# ── issue #1299: whole-file mode emits a PROMPT-EXTENSION-STATUS token on STDERR ──
# so an absent/empty extension is distinguishable from a harness refusal (no output at all).
# STDOUT stays byte-verbatim (token on STDERR only); --section mode emits no token.
LPE_TOK_CONTENT_ERR="$LPE_DIR/err-tok-content"
LPE_TOK_CONTENT_OUT="$(cd "$LPE_DIR" && bash "$LPE" implement 2>"$LPE_TOK_CONTENT_ERR")"
# content-present: STDOUT is byte-identical to before (verbatim), token is on STDERR.
assert_eq "lpe token: content-present → stdout stays byte-verbatim (token not on stdout)" \
  "$(printf 'line one\nline two')" "$LPE_TOK_CONTENT_OUT"
assert_eq "lpe token: content-present → stderr carries the content-present token" "yes" \
  "$(case "$(cat "$LPE_TOK_CONTENT_ERR")" in *'PROMPT-EXTENSION-STATUS: content-present'*) echo yes ;; *) echo no ;; esac)"
# The token line carries the `load-prompt-extension.sh: ` diagnostic prefix, and it is
# load-bearing: the phase-3 reviewer classifies the merged stdout/stderr by dropping
# `load-prompt-extension.sh: ` lines, so an unprefixed token would leak into its content
# classification and misreport an empty extension as loaded-with-content. Pin the prefix.
assert_eq "lpe token: the status line carries the load-prompt-extension.sh: diagnostic prefix (phase-3 discriminator)" "yes" \
  "$(case "$(cat "$LPE_TOK_CONTENT_ERR")" in *'load-prompt-extension.sh: PROMPT-EXTENSION-STATUS: content-present'*) echo yes ;; *) echo no ;; esac)"
# absent extension → present-empty token, empty stdout.
LPE_TOK_ABS_ERR="$LPE_DIR/err-tok-abs"
LPE_TOK_ABS_OUT="$(cd "$LPE_DIR" && bash "$LPE" pr-description 2>"$LPE_TOK_ABS_ERR")"
assert_eq "lpe token: absent extension → empty stdout" "" "$LPE_TOK_ABS_OUT"
assert_eq "lpe token: absent extension → stderr carries the present-empty token" "yes" \
  "$(case "$(cat "$LPE_TOK_ABS_ERR")" in *'PROMPT-EXTENSION-STATUS: present-empty'*) echo yes ;; *) echo no ;; esac)"
# empty extension file → present-empty token, empty stdout.
LPE_TOK_EMP_ERR="$LPE_DIR/err-tok-emp"
LPE_TOK_EMP_OUT="$(cd "$LPE_DIR" && bash "$LPE" create-issue 2>"$LPE_TOK_EMP_ERR")"
assert_eq "lpe token: empty extension file → empty stdout" "" "$LPE_TOK_EMP_OUT"
assert_eq "lpe token: empty extension file → stderr carries the present-empty token" "yes" \
  "$(case "$(cat "$LPE_TOK_EMP_ERR")" in *'PROMPT-EXTENSION-STATUS: present-empty'*) echo yes ;; *) echo no ;; esac)"
# present-empty and content-present are DISTINCT tokens: a reader keyed on 'printed text'
# alone could not tell an empty extension from a refusal; the token makes them decidable.
assert_eq "lpe token: present-empty is not content-present (distinct tokens)" "yes" \
  "$(case "$(cat "$LPE_TOK_ABS_ERR")" in *'content-present'*) echo no ;; *) echo yes ;; esac)"
# unestablished is NEVER collapsed onto present-empty (AC3): an undeliverable extension
# (a broken symlink) exits non-zero with its breadcrumb and emits NO present-empty token,
# so a non-zero exit / silence is distinguishable from a real present-empty. A broken
# symlink's guard fires regardless of uid, so this row holds under root too.
ln -s "./this-token-target-missing.md" "$LPE_DIR/.prflow/prompt-extensions/tokbroken.md"
LPE_TOK_UND_ERR="$LPE_DIR/err-tok-und"
LPE_TOK_UND_OUT="$(cd "$LPE_DIR" && bash "$LPE" tokbroken 2>"$LPE_TOK_UND_ERR")"; LPE_TOK_UND_RC=$?
assert_eq "lpe token: undeliverable extension → empty stdout" "" "$LPE_TOK_UND_OUT"
assert_eq "lpe token: undeliverable extension → exit non-zero (not present-empty)" "yes" \
  "$([ "$LPE_TOK_UND_RC" -ne 0 ] && echo yes || echo no)"
assert_eq "lpe token: undeliverable extension → NO PROMPT-EXTENSION-STATUS token at all (unestablished != empty)" "yes" \
  "$(case "$(cat "$LPE_TOK_UND_ERR")" in *'PROMPT-EXTENSION-STATUS:'*) echo no ;; *) echo yes ;; esac)"
rm -f "$LPE_DIR/.prflow/prompt-extensions/tokbroken.md"
# Scope guard: the token is emitted in WHOLE-FILE mode only. A --section extraction
# (create-issue's use) emits no PROMPT-EXTENSION-STATUS token, so its byte-and-stderr
# contract is unchanged. implement.md carries no '## ' heading, so this is the
# absent-heading --section no-op.
LPE_TOK_SEC_ERR="$LPE_DIR/err-tok-sec"
LPE_TOK_SEC_OUT="$(cd "$LPE_DIR" && bash "$LPE" implement --section '## Nope' 2>"$LPE_TOK_SEC_ERR")"
assert_eq "lpe token: --section absent-heading → empty stdout" "" "$LPE_TOK_SEC_OUT"
assert_eq "lpe token: --section mode emits NO PROMPT-EXTENSION-STATUS token (whole-file scoped)" "yes" \
  "$(case "$(cat "$LPE_TOK_SEC_ERR")" in *'PROMPT-EXTENSION-STATUS:'*) echo no ;; *) echo yes ;; esac)"

# ── issue #611: `--section '<heading>'` markdown-section extraction ──────────
# The heading-extraction rule is SPECIFIED once in skills/create-issue/SKILL.md
# (Step 2's `## Evidence axes` forwarding paragraph) and IMPLEMENTED once here, in
# this helper — the coupling that makes the four fresh re-load sites able to name a
# section instead of dumping the whole extension into context. The cases below drive
# one row per extraction-rule clause and one per flag-contract clause, plus the
# malformed-input rows the CLAUDE.md best-effort-parser convention mandates for a
# reader of agent/human-mutable markdown (both truncation shapes included) and the
# compatibility + production-realism rows.
#
# The fixture packs every clause into ONE file so the flagless byte-identity case
# (AC5) exercises them all at once rather than a reduced happy path.
LPE_SEC_DIR="$(mktemp -d)"
mkdir -p "$LPE_SEC_DIR/.prflow/prompt-extensions"
LPE_SEC_EXT="$LPE_SEC_DIR/.prflow/prompt-extensions/sectioned.md"
cat > "$LPE_SEC_EXT" <<'LPE_SEC_FIXTURE'
Preamble text before any heading.

## Alpha
alpha first body
### Alpha sub
alpha after a sub-heading

## Beta
beta body

## Comment Host
<!--
## Commented
this heading lives inside an HTML comment block and is never a heading
-->

## Fenced
before the fence
```
## NotAHeading inside a fence
```
after the fence

## Alpha
alpha second body
LPE_SEC_FIXTURE
# The trailing-space heading is appended with printf, not written into the heredoc
# above: trailing whitespace is invisible in source and editors/format-on-save strip
# it, which would silently make case 20 vacuous. printf pins the bytes.
printf '\n## Trailing Spaces   \nbody under a heading authored with trailing spaces\n' \
  >> "$LPE_SEC_EXT"

# (1) span to the next `## `-prefixed line; (13) a `###` sub-heading is section
# content and terminates nothing; (3) duplicate same-heading sections concatenate in
# FILE ORDER (the two `## Alpha` sections, second one last).
LPE_SEC_ALPHA="$(cd "$LPE_SEC_DIR" && bash "$LPE" sectioned --section '## Alpha' 2>/dev/null)"
assert_eq "lpe --section: span to next '## ' line, '###' inert, duplicates concatenated in file order" \
  "$(printf '## Alpha\nalpha first body\n### Alpha sub\nalpha after a sub-heading\n\n## Alpha\nalpha second body\n')" \
  "$LPE_SEC_ALPHA"

# (7) a `##` line inside a fenced code block neither starts nor terminates a section:
# the `## Fenced` section runs past the fenced `## NotAHeading` to the NEXT real heading.
LPE_SEC_FENCED="$(cd "$LPE_SEC_DIR" && bash "$LPE" sectioned --section '## Fenced' 2>/dev/null)"
assert_eq "lpe --section: '##' inside a fenced code block is inert (neither starts nor terminates)" \
  "$(printf '## Fenced\nbefore the fence\n```\n## NotAHeading inside a fence\n```\nafter the fence\n')" \
  "$LPE_SEC_FENCED"

# (6) a heading inside an HTML comment block is never extracted. The commented heading
# IS present in the fixture (that presence is the point — an absent heading would make
# this case vacuous), so selecting it must yield the absent-heading no-op, not content.
LPE_SEC_COMMENTED="$(cd "$LPE_SEC_DIR" && bash "$LPE" sectioned --section '## Commented' 2>/dev/null)"
assert_eq "lpe --section: heading inside an HTML comment block is not a heading (fixture carries it)" \
  "" "$LPE_SEC_COMMENTED"
assert_eq "lpe --section: the commented heading really is present in the fixture (case is not vacuous)" \
  "yes" "$(grep -qF '## Commented' "$LPE_SEC_EXT" && echo yes || echo no)"

# (2) span to end of file; (20) a heading line authored with TRAILING SPACES still
# selects its section, and a `--section` value carrying trailing whitespace still
# matches (both sides are stripped before comparison).
LPE_SEC_TRAIL="$(cd "$LPE_SEC_DIR" && bash "$LPE" sectioned --section '## Trailing Spaces' 2>/dev/null)"
assert_eq "lpe --section: heading with trailing spaces selects, and section spans to EOF" \
  "$(printf '## Trailing Spaces   \nbody under a heading authored with trailing spaces\n')" \
  "$LPE_SEC_TRAIL"
LPE_SEC_TRAILARG="$(cd "$LPE_SEC_DIR" && bash "$LPE" sectioned --section '## Beta   ' 2>/dev/null)"
assert_eq "lpe --section: a --section value carrying trailing whitespace still matches" \
  "$(printf '## Beta\nbeta body\n')" "$LPE_SEC_TRAILARG"

# (14) a CRLF-terminated heading line still selects its section. The fixture is written
# with real `\r` bytes: the trailing-space case above cannot stand in for it, because
# `\r` is the byte a CRLF-authored consumer extension actually carries and a strip that
# handles spaces but not `\r` would pass that case while failing this one.
printf '## CRLF Heading\r\nbody under a CRLF heading\r\n\r\n## After\r\nafter\r\n' \
  > "$LPE_SEC_DIR/.prflow/prompt-extensions/crlf.md"
LPE_SEC_CRLF="$(cd "$LPE_SEC_DIR" && bash "$LPE" crlf --section '## CRLF Heading' 2>/dev/null)"
assert_eq "lpe --section: a CRLF-terminated heading line still selects its section" "yes" \
  "$(case "$LPE_SEC_CRLF" in *'body under a CRLF heading'*) echo yes ;; *) echo no ;; esac)"
assert_eq "lpe --section: a CRLF section stops at the next heading (does not run to EOF)" "yes" \
  "$(case "$LPE_SEC_CRLF" in *after*) echo no ;; *) echo yes ;; esac)"

# Heading matching is EXACT (case-sensitive) — a deliberate divergence from
# workpad.py's case-insensitive `_find_section`, justified in the helper header as
# "a case-drifted heading must be reported rather than silently accepted". Without this
# row a mutation to case-insensitive matching passes the whole block, silently
# accepting the drift the contract says to report.
LPE_SEC_CASE="$(cd "$LPE_SEC_DIR" && bash "$LPE" sectioned --section '## alpha' 2>"$LPE_SEC_DIR/err-case")"
assert_eq "lpe --section: heading match is case-SENSITIVE ('## alpha' does not select '## Alpha')" \
  "" "$LPE_SEC_CASE"
assert_eq "lpe --section: a case-drifted heading is REPORTED, not silently accepted" "yes" \
  "$(grep -qF '## Alpha' "$LPE_SEC_DIR/err-case" && echo yes || echo no)"

# A heading line carrying a TRAILING INLINE HTML COMMENT is still a heading. The
# comment-block arm must not swallow it: doing so made the section unselectable AND made
# the breadcrumb enumerate the file as though the heading were absent — telling the
# caller a heading it can plainly see does not exist. The `<!-- ## Commented -->` case
# above is the contrast: that line does not BEGIN with '## ', so it stays inert.
printf '## Inline <!-- note -->\ninline body\n\n## AfterInline\nafter inline\n' \
  > "$LPE_SEC_DIR/.prflow/prompt-extensions/inline.md"
LPE_SEC_INLINE="$(cd "$LPE_SEC_DIR" && bash "$LPE" inline --section '## Inline <!-- note -->' 2>/dev/null)"
assert_eq "lpe --section: a heading with a trailing inline HTML comment is still a heading" \
  "$(printf '## Inline <!-- note -->\ninline body\n')" "$LPE_SEC_INLINE"
# ...and it does not bleed into the following section (the swallowed-heading shape
# merged both sections into one).
assert_eq "lpe --section: the section under an inline-comment heading ends at the next heading" "yes" \
  "$(case "$LPE_SEC_INLINE" in *'after inline'*) echo no ;; *) echo yes ;; esac)"
# A heading that OPENS an unclosed comment still puts the block it opened into effect
# for the lines that follow. What that buys is HEADING suppression, not content
# suppression: a comment block sitting inside a section is section CONTENT (the
# `## Comment Host` case above establishes that), so the commented lines are still
# emitted — but a `## ` line inside the opened block is inert and cannot terminate the
# section. Without the comment-state update on the heading line, that `## Later` would
# terminate here and silently truncate the section.
printf '## Opener <!--\nstill inside the opened comment\n## Later\nafter the inert pseudo-heading\n' \
  > "$LPE_SEC_DIR/.prflow/prompt-extensions/opener.md"
LPE_SEC_OPENER="$(cd "$LPE_SEC_DIR" && bash "$LPE" opener --section '## Opener <!--' 2>/dev/null)"
assert_eq "lpe --section: a heading opening an unclosed comment makes a later '## ' line inert (no truncation)" \
  "yes" "$(case "$LPE_SEC_OPENER" in *'after the inert pseudo-heading'*) echo yes ;; *) echo no ;; esac)"
assert_eq "lpe --section: ...and the commented lines are still emitted as section content" \
  "yes" "$(case "$LPE_SEC_OPENER" in *'still inside the opened comment'*) echo yes ;; *) echo no ;; esac)"

# CommonMark permits BOTH ``` and ~~~ as fence characters. Matching only ``` left a
# ~~~-fenced '## ' line live, so the section truncated at a pseudo-heading the rule calls
# inert — silent under-delivery of consumer prose into an agent prompt, while four doc
# sites asserted fence inertness without qualifying the fence kind.
printf '## Tilde\nbefore\n~~~\n## NotAHeading\n~~~\nafter\n\n## AfterTilde\nafter tilde\n' \
  > "$LPE_SEC_DIR/.prflow/prompt-extensions/tilde.md"
LPE_SEC_TILDE="$(cd "$LPE_SEC_DIR" && bash "$LPE" tilde --section '## Tilde' 2>/dev/null)"
assert_eq "lpe --section: '##' inside a ~~~ fence is inert (the section is not truncated)" \
  "yes" "$(case "$LPE_SEC_TILDE" in *'after'*) echo yes ;; *) echo no ;; esac)"
assert_eq "lpe --section: a ~~~ fenced section still ends at the next real heading" "yes" \
  "$(case "$LPE_SEC_TILDE" in *'after tilde'*) echo no ;; *) echo yes ;; esac)"
# A fence closes only on its OWN kind: a ~~~ line inside a ``` block is content, so the
# ``` block stays open and the '## ' line after the ~~~ remains inert.
printf '## Mixed\n```\n~~~\n## StillFenced\n```\nreal content\n\n## AfterMixed\nafter mixed\n' \
  > "$LPE_SEC_DIR/.prflow/prompt-extensions/mixed.md"
LPE_SEC_MIXED="$(cd "$LPE_SEC_DIR" && bash "$LPE" mixed --section '## Mixed' 2>/dev/null)"
assert_eq "lpe --section: a tilde line does not close a backtick fence (fence kind is tracked)" \
  "yes" "$(case "$LPE_SEC_MIXED" in *'real content'*) echo yes ;; *) echo no ;; esac)"

# A line that CLOSES one comment and RE-OPENS another (`<!-- a --> <!--`) leaves a block
# open. Reading only the presence of '-->' left the state closed, so every later '## '
# line read as a real heading and TRUNCATED the section at a pseudo-heading the rule calls
# inert — a silent loss of consumer prose into an agent prompt. Both the heading-line and
# the body-line arms take the last-marker rule, so both are driven here.
printf '## Reopen <!-- a --> <!--\nstill inside\n## Inert\nafter the inert line\n' \
  > "$LPE_SEC_DIR/.prflow/prompt-extensions/reopen.md"
LPE_SEC_REOPEN="$(cd "$LPE_SEC_DIR" && bash "$LPE" reopen --section '## Reopen <!-- a --> <!--' 2>/dev/null)"
assert_eq "lpe --section: a heading that closes AND re-opens a comment leaves it OPEN (no truncation)" \
  "yes" "$(case "$LPE_SEC_REOPEN" in *'after the inert line'*) echo yes ;; *) echo no ;; esac)"
printf '## Body\nintro\n<!-- a --> <!--\nstill inside\n## Inert\nafter the inert line\n' \
  > "$LPE_SEC_DIR/.prflow/prompt-extensions/reopenbody.md"
LPE_SEC_REOPENB="$(cd "$LPE_SEC_DIR" && bash "$LPE" reopenbody --section '## Body' 2>/dev/null)"
assert_eq "lpe --section: a BODY line that closes AND re-opens a comment leaves it OPEN (no truncation)" \
  "yes" "$(case "$LPE_SEC_REOPENB" in *'after the inert line'*) echo yes ;; *) echo no ;; esac)"
# The contrast that keeps the two rows above honest: a plain closing marker really does
# close, so a later '## ' line terminates normally.
printf '## Closed <!--\ninside\n-->\n## Real\nafter a real heading\n' \
  > "$LPE_SEC_DIR/.prflow/prompt-extensions/closed.md"
LPE_SEC_CLOSED="$(cd "$LPE_SEC_DIR" && bash "$LPE" closed --section '## Closed <!--' 2>/dev/null)"
assert_eq "lpe --section: a plain closing marker really closes (a later heading terminates)" \
  "yes" "$(case "$LPE_SEC_CLOSED" in *'after a real heading'*) echo no ;; *) echo yes ;; esac)"

# A heading-shaped BARE positional is a dropped `--section` flag. Ignoring it emits the
# WHOLE extension at exit 0 — the outcome the flag exists to prevent, and invisible at the
# call site. It is the likelier typo than the flag-shaped value below, because the four
# create-issue re-load sites are model-transcribed commands.
LPE_BAD6="$(cd "$LPE_SEC_DIR" && bash "$LPE" sectioned '## Alpha' 2>"$LPE_SEC_DIR/err-bad6")"; LPE_BAD6_RC=$?
assert_eq "lpe --section: a heading-shaped bare positional (dropped --section) → exit 2" "2" "$LPE_BAD6_RC"
assert_eq "lpe --section: a dropped --section never emits the whole extension" "" "$LPE_BAD6"
assert_eq "lpe --section: the dropped-flag breadcrumb suggests the flag" "yes" \
  "$(grep -qF 'did you mean --section' "$LPE_SEC_DIR/err-bad6" && echo yes || echo no)"
# ...while a stray PLAIN word keeps its pre-existing ignored behavior (compatibility).
LPE_EXTRA2="$(cd "$LPE_SEC_DIR" && bash "$LPE" sectioned plainword 2>/dev/null)"; LPE_EXTRA2_RC=$?
assert_eq "lpe --section: a stray plain word is still ignored (not heading-shaped)" "0" "$LPE_EXTRA2_RC"
assert_eq "lpe --section: ...and still emits the full file" "yes" \
  "$([ -n "$LPE_EXTRA2" ] && echo yes || echo no)"

# A '--'-prefixed --section VALUE is a dropped heading argument, refused loudly rather
# than searched for as a literal section name (which would take the silent
# absent-heading no-op — the shape the positional guard already refuses).
LPE_BAD5="$(cd "$LPE_SEC_DIR" && bash "$LPE" sectioned --section --bogus 2>"$LPE_SEC_DIR/err-bad5")"; LPE_BAD5_RC=$?
assert_eq "lpe --section: a flag-shaped --section value → exit 2" "2" "$LPE_BAD5_RC"
assert_eq "lpe --section: a flag-shaped --section value → empty stdout" "" "$LPE_BAD5"
# Pin the REJECTING GUARD's own distinct signal, not the value echo: '--bogus' also
# appears in the fallback absent-heading breadcrumb, so a value-echo assertion passes
# under the exact mutation it exists to catch (the vacuous-negative-test shape).
assert_eq "lpe --section: a flag-shaped --section value → breadcrumb names the guard, not just the value" "yes" \
  "$(grep -qF 'looks like a flag' "$LPE_SEC_DIR/err-bad5" && echo yes || echo no)"

# (15) a repeated `--section` takes its LAST occurrence.
LPE_SEC_REPEAT="$(cd "$LPE_SEC_DIR" && bash "$LPE" sectioned --section '## Alpha' --section '## Beta' 2>/dev/null)"
assert_eq "lpe --section: a repeated --section takes its last occurrence" \
  "$(printf '## Beta\nbeta body\n')" "$LPE_SEC_REPEAT"

# (4) an ABSENT heading in a NON-EMPTY file: empty stdout at exit 0 (the designed
# no-op is preserved) PLUS a stderr breadcrumb naming the requested heading and the
# headings actually present — the clause that makes a near-miss heading (case drift,
# a typo) observable instead of silently contributing nothing.
LPE_SEC_MISS="$(cd "$LPE_SEC_DIR" && bash "$LPE" sectioned --section '## Nope' 2>"$LPE_SEC_DIR/err-miss")"; LPE_SEC_MISS_RC=$?
assert_eq "lpe --section: absent heading in a non-empty file → empty stdout" "" "$LPE_SEC_MISS"
assert_eq "lpe --section: absent heading in a non-empty file → exit 0 (designed no-op preserved)" \
  "0" "$LPE_SEC_MISS_RC"
assert_eq "lpe --section: absent-heading breadcrumb names the REQUESTED heading" "yes" \
  "$(grep -qF '## Nope' "$LPE_SEC_DIR/err-miss" && echo yes || echo no)"
assert_eq "lpe --section: absent-heading breadcrumb lists the headings PRESENT" "yes" \
  "$(grep -qF '## Alpha' "$LPE_SEC_DIR/err-miss" && grep -qF '## Beta' "$LPE_SEC_DIR/err-miss" && echo yes || echo no)"
# The breadcrumb lists REAL headings only — a heading the extractor itself refuses to
# recognize must not be advertised as available, or the report would send a caller
# chasing a heading that can never be selected.
assert_eq "lpe --section: absent-heading breadcrumb omits comment-block and fenced pseudo-headings" "yes" \
  "$(grep -qF '## Commented' "$LPE_SEC_DIR/err-miss" || grep -qF '## NotAHeading' "$LPE_SEC_DIR/err-miss" && echo no || echo yes)"

# (5) an EMPTY section (heading present, no body before the next heading) emits
# NOTHING on stdout at exit 0 — not even its own heading line. This is the
# "an empty section is equivalent to an absent heading" clause of the extraction
# rule: a heading with no content contributes no consumer section, so emitting a
# bare heading would hand the consumer an empty-but-present section where the rule
# says there is none. It differs from case 4 in exactly one observable: NO
# absent-heading breadcrumb, because the heading WAS found. Distinguishing the two
# is the point — one is a missing hook, the other a present-but-empty one.
printf 'body\n\n## Empty\n## After\nafter body\n' > "$LPE_SEC_DIR/.prflow/prompt-extensions/emptysec.md"
LPE_SEC_EMPTY="$(cd "$LPE_SEC_DIR" && bash "$LPE" emptysec --section '## Empty' 2>"$LPE_SEC_DIR/err-empty")"; LPE_SEC_EMPTY_RC=$?
assert_eq "lpe --section: empty section → empty stdout (equivalent to an absent heading)" \
  "" "$LPE_SEC_EMPTY"
assert_eq "lpe --section: empty section → exit 0" "0" "$LPE_SEC_EMPTY_RC"
# Byte-empty, NOT a grep for some literal: the previous form grepped a string the
# helper never emits, so it passed unconditionally and could not have caught the arm
# it exists to police. The positive control below proves the same fixture DOES
# breadcrumb on a genuine absent heading, so this pair discriminates the two arms.
assert_eq "lpe --section: empty section carries NO absent-heading breadcrumb (the heading was found)" \
  "" "$(cat "$LPE_SEC_DIR/err-empty")"
LPE_SEC_EMPTY_CTL="$(cd "$LPE_SEC_DIR" && bash "$LPE" emptysec --section '## NoSuchHeading' 2>"$LPE_SEC_DIR/err-empty-ctl")"
assert_eq "lpe --section: positive control — the SAME fixture does breadcrumb on a genuinely absent heading" \
  "yes" "$(grep -qF 'no section headed' "$LPE_SEC_DIR/err-empty-ctl" && echo yes || echo no)"
assert_eq "lpe --section: positive control emits no stdout either" "" "$LPE_SEC_EMPTY_CTL"
# A whitespace-only body is the same shape as a wholly-absent one — a blank line is
# not consumer content — so it takes the empty-section arm too.
printf '## Blank\n\n   \n\n## After\nafter body\n' > "$LPE_SEC_DIR/.prflow/prompt-extensions/blanksec.md"
LPE_SEC_BLANK="$(cd "$LPE_SEC_DIR" && bash "$LPE" blanksec --section '## Blank' 2>/dev/null)"
assert_eq "lpe --section: whitespace-only section body takes the empty-section arm" "" "$LPE_SEC_BLANK"

# (8) an UNCLOSED fence runs to end of file — the first truncation shape of the
# mutable-markdown malformed-input matrix. Every `##` after the unclosed fence is
# swallowed, so the section cannot be terminated by one.
printf '## Open\nbefore\n```\n## swallowed by the unclosed fence\nstill inside\n' \
  > "$LPE_SEC_DIR/.prflow/prompt-extensions/unclosed.md"
LPE_SEC_UNCLOSED="$(cd "$LPE_SEC_DIR" && bash "$LPE" unclosed --section '## Open' 2>/dev/null)"
assert_eq "lpe --section: an unclosed fence runs to end of file (no '##' terminates inside it)" \
  "$(printf '## Open\nbefore\n```\n## swallowed by the unclosed fence\nstill inside\n')" \
  "$LPE_SEC_UNCLOSED"

# (18) a section ending at EOF in a file whose FINAL LINE HAS NO TERMINATING NEWLINE
# still emits that final line IN FULL — the second truncation shape. The naive
# `while read` loop drops it entirely, and `$()` strips trailing newlines on both
# sides, so this is asserted byte-exactly with cmp rather than through `$()`.
printf '## Last\nfinal line without newline' > "$LPE_SEC_DIR/.prflow/prompt-extensions/nonl.md"
( cd "$LPE_SEC_DIR" && bash "$LPE" nonl --section '## Last' 2>/dev/null ) > "$LPE_SEC_DIR/out-nonl.bin"
printf '## Last\nfinal line without newline' > "$LPE_SEC_DIR/want-nonl.bin"
assert_eq "lpe --section: final line with no terminating newline is emitted in full, byte-exact" "yes" \
  "$(cmp -s "$LPE_SEC_DIR/want-nonl.bin" "$LPE_SEC_DIR/out-nonl.bin" && echo yes || echo no)"

# (9) an EMPTY extension file and (10) an ABSENT extension file each emit nothing at
# exit 0 under --section — and an empty file gets no absent-heading breadcrumb, since
# the clause is scoped to a NON-empty file (there are no headings to report).
: > "$LPE_SEC_DIR/.prflow/prompt-extensions/emptyfile.md"
LPE_SEC_EF="$(cd "$LPE_SEC_DIR" && bash "$LPE" emptyfile --section '## Anything' 2>"$LPE_SEC_DIR/err-ef")"; LPE_SEC_EF_RC=$?
assert_eq "lpe --section: empty extension file → empty stdout" "" "$LPE_SEC_EF"
assert_eq "lpe --section: empty extension file → exit 0" "0" "$LPE_SEC_EF_RC"
# The captured stderr is ASSERTED, not merely captured: an unread capture beside a
# comment stating the contract is the fail-open shape that let the empty-file
# breadcrumb ship in the first place.
assert_eq "lpe --section: empty extension file → NO absent-heading breadcrumb (the clause is scoped to a non-empty file)" \
  "" "$(cat "$LPE_SEC_DIR/err-ef")"
LPE_SEC_AF="$(cd "$LPE_SEC_DIR" && bash "$LPE" no-such-skill --section '## Anything' 2>/dev/null)"; LPE_SEC_AF_RC=$?
assert_eq "lpe --section: absent extension file → empty stdout" "" "$LPE_SEC_AF"
assert_eq "lpe --section: absent extension file → exit 0" "0" "$LPE_SEC_AF_RC"

# (11) AC5 — FLAGLESS byte-identity against the all-clauses fixture. This is the
# compatibility guarantee every existing caller depends on: adding the flag must not
# perturb the no-flag path by a single byte.
( cd "$LPE_SEC_DIR" && bash "$LPE" sectioned 2>/dev/null ) > "$LPE_SEC_DIR/out-flagless.bin"
assert_eq "lpe --section: a FLAGLESS invocation stays byte-identical to the full file (AC5)" "yes" \
  "$(cmp -s "$LPE_SEC_EXT" "$LPE_SEC_DIR/out-flagless.bin" && echo yes || echo no)"

# (12) production realism — the LIVE .prflow/prompt-extensions/create-issue.md is the
# file the four create-issue re-load sites actually section, and it carries BOTH hooks.
# A synthetic fixture can satisfy every clause above and still miss a shape the real
# extension has, so both hooks are driven against the real bytes.
mkdir -p "$LPE_SEC_DIR/live/.prflow/prompt-extensions"
cp "$LIB/../.prflow/prompt-extensions/create-issue.md" "$LPE_SEC_DIR/live/.prflow/prompt-extensions/create-issue.md"
LPE_LIVE_AUDIT="$(cd "$LPE_SEC_DIR/live" && bash "$LPE" create-issue --section '## Audit dimensions' 2>/dev/null)"
LPE_LIVE_AXES="$(cd "$LPE_SEC_DIR/live" && bash "$LPE" create-issue --section '## Evidence axes' 2>/dev/null)"
assert_eq "lpe --section: live create-issue extension → '## Audit dimensions' extracts non-empty" "yes" \
  "$([ -n "$LPE_LIVE_AUDIT" ] && echo yes || echo no)"
assert_eq "lpe --section: live create-issue extension → '## Evidence axes' extracts non-empty" "yes" \
  "$([ -n "$LPE_LIVE_AXES" ] && echo yes || echo no)"
# Each hook feeds exactly one consumption site, so neither extraction may leak the
# other's section — the independence the SKILL.md dual-hook sentence promises.
assert_eq "lpe --section: live extension → the two hooks do not leak into each other" "yes" \
  "$(case "$LPE_LIVE_AUDIT" in *'## Evidence axes'*) echo no ;; *) case "$LPE_LIVE_AXES" in *'## Audit dimensions'*) echo no ;; *) echo yes ;; esac ;; esac)"

# ── malformed flag usage is refused LOUDLY (exit 2 + breadcrumb) ────────────
# Same discipline as the helper's existing undeliverable-shape guards: a silent
# revert to the full dump would hand the caller the whole extension where it asked
# for one section — the opposite of the context saving the flag exists for.
# (16) unrecognized `--`-prefixed argument.
LPE_BAD1="$(cd "$LPE_SEC_DIR" && bash "$LPE" sectioned --bogus 2>"$LPE_SEC_DIR/err-bad1")"; LPE_BAD1_RC=$?
assert_eq "lpe --section: unrecognized '--' argument → exit 2" "2" "$LPE_BAD1_RC"
assert_eq "lpe --section: unrecognized '--' argument → empty stdout (never the full dump)" "" "$LPE_BAD1"
assert_eq "lpe --section: unrecognized '--' argument → breadcrumb names it" "yes" \
  "$(grep -qF -- '--bogus' "$LPE_SEC_DIR/err-bad1" && echo yes || echo no)"
# (17) `--section` missing its value.
LPE_BAD2="$(cd "$LPE_SEC_DIR" && bash "$LPE" sectioned --section 2>"$LPE_SEC_DIR/err-bad2")"; LPE_BAD2_RC=$?
assert_eq "lpe --section: --section with no value → exit 2" "2" "$LPE_BAD2_RC"
assert_eq "lpe --section: --section with no value → empty stdout" "" "$LPE_BAD2"
assert_eq "lpe --section: --section with no value → breadcrumb says it requires a value" "yes" \
  "$(grep -qF 'requires a value' "$LPE_SEC_DIR/err-bad2" && echo yes || echo no)"
# (19) `--section` whose value is EMPTY after trailing-whitespace stripping. Without
# this guard a whitespace-only value would compare equal to no heading at all and
# silently select nothing, which reads exactly like a legitimate absent-heading no-op.
LPE_BAD3="$(cd "$LPE_SEC_DIR" && bash "$LPE" sectioned --section '   ' 2>"$LPE_SEC_DIR/err-bad3")"; LPE_BAD3_RC=$?
assert_eq "lpe --section: whitespace-only --section value → exit 2" "2" "$LPE_BAD3_RC"
assert_eq "lpe --section: whitespace-only --section value → empty stdout" "" "$LPE_BAD3"
assert_eq "lpe --section: whitespace-only --section value → breadcrumb says the value is empty" "yes" \
  "$(grep -qF 'empty' "$LPE_SEC_DIR/err-bad3" && echo yes || echo no)"
# (21) a `--`-prefixed argument in the SKILL-NAME positional slot — a transposed
# `--section '## X' <skill>`. Without this guard the helper looks up a skill literally
# named `--section`, finds no such extension, and exits 0 printing nothing: a silent
# no-op indistinguishable from a consumer who simply has no extension.
LPE_BAD4="$(cd "$LPE_SEC_DIR" && bash "$LPE" --section '## Alpha' 2>"$LPE_SEC_DIR/err-bad4")"; LPE_BAD4_RC=$?
assert_eq "lpe --section: '--'-prefixed skill-name positional (transposed flag) → exit 2" "2" "$LPE_BAD4_RC"
assert_eq "lpe --section: transposed flag → empty stdout (never a silent no-op)" "" "$LPE_BAD4"
assert_eq "lpe --section: transposed flag → breadcrumb names the offending positional" "yes" \
  "$(grep -qF -- '--section' "$LPE_SEC_DIR/err-bad4" && echo yes || echo no)"
# Bare NON-flag extra arguments keep today's ignored-argument behavior, so a caller
# that has always passed a stray word is not newly broken by the flag's arrival.
LPE_EXTRA="$(cd "$LPE_SEC_DIR" && bash "$LPE" sectioned stray-extra-word 2>/dev/null)"; LPE_EXTRA_RC=$?
assert_eq "lpe --section: bare non-flag extra argument stays ignored (compatibility)" "0" "$LPE_EXTRA_RC"
assert_eq "lpe --section: bare non-flag extra argument still emits the full file" "yes" \
  "$([ -n "$LPE_EXTRA" ] && echo yes || echo no)"
# The pre-existing name guards still fire when --section is present, so the flag can
# never become a bypass for the path-traversal refusal.
LPE_TRAV="$(cd "$LPE_SEC_DIR" && bash "$LPE" ../config --section '## Alpha' 2>/dev/null)"; LPE_TRAV_RC=$?
assert_eq "lpe --section: path-traversal name guard still fires with --section present" "2" "$LPE_TRAV_RC"
assert_eq "lpe --section: path-traversal name guard with --section → empty stdout" "" "$LPE_TRAV"
rm -rf "$LPE_SEC_DIR"

# ── DEVFLOW_PROMPT_EXTENSION_ROOT trusted-root override (issue #874) ────────
# The review tier checks out the PR head, so the extension bytes the reviewing
# agent appends to its own prompt were PR-author-editable. The workflow now
# materializes them from the trusted base ref into a $RUNNER_TEMP closure and
# points the loader at it through this variable. The override composes
# "${DEVFLOW_PROMPT_EXTENSION_ROOT}/${SKILL_NAME}.md" directly — the variable
# names the extensions DIRECTORY, not a repo root, so no
# '.prflow/prompt-extensions/' segment is appended to it.
#
# The variable follows the DEVFLOW_GH / DEVFLOW_JQ / DEVFLOW_BASH convention:
# honored at top precedence when set and NON-EMPTY, inert when unset, and inert
# when set to the empty string. The input-shape matrix below is closed by
# construction — the product of the variable's presence states and the target's
# filesystem states the resolution branch distinguishes.
LPE_ENV_DIR="$(mktemp -d)"
mkdir -p "$LPE_ENV_DIR/repo/.prflow/prompt-extensions" "$LPE_ENV_DIR/trusted" "$LPE_ENV_DIR/emptydir"
# The two fixtures hold DIFFERENT bytes, which is what makes "the repo-root copy
# was demonstrably not read" an observation rather than an assumption.
printf 'REPO-HEAD BYTES\n' > "$LPE_ENV_DIR/repo/.prflow/prompt-extensions/review.md"
printf 'TRUSTED BASE-REF BYTES no-trailing-newline' > "$LPE_ENV_DIR/trusted/review.md"
: > "$LPE_ENV_DIR/trusted/docs.md"
printf 'not a directory\n' > "$LPE_ENV_DIR/regular-file"

# (1) unset → repo-root resolution, stdout byte-identical to today, and NO
# trusted-root breadcrumb. The variable is published only in the review job, so
# the skills/*/SKILL.md load sites outside the review tier observe unchanged
# output; this change edits none of them.
LPE_E1="$(cd "$LPE_ENV_DIR/repo" && bash "$LPE" review 2>"$LPE_ENV_DIR/err-e1")"; LPE_E1_RC=$?
assert_eq "lpe env: unset → repo-root bytes" "REPO-HEAD BYTES" "$LPE_E1"
assert_eq "lpe env: unset → exit 0" "0" "$LPE_E1_RC"
assert_eq "lpe env: unset → no trusted-root breadcrumb on stderr" "yes" \
  "$(grep -qF 'DEVFLOW_PROMPT_EXTENSION_ROOT' "$LPE_ENV_DIR/err-e1" && echo no || echo yes)"

# (2) set to the EMPTY STRING → inert, exactly as unset (the DEVFLOW_GH ':='
# convention: an empty override never selects the override branch).
LPE_E2="$(cd "$LPE_ENV_DIR/repo" && DEVFLOW_PROMPT_EXTENSION_ROOT='' bash "$LPE" review 2>"$LPE_ENV_DIR/err-e2")"; LPE_E2_RC=$?
assert_eq "lpe env: empty string → repo-root bytes (override inert)" "REPO-HEAD BYTES" "$LPE_E2"
assert_eq "lpe env: empty string → exit 0" "0" "$LPE_E2_RC"
assert_eq "lpe env: empty string → no trusted-root breadcrumb on stderr" "yes" \
  "$(grep -qF 'DEVFLOW_PROMPT_EXTENSION_ROOT' "$LPE_ENV_DIR/err-e2" && echo no || echo yes)"

# (3) whitespace only → a directory NAME made of spaces, not a sentinel: the
# file is absent under it, so this is the ordinary no-op, never a fallback to
# the repo root (which would silently reinstate the PR-head bytes).
LPE_E3="$(cd "$LPE_ENV_DIR/repo" && DEVFLOW_PROMPT_EXTENSION_ROOT='   ' bash "$LPE" review 2>/dev/null)"; LPE_E3_RC=$?
assert_eq "lpe env: whitespace-only root → empty stdout (never the repo-root copy)" "" "$LPE_E3"
assert_eq "lpe env: whitespace-only root → exit 0" "0" "$LPE_E3_RC"

# (4) non-existent directory → absent file, exit 0, empty stdout.
LPE_E4="$(cd "$LPE_ENV_DIR/repo" && DEVFLOW_PROMPT_EXTENSION_ROOT="$LPE_ENV_DIR/no-such-dir" bash "$LPE" review 2>/dev/null)"; LPE_E4_RC=$?
assert_eq "lpe env: non-existent root → empty stdout" "" "$LPE_E4"
assert_eq "lpe env: non-existent root → exit 0" "0" "$LPE_E4_RC"

# (5) a REGULAR FILE where a directory is expected → the composed path is not a
# file, so absent; exit 0, empty stdout, and still no repo-root fallback.
LPE_E5="$(cd "$LPE_ENV_DIR/repo" && DEVFLOW_PROMPT_EXTENSION_ROOT="$LPE_ENV_DIR/regular-file" bash "$LPE" review 2>/dev/null)"; LPE_E5_RC=$?
assert_eq "lpe env: root is a regular file → empty stdout" "" "$LPE_E5"
assert_eq "lpe env: root is a regular file → exit 0" "0" "$LPE_E5_RC"

# (6) an existing directory holding no <skill>.md → the ordinary
# extension-less-consumer no-op the closure produces when the base ref carries
# no such file.
LPE_E6="$(cd "$LPE_ENV_DIR/repo" && DEVFLOW_PROMPT_EXTENSION_ROOT="$LPE_ENV_DIR/emptydir" bash "$LPE" review 2>/dev/null)"; LPE_E6_RC=$?
assert_eq "lpe env: existing root without <skill>.md → empty stdout" "" "$LPE_E6"
assert_eq "lpe env: existing root without <skill>.md → exit 0" "0" "$LPE_E6_RC"

# (7) an existing directory holding <skill>.md → those bytes verbatim, compared
# with cmp for byte exactness, AND the repo-root copy demonstrably not read.
( cd "$LPE_ENV_DIR/repo" && DEVFLOW_PROMPT_EXTENSION_ROOT="$LPE_ENV_DIR/trusted" bash "$LPE" review 2>/dev/null ) > "$LPE_ENV_DIR/out-e7.bin"
assert_eq "lpe env: trusted root → byte-exact copy of the trusted file (cmp)" "yes" \
  "$(cmp -s "$LPE_ENV_DIR/trusted/review.md" "$LPE_ENV_DIR/out-e7.bin" && echo yes || echo no)"
assert_eq "lpe env: trusted root → the repo-root copy is NOT read" "yes" \
  "$(grep -qF 'REPO-HEAD BYTES' "$LPE_ENV_DIR/out-e7.bin" && echo no || echo yes)"
# issue #1299: the status token fires on the DEVFLOW_PROMPT_EXTENSION_ROOT branch too — the
# review tier's production consumer — since the emission sits after both resolution branches.
LPE_ENV_TOK_ERR="$LPE_ENV_DIR/err-tok-trusted"
( cd "$LPE_ENV_DIR/repo" && DEVFLOW_PROMPT_EXTENSION_ROOT="$LPE_ENV_DIR/trusted" bash "$LPE" review 2>"$LPE_ENV_TOK_ERR" >/dev/null )
assert_eq "lpe env: trusted root with content → content-present token on stderr (issue #1299)" "yes" \
  "$(case "$(cat "$LPE_ENV_TOK_ERR")" in *'PROMPT-EXTENSION-STATUS: content-present'*) echo yes ;; *) echo no ;; esac)"

# (8) the SKILL_NAME guard still fires ahead of every read on the override
# branch, so the trusted root is no more escapable than the repo root. The
# sentinel below is the leak check: a name that escaped containment would reach
# it, since it sits one level ABOVE the trusted root.
printf 'ESCAPED-CONTAINMENT\n' > "$LPE_ENV_DIR/escape.md"
LPE_E8A="$(cd "$LPE_ENV_DIR/repo" && DEVFLOW_PROMPT_EXTENSION_ROOT="$LPE_ENV_DIR/trusted" bash "$LPE" ../escape 2>/dev/null)"; LPE_E8A_RC=$?
assert_eq "lpe env: trusted root + '..' name → exit 2" "2" "$LPE_E8A_RC"
assert_eq "lpe env: trusted root + '..' name → empty stdout (containment holds)" "" "$LPE_E8A"
LPE_E8B="$(cd "$LPE_ENV_DIR/repo" && DEVFLOW_PROMPT_EXTENSION_ROOT="$LPE_ENV_DIR/trusted" bash "$LPE" sub/review 2>/dev/null)"; LPE_E8B_RC=$?
assert_eq "lpe env: trusted root + '/' name → exit 2" "2" "$LPE_E8B_RC"
assert_eq "lpe env: trusted root + '/' name → empty stdout (containment holds)" "" "$LPE_E8B"

# The breadcrumb: scoped to the override branch alone (cases 1 and 2 above pin
# its absence on the repo-root branch), and it names both the resolved directory
# and which branch selected it — the observable that turns an unpropagated
# variable from a silent feature loss into a diagnosable one, surfaced at the
# prompt layer through the EXTENSION-STATUS resolved-root field.
( cd "$LPE_ENV_DIR/repo" && DEVFLOW_PROMPT_EXTENSION_ROOT="$LPE_ENV_DIR/trusted" bash "$LPE" review 2>"$LPE_ENV_DIR/err-crumb" >/dev/null )
# The breadcrumb is matched with `case` over the CAPTURED STDERR rather than with
# grep: this is a runtime-output assertion, and reading it into a shell variable and
# matching with a builtin keeps the decisive value off any non-preflight PATH tool.
LPE_CRUMB="$(cat "$LPE_ENV_DIR/err-crumb")"
assert_eq "lpe env: override branch → breadcrumb names the resolved directory" "yes" \
  "$(case "$LPE_CRUMB" in *"$LPE_ENV_DIR/trusted"*) echo yes ;; *) echo no ;; esac)"
assert_eq "lpe env: override branch → breadcrumb names the selecting branch" "yes" \
  "$(case "$LPE_CRUMB" in *DEVFLOW_PROMPT_EXTENSION_ROOT*) echo yes ;; *) echo no ;; esac)"
# An EMPTY extension under the override branch still yields empty STDOUT even
# though stderr now carries the breadcrumb. This is the operand the amended
# EXTENSION-STATUS contract classifies on: a site still keyed on "printed text"
# would read the breadcrumb as content and misreport loaded-with-content.
LPE_E9="$(cd "$LPE_ENV_DIR/repo" && DEVFLOW_PROMPT_EXTENSION_ROOT="$LPE_ENV_DIR/trusted" bash "$LPE" docs 2>"$LPE_ENV_DIR/err-e9")"; LPE_E9_RC=$?
assert_eq "lpe env: empty extension under the breadcrumb → empty stdout (loaded-empty)" "" "$LPE_E9"
assert_eq "lpe env: empty extension under the breadcrumb → exit 0" "0" "$LPE_E9_RC"
assert_eq "lpe env: empty extension → the breadcrumb is on stderr, not stdout" "yes" \
  "$([ -s "$LPE_ENV_DIR/err-e9" ] && echo yes || echo no)"
assert_eq "lpe env: empty extension under trusted root → present-empty token on stderr (issue #1299)" "yes" \
  "$(case "$(cat "$LPE_ENV_DIR/err-e9")" in *'PROMPT-EXTENSION-STATUS: present-empty'*) echo yes ;; *) echo no ;; esac)"
rm -rf "$LPE_ENV_DIR"

# ── scripts/render-prompt-extension.sh — the render-time injection wrapper (#1264) ──
# The wrapper is a faithful, NON-PROPAGATING proxy of the loader above: it exists so a
# `!`…`` placeholder in a SKILL.md body can deliver the extension as prompt text rather
# than as a command the agent may or may not choose to run. Its whole contract is
# "always exit 0, always print one status line", because a non-zero exit from an
# injected command aborts the skill invocation at zero turns — turning the loader's
# ordinary exit 2 into a silent no-verdict run. These assertions drive all four input
# shapes the contract names, plus the two exit-status-neutralization paths, and they
# assert the EXACT status line rather than merely "some output", so a vocabulary drift
# that made `unestablished` read as `present-empty` fails here.
RPE="$LIB/../scripts/render-prompt-extension.sh"
RPE_DIR="$(mktemp -d)"
mkdir -p "$RPE_DIR/closure"

# Shape 1 — extension present WITH CONTENT.
printf 'policy line one\npolicy line two\n' > "$RPE_DIR/closure/review.md"
RPE_C_OUT="$(DEVFLOW_PROMPT_EXTENSION_ROOT="$RPE_DIR/closure" bash "$RPE" review 2>/dev/null)"; RPE_C_RC=$?
assert_eq "rpe: content-present → exit 0" "0" "$RPE_C_RC"
assert_eq "rpe: content-present → exact status line" "PROMPT-EXTENSION-STATUS: content-present" \
  "${RPE_C_OUT%%$'\n'*}"
assert_eq "rpe: content-present → the extension's bytes follow the status line" \
  "$(printf 'PROMPT-EXTENSION-STATUS: content-present\n\npolicy line one\npolicy line two')" "$RPE_C_OUT"

# Shape 2 — extension PRESENT BUT EMPTY. The status line is the whole of stdout.
: > "$RPE_DIR/closure/docs.md"
RPE_E_OUT="$(DEVFLOW_PROMPT_EXTENSION_ROOT="$RPE_DIR/closure" bash "$RPE" docs 2>/dev/null)"; RPE_E_RC=$?
assert_eq "rpe: present-empty → exit 0" "0" "$RPE_E_RC"
assert_eq "rpe: present-empty → exact status line, nothing else" "PROMPT-EXTENSION-STATUS: present-empty" "$RPE_E_OUT"

# Shape 3 — extension ABSENT. Shares the loader's single no-op class with shape 2, by
# design (the loader owns directory resolution; re-deriving the path here to tell the
# two apart would duplicate that resolution in a second place, free to drift from it).
RPE_A_OUT="$(DEVFLOW_PROMPT_EXTENSION_ROOT="$RPE_DIR/closure" bash "$RPE" implement 2>/dev/null)"; RPE_A_RC=$?
assert_eq "rpe: absent → exit 0" "0" "$RPE_A_RC"
assert_eq "rpe: absent → exact status line, nothing else" "PROMPT-EXTENSION-STATUS: present-empty" "$RPE_A_OUT"

# Shape 4 — extension PRESENT BUT UNREADABLE. This is the loader's exit 2, the code
# whose propagation would abort the whole skill render; the wrapper must absorb it AND
# report it as unestablished, never as the empty no-op.
printf 'unreadable content\n' > "$RPE_DIR/closure/create-issue.md"
chmod 000 "$RPE_DIR/closure/create-issue.md"
RPE_U_OUT="$(DEVFLOW_PROMPT_EXTENSION_ROOT="$RPE_DIR/closure" bash "$RPE" create-issue 2>/dev/null)"; RPE_U_RC=$?
chmod 644 "$RPE_DIR/closure/create-issue.md"
assert_eq "rpe: present-but-unreadable → exit 0 (the loader's exit 2 is NOT propagated)" "0" "$RPE_U_RC"
assert_eq "rpe: present-but-unreadable → unestablished, never present-empty" "yes" \
  "$(case "$RPE_U_OUT" in 'PROMPT-EXTENSION-STATUS: unestablished ('*')') echo yes ;; *) echo no ;; esac)"
assert_eq "rpe: present-but-unreadable → the reason names the cause" "yes" \
  "$(case "$RPE_U_OUT" in *"is not readable"*) echo yes ;; *) echo no ;; esac)"
# The status line is ONE line: the reason carries a loader diagnostic that may itself
# span lines, and a newline leaking through would break the single-line contract the
# reading skill keys on.
assert_eq "rpe: unestablished reason is collapsed onto a single line" "yes" \
  "$(case "$RPE_U_OUT" in *$'\n'*) echo no ;; *) echo yes ;; esac)"

# An ABSENT TRUSTED CLOSURE is unestablished, not empty. The loader alone would report
# it as an ordinary absent file (exit 0, empty) — an empty-looking answer for a closure
# that failed to materialize, which on the merge-gating review tier would read as a
# clean policy pass the run never had.
RPE_NC_OUT="$(DEVFLOW_PROMPT_EXTENSION_ROOT="$RPE_DIR/no-such-closure" bash "$RPE" review 2>/dev/null)"; RPE_NC_RC=$?
assert_eq "rpe: absent trusted closure → exit 0" "0" "$RPE_NC_RC"
assert_eq "rpe: absent trusted closure → unestablished, never present-empty" "yes" \
  "$(case "$RPE_NC_OUT" in 'PROMPT-EXTENSION-STATUS: unestablished ('*"closure was not established"*) echo yes ;; *) echo no ;; esac)"

# A bad skill name is the loader's OTHER exit-2 family (argument validation, refused
# before any filesystem access). Same neutralization.
RPE_B_OUT="$(bash "$RPE" ../escape 2>/dev/null)"; RPE_B_RC=$?
assert_eq "rpe: rejected skill name → exit 0 (exit 2 neutralized)" "0" "$RPE_B_RC"
assert_eq "rpe: rejected skill name → unestablished" "yes" \
  "$(case "$RPE_B_OUT" in 'PROMPT-EXTENSION-STATUS: unestablished ('*) echo yes ;; *) echo no ;; esac)"

# No argument at all — a caller bug must not abort the render either.
RPE_N_OUT="$(bash "$RPE" 2>/dev/null)"; RPE_N_RC=$?
assert_eq "rpe: no skill name → exit 0" "0" "$RPE_N_RC"
assert_eq "rpe: no skill name → unestablished naming the missing argument" "yes" \
  "$(case "$RPE_N_OUT" in *'unestablished (no skill name'*) echo yes ;; *) echo no ;; esac)"

# The loader is UNLOCATABLE beside the wrapper — a partial vendor copy, a pruned slice,
# or a plugin cache that shipped one file of the pair. The wrapper self-anchors on its own
# path and composes the sibling loader from it, so this is the one `unestablished` cause
# that no loader exit status can report: with nothing to execute there is no exit status
# at all. Without this row the whole branch is unexercised, and a regression there is
# maximally silent — it would surface as the abort-at-zero-turns render the wrapper exists
# to prevent. The fixture copies the WRAPPER ALONE into an empty directory, so the only
# property under test is the missing sibling.
RPE_LONE_DIR="$(mktemp -d)"
RPE_LONE_DIR="$(cd "$RPE_LONE_DIR" && pwd -P)"
mkdir -p "$RPE_LONE_DIR/bin" "$RPE_LONE_DIR/closure"
cp "$RPE" "$RPE_LONE_DIR/bin/render-prompt-extension.sh"
printf 'lone policy line\n' > "$RPE_LONE_DIR/closure/review.md"
RPE_L_OUT="$(DEVFLOW_PROMPT_EXTENSION_ROOT="$RPE_LONE_DIR/closure" bash "$RPE_LONE_DIR/bin/render-prompt-extension.sh" review 2>/dev/null)"; RPE_L_RC=$?
assert_eq "rpe: loader missing beside the wrapper → exit 0 (the render is never aborted)" "0" "$RPE_L_RC"
assert_eq "rpe: loader missing beside the wrapper → unestablished, never present-empty" "yes" \
  "$(case "$RPE_L_OUT" in 'PROMPT-EXTENSION-STATUS: unestablished ('*) echo yes ;; *) echo no ;; esac)"
# Attribute the rejection to THIS guard: three other causes also emit `unestablished`, and a
# bare shape assertion would stay green if the run were refused by, say, the absent-closure
# guard instead. The reason names the locate failure and the directory it searched.
assert_eq "rpe: loader missing → the reason names the LOCATE failure, not another unestablished cause" "yes" \
  "$(case "$RPE_L_OUT" in *"could not locate load-prompt-extension.sh"*) echo yes ;; *) echo no ;; esac)"
assert_eq "rpe: loader missing → the reason names the directory that was searched" "yes" \
  "$(case "$RPE_L_OUT" in *"$RPE_LONE_DIR/bin"*) echo yes ;; *) echo no ;; esac)"
# Positive control on the SAME fixture: the closure and the skill name are otherwise valid,
# so the run succeeds when the sibling loader IS present. Without it, a closure the wrapper
# rejected for an unrelated reason would read as a passing locate-guard test.
cp "$LPE" "$RPE_LONE_DIR/bin/load-prompt-extension.sh"
RPE_LC_OUT="$(DEVFLOW_PROMPT_EXTENSION_ROOT="$RPE_LONE_DIR/closure" bash "$RPE_LONE_DIR/bin/render-prompt-extension.sh" review 2>/dev/null)"
assert_eq "rpe: positive control — the same fixture renders content once the sibling loader is restored" \
  "$(printf 'PROMPT-EXTENSION-STATUS: content-present\n\nlone policy line')" "$RPE_LC_OUT"
rm -rf "$RPE_LONE_DIR"

rm -rf "$RPE_DIR"

# The render-time placeholder is INVISIBLE to every desk gate that guards an ordinary
# fenced call site: it is inline-backticked rather than fenced, so extract-command-heads.py
# emits no head for it and the cloud-writer closure derivation cannot reach the helper.
# That leaves the change's own primary delivery path unguarded — a dropped grant, a renamed
# helper, or a typo'd skill name would keep every gate green while consumer policy silently
# stopped reaching the merge-gating reviewer, which is the exact silent class issue #1264
# exists to remove. These assertions close that gap at the two machine-consumed contracts
# the placeholder actually depends on: the resolved allowlist, and the per-skill call sites.
RPE_MANIFEST="$LIB/../lib/capability-profiles.json"
RPE_LOCK="$LIB/../lib/review-profile.tokens"

# The wildcard token is the load-bearing grant, not the vendored literal: the placeholder's
# ${CLAUDE_SKILL_DIR} resolves to an ABSOLUTE path, which no vendored literal matches. A
# manifest edit that dropped it would silently refuse the render on that tier.
for RPE_PROFILE in review implement command; do
  assert_eq "rpe grant: '$RPE_PROFILE' profile grants the wrapper's wildcard head" "yes" \
    "$(RPE_P="$RPE_PROFILE" python3 -c "
import json, os, sys
d = json.load(open(sys.argv[1]))
toks = d['profiles'][os.environ['RPE_P']]
print('yes' if 'Bash(*/render-prompt-extension.sh:*)' in toks else 'no')
" "$RPE_MANIFEST")"
done

# The review profile is a locked security boundary: the generator refuses to widen it
# until the lock moves in the same change, so the lock must carry the token too.
assert_eq "rpe grant: the review-profile lock carries the wrapper's wildcard head" "yes" \
  "$(grep -Fxq 'Bash(*/render-prompt-extension.sh:*)' "$RPE_LOCK" && echo yes || echo no)"

# No skill body carries a render-time placeholder any more. A Skill-tool load of one that does
# aborts on the placeholder's permission check and returns no skill body at all — measured on
# every placeholder-bearing skill and on neither skill without one (run 31287654057) — so the
# loader ladder is each site's sole channel. These are ABSENCE pins, one per former call site,
# each naming the extension that site loaded, so a reflexive "restore the missing placeholder"
# edit goes RED at the site it lands on rather than anywhere in the family.
for RPE_SITE in review:review review-and-fix:review-and-fix review-and-fix:receiving-code-review \
                implement:implement pr-description:pr-description; do
  RPE_BODY="${RPE_SITE%%:*}"
  RPE_NAME="${RPE_SITE#*:}"
  assert_eq "rpe placeholder: skills/$RPE_BODY/SKILL.md carries no render-time placeholder for '$RPE_NAME'" "yes" \
    "$(grep -Fq '!`${CLAUDE_SKILL_DIR}/../../scripts/render-prompt-extension.sh '"$RPE_NAME"'`' \
       "$LIB/../skills/$RPE_BODY/SKILL.md" && echo no || echo yes)"  # raw-guard-ok: loop body — the target is the $RPE_NAME loop variable, not a static pin
done

rm -rf "$LPE_DIR"
