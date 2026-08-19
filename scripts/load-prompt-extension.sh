#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2026 Daniel Radman
# SPDX-License-Identifier: MIT
# Print a consumer-owned prompt-extension file verbatim, if present.
#
# Usage: load-prompt-extension.sh SKILL_NAME [--section '<## heading>']
#   SKILL_NAME   the skill's directory name under skills/ (e.g. create-issue,
#                implement, review). This is the only POSITIONAL argument.
#   --section    optional; emit only the named section of the extension instead of
#                the whole file. Its value is the exact '## '-prefixed heading line.
#                At most one section per invocation; a repeated flag takes its LAST
#                occurrence. Omitting the flag keeps the byte-identical full-file
#                behavior every pre-existing caller depends on.
#
# The --section extraction rule (issue #611) is SPECIFIED in
# skills/create-issue/references/step-2-clarify.md (the `## Evidence axes`
# forwarding paragraph, moved there at issue #614) and IMPLEMENTED here; that
# reference sentence is the specification of record and this helper is its single
# implementation — a coupled pair, edited together. The rule:
#   * a section spans its heading line to the next line beginning '## ' (two hashes
#     PLUS A SPACE, so a '###' sub-heading line is section content, not a
#     terminator), else to end of file;
#   * duplicate same-heading sections are concatenated in file order;
#   * an empty section is equivalent to an absent heading (both emit nothing);
#   * a heading line inside an HTML comment block is never a heading;
#   * a '##' line inside a fenced code block neither starts nor terminates a
#     section, and an unclosed fence runs to end of file. Both CommonMark fence
#     characters are tracked (``` and ~~~), and a fence closes only on its own kind;
#   * trailing whitespace is stripped from both the candidate heading line and the
#     --section value before comparison, so a CRLF-authored extension and a heading
#     hand-authored with trailing spaces both still extract.
# Stated boundary: LEADING whitespace is not stripped, so an indented ATX heading and an
# indented closing fence (CommonMark permits up to three spaces on both) are not
# recognized. This matches the rule's literal wording — 'a line beginning `## `' — and is
# a deliberate limit of a best-effort parser over hand-authored markdown, not an oversight.
#
# Section bytes are selected and emitted with bash builtins only (read/printf/case
# parameter expansion) — never awk/sed/tr/head. The emitted section decides what a
# consumer skill sees, so under the repo's non-preflight-PATH-tool rule it must not
# be derived through a tool `lib/preflight.sh` does not guarantee: such a tool going
# missing would empty the selection silently rather than failing loudly.
#
# Two sibling '## '-heading scanners live in scripts/, and their terminator rules
# DIFFER deliberately — do not "unify" them without re-reading all three contracts:
#   * scripts/parse-acs.py `_extract_section` terminates on the next heading of the
#     SAME-OR-HIGHER level, and it resolves a section name at level 2 OR level 3
#     (`level in (2, 3)`), so whether a '###' line terminates depends on the level the
#     document used — unlike this helper, where '###' is always content. It also drops
#     heading lines from the returned content and matches the name case-INsensitively.
#   * scripts/workpad.py splits on '## ' in `_split_sections` and matches the heading
#     name case-INsensitively in its sibling `_find_section` (the split and the match
#     are two functions; `_split_sections` performs no name comparison of its own).
#   * this one terminates only on '## ' (a '###' line is section content) and matches
#     the heading line EXACTLY after a trailing-whitespace strip, because it feeds
#     agent-executed prompt prose where a sub-heading is part of the section body and
#     a case-drifted heading must be reported rather than silently accepted.
#
# Reads <SKILL_NAME>.md from the selected extension directory and writes it
# byte-for-byte to stdout when it exists. TWO branches select that directory:
#
#   * DEVFLOW_PROMPT_EXTENSION_ROOT, when set and non-empty (issue #874) — the
#     variable names the extension directory outright, so the composed path is
#     "${DEVFLOW_PROMPT_EXTENSION_ROOT}/<SKILL_NAME>.md" with no
#     '.prflow/prompt-extensions/' segment appended. Top precedence, and inert both
#     when unset and when set to the empty string, per the DEVFLOW_GH / DEVFLOW_JQ /
#     DEVFLOW_BASH convention. This branch writes a stderr breadcrumb naming the
#     directory it resolved. The repo-root branch adds no stderr of its OWN beyond the
#     pre-existing could-not-resolve-a-repo-root diagnostic below, unchanged by this
#     branch's arrival — so a caller that leaves the variable unset observes
#     byte-identical output. (Scoped to the BRANCH: the present-but-undeliverable and
#     argument-validation diagnostics further down are shared by both branches and are
#     likewise unchanged.)
#   * otherwise, .prflow/prompt-extensions/ anchored to the git repo root
#     (git rev-parse --show-toplevel, falling back to pwd when not in a git tree —
#     mirroring lib/config-source.sh; issue #295). Anchoring to the root means a
#     skill invoked from any subdirectory of the repo still loads the consumer's
#     committed extension, instead of silently missing it. (Limitation:
#     --show-toplevel returns the NEAREST git root, so a nested submodule/inner repo
#     or a monorepo whose .prflow/ is not at the git root is not covered —
#     consistent with config-source.sh.) This is the ONLY branch that anchors on the
#     repo root, which the issue-#295 repo-root-reader enumerations in
#     .prflow/config.schema.json and scripts/emit-git-env.sh record.
#
# In WHOLE-FILE mode (no --section) this also emits a
# `load-prompt-extension.sh: PROMPT-EXTENSION-STATUS: <content-present|present-empty>` line on
# STDERR (issue #1299), reusing scripts/render-prompt-extension.sh's status vocabulary:
# `content-present` when it printed extension text, `present-empty` on the absent/empty no-op
# arm. The token is STDERR-only so stdout stays byte-verbatim, and it makes an absent/empty
# extension distinguishable from a harness refusal (which produces no output at all). The
# `load-prompt-extension.sh: ` prefix keeps the phase-3 reviewer's stdout-classification
# discriminator (which drops `load-prompt-extension.sh: ` lines) neutralizing this diagnostic.
# --section mode emits no token, so create-issue's byte-and-stderr contract is unchanged.
#
# When the file is absent — or present but empty — this prints nothing on stdout and exits
# 0 (the no-op path), so a skill that reads stdout behaves exactly as before unless the
# consumer opted in.
#
# This is DevFlow's single upgrade-safe extension point: a consumer adds
# repo-specific instructions to any skill by committing one Markdown file in
# their own repo, with no plugin edit and no fork to maintain. The file lives in
# the consumer's repo, never in the plugin, so marketplace updates never touch
# it and never conflict with it. The skill that calls this treats the printed
# text as additional instructions appended to the end of its own prompt.
#
# SKILL_NAME is validated BEFORE any filesystem access, on BOTH resolution branches:
# a value that is empty or contains a '/' character or a '..' sequence is rejected
# (exit 2). This constrains the *name* — so the model-executed argument can never
# name a file outside the SELECTED extension directory, whichever branch chose it —
# NOT the resolved target: a symlink committed inside that directory is still
# followed by `cat`. That is by design — the directory's contents are trusted prose,
# and a consumer who symlinks outward is only reaching into their own repo.
#
# WHOSE bytes those are is a property of the caller's environment, not of this
# helper, and it differs by tier. On the local, interactive, and /devflow:implement
# tiers the directory is the consumer's own checked-out repo, so the argument is the
# only attacker-influenceable input (a skill could be coaxed to pass an unexpected
# value) and the file's bytes are trusted. On the cloud REVIEW tier that premise does
# not hold of the checkout: .github/workflows/devflow-runner.yml checks out the PULL
# REQUEST's head, so a repo-root read there would append PR-author-editable bytes to
# the merge-gating reviewer's own prompt. That tier therefore materializes the
# protected extensions from the TRUSTED BASE REF into a $RUNNER_TEMP closure, points
# this helper at it through DEVFLOW_PROMPT_EXTENSION_ROOT, and truncates the
# workspace copies unconditionally so the repo-root branch has nothing to find
# (issue #874). The bytes are trusted because of where that tier sourced them, not
# because this helper read them.
#
# Plain POSIX-portable shell, no GNU-only flags — runs on macOS/BSD without GNU
# coreutils. `cat` reproduces the file's bytes exactly, adding or stripping no
# trailing newline beyond the file's own.
#
# Exit codes:
#   0  file printed verbatim (or the selected section), or absent/empty (no-op) —
#      including the designed no-op of an absent heading or an empty section under
#      --section, which additionally emits a stderr breadcrumb when the heading is
#      absent from a NON-empty extension (the no-op stays exit 0; the breadcrumb
#      only makes it observable, so a near-miss heading is never silent)
#   2  bad arguments (missing SKILL_NAME, a SKILL_NAME containing '/' or '..' or
#      given as a '--'-prefixed token, an unrecognized '--' argument, a --section
#      missing its value, a --section whose value is empty after stripping or is itself
#      '--'-prefixed, or a heading-shaped bare positional — a dropped --section), OR the named
#      extension exists but cannot be delivered as a Markdown file (unreadable, a
#      symlink whose target is missing, or not a regular file — a directory or a
#      symlink resolving to one) — refused loudly rather than left to masquerade as
#      the empty no-op the calling skill treats as "proceed unchanged", which would
#      silently drop the consumer's customization

set -euo pipefail

# State-directory resolution (issue #1002): canonical .prflow/, with the LOUD
# transitional fallback to a superseded .devflow/ when only that one is present.
# Guarded source (the lib/resolve-jq.sh discipline): a partially-copied deployment
# degrades to the canonical name with a breadcrumb instead of aborting under `set -e`.
# Self-directory anchor. `dirname` is NOT one of the tools lib/preflight.sh
# guarantees, and under `set -e` its failing command substitution aborts the read
# before a caller default is emitted — so this uses the dirname-free spelling of
# the anchor, which is also one of the shapes lib/test/cloud_writer_deps.py can
# prove (a variable assigned by a `case` cannot be resolved by that scanner, so an
# edge built from one reads as a repo-root escape). `cd`/`pwd` are bash builtins.
_LPE_SELF_DIR="$(cd "${BASH_SOURCE[0]%/*}" && pwd)"
# shellcheck source=../lib/resolve-state-dir.sh
if [ -f "$_LPE_SELF_DIR/../lib/resolve-state-dir.sh" ] \
   && . "$_LPE_SELF_DIR/../lib/resolve-state-dir.sh" \
   && type prflow_state_dir >/dev/null 2>&1; then
  :
else
  echo "prflow: resolve-state-dir.sh not found in ../lib relative to ${BASH_SOURCE[0]} — using the canonical .prflow/ with no transitional fallback" >&2
  prflow_state_dir() { printf '%s' "${1:-}/.prflow"; }
fi

# Resolve whether an HTML comment block is OPEN at the end of a line, by walking the
# line's markers in order and keeping the LAST one that fired. Presence of '-->' is not
# enough: `<!-- a --> <!--` both closes and re-opens, and reading only the close leaves
# the block state wrong for every line that follows — which silently truncates a section
# at a '## ' line the extraction rule calls inert. Pure parameter expansion, no PATH tool.
_lpe_comment_open() {
    _lpe_open="$2"
    _lpe_rest="$1"
    # Which marker to look for next depends on the CURRENT state, so the walk must branch
    # on it rather than always seeking an opener first: a line arriving already-inside a
    # block (a bare `-->`) has no opener, and a seek-opener-first loop would break out
    # before ever consuming the close and leave the block open forever.
    while :; do
        if [ "$_lpe_open" -eq 0 ]; then
            case "$_lpe_rest" in
                *'<!--'*) _lpe_rest="${_lpe_rest#*'<!--'}"; _lpe_open=1 ;;
                *) break ;;
            esac
        else
            case "$_lpe_rest" in
                *'-->'*) _lpe_rest="${_lpe_rest#*'-->'}"; _lpe_open=0 ;;
                *) break ;;
            esac
        fi
    done
}

# Strip trailing whitespace (spaces, tabs, and a CR from a CRLF-authored file) with
# pure parameter expansion — no `tr`/`sed`. Used on both sides of the heading
# comparison, so a CRLF extension and a heading typed with trailing spaces both match.
_lpe_rstrip() {
    _lpe_rstripped="$1"
    while [ "${_lpe_rstripped%[[:space:]]}" != "$_lpe_rstripped" ]; do
        _lpe_rstripped="${_lpe_rstripped%[[:space:]]}"
    done
}

skill="${1:-}"

if [ -z "$skill" ]; then
    echo "load-prompt-extension.sh: usage: load-prompt-extension.sh SKILL_NAME [--section '<## heading>']" >&2
    exit 2
fi

# A '--'-prefixed token in the SKILL-NAME slot is a transposed invocation
# (`--section '## X' <skill>`). Refuse it loudly: without this guard the helper would
# look up a skill literally named `--section`, find no such extension, and exit 0
# printing nothing — a silent no-op indistinguishable from a consumer who genuinely
# has no extension, which is precisely the silent-drop class the guards below exist
# to close.
case "$skill" in
    --*)
        echo "load-prompt-extension.sh: SKILL_NAME must be the first argument, but got the flag '$skill' (usage: load-prompt-extension.sh SKILL_NAME [--section '<## heading>'])" >&2
        exit 2
        ;;
esac

# Parse the optional flags after the positional. A repeated --section takes its LAST
# occurrence; bare non-flag extra arguments stay ignored, preserving the pre-flag
# behavior for any caller that already passed a stray word. An unrecognized
# '--'-prefixed argument is refused rather than ignored: silently reverting to the
# full-file dump would hand a caller the entire extension where it asked for one
# section — the opposite of the context saving --section exists to provide, and
# invisible at the call site. A bare extra argument that is HEADING-shaped ('## …') is
# refused for the same reason (it is a dropped --section); only a bare PLAIN word keeps
# the pre-flag ignored behavior.
section=""
section_requested=0
shift || true
while [ "$#" -gt 0 ]; do
    case "$1" in
        --section)
            if [ "$#" -lt 2 ]; then
                echo "load-prompt-extension.sh: --section requires a value (the exact '## '-prefixed heading line)" >&2
                exit 2
            fi
            # A '--'-prefixed VALUE is a dropped heading argument (`--section --bogus`,
            # or `--section` immediately followed by the next flag). Binding it as the
            # heading would search for a section literally named '--bogus', find none,
            # and take the designed absent-heading no-op — the silent shape the sibling
            # positional guard already refuses. Refuse it the same way.
            case "$2" in
                --*)
                    echo "load-prompt-extension.sh: --section value '$2' looks like a flag, not a '## '-prefixed heading line (a dropped heading argument would otherwise select nothing silently)" >&2
                    exit 2
                    ;;
            esac
            section="$2"
            section_requested=1
            shift 2
            ;;
        --*)
            echo "load-prompt-extension.sh: unrecognized argument '$1' (usage: load-prompt-extension.sh SKILL_NAME [--section '<## heading>'])" >&2
            exit 2
            ;;
        *)
            # A heading-shaped bare positional is a dropped `--section` flag. Ignoring it
            # emits the WHOLE extension at exit 0 — the opposite of what the caller asked
            # for, and indistinguishable at the call site from a legitimate full-file
            # load. This is the likelier typo than the flag-shaped value refused above
            # (the four create-issue re-load sites are model-transcribed commands), so it
            # gets the same loud refusal. A stray plain word keeps its ignored behavior.
            case "$1" in
                '## '*)
                    echo "load-prompt-extension.sh: extra argument '$1' looks like a heading; did you mean --section '$1'? (refusing to silently emit the whole extension)" >&2
                    exit 2
                    ;;
            esac
            shift
            ;;
    esac
done

if [ "$section_requested" -eq 1 ]; then
    _lpe_rstrip "$section"
    section="$_lpe_rstripped"
    # A whitespace-only value would compare equal to no heading at all and silently
    # select nothing, reading exactly like a legitimate absent-heading no-op. Refuse it.
    if [ -z "$section" ]; then
        echo "load-prompt-extension.sh: --section value is empty after stripping trailing whitespace (expected the exact '## '-prefixed heading line)" >&2
        exit 2
    fi
fi

# Reject path-traversal vectors before touching the filesystem. '*/*' matches any
# slash; '*..*' matches any '..' sequence (covering '..', '../x', 'x/../y').
case "$skill" in
    */* | *..*)
        echo "load-prompt-extension.sh: invalid skill name '$skill' (must not contain '/' or '..')" >&2
        exit 2
        ;;
esac

# Select the extension directory. DEVFLOW_PROMPT_EXTENSION_ROOT names that directory
# OUTRIGHT — the composed path is "${DEVFLOW_PROMPT_EXTENSION_ROOT}/${skill}.md", with
# no '.prflow/prompt-extensions/' segment appended — so a caller can point this reader
# at a closure that lives nowhere near a repo (issue #874: the cloud review tier
# materializes the base ref's extensions into $RUNNER_TEMP, because its own checkout is
# the pull request's and those bytes become the reviewing agent's appended prompt).
# Precedence follows the DEVFLOW_GH / DEVFLOW_JQ / DEVFLOW_BASH convention: honored when
# set and NON-EMPTY, inert when unset, and equally inert when set to the empty string.
#
# This branch sits AFTER the SKILL_NAME guard above and BEFORE every filesystem access
# below, so containment holds relative to whichever directory is selected: the guard
# already refuses a name carrying '/' or '..', which is what keeps the composed path
# inside the selected root on both branches.
if [ -n "${DEVFLOW_PROMPT_EXTENSION_ROOT:-}" ]; then
    ext_dir="$DEVFLOW_PROMPT_EXTENSION_ROOT"
    # Scoped to this branch alone. A caller that leaves the variable unset (every
    # skill load site outside the review tier, and every local or interactive run)
    # observes byte-identical output, which is why no sibling breadcrumb is written on
    # the repo-root branch below. Naming both the directory and the branch that chose
    # it is what makes an unpropagated variable diagnosable rather than a silent
    # feature loss: the reader sees which root actually supplied the bytes.
    echo "load-prompt-extension.sh: extension directory selected by DEVFLOW_PROMPT_EXTENSION_ROOT: '${DEVFLOW_PROMPT_EXTENSION_ROOT}'" >&2
else
    # Anchor to the repo root (issue #295) so a subdirectory invocation still finds the
    # consumer's extension. Mirror lib/config-source.sh's discovery expression.
    # git rev-parse prints nothing and exits non-zero outside a git tree; the trailing
    # `|| _devflow_root=""` keeps that assignment set -e-safe. Then fall back to cwd, with a
    # breadcrumb only when NEITHER a git root NOR a .prflow/ dir can be located.
    _devflow_root="$(git rev-parse --show-toplevel 2>/dev/null)" || _devflow_root=""
    if [ -z "$_devflow_root" ]; then
        _devflow_root="$(pwd)"
        # git can exit non-zero while genuinely INSIDE a repo (safe.directory /
        # dubious-ownership refusal), or be absent from PATH — not only "outside a git
        # tree". Don't assert "not in a git repo"; report that the root could not be
        # resolved and surface git's own stderr (re-run on this rare path only; `|| true`
        # keeps it set -e-safe).
        # Probe BOTH names: a consumer who has not run /prflow:init yet carries only
        # the superseded directory, and naming a path they were never told to create
        # would misdirect them. The state-dir resolver picks which one is used and
        # breadcrumbs the superseded one itself.
        if [ ! -d "${_devflow_root}/.prflow" ] && [ ! -d "${_devflow_root}/.devflow" ]; then
            _git_err="$(git rev-parse --show-toplevel 2>&1 >/dev/null)" || true
            echo "load-prompt-extension.sh: could not resolve a git repo root${_git_err:+ (git: ${_git_err})} and no .prflow/ at '${_devflow_root}'; no extension loaded" >&2
        fi
    fi

    ext_dir="$(prflow_state_dir "${_devflow_root}")/prompt-extensions"
fi

# Composed once, after the branch: each arm selects only the DIRECTORY, so the
# "<skill>.md" filename convention lives in exactly one place.
ext_file="${ext_dir}/${skill}.md"

# Refuse every "present but undeliverable" shape loudly (exit 2 + a specific
# breadcrumb) instead of letting it fall through to the silent empty no-op the
# calling skill reads as "proceed unchanged" — that would drop the consumer
# extension. The guards below partition those shapes; an absent file (none of them
# fire) is the only path that reaches the no-op exit 0 at the very end.
#
# A symlink whose target is missing makes the `-f` test below false, so without
# this branch a committed `<skill>.md -> ../moved.md` (or a link that resolves only
# on another machine) would silently no-op and drop the consumer extension — the
# same failure class the unreadable guard below closes. Refuse it loudly too.
# (-L true AND -e false = a present-but-broken symlink; a resolvable symlink is
# -e true and is followed by design, per the header.)
if [ -L "$ext_file" ] && [ ! -e "$ext_file" ]; then
    echo "load-prompt-extension.sh: '$ext_file' is a symlink with a missing target; refusing to silently skip a consumer extension (fix or remove the link)" >&2
    exit 2
fi

# A present entry that is NOT a regular file — a directory (e.g. a fat-fingered
# `mkdir <skill>.md`), a symlink resolving to a directory, a fifo/device — also
# makes the `-f` test below false and would silently no-op, dropping the consumer
# extension (same class as the guards above). Refuse it loudly. A regular file, or
# a symlink resolving to one, is `-f` true and falls through to be read.
if [ -e "$ext_file" ] && [ ! -f "$ext_file" ]; then
    echo "load-prompt-extension.sh: '$ext_file' exists but is not a regular file; refusing to silently skip a consumer extension (expected a Markdown file)" >&2
    exit 2
fi

# By here the broken-symlink and non-regular guards above have fired on every
# undeliverable *present* shape, so the only present case reaching `-f` is a
# regular file (an absent file makes `-f` false → the no-op exit 0 at the end).
# A present-but-unreadable regular file is still refused loudly (exit 2) rather
# than letting a bare `cat` failure under `set -e` masquerade as the empty no-op
# the calling skill reads as "proceed unchanged". (Note: a process running as root
# bypasses the permission bits, so this guard only fires for an ordinary user.)
if [ -f "$ext_file" ]; then
    if [ ! -r "$ext_file" ]; then
        echo "load-prompt-extension.sh: '$ext_file' exists but is not readable; refusing to silently skip a consumer extension (fix its permissions)" >&2
        exit 2
    fi
    if [ "$section_requested" -eq 0 ]; then
        cat "$ext_file"
    else
        # One pass over the file, tracking three pieces of state: whether we are
        # inside a fenced code block, inside an HTML comment block, and inside the
        # requested section. Fence and comment state are tracked GLOBALLY (not only
        # while inside the section) because a fence opened before the heading and
        # closed after it still governs whether the lines between them are headings.
        _in_fence=0
        _in_fence_char=''
        _in_comment=0
        _in_section=0
        _found=0
        _has_body=0
        _out=""
        _headings=""
        _partial=0
        # The `|| { [ -n "$_line" ] && _partial=1; }` clause is what makes a final
        # line with NO terminating newline survive: `read` returns non-zero on it
        # while still assigning it, so a bare `while read` silently DROPS that line.
        # The flag also records that the line was unterminated, so it is re-emitted
        # without inventing a newline the source file never had.
        while IFS= read -r _line || { [ -n "$_line" ] && _partial=1; }; do
            _is_heading=0
            if [ "$_in_fence" -eq 1 ]; then
                # Inside a fence nothing is a heading; only a closing fence of the SAME
                # kind matters. CommonMark treats ``` and ~~~ as distinct fence
                # characters, so a ~~~ line inside a ``` block is content, not a close.
                case "$_line" in
                    '```'*) [ "$_in_fence_char" = '`' ] && _in_fence=0 ;;
                    '~~~'*) [ "$_in_fence_char" = '~' ] && _in_fence=0 ;;
                esac
            elif [ "$_in_comment" -eq 1 ]; then
                # Inside a comment block nothing is a heading; only the block state
                # matters — and a line can close one comment and re-open another, so the
                # LAST marker decides, not the presence of a close.
                _lpe_comment_open "$_line" 1
                _in_comment="$_lpe_open"
            else
                case "$_line" in
                    '```'*)
                        # An unclosed fence is never reset, so it runs to end of file
                        # — the truncation shape a hand-edited extension can leave.
                        _in_fence=1
                        _in_fence_char='`'
                        ;;
                    '~~~'*)
                        # The tilde fence CommonMark permits alongside ```. Without this
                        # arm a ~~~-fenced '## ' line stayed live and truncated the
                        # section at a pseudo-heading, silently under-delivering consumer
                        # prose into an agent prompt.
                        _in_fence=1
                        _in_fence_char='~'
                        ;;
                    '## '*)
                        # Two hashes PLUS A SPACE. '### Foo' fails this pattern (its
                        # third character is '#', not a space), so a sub-heading is
                        # section content and terminates nothing.
                        #
                        # This arm is tested BEFORE the HTML-comment arm on purpose: a
                        # line that BEGINS with '## ' is a heading whatever follows it,
                        # including a trailing inline comment
                        # (`## Evidence axes <!-- consumer note -->`). Ordering the
                        # comment arm first made such a heading unreachable by ANY
                        # --section value AND made the absent-heading breadcrumb
                        # enumerate the file as though the heading were not there —
                        # telling the caller a heading it can plainly see does not exist.
                        # Matching stays EXACT, so `## Evidence axes <!-- note -->` is
                        # selected by that full line, not by the bare `## Evidence axes`;
                        # a bare-name request still takes the absent-heading arm, which
                        # now lists the annotated heading so the drift is visible rather
                        # than silent. A line that merely CONTAINS '<!--' without starting
                        # '## ' still falls through to the comment arm, so
                        # `<!-- ## Commented -->` is unaffected.
                        _is_heading=1
                        # A heading line may itself OPEN an unclosed comment block
                        # (`## X <!--`, or `## X <!-- a --> <!--`). It is still this
                        # section's heading, but whatever block state it leaves must
                        # govern the lines that follow, so the LAST marker decides.
                        _lpe_comment_open "$_line" 0
                        _in_comment="$_lpe_open"
                        ;;
                    *'<!--'*)
                        # This line is not a heading either way; the LAST marker on it
                        # decides whether a block is left open for the lines that follow.
                        _lpe_comment_open "$_line" 0
                        _in_comment="$_lpe_open"
                        ;;
                esac
            fi
            if [ "$_is_heading" -eq 1 ]; then
                _lpe_rstrip "$_line"
                _headings="${_headings}${_headings:+, }${_lpe_rstripped}"
                if [ "$_lpe_rstripped" = "$section" ]; then
                    # A duplicate same-heading section re-enters rather than
                    # restarting, so the sections concatenate in file order.
                    _in_section=1
                    _found=1
                else
                    _in_section=0
                fi
            fi
            if [ "$_in_section" -eq 1 ]; then
                # One append; the unterminated final line just skips the newline the
                # source file never had.
                _out="${_out}${_line}"
                [ "$_partial" -eq 1 ] || _out="${_out}"$'\n'
                if [ "$_is_heading" -eq 0 ]; then
                    # Any non-whitespace content below a heading makes the section
                    # non-empty. Checked with a bash pattern, never `grep`/`tr`.
                    case "$_line" in *[![:space:]]*) _has_body=1 ;; esac
                fi
            fi
            [ "$_partial" -eq 1 ] && break
        done < "$ext_file"

        if [ "$_found" -eq 1 ]; then
            # Found-but-empty emits nothing and stays breadcrumb-FREE on purpose — the
            # rule's "an empty section is equivalent to an absent heading" clause. The
            # heading WAS found, so the consumer's hook is wired correctly and there is
            # nothing for a reader to fix.
            # An explicit `if`, NOT `[ … ] && printf`: under `set -e` that AND-list is
            # the last statement of this branch, so a false test would propagate a
            # non-zero status out of the script and turn the designed empty-section
            # no-op into an exit-1 failure.
            if [ "$_has_body" -eq 1 ]; then
                printf '%s' "$_out"
            fi
        elif [ -s "$ext_file" ]; then
            # The heading is absent from a NON-EMPTY extension. The no-op itself is
            # DESIGNED (a single-hook extension carrying only the other heading is the
            # routine case, and it must not fail), so this stays exit 0 — but a silent
            # no-op is indistinguishable from a heading the consumer typo'd, so name
            # what was asked for and what is actually there. Only headings the extractor
            # genuinely recognizes are listed: advertising a heading inside a comment
            # block or a fence would send the caller chasing one it can never select.
            # The two arms share one message prefix rather than spelling it twice, so
            # the wording cannot drift between them.
            #
            # The `-s` guard is what scopes this to a non-empty file, as the contract
            # states at every site that documents it. An EMPTY extension is already the
            # documented silent no-op (byte-identical to having no extension at all), so
            # breadcrumbing it would report a "missing heading" for a consumer who has
            # opted out entirely — noise on the one shape that is unambiguously fine.
            _detail="the file carries no '## '-prefixed headings"
            [ -n "$_headings" ] && _detail="headings present: ${_headings}"
            echo "load-prompt-extension.sh: no section headed '$section' in '$ext_file'; ${_detail}" >&2
        fi
    fi
fi

# issue #1299: whole-file status token, computed once, emitted at one STDERR site (never
# stdout — stdout stays byte-verbatim). Undeliverable shapes exited 2 above. The
# `load-prompt-extension.sh: ` prefix is load-bearing (phase-3 drops those lines when classifying).
if [ "$section_requested" -eq 0 ]; then
    if [ -f "$ext_file" ] && [ -s "$ext_file" ]; then
        _wf_status=content-present
    else
        _wf_status=present-empty
    fi
    printf 'load-prompt-extension.sh: PROMPT-EXTENSION-STATUS: %s\n' "$_wf_status" >&2
fi
