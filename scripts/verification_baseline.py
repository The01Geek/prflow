#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Daniel Radman
# SPDX-License-Identifier: MIT
"""Offline verification-launch baseline analyzer (issue #527, Wave 1).

Read-only, pure Python standard library, no subprocess, no network. Builds a
source-provenanced baseline of actual verification launches from LOCAL native
transcript events, plus a local + cloud lifecycle census (eligibility + source
missingness) that is independent of transcript survival. Cloud LAUNCH analysis
is excluded in Wave 1 (no durable redacted execution-event source exists
without changing workflows); cloud rows are census/missingness-only.

The analyzer changes no skills/**, agents/**, .github/workflows/** execution
logic, config, allowlists, workpad/iteration writer, consumer routing, process
ownership, cancellation, or verification outcomes. It launches no verification
command and invokes no repository-provided executable — it reads already-imported
bundles + start manifests + the registry + an optional cloud census snapshot,
and that is all. workspace_state coverage is derived from explicit source-event
results, never analyzer-time inspection (so no git/subprocess).

Output is local and gitignored under owner-only 0700 directories and 0600 files
under .prflow/tmp/verification-baselines/. Artifacts carry created_at,
source_snapshot_hash, and expires_at; --cleanup deletes baseline and
manual-review artifacts without touching native sources. Raw transcript text,
tool input, stdout/stderr, secrets, redacted displays, and source paths never
enter model prompts, errors, logs, telemetry, workflow artifacts, PR comments,
or tracked .prflow/logs/**. The report cites source-event IDs only.

Sibling helpers in workflow_flight_recorder are re-implemented locally rather
than imported (`_atomic_write` literally; the recorder's timestamp helpers via
this module's own `_parse_iso_ms`/`_ms_to_iso`/`_now_iso` equivalents), to keep
this analyzer decoupled from the recorder's private surface and to guarantee
the no-subprocess/no-git contract by construction.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import sys
import time
import tracemalloc
from dataclasses import dataclass
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any

# Reuse the recorder's PUBLIC parsing API only (stable, pure stdlib). Importing
# the module is safe: the recorder's subprocess use lives inside its own git
# helpers, none of which the analyzer calls — and the run.sh grep pin asserts
# this module contains no subprocess call site of its own.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import workflow_flight_recorder as wfr  # noqa: E402

SAFE_ID = wfr.SAFE_ID
REGISTRY_SCHEMA_VERSION = 1
CLOUD_MAPPINGS_SCHEMA_VERSION = 1

ELIGIBLE_LIFECYCLE_SCHEMA = 1
VERIFICATION_REQUEST_SCHEMA = 1
VERIFICATION_PROCESS_LAUNCH_SCHEMA = 1
# 2: `metrics.eligible_lifecycles` changed MEANING — it counted every census row
# (confirmed-ineligible included); it now counts confirmed + provisional only,
# with the total moved to the new `metrics.census_rows`. A reader that kept
# treating the old field as the row total would silently mis-read the new
# output, so this is a semantic change, not an additive one, and the version
# moves with it (PR #531 review-and-fix iter-1, code-reviewer Important).
VERIFICATION_BASELINE_SCHEMA = 2
RELATIONSHIP_GROUP_SCHEMA = 1

# Census source enum (local vs cloud).
SOURCE_LOCAL = "local"
SOURCE_CLOUD = "cloud"

# Eligibility states — never promoted, never silently omitted (cardinality pinned by test_enum_cardinalities).
ELIGIBILITY_CONFIRMED = "confirmed_eligible"
ELIGIBILITY_PROVISIONAL = "provisional_candidate"
ELIGIBILITY_INELIGIBLE = "confirmed_ineligible"
ELIGIBILITY_UNKNOWN = "eligibility_unknown"
ELIGIBILITY_STATES = (
    ELIGIBILITY_CONFIRMED,
    ELIGIBILITY_PROVISIONAL,
    ELIGIBILITY_INELIGIBLE,
    ELIGIBILITY_UNKNOWN,
)

# Manifest `candidate.invocation_evidence` kinds — the ACTUAL eligibility
# discriminator. These mirror the tokens workflow_flight_recorder's
# capture_prompt_manifest writes (a cross-module coupling, kept as named
# constants so the decision is greppable and drift is visible). The manifest's
# sibling `provisional` flag is NOT a discriminator: the recorder hardcodes it
# True for every start kind, so keying eligibility on it makes confirmed_eligible
# unreachable for all real local data (issue #527 review finding).
EVIDENCE_EXACT = "exact_user_command"
EVIDENCE_COMMAND_MARKUP = "command_markup"
EVIDENCE_EMBEDDED = "embedded_user_command_candidate"
CONFIRMED_EVIDENCE_KINDS = (EVIDENCE_EXACT, EVIDENCE_COMMAND_MARKUP)

# Local source-status enum (left-join of native imports onto census rows).
SOURCE_AVAILABLE = "source_available"
SOURCE_ELIGIBLE_NOT_IMPORTED = "eligible_not_imported"
SOURCE_IMPORT_FAILED = "import_failed"
SOURCE_MISSING = "source_missing"
SOURCE_UNREADABLE = "source_unreadable"
SOURCE_UNSUPPORTED = "source_unsupported"
SOURCE_UNAVAILABLE = "unavailable"  # cloud census absent/incomplete
# Cloud rows carry their OWN source_status domain {available, unavailable},
# distinct from the local SOURCE_AVAILABLE="source_available". This is a named
# constant (not a bare "available" literal) so the producer (build_cloud_census)
# and the compute_metrics consumer share one symbol rather than two coupled
# literals that must stay byte-identical (issue #527 review finding).
CLOUD_SOURCE_AVAILABLE = "available"
LOCAL_SOURCE_STATUSES = (
    SOURCE_AVAILABLE,
    SOURCE_ELIGIBLE_NOT_IMPORTED,
    SOURCE_IMPORT_FAILED,
    SOURCE_MISSING,
    SOURCE_UNREADABLE,
    SOURCE_UNSUPPORTED,
)

# Authorization/start classification. Wave 1 ships a single native-transcript
# classifier; per-source versioned adapters are a future hook (see
# _classify_authorization_start), not a dispatch table today.
START_DENIED_PRE = "denied_pre_start"
START_CANCELLED_PRE = "cancelled_pre_start"
START_CONFIRMED_TERMINAL = "start_confirmed_terminal"
START_CONFIRMED_RESULT_MISSING = "start_confirmed_result_missing"
START_UNKNOWN = "start_unknown"
START_CLASSES = (
    START_DENIED_PRE,
    START_CANCELLED_PRE,
    START_CONFIRMED_TERMINAL,
    START_CONFIRMED_RESULT_MISSING,
    START_UNKNOWN,
)

# Request taxonomy (versioned).
TAXONOMY_VERSION = 1
KIND_VERIFICATION = "verification"
KIND_OTHER_COMMAND = "other_command"
KIND_VERIFICATION_UNKNOWN = "verification_unknown"
REQUEST_KINDS = (KIND_VERIFICATION, KIND_OTHER_COMMAND, KIND_VERIFICATION_UNKNOWN)

# Join confidence (cardinality pinned by test_enum_cardinalities).
CONFIDENCE_EXACT = "exact"
CONFIDENCE_PARTIAL = "partial"
CONFIDENCE_AMBIGUOUS = "ambiguous"
CONFIDENCE_UNMATCHED = "unmatched"
CONFIDENCE_CLASSES = (CONFIDENCE_EXACT, CONFIDENCE_PARTIAL, CONFIDENCE_AMBIGUOUS, CONFIDENCE_UNMATCHED)

# Relationship classes (cardinality pinned by test_enum_cardinalities).
REL_SINGLE = "single"
REL_CANDIDATE_TRANSPORT_RETRY = "candidate_transport_retry"
REL_INTENTIONAL_RERUN = "intentional_rerun_evidence"
REL_INDEPENDENT_LIFECYCLE = "independent_lifecycle"
REL_UNCLASSIFIABLE = "unclassifiable"
RELATIONSHIP_CLASSES = (
    REL_SINGLE,
    REL_CANDIDATE_TRANSPORT_RETRY,
    REL_INTENTIONAL_RERUN,
    REL_INDEPENDENT_LIFECYCLE,
    REL_UNCLASSIFIABLE,
)

MUTATION_STATE_UNBOUNDED = "mutation_state_unbounded"

# Adjudication verdicts reviewers record (manual-review artifact, initially empty).
ADJUDICATION_CONFIRMED_RETRY = "confirmed_retry_pattern"
ADJUDICATION_INTENTIONAL_RERUN = "intentional_rerun"
ADJUDICATION_INSUFFICIENT = "insufficient_evidence"
ADJUDICATION_VERDICTS = (ADJUDICATION_CONFIRMED_RETRY, ADJUDICATION_INTENTIONAL_RERUN, ADJUDICATION_INSUFFICIENT)

# Verification taxonomy signatures (versioned). A Bash tool_use whose command
# matches one of these is a verification request. Conservative: anything not
# matching a verification signature AND not a clearly-non-verification head is
# verification_unknown (never silently dismissed as "other").
VERIFICATION_PATTERNS = (
    re.compile(r"\blib/test/run\.sh\b"),
    re.compile(r"\bpytest\b"),
    re.compile(r"\bpython3?\s+-m\s+pytest\b"),
    re.compile(r"\bruff\b"),
    re.compile(r"\bshellcheck\b"),
    re.compile(r"\bnpm\s+(run\s+)?test\b"),
    re.compile(r"\byarn\s+test\b"),
    re.compile(r"\bcargo\s+test\b"),
    re.compile(r"\bgo\s+test\b"),
    re.compile(r"\bmvn\s+test\b"),
    re.compile(r"\bgradle\s+test\b"),
    re.compile(r"\bjest\b"),
    re.compile(r"\bvitest\b"),
    re.compile(r"\btox\b"),
)
# Clearly non-verification command heads (a request starting with one of these
# is other_command, not verification). Conservative and small.
NON_VERIFICATION_HEADS = frozenset(
    {"git", "gh", "ls", "cat", "echo", "cd", "pwd", "mkdir", "rm", "cp", "mv",
     "touch", "chmod", "chown", "stat", "file", "which", "env", "export",
     # Read-only text/inspection tools: never a verification launch, so an
     # incidental test-tool name in their arguments (`grep -r pytest .`,
     # `cat lib/test/run.sh`) must not be counted as one (issue #527 review).
     "grep", "sed", "awk", "find", "wc", "head", "tail", "cut", "tr", "sort",
     "uniq", "diff"}
)

# Secret-bearing token patterns (canonicalize+redact before digesting). Matched
# values are replaced with typed markers; the digest is of the redacted form, so
# no secret material reaches the binding identity. A redacted digest alone never
# establishes an exact match (see join_confidence).
# A secret VALUE is a quoted string (whole, including internal whitespace) or a
# bare non-whitespace run. `(\S+)` alone stops at the first space INSIDE a quoted
# value, leaving the raw remainder in the redacted display AND in the digest —
# the PR #531 iteration-1 leak (a quoted env secret with spaces survived
# redaction in fragments). Quoted forms must be consumed whole.
# A value is a greedy run of chunks — quoted strings consumed whole, plus any
# other non-space characters — so POSIX adjacent concatenation ("abc"def, a
# single shell word) is consumed to the word boundary, never split at the
# closing quote (PR #531 iteration-1 gate: the quoted-first alternation
# stopped at the close and leaked the concatenated remainder).
# Each quoted chunk closes at its matching quote OR at end-of-string: an
# opening quote with no close (typo, truncation) swallows the rest of the
# line in real shell, so redacting to EOL is the faithful, fail-closed
# reading (PR #531 iteration-1 re-gate finding 1 — the \S fallback used to
# stop at the first in-quote space and leak the tail).
# The bare-char alternative EXCLUDES quotes (`[^\s\"']`), so a quote can only
# be consumed by the quoted alternative — the segmentation is unambiguous and
# the match is linear. Admitting a quote into BOTH the quoted chunk and the
# bare fallback made a quote-dense run exponentially backtrack when a required
# trailing token (SECRET_SHORT_U's `:`) was absent (PR #531 early-shadow: a
# ~40-quote `-u` command hung _redact_secrets on attacker-shaped transcript
# text). Defense-in-depth: _SECRET_VALUE's own uses have no required suffix so
# they never backtracked, but the quote-exclusion is applied here too.
#
# A BACKSLASH ESCAPE is one shell character, so an escaped space does not end
# the word: `TOKEN=sec\ ret` is the single value `sec ret`. The bare-char class
# stopped at the escaped space, so the tail (`ret`) survived in
# redacted_display AND in the digest input while secret_affected=True falsely
# asserted redaction was complete (PR #531 review-and-fix iter-1, Phase-2 VC-6
# FAIL). This is the same recall class as the quoted-value and URL-password
# leaks above, in the escaped-value shape — fixed for the whole class (env,
# --flag, and -u alike), not the one cited spelling.
#
# The escape alternatives lead each chunk group and the bare-char classes
# EXCLUDE backslash (`[^\s\"'\\]`), so a backslash is consumable by EXACTLY ONE
# alternative — the same unambiguous-segmentation property the quote-exclusion
# establishes, so the linear-time guarantee is preserved rather than trading a
# leak for the ReDoS this file already fixed once. `\\$` (trailing lone
# backslash) and `\\[\s\S]` (escape pair) are mutually exclusive: the former
# requires end-of-string, the latter a following character.
_ESC_CHUNK = r"\\[\s\S]|\\$"
# A double-quoted chunk processes `\"` (shell escapes inside dquotes); a
# single-quoted chunk does NOT (backslash is literal in POSIX sglquotes), so it
# keeps consuming to the closing quote regardless.
_DQ_CHUNK = r"\"(?:\\[\s\S]|[^\"\\])*(?:\"|$)"
_SQ_CHUNK = r"'[^']*(?:'|$)"
_SECRET_VALUE = r"((?:" + _ESC_CHUNK + r"|" + _DQ_CHUNK + r"|" + _SQ_CHUNK + r"|[^\s\"'\\])+)"
SECRET_ENV_ASSIGNMENT = re.compile(
    # The keyword must be a SUFFIX of the variable name (name ends in the
    # keyword, immediately before `=`), not merely a substring. The old
    # `[A-Z0-9_]*KEYWORD[A-Z0-9_]*` form false-positived on `PATH=` (PAT),
    # `PATTERN=` (PAT), `KEYWORDS=` (KEY) — ubiquitous in this repo's stub
    # transcripts, blinding the baseline for the most common launch shape
    # (PR #531 early-shadow). Suffix-anchoring keeps the real names
    # (GITHUB_TOKEN, APIKEY, API_KEY, MY_PAT, AWS_SECRET_ACCESS_KEY all END
    # in a keyword) while rejecting the collision words above. Over-redaction
    # of a rare name that merely ends in a keyword (COMPASS=) stays the safe
    # direction (partial confidence, no leak).
    # A trailing `S?` admits the plural/compound forms (API_KEYS, GITHUB_TOKENS,
    # SECRETS) without re-admitting the collision words: PATH/PATTERN/KEYWORDS
    # end in a NON-`S` char after the keyword prefix, so `S?=` still rejects
    # them (PR #531 iteration-2 fix-delta gate: suffix-anchoring dropped plurals).
    # `(?<![-\w])` (not `\b`): a bare word-boundary treats the hyphen->letter
    # transition inside an attached-form flag (`--api-key=v`) as a boundary, so
    # the env pattern matched the interior `key=v` segment and appended a
    # phantom `env:KEY` slot beside the real `flag:api-key` one — mislabeling
    # the redaction provenance in the serialized artifact (PR #531
    # review-and-fix local iteration; no leak, the value was still redacted).
    # The lookbehind refuses an env-name start preceded by `-` or a word char.
    r"(?<![-\w])([A-Z0-9_]*(?:TOKEN|SECRET|PASSWORD|CREDENTIAL|PAT|PASS|KEY)S?)=" + _SECRET_VALUE,
    re.IGNORECASE,
)
SECRET_FLAG = re.compile(
    # Match ``--<name>`` whose name is exactly a keyword (``--token``) OR ends in a
    # hyphen-delimited keyword segment (``--api-key``, ``--auth-token``, ``--access-key``,
    # ``--secret-key``). Anchoring the keyword at a segment boundary avoids false-positiving
    # on common flags like ``--pattern`` (which contains ``pat``) while still catching every
    # compound secret flag the previous exact-match form missed.
    # The trailing `S?` mirrors SECRET_ENV_ASSIGNMENT's, and for the same
    # reason: the plural/compound spellings are real (`--tokens`, `--api-keys`,
    # `--secrets`, `--credentials`). Without it the keyword had to be followed
    # immediately by `[ =]`, so `--tokens` matched nothing at all and the raw
    # value reached redacted_display AND the digest with secret_affected=False —
    # which additionally skipped the secret-affected carve-outs in
    # join_confidence / _classify_relationship, so a credential-bearing binding
    # was treated as a clean `exact` match. The env sibling was given `S?` by an
    # earlier iteration of this same PR; this one was left behind — the same
    # class fix, one regex over (PR #531 review-and-fix, convergence shadow).
    # `S?` does not re-admit false positives for the same reason it doesn't
    # there: a non-secret flag that merely CONTAINS a keyword (`--pattern`,
    # `--keystore`) still fails the segment-boundary anchor.
    # Separator: attached `=`, a space, or space-padded `=` (` = `, `= `, ` =`).
    # Canonicalization collapses whitespace runs first, so ` ?= ?| ` covers every
    # canonical spelling. The old `[ =]` mis-parsed the space-padded forms:
    # `--token = hunter2` consumed the bare `=` AS the value, leaving the real
    # secret raw in redacted_display AND the digest input while
    # secret_affected=True falsely asserted redaction was complete, and the
    # sibling `--token= hunter2` matched nothing at all (leak with
    # secret_affected=False — the worse direction: no exclusion from the
    # secret-affected carve-outs either). Low-realism spellings, but the same
    # partial-redaction class this file already fixed for quoted/escaped values
    # (PR #531 review, Suggestion: fixed for the class, both siblings).
    # `-{1,2}` + `[-_]` segment delimiters (not `--` + `-` only): the env
    # pattern's hyphen lookbehind refuses every hyphen-preceded assignment, so
    # the flag pattern must carry the shapes the old `\b` env match had
    # accidentally covered — underscore long flags (`--api_key=v`, the
    # argparse/absl spelling) and single-dash forms (`-key=v`). Without this,
    # those secrets leaked raw with secret_affected=False (Step 3.5 fix-delta
    # gate, PR #531 review-and-fix local iteration — the worse direction: no
    # redaction AND no secret-affected carve-out).
    # `(?<!\w)` start anchor (NOT `(?<!\S)`): the anchor exists only to refuse
    # the mid-token mislabel (`X-API-KEY=v` matching at `-API-KEY=` as a
    # "flag"), and a preceding WORD character is exactly that case. Refusing
    # all of `\S` over-narrowed: a flag preceded by a quote, paren, or an
    # enclosing assignment's `=` (`run.sh "--token=v"`, `ARGS=--api-key=v`)
    # was matched by no pattern and leaked raw with secret_affected=False —
    # the worse direction (Step 3.5 fix-delta re-gate, PR #531 review-and-fix
    # local iteration, inner attempt 2). `(?<!\w)` admits those non-word
    # prefixes while still refusing the word-adjacent mid-token start; the
    # mislabeled token routes to SECRET_ASSIGNMENT_FALLBACK's honest
    # `assign:` label (still redacted either way).
    r"(?<!\w)(-{1,2}(?:[A-Za-z0-9_-]*[-_])?(?:token|key|password|passwd|secret|pat|credential)s?)"
    r"(?: ?= ?| )" + _SECRET_VALUE,
    re.IGNORECASE,
)
SECRET_ASSIGNMENT_FALLBACK = re.compile(
    # Whitespace-anchored assignment whose NAME contains a hyphen — the shapes
    # neither the env pattern (its lookbehind refuses hyphen-preceded starts,
    # and its name class has no `-`) nor the flag pattern (requires a leading
    # dash) can cover: header-style data tokens (`X-API-KEY=v`) and bespoke
    # single-dash property forms (`-Dapikey=v`). Runs AFTER the env and flag
    # substitutions; the `(?!<)` value guard keeps it from re-processing an
    # already-substituted `<env:...>`/`<flag:...>` marker (a raw secret that
    # itself begins with `<` is outside the recognized classes — the module's
    # documented Wave-1 recognition limitation covers it). The hyphen
    # requirement keeps plain `NAME=v` env shapes on the env pattern's honest
    # `env:` label. Same suffix-anchored keyword set + `S?` as the env pattern,
    # for the same collision-rejection reasons (Step 3.5 fix-delta gate,
    # PR #531 review-and-fix local iteration).
    # `(?<![\w.-])` start anchor (see SECRET_FLAG's `(?<!\w)` rationale — a
    # quote/paren-preceded token must still match; additionally refusing `-`
    # and `.` keeps this fallback from re-matching MID-token after a word char
    # was consumed, since its own name class contains both).
    r"(?<![\w.-])((?=[A-Za-z0-9_.\-]*-)[-A-Za-z0-9_.]*(?:TOKEN|SECRET|PASSWORD|CREDENTIAL|PAT|PASS|KEY)S?)=(?!<)" + _SECRET_VALUE,
    re.IGNORECASE,
)
# curl-style short-flag credentials: `-u user:pass`. The value halves get the
# same quoted-whole / unterminated-to-EOL treatment as _SECRET_VALUE, with
# quotes EXCLUDED from the bare-char classes so the required trailing `:`
# cannot trigger exponential backtracking on a quote-dense colon-less operand
# (PR #531 early-shadow ReDoS). The separator is OPTIONAL so curl's compact
# `-uuser:pass` is covered, and the lookbehind keeps `-u` inside `--user`-style
# long flags from firing. A colon is required, so a bare `-u` with a colon-free
# operand (`sort -u file.txt`) never matches; a `-u` operand that DOES contain
# a colon (`sort -u a:b`) is over-redacted — the safe direction (partial
# confidence, no leak), not the credential-only match the old comment claimed.
#
# The two WHOLE-OPERAND-quoted alternatives lead the group and are load-bearing
# (issue #527 review, Important 1): the halves-oriented third alternative only
# matches when a colon survives at the TOP level, but `-u "user:pass"` hides the
# colon INSIDE the quotes, so `"[^"]*(?:"|$)` consumed the operand whole, no
# top-level `:` remained, the pattern did not fire, and the raw credential
# reached both `redacted_display` and the digest input with secret_affected
# False (excluding it from the secret-affected retry-candidate carve-out).
# `[^"':]*` before the colon pins the FIRST in-quote colon as the separator, so
# each alternative has one deterministic parse and adds no backtracking pair —
# the ReDoS-safety property the quote-exclusion above establishes is preserved.
# The halves-oriented third alternative carries the SAME escape-awareness as
# _SECRET_VALUE (and shares its chunk definitions rather than re-deriving them —
# a second copy of this segmentation is exactly the coupled-mirror drift that
# would let one spelling regress silently): `-u user:pa\ ss` is one operand, and
# the escape-blind bare classes leaked the `ss` tail (PR #531 review-and-fix
# iter-1, Phase-2 VC-6 FAIL — same class as the env/--flag leak).
# The two WHOLE-OPERAND-quoted alternatives must carry the same escape-awareness
# and the same adjacent-concatenation consume as the halves alternative below.
# Giving it to the halves alternative ALONE left these two siblings of the same
# regex on the old escape-blind classes, so `-u "user:pa\"ss"` matched only
# through the unescaped `\"` and leaked the `ss"` tail into redacted_display AND
# the digest with secret_affected=True — the very "fixed for the whole class,
# not the one cited spelling" claim, falsified in the sibling alternative one
# line away (PR #531 review-and-fix iter-1, blinded fix-delta gate).
#
# The dquoted operand processes `\"`; the squoted one does NOT (backslash is
# literal in POSIX single quotes, and the first `'` closes), so they are
# deliberately asymmetric rather than uniformly "escape-aware" — a symmetric
# rule would misread the shell. Both then take a TAIL of ordinary chunks so
# POSIX adjacent concatenation (`'user:pa\'ss'`, one shell word) is consumed to
# the word boundary instead of stopping at the first closing quote. An
# unterminated trailing quote consumes to EOL, matching the existing
# unterminated-quote reading (in real shell the open quote does swallow the
# rest). Each half's class excludes its own terminator, so every character has
# exactly one parse path and the match stays linear.
_SHORT_U_DQ = r"\"(?:\\[\s\S]|[^\"':\\])*:(?:\\[\s\S]|[^\"\\])*(?:\"|$)"
_SHORT_U_SQ = r"'[^':]*:[^']*(?:'|$)"
_SHORT_U_TAIL = r"(?:" + _ESC_CHUNK + r"|" + _DQ_CHUNK + r"|" + _SQ_CHUNK + r"|[^\s\"'\\])*"
SECRET_SHORT_U = re.compile(
    r"(?<![\w-])(-u[ =]?)"
    r"("
    + _SHORT_U_DQ + _SHORT_U_TAIL
    + r"|" + _SHORT_U_SQ + _SHORT_U_TAIL
    + r"|(?:" + _ESC_CHUNK + r"|" + _DQ_CHUNK + r"|" + _SQ_CHUNK + r"|[^\s:\"'\\])+"
    r":(?:" + _ESC_CHUNK + r"|" + _DQ_CHUNK + r"|" + _SQ_CHUNK + r"|[^\s\"'\\])+"
    r")"
)
# URL credentials: `https://user:pass@host`. The PASSWORD half deliberately
# admits `/` and `@` (issue #527 review, Suggestion 1 — the same recall class as
# the `-u` whole-operand gap above): the old `[^/\s:@]+` password class failed on
# `https://user:pa/ss@host` (no match at all — the WHOLE credential leaked) and
# truncated `https://user:pa@ss@host` at the first `@` (leaking the `ss` tail).
# Greedy backtracking to the LAST `@` is where a URL's userinfo actually ends.
# The USER half still excludes `/`, which is what keeps a pathy
# `https://host/a:b@c` from false-positiving — and where a genuinely ambiguous
# authority does match, over-redaction is the safe direction (partial
# confidence, no leak), never a merged command.
#
# Both halves carry the SAME escape-awareness as _SECRET_VALUE, and share its
# chunk definitions rather than spelling a third copy of the segmentation (the
# coupled-mirror hazard that produced this very bug). The old `[^\s]+` password
# class stopped at a backslash-escaped space — one shell character, not a word
# boundary — so the required `@` became unreachable and the pattern did not fire
# AT ALL: on `https://user:pa\ ss@host` the whole credential, user and password
# both, reached redacted_display and the digest with secret_affected=False,
# which additionally skips the secret-affected carve-outs in join_confidence /
# _classify_relationship, so a credential-bearing binding read as a clean
# `exact` match. Strictly worse than the four sibling leaks fixed before it,
# which at least kept secret_affected=True. It stayed blind through four rounds
# of fixing its siblings precisely because no test row exercised this class —
# the untested sibling is the one that regressed (PR #531 review-and-fix,
# convergence shadow).
_URL_USER = r"(?:" + _ESC_CHUNK + r"|" + _DQ_CHUNK + r"|" + _SQ_CHUNK + r"|[^/\s:@\"'\\])+"
_URL_PASS = r"(?:" + _ESC_CHUNK + r"|" + _DQ_CHUNK + r"|" + _SQ_CHUNK + r"|[^\s\"'\\])+"
SECRET_URL = re.compile(r"(https?://)" + _URL_USER + r":" + _URL_PASS + r"@")
# Same escape-awareness, for class consistency rather than because a
# space-bearing bearer token is realistic (they are base64url by construction):
# leaving the one sibling escape-blind is exactly how the URL class survived
# four rounds of sibling fixes. Its fail-direction was milder — the tail leaked
# but secret_affected stayed True, so the carve-outs still fired.
# Quoted-chunk alternatives included (PR #531 early-shadow): a QUOTED Bearer
# value (`Bearer "abc"`) previously matched nothing and leaked raw with
# secret_affected=False — the same untested-sibling shape as the URL class.
BEARER_TOKEN = re.compile(r"(Bearer\s+)((?:" + _ESC_CHUNK + r"|" + _DQ_CHUNK + r"|" + _SQ_CHUNK + r"|[A-Za-z0-9._\-+/=])+)", re.IGNORECASE)

DEFAULT_MANIFESTS_DIR = ".prflow/tmp/workflow-manifests"
DEFAULT_BUNDLES_DIR = ".prflow/tmp/workflow-runs"
DEFAULT_REGISTRY = "scripts/workflow-flight-recorder-registry.json"
DEFAULT_OUT_DIR = ".prflow/tmp/verification-baselines"
DEFAULT_CLOUD_SNAPSHOT = None
DEFAULT_MAX_SOURCE_BYTES = 64 * 1024 * 1024  # 64 MiB per source; breach -> skipped reason.
DEFAULT_TTL_SECONDS = 30 * 24 * 3600  # expires_at = created_at + 30d

DIR_MODE = 0o700
FILE_MODE = 0o600


# --------------------------------------------------------------------------- #
# Input-byte accounting (performance.input_bytes).
# --------------------------------------------------------------------------- #
def _count_input_bytes(stats: "dict | None", n: int) -> None:
    """Accumulate bytes actually READ from source inputs (manifests, bundle
    metadata, transcripts, stop-attempts logs, the registry, the cloud census
    snapshot) into ``stats["input_bytes"]``. performance.input_bytes
    previously summed only the short per-row eligibility_evidence strings — a
    self-measurement tool under-reporting its own measured input by orders of
    magnitude (issue #527 review finding). Only successfully-read content is
    counted (an unreadable file contributes no bytes because none were read).
    A transcript read more than once counts each read (it is read at
    classification time and again at extraction time): the figure measures real
    transcript read I/O, not the deduplicated corpus size. The registry, read
    twice per run (load_registry + load_cloud_mappings), is the one exception —
    it is counted ONCE by size in main() (see the "counted once" note there), so
    this is not an unqualified "every read" universal (PR #531 early-shadow)."""
    if stats is not None:
        stats["input_bytes"] = stats.get("input_bytes", 0) + n


# --------------------------------------------------------------------------- #
# Path validation (reject symlinks, traversal, root escapes before opening).
# --------------------------------------------------------------------------- #
def _validate_admitted_path(raw: str, must_exist: bool = False) -> Path:
    """Resolve an admitted path, rejecting symlink escapes, traversal, and root escapes.

    Transcript text and cloud-snapshot paths are attacker-shaped data; never
    open them raw. Admits paths under the process cwd (ASSUMED to be the repo
    root — invoke the analyzer from the repo root; there is no git-root
    anchoring here, and the default relative paths stop resolving from a
    subdirectory), normalized and realpath-checked so a symlink escape or a
    ``..`` escape cannot reach outside the admitted root. An in-root symlink
    resolving to an in-root target is admitted (the containment check runs on
    the resolved target); what is rejected is every ESCAPE — symlink escapes,
    traversal escapes, root escapes — plus any unresolvable symlink
    (fail-closed).
    """
    if not isinstance(raw, str) or not raw:
        raise ValueError("path must be a non-empty string")
    candidate = Path(raw)
    # Reject path-traversal/root-escape syntactically before any filesystem call.
    if candidate.is_absolute() and not _within_repo_root(candidate):
        raise ValueError(f"path escapes the admitted root: {raw}")
    # Fail CLOSED on a symlink loop here, not just in the strict=True branch
    # below. resolve(strict=False) is version-divergent on an unresolvable loop:
    # Python <=3.12 raises RuntimeError (ELOOP), Python >=3.13 returns the path
    # unresolved. Catch both the raising forms (RuntimeError on <=3.12, OSError
    # defensively) so the loop is rejected identically on every interpreter
    # (issue #527: the >=3.13 non-raising path still fails closed via the
    # is_symlink()/strict=True block below).
    try:
        normalized = (Path(os.getcwd()) / candidate).resolve(strict=False)
    except (OSError, RuntimeError) as exc:
        raise ValueError(f"path could not be resolved (fail-closed): {raw}: {exc}") from exc
    if not _within_repo_root(normalized):
        raise ValueError(f"resolved path escapes the admitted root: {normalized}")
    # Primary symlink protection is the resolve()+_within_repo_root containment
    # check above: .resolve(strict=False) already collapses every resolvable
    # symlink (including a dangling one), so containment is checked on the real
    # target. This branch fires only for a symlink resolve() could NOT collapse
    # (e.g. a self-referential loop, where realpath returns the path unresolved)
    # and fails CLOSED on it: resolve(strict=True) raises OSError there, which
    # is rejected, not admitted (issue #527 review: the branch is near-dead by
    # design — kept for the unresolvable-symlink edge, not as the primary
    # containment).
    try:
        if normalized.is_symlink():
            target = normalized.resolve(strict=True)
            if not _within_repo_root(target):
                raise ValueError(f"symlink escapes the admitted root: {raw} -> {target}")
    except OSError as exc:
        raise ValueError(f"symlink target could not be resolved/verified (fail-closed): {raw}: {exc}") from exc
    if must_exist and not normalized.exists():
        raise FileNotFoundError(f"admitted path does not exist: {normalized}")
    return normalized


def _within_repo_root(path: Path) -> bool:
    root = Path(os.getcwd()).resolve(strict=False)
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


# --------------------------------------------------------------------------- #
# Atomic write (0700 dirs, 0600 files, fsync, atomic replace) — no shell.
# --------------------------------------------------------------------------- #
def _atomic_write(path: Path, data: bytes) -> None:
    parent = path.parent
    parent.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(parent, DIR_MODE)
    except OSError as exc:
        # Best-effort hardening stays best-effort (the run continues), but a
        # failed chmod silently degrades the documented owner-only promise —
        # surface it so the degraded permission state is auditable
        # (PR #531 iteration-1, silent-failure finding 6).
        print(f"devflow verification-baseline: could not chmod {parent} to 0700 ({exc}); artifacts may carry umask permissions", file=sys.stderr)
    tmp_fd, tmp_path = tempfile_staged(parent)
    try:
        with os.fdopen(tmp_fd, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(tmp_path, FILE_MODE)
        os.replace(tmp_path, path)
    finally:
        # str-vs-Path: tmp_path is a str; compare like-for-like (the sibling
        # exporter already does) so the guard is live, not vacuously true.
        if os.path.exists(tmp_path) and tmp_path != str(path):
            try:
                os.unlink(tmp_path)
            except OSError:
                pass


def tempfile_staged(parent: Path) -> "tuple[int, str]":
    import tempfile
    return tempfile.mkstemp(dir=str(parent), prefix=".vb-")


# --------------------------------------------------------------------------- #
# Timestamps (tz-aware; unknown stays unknown — None, never 0).
# --------------------------------------------------------------------------- #
def _now_iso() -> str:
    return datetime.now(tz=timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _parse_iso_ms(value: Any) -> "int | None":
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    return int(parsed.timestamp() * 1000)


def _ms_to_iso(ms: "int | None") -> "str | None":
    if ms is None:
        return None
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _expires_at(created_iso: str, ttl_seconds: int = DEFAULT_TTL_SECONDS) -> str:
    try:
        created = datetime.fromisoformat(created_iso.replace("Z", "+00:00"))
    except ValueError:
        # Latent (the only caller passes _now_iso() output, which always
        # parses) — but the artifact's retention promise rides on expires_at,
        # so a silent created==expires fallback was the one quiet degradation
        # in a loud module (PR #531 early-shadow). Breadcrumb + unchanged
        # return contract.
        print(
            f"devflow verification-baseline: expires_at could not be derived from "
            f"unparseable created timestamp {created_iso!r}; artifact carries it unchanged",
            file=sys.stderr,
        )
        return created_iso
    return (created + timedelta(seconds=ttl_seconds)).isoformat(timespec="milliseconds").replace("+00:00", "Z")


# --------------------------------------------------------------------------- #
# Surrogate IDs + safe digests.
# --------------------------------------------------------------------------- #
def _sha8(*parts: str) -> str:
    digest = hashlib.sha256("␟".join(parts).encode("utf-8")).hexdigest()
    return digest[:12]


def _sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _surrogate_id(source: str, *identity_parts: str) -> str:
    """Row-local surrogate ID so unknown natural-key fields never coalesce.

    Distinct from a natural key: two rows with unknown/empty natural-key fields
    still get distinct surrogate IDs (the position-in-input is part of the
    hash), so they never join as if they shared an identity.
    """
    return f"{source}-{_sha8(*identity_parts)}"


def _source_event_id(session_id: str, event_index: int) -> str:
    """Cite source events by ID, not raw transcript path/text."""
    return f"evt:{_sha8(session_id)}:{event_index}"


# --------------------------------------------------------------------------- #
# Secret redaction + safe binding identity.
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class BindingIdentity:
    # SHA-256 of the REDACTED canonical command (computed after secret redaction,
    # so no secret material is digested; NOT an HMAC — a same-shape command
    # yields the same digest by design, see test_secret_redaction_boundary).
    digest: str
    secret_affected: bool
    secret_slots: tuple[str, ...]  # typed markers, e.g. ("env:TOKEN", "flag:key", "url-cred", "bearer")
    redacted_display: str  # canonical + redacted, length-bounded (local record only)

    def __post_init__(self) -> None:
        # Construction-time invariants (issue #527 review, type-design note):
        # the factory (_binding_identity) is the intended constructor, but a
        # direct construction / dataclasses.replace must not be able to put an
        # unredacted-looking payload into the record silently. The full
        # "digest is of the redacted form" property cannot be checked in-type;
        # these are the checkable halves.
        if not re.fullmatch(r"[0-9a-f]{64}", self.digest):
            raise ValueError("BindingIdentity.digest must be a lowercase sha256 hex digest")
        if self.secret_affected != bool(self.secret_slots):
            raise ValueError("BindingIdentity.secret_affected must equal bool(secret_slots)")
        if len(self.redacted_display) > 500:
            raise ValueError("BindingIdentity.redacted_display must be length-bounded (<=500)")

    def to_dict(self) -> dict[str, Any]:
        return {
            "digest": self.digest,
            "secret_affected": self.secret_affected,
            "secret_slots": list(self.secret_slots),
            # NOTE: redacted_display is local-record-only (gitignored 0700); it is
            # never emitted into reports/PR comments/logs (reports cite source-event IDs only).
            "redacted_display": self.redacted_display,
        }


def _canonical_command(command: str) -> str:
    # Collapse internal runs of whitespace and strip. Binding identity is
    # case-sensitive on purpose (a differently-cased command is a different
    # binding); the head is deliberately not lowercased.
    return re.sub(r"\s+", " ", command).strip()


def _redact_secrets(command: str) -> "tuple[str, bool, list[str]]":
    """Canonicalize + redact secret-bearing tokens before digesting.

    Returns (redacted_command, secret_affected, typed_slots). For every
    RECOGNIZED pattern class (env assignment incl. quoted values, --flag
    secrets incl. quoted values and underscore/single-dash spellings,
    hyphen-named assignment tokens via the ``assign:`` fallback
    (``X-API-KEY=v``, ``-Dapikey=v``), `-u user:pass` incl. quoted halves AND
    a quoted whole operand, URL credentials incl. a password containing `/`
    or `@`, Bearer tokens), no raw secret and no unkeyed digest of secret material leaves
    this function: the digest (in BindingIdentity) is computed over
    ``redacted_command``. Known Wave-1 limitation (documented, not guessed
    at): a secret passed through a shape OUTSIDE these classes — e.g. a bare
    positional password, a bespoke short flag other than ``-u``, or an
    assignment value that itself begins with ``<`` (the fallback's
    marker-safety guard skips it) — is not recognized and therefore not
    redacted; extending the class set is the
    remedy, and the conservative direction (per issue #527's gotcha) is that
    an over-broad redaction lowers confidence rather than merging commands,
    so new classes should prefer precision (like ``-u``'s colon requirement)
    over recall.
    """
    redacted = command
    slots: list[str] = []

    def env_repl(match: "re.Match[str]") -> str:
        name = match.group(1)
        slots.append(f"env:{name.upper()}")
        return f"{name}=<env:{name.upper()}>"

    redacted = SECRET_ENV_ASSIGNMENT.sub(env_repl, redacted)

    def flag_repl(match: "re.Match[str]") -> str:
        flag = match.group(1).lower()
        slots.append(f"flag:{flag.lstrip('-')}")
        return f"{match.group(1)}=<flag:{flag.lstrip('-')}>"

    redacted = SECRET_FLAG.sub(flag_repl, redacted)

    def assign_repl(match: "re.Match[str]") -> str:
        name = match.group(1)
        label = name.lstrip("-").upper()
        slots.append(f"assign:{label}")
        return f"{name}=<assign:{label}>"

    # After env+flag: catches hyphen-named assignments neither sibling covers
    # (see SECRET_ASSIGNMENT_FALLBACK's rationale); the value guard skips
    # already-substituted markers.
    redacted = SECRET_ASSIGNMENT_FALLBACK.sub(assign_repl, redacted)

    def short_u_repl(match: "re.Match[str]") -> str:
        slots.append("flag:u")
        return f"{match.group(1)}<flag:u>"

    redacted = SECRET_SHORT_U.sub(short_u_repl, redacted)

    def url_repl(match: "re.Match[str]") -> str:
        slots.append("url-cred")
        return f"{match.group(1)}<url-cred>@"

    redacted = SECRET_URL.sub(url_repl, redacted)

    def bearer_repl(match: "re.Match[str]") -> str:
        slots.append("bearer")
        return f"{match.group(1)}<bearer>"

    redacted = BEARER_TOKEN.sub(bearer_repl, redacted)

    affected = bool(slots)
    # Deduplicate slots preserving order.
    seen: set[str] = set()
    unique_slots = [s for s in slots if not (s in seen or seen.add(s))]
    return redacted, affected, unique_slots


def _binding_identity(command: str) -> BindingIdentity:
    canonical = _canonical_command(command)
    redacted, affected, slots = _redact_secrets(canonical)
    # Length-bound the local-only display so even the redacted form cannot dump
    # unbounded command text into the (gitignored, 0700) record.
    display = redacted[:500]
    digest = _sha256_hex(redacted.encode("utf-8"))
    return BindingIdentity(digest=digest, secret_affected=affected, secret_slots=tuple(slots), redacted_display=display)


# --------------------------------------------------------------------------- #
# Records (each schema-versioned independently; additive fields do not bump).
#
# Type-design hardening (issue #527 review, Important 5): every record type
# validates its taxonomy fields at construction (__post_init__), so an invalid
# enum value is a loud ValueError at the producer, not a silent stringly-typed
# row that degrades downstream tallies. The three extraction-side records
# (VerificationRequest, VerificationProcessLaunch, RelationshipGroup) are
# frozen — nothing mutates them after construction. EligibleLifecycle is
# deliberately NOT frozen: join_local_imports / extract_verification_lifecycles
# mutate ``source_status`` in place (the left-join contract) — so its taxonomy
# invariants are re-validated on EVERY assignment via __setattr__ (source,
# source_status, eligibility_state), not only at construction (the earlier
# "construction only" sentence here was falsified by that very hardening —
# PR #531 early-shadow, type-design finding 1). Literal[...] aliases were considered and
# rejected: they would duplicate every enum literal already named by the
# module-level constant tuples, creating coupled mirrors this repo's
# conventions forbid — the __post_init__ checks validate against those same
# tuples instead.
#
# Deliberate Wave-1 boundary (PR #531 review, type-design note, recorded
# deferral): the dict-bag fields (identity, subject, provenance, timing,
# workspace_state) stay plain dicts whose shapes mirror the serialized JSON
# schema one-to-one; their structural invariants live in the per-field comments
# and the test fixtures. Promoting them to nested record types is Wave-2 schema
# work — revisit when a second consumer of these records exists (today the only
# reader is the serializer + the report generator), so the type wall lands where
# an actual cross-consumer contract needs it rather than as speculative depth.
# --------------------------------------------------------------------------- #
def _require_member(field_name: str, value: Any, allowed: tuple) -> None:
    if value not in allowed:
        raise ValueError(f"{field_name} must be one of {allowed}; got {value!r}")


@dataclass
class EligibleLifecycle:
    source: str  # local | cloud
    surrogate_id: str
    consumer: str | None
    subject: dict | None
    identity: dict  # local: session_id/project_path/started_at; cloud: repo/workflow/run_id/attempt/job/started_at
    eligibility_state: str
    eligibility_evidence: str
    host_profile: dict | None
    source_status: str  # local: LOCAL_SOURCE_STATUSES; cloud: available|unavailable
    provenance: dict  # session_id refs + snapshot_ref (no raw native paths)
    schema_version: int = ELIGIBLE_LIFECYCLE_SCHEMA

    def __post_init__(self) -> None:
        _require_member("EligibleLifecycle.source", self.source, (SOURCE_LOCAL, SOURCE_CLOUD))
        _require_member("EligibleLifecycle.eligibility_state", self.eligibility_state, ELIGIBILITY_STATES)
        self._require_valid_source_status(self.source_status)

    def _require_valid_source_status(self, value: str) -> None:
        """The source-conditional status check, shared by construction AND
        mutation so the two cannot drift into different accepted sets."""
        self._require_status_in_source_domain(value, self.source)

    @staticmethod
    def _require_status_in_source_domain(value: str, source: str) -> None:
        """Single owner of the source->status domain mapping (both __setattr__
        arms and __post_init__ route here, so the accepted sets cannot drift)."""
        allowed_status = (
            LOCAL_SOURCE_STATUSES if source == SOURCE_LOCAL
            else (CLOUD_SOURCE_AVAILABLE, SOURCE_UNAVAILABLE)
        )
        _require_member("EligibleLifecycle.source_status", value, allowed_status)

    def __setattr__(self, name: str, value: Any) -> None:
        """Construction-enforced source_status invariant (PR #531 review,
        type-design suggestion 2): the field is publicly assignable on a
        non-frozen dataclass, so routing every site through set_source_status
        held the invariant only by CONVENTION — a new direct-assignment site
        would silently bypass it. Validating in __setattr__ makes the invariant
        hold by construction for every assignment path (dataclass __init__,
        set_source_status, and any direct ``row.source_status = …``).
        Field-order note: ``source`` is declared before ``source_status``, so
        the cross-field check always sees ``source`` already bound during
        __init__ (dataclasses assign fields in declaration order)."""
        if name == "source_status":
            self._require_valid_source_status(value)
        elif name == "source" and "source_status" in self.__dict__:
            # Symmetric guard (PR #531 review-and-fix local iteration): the
            # cross-field invariant was enforced only on the source_status
            # side, so reassigning ``source`` after construction could leave a
            # local-domain status on a cloud row with no error — exactly the
            # inconsistent state the docstring says is impossible "for every
            # assignment path". Validate the NEW source value itself first
            # (else `row.source = "bogus"` would slip through the else-arm of
            # the domain map — the Step 3.5 gate's fail-open catch), then
            # re-validate the already-bound status against it, through the one
            # shared domain helper (no drifting copies). Validation runs
            # BEFORE assignment, so a rejected mutation leaves the row
            # unchanged. (No live call site reassigns source; this closes the
            # latent path by construction.)
            _require_member("EligibleLifecycle.source", value, (SOURCE_LOCAL, SOURCE_CLOUD))
            self._require_status_in_source_domain(self.source_status, value)
        elif name == "eligibility_state" and "eligibility_state" in self.__dict__:
            # The third taxonomy field gets the same reassignment guard as its
            # two siblings (PR #531 early-shadow, type-design finding 2): it
            # feeds owning_lifecycle_eligibility_state's producer path at
            # extraction, so a silent post-construction corruption here would
            # detonate inside a VALIDATED field's constructor at a distance.
            # (__post_init__ still validates the initial assignment; the
            # __dict__ gate keeps dataclass __init__'s first write on that
            # path.)
            _require_member("EligibleLifecycle.eligibility_state", value, ELIGIBILITY_STATES)
        object.__setattr__(self, name, value)

    def set_source_status(self, value: str) -> None:
        """Re-validating mutator — the documented way source_status changes.

        This class is deliberately not frozen: the left-join contract mutates
        source_status in place. But __post_init__ runs once, so validating only
        there made the class's own documented guarantee — "an invalid enum value
        is a loud ValueError at the producer, not a silent stringly-typed row
        that degrades downstream tallies" — true for the row's first millisecond
        and false for the mutation-heavy lifetime it actually has. Every
        assignment site routes through here, and __setattr__ above now enforces
        the same check on ANY assignment path, so the invariant holds by
        construction, not convention; validation runs BEFORE assignment, so a
        rejected mutation leaves the row unchanged rather than half-applied
        (PR #531 review-and-fix, park-calibration gate: the shadow re-raised a
        finding iteration 1 had parked, so the parked grade was wrong).
        """
        self._require_valid_source_status(value)
        self.source_status = value

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "source": self.source,
            "surrogate_id": self.surrogate_id,
            "consumer": self.consumer,
            "subject": self.subject,
            "identity": self.identity,
            "eligibility_state": self.eligibility_state,
            "eligibility_evidence": self.eligibility_evidence,
            "host_profile": self.host_profile,
            "source_status": self.source_status,
            "provenance": self.provenance,
        }


@dataclass(frozen=True)
class VerificationRequest:
    request_id: str
    source_event_id: str
    lifecycle_id: str | None
    tool_use_id: str
    consumer_skill: str | None
    phase_checkpoint: str | None
    command_head: str
    binding: BindingIdentity
    request_kind: str  # verification | other_command | verification_unknown
    authorization_start: str
    timing: dict  # requested_at, started_at, finished_at, duration_ms
    result_presence: bool | None
    exit_evidence: dict | None
    skipped_check_evidence: dict | None
    provenance: dict
    schema_version: int = VERIFICATION_REQUEST_SCHEMA

    def __post_init__(self) -> None:
        _require_member("VerificationRequest.request_kind", self.request_kind, REQUEST_KINDS)
        _require_member("VerificationRequest.authorization_start", self.authorization_start, START_CLASSES)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "request_id": self.request_id,
            "source_event_id": self.source_event_id,
            "lifecycle_id": self.lifecycle_id,
            "tool_use_id": self.tool_use_id,
            "consumer_skill": self.consumer_skill,
            "phase_checkpoint": self.phase_checkpoint,
            "command_head": self.command_head,
            "binding": self.binding.to_dict(),
            "request_kind": self.request_kind,
            "authorization_start": self.authorization_start,
            "timing": self.timing,
            "result_presence": self.result_presence,
            "exit_evidence": self.exit_evidence,
            "skipped_check_evidence": self.skipped_check_evidence,
            "provenance": self.provenance,
        }


@dataclass(frozen=True)
class VerificationProcessLaunch:
    launch_id: str
    request_id: str
    source_event_id: str
    lifecycle_id: str | None
    tool_use_id: str
    consumer_skill: str | None
    phase_checkpoint: str | None
    command_head: str
    binding: BindingIdentity
    start_authorization: str
    timing: dict  # started_at, finished_at, duration_ms, caller_observed_duration_ms
    workspace_state: dict  # covered_roots, observation_method, coverage, mutation_state_unbounded
    result_presence: bool | None
    exit_evidence: dict | None
    skipped_check_evidence: dict | None
    provenance: dict
    # The eligibility state of the census row this launch was extracted from.
    # A REAL validated field, not a `provenance` dict key: this is the value the
    # numerator/denominator visibility fix exists to publish, so a call site that
    # forgot it — or a renamed key — must be a loud error at the producer, not a
    # silent collapse into an "unrecorded" bucket indistinguishable from a
    # genuine omission. Every other taxonomy value on this class is
    # _require_member-validated; asserting this one's invariant in prose while
    # leaving it in an unvalidated bag is the stringly-typed hazard this module's
    # own comments warn against (PR #531 review-and-fix iter-1, shadow).
    #
    # REQUIRED — no default. A default of ELIGIBILITY_UNKNOWN is a full member of
    # ELIGIBILITY_STATES, so it passes _require_member cleanly: an omitting call
    # site would have silently received it and landed in the same bucket as a row
    # whose eligibility genuinely could not be established — reproducing the
    # exact silent-collapse this field exists to prevent, one layer down, while
    # the comment above claimed otherwise. _require_member cannot tell "explicitly
    # unknown" from "never set"; only the absence of a default can, and it makes
    # a forgetful call site a TypeError at construction (PR #531 review-and-fix,
    # convergence shadow: the claim above was false against the defaulted field).
    owning_lifecycle_eligibility_state: str
    retrigger_evidence: bool = False  # explicit iteration/checkpoint/post-fix/base-merge/human-retrigger; Wave 1 extraction never sets this True (no markers extracted), but the field carries the guard the candidate classification requires.
    schema_version: int = VERIFICATION_PROCESS_LAUNCH_SCHEMA

    def __post_init__(self) -> None:
        _require_member("VerificationProcessLaunch.start_authorization", self.start_authorization, START_CLASSES)
        _require_member("VerificationProcessLaunch.owning_lifecycle_eligibility_state",
                        self.owning_lifecycle_eligibility_state, ELIGIBILITY_STATES)
        if not isinstance(self.retrigger_evidence, bool):
            # The load-bearing no-retrigger guard must be a real bool — a truthy
            # string ("false") silently flipping candidates to intentional_rerun
            # is exactly the stringly-typed hazard flagged in review (#527).
            raise ValueError(
                f"VerificationProcessLaunch.retrigger_evidence must be bool; got {self.retrigger_evidence!r}"
            )
        if self.result_presence is not None and not isinstance(self.result_presence, bool):
            # Symmetric with retrigger_evidence (PR #531 early-shadow,
            # type-design finding 3): result_presence feeds the same
            # candidate classifier via an `is False` identity check — a
            # stringly "False" fails CLOSED there (under-count, never a
            # fabricated candidate), so this is uniformity of enforcement,
            # not a live-bug fix.
            raise ValueError(
                f"VerificationProcessLaunch.result_presence must be bool or None; got {self.result_presence!r}"
            )

    @property
    def is_prior_missing_evidence(self) -> bool:
        # A launch is prior-missing-result evidence ONLY when its start was
        # confirmed but its result went missing (START_CONFIRMED_RESULT_MISSING).
        # result_presence is deliberately NOT consulted here — the start class is
        # the single discriminator. Denied/cancelled/unknown starts do NOT prove a
        # missing response and must fail closed. Single authoritative definition
        # shared by both _classify_relationship candidate sites.
        return self.start_authorization == START_CONFIRMED_RESULT_MISSING

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "launch_id": self.launch_id,
            "request_id": self.request_id,
            "source_event_id": self.source_event_id,
            "lifecycle_id": self.lifecycle_id,
            "tool_use_id": self.tool_use_id,
            "consumer_skill": self.consumer_skill,
            "phase_checkpoint": self.phase_checkpoint,
            "command_head": self.command_head,
            "binding": self.binding.to_dict(),
            "start_authorization": self.start_authorization,
            "timing": self.timing,
            "workspace_state": self.workspace_state,
            "result_presence": self.result_presence,
            "exit_evidence": self.exit_evidence,
            "skipped_check_evidence": self.skipped_check_evidence,
            "provenance": self.provenance,
            "owning_lifecycle_eligibility_state": self.owning_lifecycle_eligibility_state,
            "retrigger_evidence": self.retrigger_evidence,
        }


@dataclass(frozen=True)
class RelationshipGroup:
    group_id: str
    # tuple (not list): the frozen record was only shallow-frozen with a list
    # (group.members.append() succeeded), mirroring BindingIdentity.secret_slots'
    # existing tuple precedent (PR #531 review + early-shadow re-raise — the
    # park-calibration gate promoted iteration 1's parked grade).
    members: tuple[str, ...]  # launch_ids
    relationship: str
    join_confidence: str
    workspace_state: dict
    binding_digest: str | None
    consumer: str | None
    duration_ms: int | None  # group representative duration (max member duration)
    provenance: dict
    schema_version: int = RELATIONSHIP_GROUP_SCHEMA

    def __post_init__(self) -> None:
        _require_member("RelationshipGroup.relationship", self.relationship, RELATIONSHIP_CLASSES)
        _require_member("RelationshipGroup.join_confidence", self.join_confidence, CONFIDENCE_CLASSES)
        # Relationship<->cardinality invariant, self-enforced at the record
        # (previously producer-held control flow only): non-empty always;
        # REL_SINGLE means exactly one member; every multi-member class means
        # at least two.
        if not self.members:
            raise ValueError("RelationshipGroup.members must be non-empty")
        if self.relationship == REL_SINGLE and len(self.members) != 1:
            raise ValueError("RelationshipGroup: REL_SINGLE requires exactly one member")
        if self.relationship != REL_SINGLE and len(self.members) < 2:
            raise ValueError(f"RelationshipGroup: {self.relationship} requires >= 2 members")

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "group_id": self.group_id,
            "members": list(self.members),
            "relationship": self.relationship,
            "join_confidence": self.join_confidence,
            "workspace_state": self.workspace_state,
            "binding_digest": self.binding_digest,
            "consumer": self.consumer,
            "duration_ms": self.duration_ms,
            "provenance": self.provenance,
        }


# --------------------------------------------------------------------------- #
# Cloud mappings loader (additive registry section; load_registry ignores it).
# --------------------------------------------------------------------------- #
def load_cloud_mappings(registry_path: Path) -> dict[str, dict[str, object]]:
    """Return {(workflow_file, job): agent_job_entry} from the registry's
    additive cloud_mappings section. Returns {} when the section is absent
    (cloud census is optional; silent, by design), when it is present but
    malformed/wrong-schema, OR when the registry itself is unreadable/corrupt
    or not a JSON object. Every case yields an empty table, so a present snapshot then
    builds an all-ineligible cloud census reported as available — and every
    case EXCEPT the absent section (the one silent-by-design arm) additionally
    emits a stderr breadcrumb, so an operator misconfiguration is a LOUD
    degradation distinguishable from a genuinely-empty window (not silently
    indistinguishable from it). The section
    is committed data authored once and the registry's top-level schema_version
    is validated by load_registry, so a malformed section is a rare authoring
    error rather than a runtime hazard."""
    try:
        document = json.loads(registry_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        # UnicodeDecodeError is a ValueError, not an OSError — without it a
        # non-UTF-8 registry aborts the analyzer instead of degrading (#527).
        # An unreadable/corrupt registry is a strictly WORSE misconfiguration
        # than a malformed section, so it takes the same loud-degradation arm
        # (PR #531 review-and-fix local iteration: the silent {} here
        # contradicted this function's own documented loud contract — narrow
        # today because load_registry has just succeeded on the same path in
        # main(), but full-width for any future caller without that preface).
        print(
            "devflow verification-baseline: registry unreadable/corrupt for cloud_mappings "
            f"({type(exc).__name__}); cloud jobs will read ineligible. Fix or restore the registry.",
            file=sys.stderr,
        )
        return {}
    if not isinstance(document, dict):
        print(
            "devflow verification-baseline: registry top level is not a JSON object; "
            "cloud_mappings unavailable — cloud jobs will read ineligible. Fix the registry.",
            file=sys.stderr,
        )
        return {}
    mappings = document.get("cloud_mappings")
    if mappings is None:
        # Section absent — cloud census is optional. Silent, by design.
        return {}
    # Section PRESENT but malformed/wrong-schema: distinct from "absent". Both
    # yield {} (so a present snapshot builds an all-ineligible cloud census), but
    # an operator misconfiguration must be a LOUD degradation — otherwise "config
    # is broken" is indistinguishable from "the window genuinely had no agent
    # jobs" (issue #527 review finding; the repo's unknown-is-not-zero /
    # loud-degradation discipline). The return contract is unchanged.
    if not isinstance(mappings, dict) or mappings.get("schema_version") != CLOUD_MAPPINGS_SCHEMA_VERSION:
        print(
            "devflow verification-baseline: cloud_mappings section is present but "
            f"malformed (not an object, or schema_version != {CLOUD_MAPPINGS_SCHEMA_VERSION}); "
            "ignoring it — cloud jobs will read ineligible. Fix the registry's cloud_mappings section.",
            file=sys.stderr,
        )
        return {}
    agent_jobs = mappings.get("agent_jobs")
    if not isinstance(agent_jobs, list):
        print(
            "devflow verification-baseline: cloud_mappings.agent_jobs is present but "
            "not a list; ignoring the cloud_mappings section — cloud jobs will read "
            "ineligible. Fix the registry's cloud_mappings section.",
            file=sys.stderr,
        )
        return {}
    # `object` (not `str`) in the value type: `consumer_approximate` is a bool.
    # It is carried rather than dropped because the registry's own comment
    # instructs downstream stratification NOT to treat the devflow.yml `command`
    # job's consumer as exact — an instruction nothing could honor while its only
    # reader silently discarded the flag, leaving an approximate attribution
    # indistinguishable from an exact one (PR #531 review-and-fix iter-1,
    # Phase-2 VC-33 FAIL). Default False: absent means exact, and a non-bool
    # shape coerces rather than admitting a truthy string.
    table: dict[str, dict[str, object]] = {}
    dropped = 0
    for entry in agent_jobs:
        if not isinstance(entry, dict):
            dropped += 1
            continue
        wf = entry.get("workflow_file")
        job = entry.get("job")
        if not isinstance(wf, str) or not isinstance(job, str):
            dropped += 1
            continue
        table[f"{wf}\x1f{job}"] = {
            "consumer_approximate": entry.get("consumer_approximate") is True,
            "consumer": str(entry.get("consumer") or ""),
            "routed_command": str(entry.get("routed_command") or ""),
            "agent_step": str(entry.get("agent_step") or ""),
        }
    if dropped:
        # Individual malformed entries silently reducing the table is the same
        # loud-degradation class as a malformed section: name the count so an
        # operator sees the misconfiguration (issue #527 review, class sweep).
        print(
            f"devflow verification-baseline: cloud_mappings.agent_jobs dropped {dropped} "
            "malformed entr(ies) (non-object, or non-string workflow_file/job); the "
            "corresponding cloud jobs will read ineligible. Fix the registry's cloud_mappings section.",
            file=sys.stderr,
        )
    return table


# --------------------------------------------------------------------------- #
# Local census: one EligibleLifecycle row per start manifest.
# --------------------------------------------------------------------------- #
def build_local_census(manifests_dir: Path, registry: dict, stats: "dict | None" = None) -> list[EligibleLifecycle]:
    rows: list[EligibleLifecycle] = []
    if not manifests_dir.exists() or not manifests_dir.is_dir():
        # This function is the SOLE producer of the entire local denominator, so
        # returning [] silently made a typo'd --manifests-dir, a stale path, or a
        # wrong cwd produce census_rows: 0 / eligible_lifecycles: 0 at exit 0 — a
        # report reading exactly like "we measured a genuinely empty corpus".
        # That is this module's own "unknown is not zero" contract broken at the
        # one place it matters most, and it was the only degradation in the file
        # left completely silent while every sibling breadcrumbs (a malformed
        # cloud_mappings section, a gh failure, a dropped API row, a chmod
        # failure, even a stat failure whose only impact is a telemetry byte
        # count). Non-fatal on purpose — a not-yet-created manifests dir is a
        # legitimate "no data yet" state on a first run — but never silent: an
        # absent corpus and an unmeasured one must be distinguishable by a reader
        # (PR #531 review-and-fix, convergence shadow).
        print(
            f"devflow verification-baseline: manifests dir {manifests_dir} does not exist or is "
            "not a directory; the local census is EMPTY (0 rows) because nothing was measured — "
            "verify --manifests-dir points at the right path rather than reading this as a "
            "genuinely empty corpus",
            file=sys.stderr,
        )
        return rows
    # `is_file() or is_symlink()`: is_file() follows symlinks, so a BROKEN
    # symlink (or a symlink to a directory) named *.json would otherwise be
    # silently excluded — no row, no breadcrumb — violating unknown-is-not-zero
    # for exactly the planted entry the guard below exists to surface (Step 3.5
    # fix-delta gate). Including is_symlink() routes every symlink, dangling or
    # not, into the loud rejection arm.
    manifest_files = sorted(p for p in manifests_dir.iterdir() if p.suffix == ".json" and (p.is_file() or p.is_symlink()))
    for position, path in enumerate(manifest_files):
        if path.is_symlink():
            # AC #61: reject symlinks before opening. The top-level dirs route
            # through _validate_admitted_path, but files DISCOVERED under them
            # are agent-writable at runtime — a planted symlink must never be
            # followed to an out-of-root read (PR #531 review-and-fix local
            # iteration). The row is still counted (unknown-manifest shape:
            # unknown is not zero), with a loud breadcrumb.
            print(
                f"devflow verification-baseline: rejecting symlinked manifest {path.name} "
                "(AC #61: symlinks under admitted roots are never followed); "
                "counted as an unknown-manifest row",
                file=sys.stderr,
            )
            rows.append(_unknown_manifest_row(path, position, reason="symlinked manifest rejected (AC #61: symlinks under admitted roots are never followed)"))
            continue
        try:
            raw = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            # Unreadable manifest -> denominator row with eligibility_unknown.
            # UnicodeDecodeError (a ValueError) is caught explicitly: a
            # non-UTF-8 manifest is a source_unreadable denominator row, never
            # an analyzer abort (issue #527 review finding).
            rows.append(_unknown_manifest_row(path, position))
            continue
        # Count the bytes BEFORE the decode attempt: a manifest that was read
        # but fails JSON-decode was still read, and the docstring's "none were
        # read" carve-out covers only unreadable files (PR #531 iteration-1).
        _count_input_bytes(stats, len(raw.encode("utf-8")))
        try:
            doc = json.loads(raw)
        except json.JSONDecodeError:
            rows.append(_unknown_manifest_row(path, position))
            continue
        if not isinstance(doc, dict):
            rows.append(_unknown_manifest_row(path, position))
            continue
        rows.append(_local_row_from_manifest(doc, path, position, registry))
    return rows


def _unknown_manifest_row(path: Path, position: int, reason: str = "manifest unreadable or malformed") -> EligibleLifecycle:
    # `reason` is the DURABLE row-level attribution (stderr is ephemeral): a
    # symlink rejection is a security-relevant event that must not read as
    # "unreadable or malformed" in the artifact six months later (PR #531
    # early-shadow, silent-failure finding 4).
    sid = _safe_session_id_from_name(path.stem)
    return EligibleLifecycle(
        source=SOURCE_LOCAL,
        surrogate_id=_surrogate_id(SOURCE_LOCAL, sid or path.name, str(position)),
        consumer=None,
        subject=None,
        identity={"session_id": sid, "project_path": None, "started_at": None},
        eligibility_state=ELIGIBILITY_UNKNOWN,
        eligibility_evidence=reason,
        host_profile=None,
        source_status=SOURCE_UNREADABLE,
        provenance={"manifest_session_id": sid},
    )


def _safe_session_id(sid: object) -> str | None:
    """Single admission predicate for session ids (AC #61). SAFE_ID's char
    class admits `.`/`..` (both fullmatch `[A-Za-z0-9._-]+`), and a
    manifest-supplied `..` session id joined onto bundles_dir escapes the
    admitted root by one level — outside every symlink guard (PR #531
    early-shadow final pass, Important). Reject the two path-navigation names
    here, once, for every caller."""
    if not isinstance(sid, str) or sid in (".", ".."):
        return None
    return sid if SAFE_ID.fullmatch(sid) else None


def _safe_session_id_from_name(stem: str) -> str | None:
    return _safe_session_id(stem)


def _local_row_from_manifest(doc: dict, path: Path, position: int, registry: dict) -> EligibleLifecycle:
    sid = doc.get("session_id") if isinstance(doc.get("session_id"), str) else _safe_session_id_from_name(path.stem)
    sid = _safe_session_id(sid)
    candidate = doc.get("candidate") if isinstance(doc.get("candidate"), dict) else {}
    workflow = candidate.get("workflow") if isinstance(candidate.get("workflow"), str) else None
    subject = candidate.get("subject") if isinstance(candidate.get("subject"), dict) else None
    evidence = str(candidate.get("invocation_evidence") or "")
    started_at = doc.get("submitted_at") if isinstance(doc.get("submitted_at"), str) else None

    # Eligibility (local) keys on invocation_evidence, NOT the manifest's
    # `provisional` flag: the recorder hardcodes provisional=True for every start
    # kind (exact / command-markup / embedded), so keying on it would classify
    # every real lifecycle provisional and make confirmed_eligible unreachable
    # (issue #527 review finding). Exact slash-command and command-markup starts
    # are confirmed here; an embedded candidate (or an unrecognized/missing
    # evidence kind for a registered workflow) stays provisional — the recorder
    # already flags embedded starts as needing native-transcript corroboration,
    # and this analyzer does not promote provisional -> confirmed. Unknown
    # manifest -> eligibility_unknown (in _unknown_manifest_row).
    if not workflow or workflow not in registry:
        state = ELIGIBILITY_INELIGIBLE
        ev_text = evidence or f"workflow {workflow!r} not in registry (non-agent or unregistered)"
    elif evidence in CONFIRMED_EVIDENCE_KINDS:
        state = ELIGIBILITY_CONFIRMED
        ev_text = evidence or "exact slash-command or command-markup start"
    else:
        state = ELIGIBILITY_PROVISIONAL
        ev_text = evidence or "embedded first-message candidate; provisional pending native-transcript corroboration"

    host_profile = _host_profile_from_manifest(doc)
    identity = {
        "session_id": sid,
        "project_path": _hashed_if_present(doc.get("cwd")),
        "started_at": started_at,
    }
    return EligibleLifecycle(
        source=SOURCE_LOCAL,
        surrogate_id=_surrogate_id(SOURCE_LOCAL, sid or "unknown", str(position), started_at or ""),
        consumer=workflow if workflow in registry else None,
        subject=subject,
        identity=identity,
        eligibility_state=state,
        eligibility_evidence=ev_text,
        host_profile=host_profile,
        source_status=SOURCE_ELIGIBLE_NOT_IMPORTED,  # default; left-join updates
        provenance={"manifest_session_id": sid},
    )


def _hashed_if_present(value: Any) -> str | None:
    # cwd encodes the repo path; never persist it raw — hash it for identity.
    if not isinstance(value, str) or not value:
        return None
    return _sha8(value)


def _subdict(doc: dict, key: str) -> dict:
    v = doc.get(key)
    return v if isinstance(v, dict) else {}


def _host_profile_from_manifest(doc: dict) -> dict | None:
    profile: dict[str, Any] = {}
    for key in ("provider", "prflow_version", "claude_code_version"):
        v = doc.get(key)
        # The recorder (capture_prompt_manifest) writes these as {"value","source"}
        # dicts, NOT bare strings — reading them as `str` silently dropped all
        # three on every real manifest, leaving the provider / devflow-version /
        # claude-version stratification dimensions permanently non-comparable
        # (issue #527 review; the same wrong-shape-read class as the eligibility
        # bug). Extract `.value`; a bare string is still accepted for robustness.
        if isinstance(v, dict):
            v = v.get("value")
        if isinstance(v, str) and v:
            profile[key] = v
    me = _subdict(doc, "model_effort")
    if isinstance(me.get("requested_model"), str):
        profile["model"] = me["requested_model"]
    git = _subdict(doc, "git")
    if isinstance(git.get("branch"), str):
        profile["branch"] = git["branch"]
    if isinstance(doc.get("cwd"), str):
        # host OS is not derivable without a subprocess; leave it absent (None)
        # so stratify counts the launch's stratum as incomplete (unknown host ->
        # non-comparable), consistent with how _workspace_state treats unknown.
        pass
    return profile or None


# --------------------------------------------------------------------------- #
# Local native import left-join + source missingness.
# --------------------------------------------------------------------------- #
def join_local_imports(rows: list[EligibleLifecycle], bundles_dir: Path, max_bytes: int, stats: "dict | None" = None) -> list[EligibleLifecycle]:
    """Left-join imported bundles onto local census rows; set source_status."""
    out: list[EligibleLifecycle] = []
    for row in rows:
        if row.source != SOURCE_LOCAL:
            out.append(row)
            continue
        if row.eligibility_state == ELIGIBILITY_UNKNOWN:
            # An unreadable/malformed manifest already carries a terminal
            # source_status (source_unreadable) and has no usable identity to
            # join a bundle for. Preserve its distinct reason code rather than
            # clobbering it to source_missing / eligible_not_imported below —
            # the "distinct reason codes, never silently reclassified" contract
            # (issue #527 review finding).
            out.append(row)
            continue
        sid = row.identity.get("session_id")
        if not sid:
            row.set_source_status(SOURCE_MISSING)
            out.append(row)
            continue
        bundle = bundles_dir / sid
        status = _classify_source_status(bundle, max_bytes, stats)
        row.set_source_status(status)
        out.append(row)
    return out


def _classify_source_status(bundle: Path, max_bytes: int, stats: "dict | None" = None) -> str:
    # SYMLINK CHECKS RUN BEFORE exists() CHECKS, deliberately: exists()
    # follows symlinks, so a DANGLING symlink reads as "absent" and would
    # silently take the not-imported/legacy/no-transcript arms with no
    # breadcrumb — is_symlink() (an lstat) is true for a dangling link too,
    # so ordering it first keeps every planted symlink loud (Step 3.5
    # fix-delta gate). Residual, accepted for the local-only 0600-output
    # threat model: the is_symlink()-then-open sequence is check-then-open —
    # a swap between the two is not excluded (no O_NOFOLLOW open); the
    # extraction-site re-check narrows the window, and the census output
    # never leaves the machine.
    if bundle.is_symlink():
        # AC #61: a symlinked bundle directory redirects every child read
        # out of the admitted root — reject before opening anything under it
        # (PR #531 review-and-fix local iteration).
        print(
            f"devflow verification-baseline: rejecting symlinked bundle dir {bundle.name} "
            "(AC #61: symlinks under admitted roots are never followed)",
            file=sys.stderr,
        )
        return SOURCE_UNREADABLE
    if not bundle.exists() or not bundle.is_dir():
        return SOURCE_ELIGIBLE_NOT_IMPORTED
    metadata = bundle / "metadata.json"
    transcript = bundle / "transcript.jsonl"
    if metadata.is_symlink():
        print(
            f"devflow verification-baseline: rejecting symlinked metadata.json in {bundle.name} "
            "(AC #61: symlinks under admitted roots are never followed)",
            file=sys.stderr,
        )
        return SOURCE_UNREADABLE
    if metadata.exists():
        try:
            meta_text = metadata.read_text(encoding="utf-8")
            _count_input_bytes(stats, len(meta_text.encode("utf-8")))
            meta = json.loads(meta_text)
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            # An unreadable/corrupt metadata.json is a denominator row whose
            # reason is "unreadable" (a permission/corruption fault), distinct
            # from a readable-but-unsupported schema version below.
            return SOURCE_UNREADABLE
        if not isinstance(meta, dict):
            return SOURCE_UNREADABLE
        sv = meta.get("schema_version")
        # Bundle metadata is schema_version 2 (recorder contract). Anything else
        # is unsupported — a denominator row, never a clean classification.
        if sv not in (2,):
            return SOURCE_UNSUPPORTED
    else:
        # Legacy/absent metadata -> treat as unsupported source version.
        return SOURCE_UNSUPPORTED
    if transcript.is_symlink():
        # AC #61: never follow a symlinked transcript (same class as the
        # metadata/bundle-dir rejections above). Ordered BEFORE exists():
        # a dangling transcript symlink would otherwise silently take the
        # no-transcript arm with no breadcrumb.
        print(
            f"devflow verification-baseline: rejecting symlinked transcript.jsonl in {bundle.name} "
            "(AC #61: symlinks under admitted roots are never followed)",
            file=sys.stderr,
        )
        return SOURCE_UNREADABLE
    if not transcript.exists():
        # No transcript: what does the (success-only) stop-attempts log say?
        # unreadable log -> source_unreadable (never a silent "no failure");
        # a log with entries but no captured success -> attempted-but-failed;
        # a log CLAIMING a capture whose artifact is gone -> import_failed
        # (capture-claimed-artifact-gone inconsistency); no log at all ->
        # source_missing (nothing was ever attempted through the stop hook).
        state, _claims = _stop_attempts_state(bundle, stats)
        if state == "unreadable":
            return SOURCE_UNREADABLE
        if state in ("uncaptured", "captured"):
            return SOURCE_IMPORT_FAILED
        return SOURCE_MISSING
    try:
        size = transcript.stat().st_size
    except OSError:
        return SOURCE_UNREADABLE
    if size > max_bytes:
        # Source-level limit breach -> denominator row with a visible reason;
        # never truncates into a clean classification.
        return SOURCE_UNSUPPORTED
    if size == 0:
        # An empty transcript is available-but-event-less ONLY when the
        # stop-attempts log does not contradict it. Short-circuiting to
        # available unconditionally read an import failure as a clean empty
        # session (PR #531 iteration-1, silent-failure finding 3): a log
        # claiming a non-zero-byte capture beside a 0-byte transcript is an
        # import failure, and an unreadable log is unreadable here exactly as
        # on the no-transcript path.
        state, claims = _stop_attempts_state(bundle, stats)
        if state == "unreadable":
            return SOURCE_UNREADABLE
        if state == "uncaptured":
            # Symmetry with the no-transcript path: an attempted-never-captured
            # log beside a 0-byte transcript is an interrupted import, not a
            # clean empty session (PR #531 iteration-1 gate finding 5).
            return SOURCE_IMPORT_FAILED
        if state == "captured" and any(c is None or c > 0 for c in claims):
            # A claim of >0 captured bytes contradicts the empty file; a claim
            # whose byte field is unusable (None) is UNESTABLISHABLE and fails
            # closed the same way — never read as "no contradiction".
            return SOURCE_IMPORT_FAILED
        return SOURCE_AVAILABLE
    # Read once and reuse for the parse check (parse_events validates JSONL).
    try:
        raw = transcript.read_bytes()
    except OSError:
        return SOURCE_UNREADABLE
    _count_input_bytes(stats, len(raw))
    # Final parse check: malformed JSONL -> unreadable, not missing.
    try:
        wfr.parse_events(raw)
    except ValueError:
        return SOURCE_UNREADABLE
    # A usable transcript is the artifact that matters; the log is consulted
    # only for its own readability (an unreadable failure log is still a
    # telemetry defect worth surfacing as unreadable rather than laundering).
    state, _claims = _stop_attempts_state(bundle, stats)
    if state == "unreadable":
        return SOURCE_UNREADABLE
    return SOURCE_AVAILABLE


def _import_failed(bundle: Path, stats: "dict | None" = None) -> "bool | None":
    """Thin tri-state wrapper over ``_stop_attempts_state`` (the production
    classification path in ``_classify_source_status`` calls
    ``_stop_attempts_state`` directly; this wrapper carries the documented
    tri-state contract and is exercised by the test suite).

    Tri-state, aligned to the REAL stop-attempts writer contract
    (workflow_flight_recorder._append_bundle_attempt): the log records
    SUCCESS-ONLY entries — ``{captured_at, transcript_bytes, transcript_sha256,
    event_count, result: "captured", source}`` — appended once per successful
    capture/verified import. It never records failures, so failure detection is
    structural, not key-based (PR #531 iteration-1 VC-5: the previous reader
    branched on ``error``/``bytes_verified``/``ok`` keys no writer ever
    produces, so its failure arm was dead code against real bundles).

    Returns:
      * ``None``  — the log itself is unusable: unreadable/undecodable, or it
        has non-blank lines none of which parse as JSON objects (an
        all-corrupt failure log is never "no failure evidence" — that read
        fails open on exactly the input the log exists to explain).
      * ``True``  — the log exists but records no successful capture
        (attempted-but-never-captured).
      * ``False`` — no log at all (nothing attempted through the stop-hook
        path), or the log records at least one successful capture. Whether a
        claimed capture is contradicted by the on-disk transcript is the
        CALLER's cross-check (via ``_stop_attempts_state`` directly) — this
        function never reports that contradiction.

    The transcript-presence cross-check lives in the caller because only the
    caller knows whether a usable transcript exists; this function answers
    "what does the log alone say about capture success?" via the
    ``captured_byte_claims`` list ``_stop_attempts_state`` returns.
    """
    state, claims = _stop_attempts_state(bundle, stats)
    if state == "unreadable":
        return None
    if state == "none":
        return False
    if state == "uncaptured":
        return True
    # state == "captured": the log says a capture succeeded; consistency with
    # the on-disk transcript is the caller's cross-check, never reported here.
    del claims
    return False


def _stop_attempts_state(bundle: Path, stats: "dict | None" = None) -> "tuple[str, list[int | None]]":
    """Read stop-attempts.jsonl in the writer's real shape.

    Returns (state, captured_byte_claims) where state is one of:
    ``none`` (no log), ``unreadable`` (I/O or decode failure, or non-blank
    lines with zero parseable JSON objects), ``uncaptured`` (log present, no
    ``result == "captured"`` entry), ``captured`` (at least one captured
    entry). ``captured_byte_claims`` holds one entry per captured record: its
    ``transcript_bytes`` when that is a genuine int, else ``None``
    (unestablishable — the caller's consistency check treats ``None`` as a
    contradiction, never as "no claim")."""
    attempts = bundle / "stop-attempts.jsonl"
    # Symlink check BEFORE exists() — the same deliberate ordering as the
    # bundle/metadata/transcript siblings in _classify_source_status: exists()
    # follows symlinks, so a DANGLING stop-attempts symlink would silently
    # read as "none" (-> source_missing) with no breadcrumb (Step 3.5
    # fix-delta re-gate, inner attempt 2).
    if attempts.is_symlink():
        # AC #61: never follow a symlinked stop-attempts log (same class as
        # the other discovered-file rejections).
        print(
            f"devflow verification-baseline: rejecting symlinked stop-attempts.jsonl in {bundle.name} "
            "(AC #61: symlinks under admitted roots are never followed)",
            file=sys.stderr,
        )
        return "unreadable", []
    if not attempts.exists():
        return "none", []
    try:
        text = attempts.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return "unreadable", []
    _count_input_bytes(stats, len(text.encode("utf-8")))
    nonblank = 0
    parsed = 0
    corrupt = 0
    claims: list["int | None"] = []
    captured = False
    for line in text.splitlines():
        if not line.strip():
            continue
        nonblank += 1
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            corrupt += 1
            continue
        if not isinstance(entry, dict):
            corrupt += 1
            continue
        parsed += 1
        if entry.get("result") == "captured":
            captured = True
            tb = entry.get("transcript_bytes")
            # A captured entry whose byte claim is missing or non-int appends
            # None (unestablishable), never nothing: dropping it silently made
            # the caller's consistency check read a corrupted claim as "no
            # contradiction" — the unknown-is-not-zero collapse (PR #531
            # iteration-1 gate finding 5). bool is excluded (bool ⊂ int would
            # admit True as byte-count 1).
            # The writer emits len(raw) >= 0, so a negative int is corrupt
            # exactly like a string/bool claim — unestablishable (None).
            if isinstance(tb, int) and not isinstance(tb, bool) and tb >= 0:
                claims.append(tb)
            else:
                claims.append(None)
    if nonblank and not parsed:
        # Valid UTF-8 but wholly JSON-corrupt: the failure log is unusable.
        return "unreadable", []
    if captured:
        # A corrupt line ALONGSIDE valid captured entries is an unestablishable
        # claim: it could have been a >0-byte capture the reader cannot see, so
        # the byte-consistency check must fail closed rather than proceed on the
        # parseable subset (PR #531 early-shadow: a 0-byte-transcript + one valid
        # {captured, bytes:0} + one corrupt line read as clean SOURCE_AVAILABLE).
        if corrupt:
            claims.append(None)
        return "captured", claims
    return "uncaptured", []


# --------------------------------------------------------------------------- #
# Verification request + process-launch extraction (local-native only).
# --------------------------------------------------------------------------- #
def _strip_env_prefix(command: str) -> str:
    """Strip leading VAR=value assignments — and a leading ``env`` wrapper with
    its own VAR=value arguments — to find the real command head, so
    ``env FOO=bar pytest`` classifies by ``pytest``, not by ``env``
    (issue #527 review: the ``env`` wrapper hid real launches as
    other_command). A bare ``env`` (no wrapped command) keeps ``env`` as its
    head and stays other_command via NON_VERIFICATION_HEADS.

    Known Wave-1 taxonomy gap (documented, not guessed at): other wrapper heads
    that run a payload command from their arguments — ``find … -exec pytest``,
    ``nice``/``nohup``/``timeout`` — are NOT unwrapped, so a verification
    launch behind one of them classifies by the wrapper's own head (``find`` is
    a read-only inspection head, so it reads other_command) or by pattern match
    over the whole segment (``xargs pytest`` matches the pattern set). The same
    gap covers PIPELINES: ``|`` is not a split delimiter, so a piped launch
    (``cat data | pytest``) classifies by the pipe-head (``cat`` →
    other_command). Both can under-count wrapped/piped launches; the
    conservative direction (an under-count of candidates, never a fabricated
    one)."""
    head = command.strip().split(None, 1)[0] if command.strip() else ""
    while head and (
        ("=" in head and not head.startswith("/") and not head.startswith("-"))
        or head == "env"
    ):
        rest = command.strip().split(None, 1)
        if len(rest) < 2:
            return head
        command = rest[1]
        head = command.strip().split(None, 1)[0] if command.strip() else ""
    return head


def _classify_simple_command(segment: str) -> str:
    # Classify ONE simple command by its head: a clearly-non-verification head
    # (git, cat, grep, echo, …) means the segment's action is that command and a
    # test-tool name in its arguments (`cat lib/test/run.sh`, `grep -r pytest .`)
    # is not a launch; otherwise a verification pattern match makes it a launch.
    head = _strip_env_prefix(segment)
    if head in NON_VERIFICATION_HEADS:
        return KIND_OTHER_COMMAND
    if any(pat.search(segment) for pat in VERIFICATION_PATTERNS):
        return KIND_VERIFICATION
    return KIND_VERIFICATION_UNKNOWN


def _split_top_level_segments(command: str) -> list[str]:
    # Split on `&&` / `||` / `;` — AND unquoted newlines — that occur OUTSIDE
    # single/double quotes, so a
    # delimiter inside a quoted argument (`git commit -m "refactor && pytest"`)
    # does not manufacture a spurious verification segment out of the quoted text
    # (issue #527 review finding — the quoted-delimiter false-positive that the
    # naive re.split left open). Not a full shell parser: it tracks quote
    # state plus backslash escapes (inside double quotes and outside quotes),
    # which is sufficient to keep a quoted or escaped delimiter from splitting.
    segments: list[str] = []
    buf: list[str] = []
    quote: str | None = None
    i = 0
    n = len(command)
    while i < n:
        ch = command[i]
        if quote:
            # Inside double quotes a backslash escapes the next character
            # (POSIX), so `\"` is a literal quote and must NOT flip quote
            # state — an odd count of escaped quotes otherwise exposes a
            # quoted `&&` as a top-level delimiter and fabricates a
            # verification segment out of quoted prose (PR #531 iteration-1).
            # Inside single quotes a backslash is literal (POSIX), so no
            # escape handling applies there.
            if quote == '"' and ch == "\\" and i + 1 < n:
                buf.append(ch)
                buf.append(command[i + 1])
                i += 2
                continue
            buf.append(ch)
            if ch == quote:
                quote = None
            i += 1
            continue
        if ch == "\\" and i + 1 < n:
            # Outside quotes a backslash escapes the next character, so an
            # escaped quote (`\"`) does not OPEN quote state either.
            buf.append(ch)
            buf.append(command[i + 1])
            i += 2
            continue
        if ch in ("'", '"'):
            quote = ch
            buf.append(ch)
            i += 1
            continue
        two = command[i : i + 2]
        if two in ("&&", "||") or ch in (";", "\n"):
            # Unquoted `\n` is a top-level delimiter like `;`: multi-line Bash
            # input is the COMMON transcript shape, and without this the
            # second line's launch was silently classified into the first
            # line's head (`cd repo\npytest` read other_command) — a
            # systematic launch undercount, unlike the disclosed wrapper/
            # pipeline gaps (PR #531 early-shadow final pass, Important). A
            # quoted newline still never splits (quote state above).
            segments.append("".join(buf))
            buf = []
            i += 2 if two in ("&&", "||") else 1
            continue
        buf.append(ch)
        i += 1
    segments.append("".join(buf))
    return segments


def _classify_taxonomy(command: str) -> str:
    # Classify each top-level `&&`/`||`/`;` segment (quote-aware) by its own head,
    # then combine. A chained command is a verification launch iff SOME segment is
    # one — so `cd repo && pytest` is verification (the pytest segment), while
    # `cat lib/test/run.sh && echo done` is other_command (both segments are
    # read-only tools whose args merely mention a test tool). Classifying the whole
    # command against the pattern set first (or splitting quote-blind) counted
    # those incidental mentions as launches, inflating the very baseline this tool
    # measures (issue #527 review finding).
    kinds = [_classify_simple_command(seg.strip()) for seg in _split_top_level_segments(command) if seg.strip()]
    if KIND_VERIFICATION in kinds:
        return KIND_VERIFICATION
    if KIND_VERIFICATION_UNKNOWN in kinds:
        return KIND_VERIFICATION_UNKNOWN
    return KIND_OTHER_COMMAND


def _command_head(command: str) -> str:
    # The head is derived from the REDACTED canonical, never the raw one:
    # _strip_env_prefix returns the whole assignment token as the head in two
    # shapes (a bare `TOKEN=v` whole command, and a `--password=v cmd` flag
    # lead), so a raw-canonical head persisted raw secret material into
    # command_head / metrics.command_heads while the same command's
    # redacted_display and digest were carefully redacted — bypassing the whole
    # pipeline (AC #51; PR #531 early-shadow final pass, Critical). Redacted,
    # those shapes yield marker-bearing heads (`TOKEN=<env:TOKEN>`) instead.
    canonical = _canonical_command(command)
    redacted, _affected, _slots = _redact_secrets(canonical)
    head = _strip_env_prefix(redacted)
    # Bound the head (local record only).
    return head[:120]


def _exit_evidence(result: dict | None) -> "dict | None":
    if not result:
        return None
    is_error = bool(result.get("is_error", False))
    content = result.get("content")
    text = ""
    if isinstance(content, str):
        text = content
    elif isinstance(content, list):
        text = "\n".join(p.get("text", "") for p in content if isinstance(p, dict) and isinstance(p.get("text"), str))
    # Exit-code heuristic: search for a trailing nonzero code in common shapes.
    # Observational only — never used to predict authorization.
    exit_code: int | None = None
    # Require a specific shape (`exit code`/`exit status`/`rc`) adjacent to the
    # number — the bare `exit` alternative matched incidental prose like "will exit
    # 5 minutes" and bound the wrong number, polluting the terminal-vs-result-missing
    # split (issue #527 review).
    m = re.search(r"(?:exit code|exit status|\brc\b)\s*[:=]?\s*(-?\d+)", text, re.IGNORECASE)
    if m:
        try:
            exit_code = int(m.group(1))
        except ValueError:
            exit_code = None
    return {"is_error": is_error, "exit_code": exit_code, "terminal_signal_present": bool(text.strip())}


def _classify_authorization_start(result: dict | None, ev: dict | None) -> str:
    """Classify a request's authorization/start state (Wave 1: native Claude
    transcripts). This is a single classifier, not a per-source adapter table —
    per-source versioned adapters are a future hook for when a second source
    format is added; today native transcripts are the only source.

    Takes the already-located ``result`` and its precomputed ``ev`` (exit
    evidence) so the caller's per-lifecycle ``tool_use_id -> result`` index is
    the single scan over ``events``.
    """
    if result is None:
        # No result observed -> the request may have been denied or cancelled
        # pre-start, or the transcript is truncated. Conservative: start_unknown.
        return START_UNKNOWN
    # An explicit permission-denial in the result -> denied_pre_start.
    content = result.get("content")
    text = ""
    if isinstance(content, str):
        text = content
    elif isinstance(content, list):
        text = "\n".join(p.get("text", "") for p in content if isinstance(p, dict) and isinstance(p.get("text"), str))
    # A parsed exit code is proof the process ran to termination — a pre-start
    # denial/cancellation never carries one. Establish this FIRST so that a
    # cancel/interrupt/abort word appearing incidentally in the command's OWN
    # output (a passing suite that prints "1 aborted", "KeyboardInterrupt" in a
    # captured traceback, a test named test_interrupt) cannot reclassify a real
    # launch out of the counts (issue #527 review finding).
    if ev and ev.get("exit_code") is not None:
        return START_CONFIRMED_TERMINAL
    # Scan only a BOUNDED PREFIX for denial/cancel signals: the harness's own
    # rejection/denial message LEADS the result, whereas an incidental
    # "Permission denied" in a deep traceback or a "1 aborted" test summary sits
    # LATER in a real command's own output — the early-shadow finding that a
    # failing pytest with a PermissionError was misclassified denied. Anchoring
    # to the prefix keeps the structured leading signal and ignores incidental
    # deep-output words.
    prefix = text[:400]
    # Pre-start denial and cancellation are ERROR results with no terminal exit
    # code. Gate ALL the denial/cancel signals on is_error (a SUCCESSFUL command's
    # stdout can echo any of these words — including the harness's own rejection
    # phrasing, which appears verbatim in this repo's tests: a transcript of
    # running them would otherwise drop a real launch): only a structured error
    # signal, in the leading prefix, may drop a request from the launch counts. A
    # genuine Claude Code tool rejection is always delivered with is_error set, so
    # gating loses no real rejection while eliminating the successful-echo false
    # positive (PR #531 early-shadow recognized the rejection strings; the
    # iteration-2 fix-delta gate moved them under is_error).
    if result.get("is_error"):
        if re.search(
            r"permission\s+denied|not\s+allowed|was\s+not\s+granted|user rejected"
            r"|tool use was rejected|does(?:n't| not) want to proceed with this tool",
            prefix, re.IGNORECASE,
        ):
            return START_DENIED_PRE
        # A result that indicates cancellation (e.g. "command was cancelled").
        if re.search(r"\bcancel\w*|\binterrupt\w*|\babort\w*", prefix, re.IGNORECASE):
            return START_CANCELLED_PRE
    # Terminal result text but no parsed exit code -> result missing.
    # DISCLOSED Wave-1 recognition bound (PR #531 early-shadow): an is_error
    # result whose phrasing matches NEITHER denial/cancel set above falls
    # through here — with terminal text it reads result_missing and COUNTS as
    # a launch. That is deliberate: an unrecognized error phrasing may be a
    # real launch that errored (counting keeps the baseline conservative
    # toward over-counting launches, never fabricating retries — the
    # candidate gates all sit downstream), and the denial/cancel sets are the
    # harness's own structured leading phrases, extended as new ones are
    # observed rather than guessed at.
    if ev and ev.get("terminal_signal_present"):
        return START_CONFIRMED_RESULT_MISSING
    return START_UNKNOWN


def _only_explicit_process_start(ev: dict | None) -> bool:
    """Only explicit evidence that the execution surface started a process
    creates a launch. A tool_result with terminal content is explicit; absence
    or a pure denial/cancel is not. Takes the precomputed exit evidence."""
    return bool(ev and ev.get("terminal_signal_present"))


def _workspace_state(events: list, start_idx: int, end_idx: int) -> dict:
    """Coverage from explicit source-event results, NOT analyzer-time inspection.

    A complete workspace_state requires explicit coverage of HEAD, index,
    submodules, all tracked files, all untracked files, and each
    ignored/generated/dependency root. Native transcripts almost never carry
    such an enumeration around a verification command, so the conservative
    default is coverage=incomplete -> relationship unclassifiable
    (mutation_state_unbounded). This is the conservative bias the issue demands:
    never claim a stable workspace without explicit evidence. coverage=complete
    additionally requires every required root to be covered by ONE single
    tool_result (a genuine enumeration shape), never keywords accumulated
    across unrelated results (issue #527 review, Important 4).
    """
    # A complete enumeration requires explicit coverage of every root in
    # `required` (head, index, submodule, tracked, untracked, and the
    # ignored/generated/dependency root) — and it must come from a SINGLE
    # tool_result (the shape of one explicit workspace enumeration, e.g. a
    # `git status --ignored` result). The coverage signal is a keyword-presence
    # reading of result text, not a true before/after mutation bound, so
    # cross-result accumulation is deliberately NOT allowed to establish
    # "complete": keywords scattered across unrelated results over the whole
    # lifecycle window could assemble a coverage no single source event ever
    # established — the non-conservative direction that ENABLES a
    # candidate_transport_retry the evidence does not support (issue #527
    # review finding, Important 4). ``covered_roots`` still reports the union
    # across results for visibility. The ignored/generated/dependency root is
    # rarely explicitly observable in Wave 1, so coverage is usually incomplete
    # by construction; adding a root to `required` is the one place to update.
    required = {"head", "index", "submodule", "tracked", "untracked", "ignored_gen_dep"}

    def _covered_in(text: str) -> set[str]:
        covered: set[str] = set()
        lower = text.lower()
        if re.search(r"\bhead\b", lower):
            covered.add("head")
        # Word-boundary matches: a bare substring marks a root covered on
        # incidental text (and "tracked" is literally inside "untracked"), so
        # a false "complete" coverage is exactly what these boundaries guard
        # against (issue #527 review finding; applied uniformly across roots).
        if re.search(r"\bindex\b", lower):
            covered.add("index")
        if re.search(r"\bsubmodules?\b", lower):
            covered.add("submodule")
        if re.search(r"\buntracked\b", lower):
            covered.add("untracked")
        if re.search(r"\btracked\b", lower):
            covered.add("tracked")
        # ignored/generated/dependency root: covered when a result explicitly
        # enumerates ignored files OR a generated/dependency root path.
        if re.search(r"\bignored\b", lower) or any(
            marker in lower for marker in ("node_modules", "target/", "dist/", "build/", "__pycache__", ".venv", "venv/")
        ):
            covered.add("ignored_gen_dep")
        return covered

    union: set[str] = set()
    complete = False
    for event in events[start_idx : end_idx + 1]:
        content = event.raw.get("message", {}).get("content") if isinstance(event.raw.get("message"), dict) else None
        if not isinstance(content, list):
            continue
        for item in content:
            if not isinstance(item, dict) or item.get("type") != "tool_result":
                continue
            text = ""
            c = item.get("content")
            if isinstance(c, str):
                text = c
            elif isinstance(c, list):
                text = "\n".join(p.get("text", "") for p in c if isinstance(p, dict) and isinstance(p.get("text"), str))
            covered = _covered_in(text)
            union |= covered
            if required.issubset(covered):
                complete = True
    coverage = "complete" if complete else "incomplete"
    return {
        "covered_roots": sorted(union),
        "observation_method": "source_event_results",
        "coverage": coverage,
        "mutation_state_unbounded": coverage == "incomplete",
    }


def extract_verification_lifecycles(
    rows: list[EligibleLifecycle], bundles_dir: Path, registry: dict, max_bytes: int,
    stats: "dict | None" = None,
) -> "tuple[list[VerificationRequest], list[VerificationProcessLaunch], list[EligibleLifecycle]]":
    """Extract verification requests + process launches from source_available
    local lifecycles. Returns (requests, launches, updated_rows)."""
    requests: list[VerificationRequest] = []
    launches: list[VerificationProcessLaunch] = []
    for row in rows:
        if row.source != SOURCE_LOCAL or row.source_status != SOURCE_AVAILABLE:
            continue
        sid = row.identity.get("session_id")
        if not sid:
            continue
        bundle = bundles_dir / sid
        transcript = bundle / "transcript.jsonl"
        if bundle.is_symlink() or transcript.is_symlink():
            # AC #61 re-check at the second read (classification already
            # rejected symlinks, but the extraction read is a separate open —
            # a swap between the two must not be followed either).
            print(
                f"devflow verification-baseline: rejecting symlinked transcript path for session {sid} "
                "at extraction (AC #61: symlinks under admitted roots are never followed)",
                file=sys.stderr,
            )
            row.set_source_status(SOURCE_UNREADABLE)
            continue
        try:
            raw = transcript.read_bytes()
        except OSError:
            row.set_source_status(SOURCE_UNREADABLE)
            continue
        _count_input_bytes(stats, len(raw))
        if len(raw) > max_bytes:
            row.set_source_status(SOURCE_UNSUPPORTED)
            continue
        if not raw.strip():
            # Empty transcript: available, but no events to extract.
            continue
        try:
            events = wfr.parse_events(raw)
        except ValueError:
            row.set_source_status(SOURCE_UNREADABLE)
            continue
        if stats is not None:
            stats["extraction_attempted_count"] = stats.get("extraction_attempted_count", 0) + 1
            # AC #64: performance reporting includes event count. Tallied at
            # the extraction parse (each extracted transcript's events counted
            # once); cloud sources carry no native events, so this is the
            # analyzer's whole parsed-event corpus (PR #531 review-and-fix
            # local iteration — the field was unconditionally null before).
            stats["event_count"] = stats.get("event_count", 0) + len(events)
        try:
            occurrences = wfr.detect_occurrences(events, registry)
            # Use the manifest's consumer to scope the root occurrence; fall back
            # to the first top-level occurrence of any registered workflow.
            # Share the producer's own boundary contract (Step 3.5 fix-delta
            # gate): resolve_boundaries is the recorder's boundary logic —
            # explicit completion markers (exact), else the next top-level /
            # same-workflow boundary (approximate) — so lifecycle spans here
            # can never drift from the recorder's. detect_occurrences alone
            # never sets end_event; a hand-rolled next-start bound both
            # re-derived this contract and missed the completion-marker arm.
            # Pure event math: no subprocess, offline guarantee unchanged
            # (behaviorally pinned by test_analyzer_spawns_no_process_end_to_end).
            wfr.resolve_boundaries(events, occurrences)
            root = _select_root_occurrence(occurrences, row.consumer)
            if root is None:
                # A source-available transcript in which no registered root
                # occurrence is detected is a manifest<->transcript<->registry
                # INCONSISTENCY (the census row exists only because a start
                # manifest recorded a registered invocation), the same failure
                # class as the exception arm below: registry first-message-form
                # drift, a detect_occurrences regression, or a de-registered
                # form would zero the NUMERATOR corpus-wide while the report
                # read a clean 0 at exit 0 — "unknown is not zero" broken at
                # the numerator (PR #531 review-and-fix local iteration). Count
                # it, attribute it on the row, and say so; the row itself stays
                # source_available (the transcript is fine — detection is not).
                row.provenance["extraction_error"] = "no_root_occurrence"
                if stats is not None:
                    stats["no_occurrence_count"] = stats.get("no_occurrence_count", 0) + 1
                print(
                    f"devflow verification-baseline: no root occurrence detected in an available "
                    f"transcript (session {sid}) — registry drift or occurrence-detection "
                    "regression?; row counted, launches not extracted",
                    file=sys.stderr,
                )
                continue
            # end_event is None only when resolve_boundaries found no marker,
            # end_event is None in two residual cases resolve_boundaries
            # leaves open: (a) no marker, no later boundary, no later event —
            # the single-lifecycle tail, where the transcript end is the span
            # end; and (b) a later boundary EXISTS but is exactly adjacent
            # (zero-event gap): wfr's next-boundary arm requires
            # `next.start_event - 1 > start_event` (strict), and its
            # terminal-stop arm requires NO next boundary, so neither fires
            # (shadow Phase-2 FAIL b2:VC-4). In case (b) the len-1 fallback
            # would swallow the later lifecycle's whole span, so bound by the
            # same boundary-candidate set resolve_boundaries scans (top-level
            # or same-workflow later starts) — an empty span (end == start)
            # for the adjacent case, matching the producer's semantics.
            end_idx = root.end_event if root.end_event is not None else (len(events) - 1)
            if root.end_event is None:
                later_starts = [o.start_event for o in occurrences
                                if o.start_event > root.start_event
                                and (o.mode == "top-level" or o.workflow == root.workflow)]
                if later_starts:
                    end_idx = min(later_starts) - 1
            row.provenance["lifecycle_id"] = f"{sid}\x1f{root.occurrence_id}"
            reqs, launches_in = _extract_from_lifecycle(events, root, end_idx, sid, row.consumer,
                                                        row.eligibility_state)
        except Exception as exc:
            # Per-transcript exception isolation (issue #527 review, Important
            # 2): a JSON-valid but unexpected event shape that raises KeyError/
            # TypeError/etc. inside occurrence detection or extraction must
            # degrade THIS row to a denominator entry, never abort the whole
            # baseline and lose every healthy bundle. The transcript parsed but
            # this analyzer version cannot process its shape ->
            # source_unsupported (a distinct reason code, never a clean
            # classification), with a LOUD stderr breadcrumb naming the session
            # id + exception type only — no raw transcript text ever reaches
            # errors/logs (the redaction boundary).
            row.set_source_status(SOURCE_UNSUPPORTED)
            # Attribute the cause on the row and count it separately from the
            # other SOURCE_UNSUPPORTED producers (size breach, unknown schema),
            # so an analyzer-side defect that degrades EVERY transcript is
            # visible as extraction_failure_count == attempted rows instead of
            # masquerading as a clean exit-0 baseline over an unsupported
            # corpus (PR #531 iteration-1, silent-failure finding 5).
            row.provenance["extraction_error"] = type(exc).__name__
            if stats is not None:
                stats["extraction_failure_count"] = stats.get("extraction_failure_count", 0) + 1
            print(
                f"devflow verification-baseline: extraction failed for session {sid} "
                f"({type(exc).__name__}); row degraded to {SOURCE_UNSUPPORTED}",
                file=sys.stderr,
            )
            continue
        requests.extend(reqs)
        launches.extend(launches_in)
    return requests, launches, rows


def _select_root_occurrence(occurrences: list, consumer: str | None):
    if consumer:
        for occ in occurrences:
            if occ.workflow == consumer and occ.mode == "top-level":
                return occ
    for occ in occurrences:
        if occ.mode == "top-level":
            return occ
    return occurrences[0] if occurrences else None


def _build_result_indexes(events: list) -> "tuple[dict[str, dict], dict[str, object]]":
    """One O(events) pass: map tool_use_id -> result item and -> the enclosing
    event. Built once per lifecycle so every tool_use lookup is O(1) instead of
    a full re-scan via ``_result_for`` / ``_find_result_event``."""
    result_by_id: dict[str, dict] = {}
    result_event_by_id: dict[str, object] = {}
    for event in events:
        content = event.raw.get("message", {}).get("content") if isinstance(event.raw.get("message"), dict) else None
        if not isinstance(content, list):
            continue
        for item in content:
            if isinstance(item, dict) and item.get("type") == "tool_result" and isinstance(item.get("tool_use_id"), str):
                result_by_id[item["tool_use_id"]] = item
                result_event_by_id[item["tool_use_id"]] = event
    return result_by_id, result_event_by_id


def _extract_from_lifecycle(events, root, end_idx, sid, consumer, eligibility_state):
    requests: list[VerificationRequest] = []
    launches: list[VerificationProcessLaunch] = []
    # Per-lifecycle indexes + workspace_state: computed once, reused for every
    # tool_use in this lifecycle (start_event/end_idx are lifecycle-scoped, so
    # _workspace_state's result is identical across launches in the same one).
    result_by_id, result_event_by_id = _build_result_indexes(events)
    ws = _workspace_state(events, root.start_event, end_idx)
    # Globally-unique lifecycle identity. root.occurrence_id is only a
    # per-transcript counter — workflow_flight_recorder's detect_occurrences resets
    # it every call, so the root occurrence of EVERY session is the identical string
    # (e.g. "implement-1"). group_launches buckets launches across ALL sessions by
    # binding digest alone, so a bare occurrence_id collapses two independent
    # sessions' runs of the same command into one "lifecycle" — defeating the
    # REL_INDEPENDENT_LIFECYCLE guard and fabricating transport-retry candidates out
    # of ordinary independent reruns (issue #527 review finding). Compose the session
    # id in so lifecycle_id is a valid GLOBAL join key.
    lifecycle_id = f"{sid}\x1f{root.occurrence_id}"
    for event in events[root.start_event : end_idx + 1]:
        if (event.role or event.raw.get("type")) != "assistant":
            continue
        for tool_use in event.tool_uses:
            if tool_use.get("name") != "Bash":
                continue
            inputs = tool_use.get("input") if isinstance(tool_use.get("input"), dict) else {}
            command = inputs.get("command") if isinstance(inputs.get("command"), str) else ""
            if not command:
                continue
            tool_use_id = str(tool_use.get("id") or "")
            req_id = _surrogate_id("req", sid, str(event.index), tool_use_id)
            binding = _binding_identity(command)
            result = result_by_id.get(tool_use_id)
            ev = _exit_evidence(result)
            head = _command_head(command)
            auth = _classify_authorization_start(result, ev)
            req_timing = {
                "requested_at": _ms_to_iso(event.timestamp_ms),
                "started_at": None,
                "finished_at": None,
                "duration_ms": None,
            }
            req = VerificationRequest(
                request_id=req_id,
                source_event_id=_source_event_id(sid, event.index),
                lifecycle_id=lifecycle_id,
                tool_use_id=tool_use_id,
                consumer_skill=consumer,
                phase_checkpoint=None,  # Wave 1: not explicitly extracted
                command_head=head,
                binding=binding,
                request_kind=_classify_taxonomy(command),
                authorization_start=auth,
                timing=req_timing,
                result_presence=result is not None,
                exit_evidence=ev,
                skipped_check_evidence=None,
                provenance={"session_id": sid, "event_index": event.index},
            )
            requests.append(req)
            # Only explicit process-start evidence creates a launch, and only for
            # confirmed verification commands; other_command/verification_unknown
            # are request metrics only (excluded from actual-launch counts).
            if req.request_kind == KIND_VERIFICATION and _only_explicit_process_start(ev) and auth in (START_CONFIRMED_TERMINAL, START_CONFIRMED_RESULT_MISSING):
                launch_id = _surrogate_id("launch", sid, str(event.index), tool_use_id)
                result_event = result_event_by_id.get(tool_use_id)
                launch_timing = _launch_timing(event, result_event)
                launches.append(VerificationProcessLaunch(
                    launch_id=launch_id,
                    request_id=req_id,
                    source_event_id=_source_event_id(sid, event.index),
                    lifecycle_id=lifecycle_id,
                    tool_use_id=tool_use_id,
                    consumer_skill=consumer,
                    phase_checkpoint=None,
                    command_head=head,
                    binding=binding,
                    start_authorization=auth,
                    timing=launch_timing,
                    # Per-launch copy: ws is computed once per lifecycle, and the
                    # frozen dataclass is shallow-frozen — sharing one dict object
                    # across every launch would let a future in-place mutation of
                    # one launch's workspace_state alias into all of them, directly
                    # under the coverage gate _classify_relationship keys on
                    # (PR #531 iteration-1, type-design note). The nested
                    # covered_roots LIST is copied too (a bare dict(ws) is shallow
                    # and would still alias that list — PR #531 early-shadow).
                    workspace_state={**ws, "covered_roots": list(ws.get("covered_roots", []))},
                    result_presence=result is not None,
                    exit_evidence=ev,
                    skipped_check_evidence=None,
                    provenance={"session_id": sid, "event_index": event.index},
                    # The OWNING row's eligibility state. Extraction admits any
                    # source_available local row with no eligibility check, so an
                    # ineligible-but-importable row's launches land in the
                    # numerator while its own row sits in the confirmed_ineligible
                    # bucket — a launch counted with nothing behind it in the
                    # eligible denominator (PR #531 review-and-fix iter-1,
                    # Phase-2 VC-2 FAIL). Wave 1 does not change WHICH launches
                    # are counted (a numerator-policy decision for the issue
                    # owner, not this fix loop); it makes the composition
                    # VISIBLE — metrics tally launches by this state, so an
                    # incoherent ratio is readable rather than silent. "Never
                    # silently omitted" cuts both ways: the row is not dropped,
                    # and neither is the discrepancy.
                    owning_lifecycle_eligibility_state=eligibility_state,
                ))
    return requests, launches


def _launch_timing(tool_use_event, result_event) -> dict:
    """started_at from the tool_use event; finished_at/duration from the result
    event's timestamp — explicit source-event timing only, not analyzer-time
    inspection. Unknown stays None, never 0."""
    started = _ms_to_iso(tool_use_event.timestamp_ms)
    finished = _ms_to_iso(result_event.timestamp_ms) if result_event is not None else None
    duration_ms = None
    if tool_use_event.timestamp_ms is not None and result_event is not None and result_event.timestamp_ms is not None:
        duration_ms = result_event.timestamp_ms - tool_use_event.timestamp_ms
        if duration_ms < 0:
            duration_ms = None
    return {
        "started_at": started,
        "finished_at": finished,
        "duration_ms": duration_ms,
        "caller_observed_duration_ms": duration_ms,
    }


# --------------------------------------------------------------------------- #
# Join confidence — only explicit lifecycle+source-event IDs produce exact.
# --------------------------------------------------------------------------- #
def join_confidence(launch_a: VerificationProcessLaunch, launch_b: VerificationProcessLaunch) -> str:
    """Pairwise reference implementation of the issue-#527 join-confidence
    contract (exact/partial/ambiguous/unmatched; only explicit lifecycle +
    source-event identity produces exact — guessed joins are forbidden).

    NOT called by the Wave-1 group classifier: ``_classify_relationship``
    derives its GROUP-level confidence per relationship arm (a group is n
    members, not a pair), applying the same secret-affected and
    explicit-identity rules. This function is the pairwise contract surface the
    test suite pins the AC against, kept as the reference for a future adapter
    that joins across sources pairwise (PR #531 review, test-quality note:
    documented as deliberate, not dead-by-accident)."""
    # Only explicit lifecycle + source-event identity produces exact; guessed
    # joins are forbidden.
    # The exact arm requires the same source event AND the same tool_use: one
    # assistant event can carry multiple Bash tool_uses, and _source_event_id
    # is event-scoped, so a bare source_event_id match would join two DIFFERENT
    # commands from one message as exact — bypassing the secret-affected
    # carve-out below (PR #531 review-and-fix local iteration; unreachable in
    # Wave 1's per-tool_use extraction, but this is the pinned reference
    # implementation for future cross-source adapters).
    if (launch_a.source_event_id and launch_b.source_event_id
            and launch_a.source_event_id == launch_b.source_event_id
            and launch_a.tool_use_id == launch_b.tool_use_id):
        return CONFIDENCE_EXACT
    if launch_a.lifecycle_id and launch_b.lifecycle_id and launch_a.lifecycle_id == launch_b.lifecycle_id:
        if launch_a.binding.digest == launch_b.binding.digest:
            # Secret-affected: a redacted digest alone cannot establish an exact
            # match; requires the same explicit source correlation (distinct
            # source events here) -> partial, excluded from retry-candidate counts.
            if launch_a.binding.secret_affected or launch_b.binding.secret_affected:
                return CONFIDENCE_PARTIAL
            return CONFIDENCE_EXACT
        return CONFIDENCE_AMBIGUOUS
    if launch_a.binding.digest == launch_b.binding.digest:
        # Same binding but distinct lifecycle -> partial (never exact without
        # explicit lifecycle+source identity; guessed joins are forbidden).
        return CONFIDENCE_PARTIAL
    return CONFIDENCE_UNMATCHED


# --------------------------------------------------------------------------- #
# Relationship grouping + classification (conservative: never auto-prove dupes).
# --------------------------------------------------------------------------- #
def group_launches(launches: list[VerificationProcessLaunch]) -> list[RelationshipGroup]:
    """Repeated-binding groups: launches sharing a binding digest."""
    buckets: dict[str, list[VerificationProcessLaunch]] = {}
    order: list[str] = []
    for launch in launches:
        key = launch.binding.digest
        if key not in buckets:
            buckets[key] = []
            order.append(key)
        buckets[key].append(launch)
    groups: list[RelationshipGroup] = []
    for key in order:
        members = buckets[key]
        relationship, confidence = _classify_relationship(members)
        durations = [m.timing.get("duration_ms") for m in members if isinstance(m.timing.get("duration_ms"), int)]
        group_duration = max(durations) if durations else None
        ws = _merge_workspace_state(members)
        groups.append(RelationshipGroup(
            group_id=_surrogate_id("grp", key, members[0].lifecycle_id or "multi"),
            members=tuple(m.launch_id for m in members),
            relationship=relationship,
            join_confidence=confidence,
            workspace_state=ws,
            binding_digest=key,
            consumer=members[0].consumer_skill,
            duration_ms=group_duration,
            provenance={"binding_digest": key, "member_count": len(members)},
        ))
    return groups


def _classify_relationship(members: list[VerificationProcessLaunch]) -> "tuple[str, str]":
    if len(members) == 1:
        return REL_SINGLE, CONFIDENCE_EXACT
    # A redacted digest alone cannot establish an exact binding match: secret-
    # affected groups are excluded from retry-candidate counts (partial confidence).
    if any(m.binding.secret_affected for m in members):
        return REL_UNCLASSIFIABLE, CONFIDENCE_PARTIAL
    # Explicit retrigger evidence (distinct lifecycle IDs, explicit iterations,
    # explicit checkpoints, post-fix commits, base merges, human retriggers)
    # cannot be transport-retry candidates. Wave 1 detects none explicitly, so
    # this branch is conservative: it stays inert unless a future adapter marks
    # retrigger evidence on a member.
    if any(_has_explicit_retrigger(m) for m in members):
        return REL_INTENTIONAL_RERUN, CONFIDENCE_PARTIAL
    lifecycles = {m.lifecycle_id for m in members if m.lifecycle_id}
    if len(lifecycles) > 1:
        # Distinct lifecycle IDs -> independent (cannot be transport-retry).
        return REL_INDEPENDENT_LIFECYCLE, CONFIDENCE_PARTIAL
    # A transport-retry candidate requires the SAME EXPLICIT lifecycle. If any
    # member carries no lifecycle_id, there is no explicit shared lifecycle to
    # key on, so the group cannot be a candidate — it is unclassifiable, never a
    # candidate by the empty-set falling through the len>1 check above (PR #531
    # early-shadow: Wave-1 extraction always sets a lifecycle_id, but a direct
    # construction / future adapter could produce None-lifecycle members).
    if len(lifecycles) != 1 or any(not m.lifecycle_id for m in members):
        return REL_UNCLASSIFIABLE, CONFIDENCE_AMBIGUOUS
    # DISTINCT CONSUMER ROLES cannot be a transport-retry candidate (issue #527
    # AC, which enumerates nine such dimensions). Eight were foreclosed —
    # lifecycle above, command binding structurally (group_launches keys groups
    # BY binding digest), iterations/checkpoints/post-fix commits/base merges/
    # human retriggers via retrigger_evidence, cloud run attempts not applicable
    # in Wave 1 — but consumer roles were foreclosed by NOTHING:
    # _classify_relationship never read consumer_skill, so two different
    # consumers each running the same command in one lifecycle (implement's
    # Phase 3 and review both running the suite) classified as a transport
    # retry, inflating candidate_retries with intentional work (PR #531
    # review-and-fix iter-1, Phase-2 VC-4 FAIL).
    #
    # Placed AFTER the lifecycle branches so REL_INDEPENDENT_LIFECYCLE keeps
    # precedence (existing behavior unchanged); this fires only for the
    # same-single-lifecycle groups that are the actual gap. Two DIFFERENT
    # consumers each deciding to run the command is evidence the rerun was
    # intentional — the same reading, and the same class, the retrigger branch
    # above already applies to explicit iterations/checkpoints. `None` is an
    # UNRECORDED role, not a distinct one (Wave-1 rows may carry no consumer),
    # so it never forecloses: only 2+ distinct NON-None roles do — an absent
    # operand must not silently decide this.
    consumer_roles = {m.consumer_skill for m in members if m.consumer_skill}
    if len(consumer_roles) > 1:
        return REL_INTENTIONAL_RERUN, CONFIDENCE_PARTIAL
    # Same lifecycle, repeated binding -> candidate transport-retry only if ALL
    # requirements hold; else unclassifiable. The single ``ws_matching`` check
    # (every member has complete coverage AND all share the same covered-roots
    # set) guards the mutation_state_unbounded case: an incomplete or
    # non-matching workspace makes the relationship unclassifiable. The retrigger
    # guard already fired above, so no-retrigger is guaranteed here; and
    # ws_matching is guaranteed True past the next return, so neither is restated
    # in the final candidate guard below.
    # WAVE-1 SCOPE OF "MATCHING" (disclosed, not guessed at — PR #531
    # early-shadow final pass): workspace_state is computed ONCE per lifecycle
    # and copied onto every launch, so this check compares N copies of one
    # per-lifecycle value — it establishes that the LIFECYCLE's workspace was
    # completely enumerated, NOT a per-launch pre/post state comparison
    # (launch-adjacent windows are Wave-2 work; Wave 1 has no per-launch
    # enumeration evidence to compare). The gate is therefore coverage-of-
    # enumeration, and the candidate class remains a MANUAL-REVIEW candidate,
    # never an auto-proved duplicate.
    ws_complete = all(m.workspace_state.get("coverage") == "complete" for m in members)
    ws_roots = {tuple(m.workspace_state.get("covered_roots", [])) for m in members}
    ws_matching = ws_complete and len(ws_roots) == 1
    if not ws_matching:
        return REL_UNCLASSIFIABLE, CONFIDENCE_AMBIGUOUS
    # A candidate needs affirmative prior missing-result evidence. A future
    # adapter may admit denied, cancelled, or unknown starts into launches, but
    # those states do not prove a missing response and must fail closed.
    # "PRIOR missing response" is an ordering requirement, not a
    # set-membership one (PR #531 iteration-1): the missing response must
    # precede a relaunch, so the evidence must sit on a member that is NOT the
    # temporally last launch. A group whose ONLY missing response is the final
    # launch (run 1 completed cleanly, run 2's result was lost) shows no
    # missing-response-then-relaunch shape and is not a transport-retry
    # candidate. Members arrive in event order (extraction appends in
    # transcript order); when every member carries a started_at the explicit
    # timestamps decide the order, otherwise event order is the documented
    # fallback.
    # Temporal order must be decided by PARSED timestamps, never a string sort:
    # lexicographically "…:00.500Z" < "…:00Z" (0x2E < 0x5A) although it is
    # 500ms LATER, and "+00:00" vs "Z" spellings misorder the same way — a
    # string sort can put a temporally-last missing response first and
    # FABRICATE a candidate (PR #531 iteration-1 gate finding 3). Reuse the
    # module's own ISO parser (the consumer's operation); if ANY member's
    # started_at fails to parse, fall back to event/list order rather than
    # sorting on a half-parsed key set.
    ordered = members
    keys = [_parse_iso_ms(m.timing.get("started_at")) for m in members]
    if all(k is not None for k in keys):
        order = sorted(range(len(members)), key=lambda i: (keys[i], i))
        ordered = [members[i] for i in order]
    has_prior_missing = any(m.is_prior_missing_evidence for m in ordered[:-1])
    # "Explicitly bounded interval" = both endpoints (started_at AND
    # finished_at) are present on at least two members, so the gap between the
    # missing-result launch and its successor is computable from explicit
    # source events. Wave 1 deliberately imposes NO magnitude threshold on
    # that gap (a max-gap constant would be an analyst-invented cutoff the
    # issue never authorized); the candidate is conservative-by-evidence, and
    # the manual-review sample is where magnitude judgment happens.
    bounded = [m for m in members if m.timing.get("started_at") and m.timing.get("finished_at")]
    # The bounded-interval requirement is tied to the MISSING-RESPONSE PAIR,
    # not any two bounded members: the retry interval that needs establishing
    # is the one between the launch whose response went missing and its
    # temporal successor — two other members being bounded says nothing about
    # it (PR #531 early-shadow final pass). `ordered[:-1]` indexing mirrors
    # the has_prior_missing scan above.
    interval_bounded = False
    if len(bounded) >= 2:
        for idx, m in enumerate(ordered[:-1]):
            if m.is_prior_missing_evidence:
                nxt = ordered[idx + 1]
                if (m.timing.get("started_at") and m.timing.get("finished_at")
                        and nxt.timing.get("started_at") and nxt.timing.get("finished_at")):
                    interval_bounded = True
                    break
    if has_prior_missing and interval_bounded:
        return REL_CANDIDATE_TRANSPORT_RETRY, CONFIDENCE_EXACT
    return REL_UNCLASSIFIABLE, CONFIDENCE_AMBIGUOUS


def _has_explicit_retrigger(launch: VerificationProcessLaunch) -> bool:
    # Wave 1 extraction never sets this True from native events (no explicit
    # iteration/checkpoint/post-fix/base-merge/human-retrigger markers are
    # extracted), so retrigger evidence is never fabricated. The field carries
    # the no-retrigger guard the candidate classification requires, and is the
    # hook a future versioned adapter records retrigger evidence into.
    return bool(launch.retrigger_evidence)


def _merge_workspace_state(members: list[VerificationProcessLaunch]) -> dict:
    covered: set[str] = set()
    for m in members:
        covered.update(m.workspace_state.get("covered_roots", []))
    coverages = {m.workspace_state.get("coverage") for m in members}
    coverage = "complete" if coverages == {"complete"} else "incomplete"
    return {
        "covered_roots": sorted(covered),
        "observation_method": "source_event_results",
        "coverage": coverage,
        "mutation_state_unbounded": coverage == "incomplete",
    }


# --------------------------------------------------------------------------- #
# Metrics (unknown stays unknown — null/unavailable, never 0).
# --------------------------------------------------------------------------- #
def compute_metrics(
    rows: list[EligibleLifecycle],
    requests: list[VerificationRequest],
    launches: list[VerificationProcessLaunch],
    groups: list[RelationshipGroup],
    has_cloud_snapshot: bool,
    cloud_unavailable: bool = False,
    cloud_attempted: bool = False,
) -> dict[str, Any]:
    def count_by(values):
        tally: dict[str, int] = {}
        for v in values:
            tally[str(v)] = tally.get(str(v), 0) + 1
        return tally

    def count_into(values, keys):
        tally = {k: 0 for k in keys}
        for v in values:
            tally[v] = tally.get(v, 0) + 1
        return tally

    eligibility_bounds = count_into((r.eligibility_state for r in rows), ELIGIBILITY_STATES)

    source_missingness = {s: 0 for s in LOCAL_SOURCE_STATUSES}
    source_missingness[SOURCE_UNAVAILABLE] = 0
    for row in rows:
        if row.source == SOURCE_LOCAL:
            source_missingness[row.source_status] = source_missingness.get(row.source_status, 0) + 1
        elif row.source_status != CLOUD_SOURCE_AVAILABLE:
            source_missingness[SOURCE_UNAVAILABLE] += 1
    # Cloud coverage unavailability is a run-level signal (cloud_coverage), not a
    # per-row status, so drive the ``unavailable`` counter from it rather than
    # leaving it structurally 0 (cloud rows always carry source_status=available,
    # or there are no cloud rows — snapshot absent, incomplete, or all-malformed).
    # Keyed on cloud_attempted, NOT has_cloud_snapshot: a corrupt/wrong-schema
    # --cloud-census parses to no snapshot at all (has_cloud_snapshot=False), and
    # keying on it left this counter at 0 exactly while the report printed
    # "cloud coverage: unavailable" (issue #527 review, suggestion 2). A run
    # that never passed --cloud-census records 0 here — no cloud measurement was
    # attempted, so there is no unavailable measurement to count.
    if cloud_attempted and cloud_unavailable:
        source_missingness[SOURCE_UNAVAILABLE] = source_missingness.get(SOURCE_UNAVAILABLE, 0) + 1

    actual_launches = [
        launch for launch in launches
        if launch.start_authorization in (START_CONFIRMED_TERMINAL, START_CONFIRMED_RESULT_MISSING)
    ]
    # terminal_results is expected to sit near zero on real transcript corpora:
    # it requires a PARSED exit code, and _exit_evidence's heuristic only
    # matches results that spell one out ("exit code 0", "rc: 2") — most real
    # tool_results do not. That is measurement honesty, not a defect: unknown
    # terminal evidence stays out of the count rather than being guessed
    # (issue #527 review, forward-looking disclosure).
    terminal_results = sum(1 for launch in actual_launches if launch.exit_evidence and launch.exit_evidence.get("exit_code") is not None)
    missing_results = sum(1 for launch in launches if launch.start_authorization == START_CONFIRMED_RESULT_MISSING)

    rel_dist = count_into((g.relationship for g in groups), RELATIONSHIP_CLASSES)
    ws_dist = count_into((g.workspace_state.get("coverage", "incomplete") for g in groups), ("complete", "incomplete"))
    join_dist = count_into((g.join_confidence for g in groups), CONFIDENCE_CLASSES)

    command_heads = count_by(launch.command_head for launch in launches)
    consumers = count_by((launch.consumer_skill or "unknown") for launch in launches)

    candidate_group_durations = [g.duration_ms for g in groups if g.relationship == REL_CANDIDATE_TRANSPORT_RETRY and isinstance(g.duration_ms, int)]
    estimated_wall = sum(candidate_group_durations) if candidate_group_durations else None

    # `eligible_lifecycles` counted len(rows) — EVERY census row, including the
    # ones the analyzer had just certified confirmed_ineligible (the producer
    # emits one row per job: precheck, dedupe, telemetry, relay included), so a
    # measurement tool whose entire purpose is not over-claiming published an
    # inflated headline denominator under a name asserting the opposite, and the
    # parameter's own `list[EligibleLifecycle]` type encoded the invariant the
    # data violated. `census_rows` now carries the total (nothing is hidden —
    # the full per-state split remains in eligibility_state_bounds) and
    # `eligible_lifecycles` means what it says: confirmed + provisional.
    # (PR #531 review-and-fix iter-1, code-reviewer Important.)
    eligible_denominator = eligibility_bounds[ELIGIBILITY_CONFIRMED] + eligibility_bounds[ELIGIBILITY_PROVISIONAL]
    # Numerator composition by the OWNING row's eligibility (Phase-2 VC-2 FAIL):
    # extraction admits any source_available local row regardless of eligibility,
    # so a launch can sit in the numerator with nothing behind it in the
    # denominator above. Wave 1 keeps the numerator as-is and makes the
    # discrepancy readable instead of silent; a non-zero non-eligible tally is
    # the signal that the ratio is not a clean fraction.
    launches_by_eligibility = count_into(
        (launch.owning_lifecycle_eligibility_state for launch in actual_launches),
        ELIGIBILITY_STATES,
    )
    return {
        "census_rows": len(rows),
        "eligible_lifecycles": eligible_denominator,
        "local_actual_launches_by_lifecycle_eligibility": launches_by_eligibility,
        "eligibility_state_bounds": eligibility_bounds,
        "source_availability_and_missingness": source_missingness,
        "local_actual_launches": len(actual_launches),
        "terminal_results": terminal_results,
        "missing_results": missing_results,
        "repeated_binding_groups": sum(1 for g in groups if len(g.members) > 1),
        "candidate_retries": rel_dist[REL_CANDIDATE_TRANSPORT_RETRY],
        "intentional_rerun_evidence": rel_dist[REL_INTENTIONAL_RERUN],
        "independent_lifecycles": rel_dist[REL_INDEPENDENT_LIFECYCLE],
        "unclassifiable_groups": rel_dist[REL_UNCLASSIFIABLE],
        "single_groups": rel_dist[REL_SINGLE],
        "workspace_coverage_distribution": ws_dist,
        "join_confidence_distribution": join_dist,
        "command_heads": command_heads,
        "consumers_checkpoints": consumers,
        "provenance": {
            "local_manifests": sum(1 for r in rows if r.source == SOURCE_LOCAL),
            "local_bundles_available": sum(1 for r in rows if r.source == SOURCE_LOCAL and r.source_status == SOURCE_AVAILABLE),
            "cloud_snapshot": has_cloud_snapshot,
        },
        "host_profile": _aggregate_host_profile(rows),
        "child_duration_ms": None,  # unknown in Wave 1 (no child-process timing in native events)
        "caller_observed_duration_ms": [launch.timing.get("duration_ms") for launch in launches if isinstance(launch.timing.get("duration_ms"), int)] or None,
        "estimated_repeated_suite_wall_time_ms": estimated_wall,
        "verification_requests": len(requests),
        "verification_process_launches": len(launches),
        # Unknown-is-not-zero: a count that could not be established is null, never 0.
        "notes": "unknown values are null/unavailable, never zero; candidate_retries is a conservative candidate count, not confirmed duplicates",
    }


def _aggregate_host_profile(rows: list[EligibleLifecycle]) -> dict[str, Any]:
    agg: dict[str, set[str]] = {}
    for row in rows:
        if not row.host_profile:
            continue
        for key, value in row.host_profile.items():
            if isinstance(value, str) and value:
                agg.setdefault(key, set()).add(value)
    return {k: sorted(v) for k, v in agg.items()} or {"note": "no host_profile observed"}


# --------------------------------------------------------------------------- #
# Manual-review sampling (deterministic: SHA-256(snapshot_hash || group_id)).
# --------------------------------------------------------------------------- #
def manual_review_sample(groups: list[RelationshipGroup], snapshot_hash: str) -> dict[str, Any]:
    # Sampling unit = relationship groups with >1 member (repeated-binding groups
    # — the only ones that could be retries). Single-launch groups cannot be retries.
    population = [g for g in groups if len(g.members) > 1]
    if not population:
        return {
            "seed": snapshot_hash,
            "eligible_population": [],
            "high_cost_ids": [],
            "remainder_selected_ids": [],
            "selected_ids": [],
            "nonresponses": {},
            "adjudication_totals": {v: 0 for v in ADJUDICATION_VERDICTS},
        }
    n = len(population)
    durations = sorted((g.duration_ms for g in population if isinstance(g.duration_ms, int)), reverse=True)
    decile_count = max(1, math.ceil(0.1 * n))
    if durations:
        threshold = durations[min(decile_count, len(durations)) - 1]
    else:
        threshold = None
    if threshold is not None:
        high_cost = [g for g in population if isinstance(g.duration_ms, int) and g.duration_ms >= threshold]
    else:
        high_cost = []
    high_cost_ids = {g.group_id for g in high_cost}
    remainder = [g for g in population if g.group_id not in high_cost_ids]
    sample_size = min(50, max(20, math.ceil(0.1 * len(remainder)))) if remainder else 0
    sample_size = min(sample_size, len(remainder))

    def sort_key(g: RelationshipGroup) -> str:
        return hashlib.sha256((snapshot_hash + g.group_id).encode("utf-8")).hexdigest()

    remainder_sorted = sorted(remainder, key=sort_key)
    remainder_selected = remainder_sorted[:sample_size]
    return {
        "seed": snapshot_hash,
        "eligible_population": [g.group_id for g in population],
        "high_cost_ids": [g.group_id for g in high_cost],
        "remainder_selected_ids": [g.group_id for g in remainder_selected],
        "selected_ids": [g.group_id for g in high_cost] + [g.group_id for g in remainder_selected],
        "nonresponses": {},
        "adjudication_totals": {v: 0 for v in ADJUDICATION_VERDICTS},
    }


# --------------------------------------------------------------------------- #
# Stratification (incomplete strata marked non-comparable).
# --------------------------------------------------------------------------- #
def stratify(launches: list[VerificationProcessLaunch], rows: list[EligibleLifecycle]) -> dict[str, Any]:
    host_by_sid: dict[str | None, dict[str, Any]] = {}
    for row in rows:
        if row.source == SOURCE_LOCAL and row.identity.get("session_id"):
            host_by_sid[row.identity["session_id"]] = row.host_profile or {}

    def dims_for(launch: VerificationProcessLaunch) -> dict[str, str | None]:
        hp = host_by_sid.get(launch.provenance.get("session_id"), {})
        return {
            "consumer_checkpoint": launch.consumer_skill,
            "command_binding": launch.binding.digest,
            # host_os: _host_profile_from_manifest deliberately never writes
            # this key in Wave 1 (host OS is not derivable from a manifest
            # without a subprocess), so this dimension is ALWAYS None and every
            # stratum counts as incomplete/non-comparable — the intended
            # unknown-host handling, pinned by
            # test_stratify_host_profile_dimension_is_always_incomplete
            # (issue #527 review, Important 6).
            "host_profile": hp.get("host_os"),
            "repository_size_bucket": None,  # unknown without a subprocess
            "duration_bucket": _duration_bucket(launch.timing.get("duration_ms")),
            "model": hp.get("model"),
            "effort": None,  # not extracted in Wave 1
            "output_style": None,  # not extracted in Wave 1
            "prompt_fingerprint": None,  # not extracted in Wave 1
            "prflow_version": hp.get("prflow_version"),
            "claude_action_version": hp.get("claude_code_version"),
            "provider": hp.get("provider"),
        }

    strata: dict[str, list[str]] = {}
    incomplete = 0
    for launch in launches:
        dims = dims_for(launch)
        if any(v is None for v in dims.values()):
            incomplete += 1
        key = json.dumps(dims, sort_keys=True, separators=(",", ":"))
        strata.setdefault(key, []).append(launch.launch_id)
    return {
        "strata_count": len(strata),
        "strata": {k: len(v) for k, v in strata.items()},
        "incomplete_strata_launches": incomplete,
        "non_comparable_note": "incomplete strata (any null dimension) are non-comparable; captured-only rows are never the eligible-lifecycle denominator",
    }


def _duration_bucket(ms: Any) -> "str | None":
    if not isinstance(ms, int):
        return None
    if ms < 10_000:
        return "<10s"
    if ms < 60_000:
        return "10s-1m"
    if ms < 300_000:
        return "1m-5m"
    if ms < 600_000:
        return "5m-10m"
    return ">10m"


# --------------------------------------------------------------------------- #
# Cloud census reader (snapshot is metadata-only; no launch/duration claims).
# --------------------------------------------------------------------------- #
CLOUD_SNAPSHOT_SCHEMA = 1


def read_cloud_census(snapshot_path: Path, stats: "dict | None" = None) -> "tuple[dict[str, Any] | None, str]":
    """Read an explicit Actions run/job census snapshot.

    Returns ``(doc, reason)``: ``doc`` is the parsed snapshot or ``None`` when it
    could not be read; ``reason`` names whether it was absent, unreadable/
    corrupt, or wrong-schema so a caller can surface a distinct breadcrumb rather
    than conflating "no flag" with "corrupt file" with "schema mismatch" (all
    three otherwise read as bare ``None``). Cloud coverage reads ``unavailable``
    (never zero) on any non-``ok`` reason.
    """
    if snapshot_path is None:
        return None, "absent"
    try:
        text = snapshot_path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        # UnicodeDecodeError: a non-UTF-8 snapshot is an unreadable census
        # (coverage unavailable), never an analyzer abort (#527 review). A
        # failed read contributes NO input bytes — this is what keeps
        # _count_input_bytes' "none were read" universal true for the cloud
        # snapshot too (PR #531 review-and-fix local iteration: main()
        # previously stat()-counted the size whether or not the read
        # succeeded, the one arm contradicting the docstring's universal).
        return None, f"unreadable/corrupt ({type(exc).__name__})"
    # Successfully-read content is counted here (actual bytes read, not a stat
    # size), matching every sibling reader's convention.
    _count_input_bytes(stats, len(text.encode("utf-8")))
    try:
        doc = json.loads(text)
    except json.JSONDecodeError as exc:
        return None, f"unreadable/corrupt ({type(exc).__name__})"
    if not isinstance(doc, dict):
        return None, "not a JSON object"
    if doc.get("schema_version") != CLOUD_SNAPSHOT_SCHEMA:
        return None, f"schema_version != {CLOUD_SNAPSHOT_SCHEMA}"
    # Verify the recorded snapshot_hash over `rows` — the exporter computes it as
    # sha256 of the compact-serialized rows (build_snapshot), and the docs call
    # the snapshot "immutable". Without this check a snapshot whose rows were
    # hand-edited, truncated by a partial copy, or corrupted after export passed
    # as fully available and its stale hash even seeded the deterministic sample
    # (PR #531 early-shadow: the integrity mechanism existed on the producer side
    # but the consumer's enforcement half was missing — fail-open on exactly the
    # tampered input the hash exists to detect). A mismatch reads unavailable.
    rows = doc.get("rows")
    if isinstance(rows, list):
        # A rows-present snapshot's integrity is UNVERIFIABLE without a usable
        # recorded hash: an absent/non-string snapshot_hash is a legitimate
        # alteration shape (a hand-edit or partial copy that dropped the field),
        # so the guard must fail CLOSED — a guard whose comparand can be absent
        # must not pass on the absent case (CLAUDE.md; convergence-shadow: the
        # iteration-2 hash check returned "ok" when the hash was stripped).
        recorded = doc.get("snapshot_hash")
        if not isinstance(recorded, str):
            return None, "snapshot_hash absent/non-string with rows present (integrity unverifiable)"
        actual = _sha256_hex(json.dumps(rows, sort_keys=True, separators=(",", ":")).encode("utf-8"))
        if actual != recorded:
            return None, "snapshot_hash mismatch (rows altered since export)"
    return doc, "ok"


def build_cloud_census(snapshot: dict[str, Any] | None, cloud_mappings: dict[str, dict[str, object]]) -> "tuple[list[EligibleLifecycle], dict[str, Any]]":
    rows: list[EligibleLifecycle] = []
    coverage: dict[str, Any] = {"available": False, "pagination_complete": None, "unavailable": True}
    if snapshot is None:
        # Absent cloud census -> unavailable, never zero.
        return rows, coverage
    coverage["available"] = True
    coverage["unavailable"] = False
    coverage["pagination_complete"] = bool(snapshot.get("pagination_complete", False))
    coverage["snapshot_hash"] = snapshot.get("snapshot_hash")
    coverage["repository"] = snapshot.get("repository")
    coverage["query_time"] = snapshot.get("query_time")
    # An incomplete pagination (a mid-export transport failure left a partial row
    # set) is NOT an available census — collapse it to unavailable so a partial
    # measurement is never read as a complete one (the exporter's "absent or
    # incomplete -> unavailable, never zero" contract).
    if not coverage["pagination_complete"]:
        coverage["available"] = False
        coverage["unavailable"] = True
        coverage["reason"] = "pagination incomplete"
        return rows, coverage
    raw_rows = snapshot.get("rows")
    if not isinstance(raw_rows, list):
        # Incomplete cloud census -> unavailable.
        coverage["available"] = False
        coverage["unavailable"] = True
        coverage["reason"] = "snapshot rows missing or malformed"
        return rows, coverage
    position = 0
    malformed_rows = 0
    identityless_rows = 0
    for raw in raw_rows:
        if not isinstance(raw, dict):
            # A corrupt/API-shifted row never vanishes from the denominator silently:
            # count it so the reader can see rows were dropped (never silently omitted).
            malformed_rows += 1
            continue
        wf = raw.get("workflow_file")
        job = raw.get("job")
        if not (isinstance(wf, str) and isinstance(job, str)):
            # A dict row with absent/non-string identity fields previously fell
            # into the confirmed_ineligible arm ("job None not in
            # cloud_mappings") — so an API field rename/omission read as a
            # valid all-non-agent window, coverage available, no breadcrumb:
            # broken-shape indistinguishable from genuinely agent-less
            # (PR #531 early-shadow, silent-failure finding 1). Count them as
            # their own class; an ALL-identityless set collapses to
            # unavailable below like the all-malformed arm.
            identityless_rows += 1
            continue
        key = f"{wf}\x1f{job}"
        mapping = cloud_mappings.get(key)
        repo = snapshot.get("repository") or raw.get("repository")
        run_id = raw.get("run_id")
        run_attempt = raw.get("run_attempt")
        started_at = raw.get("started_at")
        # Cloud eligibility: allowlisted (workflow_file, job) + scheduled/started
        # agent-step evidence. A job is "started" only when it reached an in-progress
        # or completed-with-a-real-conclusion state — a GitHub Actions SKIPPED job
        # has status="completed" + conclusion="skipped" but the agent step never ran,
        # so it must NOT be confirmed_eligible (it would over-claim the denominator).
        # started_at is the job-level start only; the run-level created_at is NOT a
        # job start and is deliberately not used as a fallback.
        status = str(raw.get("status") or "")
        conclusion = raw.get("conclusion")
        # `cancelled` and `action_required` are the two terminal conclusions a
        # job can carry WITHOUT its step ever running (a run cancelled while
        # the job was queued; an approval never granted): status="completed" +
        # that conclusion + started_at=null is exactly the never-started shape,
        # so a non-skipped conclusion alone is NOT start evidence — treating it
        # as such failed open on the stall-backstop's own cancelled runs
        # (PR #531 iteration-1; the same fail-open class the skipped/queued
        # arms already close). For these conclusions the job-level started_at
        # is the only admissible start evidence.
        # "stale" is included on the same conservative basis: it is a terminal
        # conclusion GitHub can stamp on a superseded/stale job without the
        # step having run; requiring a job-level started_at can only demote a
        # never-evidenced row to provisional/ineligible, never promote one.
        _non_start_conclusions = ("cancelled", "action_required", "stale")
        completed_and_ran = (
            status == "completed"
            and conclusion not in (None, "skipped")
            and conclusion not in _non_start_conclusions
        )
        # A SKIPPED job never ran its agent step, so it is never "started" —
        # regardless of whether the Actions API populated a started_at for it. The
        # trailing `bool(started_at)` must not re-admit a skipped job: keying the
        # exclusion on that unverified API-shape assumption fails OPEN on the exact
        # input the guard exists to reject (issue #527 review; unverified-assumption
        # class). Exclude skipped explicitly.
        scheduled_started = (
            status in ("queued", "in_progress") or completed_and_ran or bool(started_at)
        ) and conclusion != "skipped"
        # A job is evidenced STARTED only when it completed with a real
        # start-implying conclusion, is in_progress with a job-level
        # started_at, or carries a cancelled/action_required conclusion WITH a
        # job-level started_at (cancellation after a genuine start). A queued
        # job (or an in_progress row the API has not stamped a job start on,
        # or a bare started_at under an unknown status) is scheduled but not
        # evidenced-started: it stays provisional_candidate — in the
        # denominator, never confirmed, never promoted — instead of
        # over-claiming the confirmed eligible denominator (issue #527 review,
        # suggestion 3).
        started_evidenced = (
            completed_and_ran
            or (status == "in_progress" and bool(started_at))
            or (status == "completed" and conclusion in _non_start_conclusions and bool(started_at))
        )
        if mapping is None:
            # Precheck/dedupe/telemetry/relay/skipped non-agent jobs: ineligible.
            state = ELIGIBILITY_INELIGIBLE
            evidence = f"job {job!r} not in cloud_mappings agent_jobs (non-agent)"
        elif not scheduled_started:
            state = ELIGIBILITY_INELIGIBLE
            evidence = "agent job present but no scheduled/started agent-step evidence (skipped or never started)"
        elif not started_evidenced:
            state = ELIGIBILITY_PROVISIONAL
            evidence = (
                f"allowlisted agent job {job!r} scheduled (status={status or 'unknown'}) but its start is "
                "not yet evidenced (no completed conclusion / no in-progress job start) — provisional, never promoted"
            )
        else:
            state = ELIGIBILITY_CONFIRMED
            evidence = f"allowlisted agent job {job!r} consumer={mapping.get('consumer')} routed={mapping.get('routed_command')}"
        rows.append(EligibleLifecycle(
            source=SOURCE_CLOUD,
            surrogate_id=_surrogate_id(SOURCE_CLOUD, str(repo), str(wf), str(job), str(run_id), str(run_attempt), str(position)),
            consumer=mapping.get("consumer") if mapping else None,
            subject=None,
            identity={
                "repository": repo,
                "workflow_file": wf,
                "run_id": run_id,
                "run_attempt": run_attempt,
                "job": job,
                "started_at": started_at,
            },
            eligibility_state=state,
            eligibility_evidence=evidence,
            host_profile={"conclusion": raw.get("conclusion"), "status": status},
            source_status=CLOUD_SOURCE_AVAILABLE,
            provenance={
                "snapshot_hash": snapshot.get("snapshot_hash"),
                "run_id": run_id,
                "run_attempt": run_attempt,
                # Surfaced on the ROW, not merely carried in the mapping table:
                # the consumer attribution of a multiplexed job (devflow.yml's
                # `command` routes three commands, and the census snapshot is
                # job-level) is a Wave-1 approximation, and a stratifier reading
                # this row must be able to tell it from an exact attribution.
                # Nothing could, while the flag was dropped by its only reader
                # (PR #531 review-and-fix iter-1, Phase-2 VC-33 FAIL).
                "consumer_approximate": bool(mapping.get("consumer_approximate")) if mapping else False,
            },
        ))
        position += 1
    if malformed_rows:
        coverage["malformed_row_count"] = malformed_rows
        # Surface the dropped-row count on stderr, mirroring load_cloud_mappings'
        # dropped-entry breadcrumb — a count buried only inside the JSON artifact
        # is not loud degradation (PR #531 early-shadow).
        print(
            f"devflow verification-baseline: cloud census dropped {malformed_rows} "
            "malformed row(s) (non-dict); the denominator excludes them",
            file=sys.stderr,
        )
        # An ALL-malformed row set (rows present but none usable) is a broken
        # snapshot, not a genuinely agent-less window: collapse to unavailable so
        # a corrupt census is never read as a clean zero-eligibility measurement.
        if not rows:
            coverage["available"] = False
            coverage["unavailable"] = True
            coverage["reason"] = f"all {malformed_rows} snapshot row(s) malformed"
    if identityless_rows:
        coverage["identityless_row_count"] = identityless_rows
        print(
            f"devflow verification-baseline: cloud census dropped {identityless_rows} "
            "identityless row(s) (absent/non-string workflow_file or job — API shape "
            "drift or exporter regression?); the denominator excludes them",
            file=sys.stderr,
        )
        if not rows:
            coverage["available"] = False
            coverage["unavailable"] = True
            coverage["reason"] = f"all usable rows identityless ({identityless_rows})"
    # Cloud rows report census/eligibility/missingness ONLY — no launch/duration/
    # relationship/retry-candidate claims are made here (cloud launch analysis is
    # excluded in Wave 1).
    return rows, coverage


# --------------------------------------------------------------------------- #
# Source snapshot hash + performance reporting.
# --------------------------------------------------------------------------- #
def compute_source_snapshot_hash(rows: list[EligibleLifecycle], cloud_snapshot: dict | None) -> str:
    parts: list[str] = []
    for row in sorted(rows, key=lambda r: r.surrogate_id):
        if row.source == SOURCE_LOCAL:
            parts.append(f"local:{row.identity.get('session_id')}:{row.source_status}:{row.eligibility_state}")
        else:
            parts.append(f"cloud:{row.identity.get('run_id')}:{row.identity.get('job')}:{row.eligibility_state}")
    if cloud_snapshot is not None:
        parts.append(f"snapshot:{cloud_snapshot.get('snapshot_hash')}")
    return _sha256_hex("\n".join(parts).encode("utf-8"))


# --------------------------------------------------------------------------- #
# Report generation (no over-claiming; cites source-event IDs only).
# --------------------------------------------------------------------------- #
def generate_report(baseline: "VerificationBaseline") -> str:
    m = baseline.metrics
    sample = baseline.manual_review_sample
    lines: list[str] = []
    lines.append("# Verification-launch baseline (Wave 1)")
    lines.append("")
    lines.append(f"- created_at: {baseline.created_at}")
    lines.append(f"- source_snapshot_hash: {baseline.source_snapshot_hash}")
    lines.append(f"- expires_at: {baseline.expires_at}")
    lines.append("")
    lines.append("## Census + eligibility (denominator)")
    lines.append(f"- census rows: {m['census_rows']} (every job row, including confirmed-ineligible)")
    lines.append(f"- eligible lifecycles: {m['eligible_lifecycles']} (confirmed + provisional)")
    _ineligible_launches = sum(
        c for s, c in m["local_actual_launches_by_lifecycle_eligibility"].items()
        if s not in (ELIGIBILITY_CONFIRMED, ELIGIBILITY_PROVISIONAL)
    )
    if _ineligible_launches:
        # Never print the ratio's numerator without this when it does not sit
        # over the denominator above — the incoherence must be readable at the
        # surface a human actually reads (PR #531 review-and-fix iter-1, VC-2).
        lines.append(
            f"- ⚠️ {_ineligible_launches} actual launch(es) come from lifecycles that are NOT in the "
            f"eligible denominator above (extraction admits any source-available local row regardless "
            f"of eligibility) — treat the launch/eligible ratio as non-comparable, not a clean fraction"
        )
    bounds = m["eligibility_state_bounds"]
    lines.append(f"- eligibility bounds: confirmed={bounds.get(ELIGIBILITY_CONFIRMED, 0)} provisional={bounds.get(ELIGIBILITY_PROVISIONAL, 0)} ineligible={bounds.get(ELIGIBILITY_INELIGIBLE, 0)} unknown={bounds.get(ELIGIBILITY_UNKNOWN, 0)}")
    sm = m["source_availability_and_missingness"]
    lines.append(f"- source availability/missingness: available={sm.get(SOURCE_AVAILABLE, 0)} eligible_not_imported={sm.get(SOURCE_ELIGIBLE_NOT_IMPORTED, 0)} import_failed={sm.get(SOURCE_IMPORT_FAILED, 0)} source_missing={sm.get(SOURCE_MISSING, 0)} source_unreadable={sm.get(SOURCE_UNREADABLE, 0)} source_unsupported={sm.get(SOURCE_UNSUPPORTED, 0)} unavailable={sm.get(SOURCE_UNAVAILABLE, 0)}")
    if baseline.cloud_coverage.get("unavailable"):
        lines.append("- cloud coverage: unavailable (absent or incomplete cloud census; never zero)")
    else:
        lines.append(f"- cloud coverage: available (pagination_complete={baseline.cloud_coverage.get('pagination_complete')})")
    lines.append("")
    lines.append("## Local actual launches (observed)")
    lines.append(f"- verification requests: {m['verification_requests']}")
    lines.append(f"- confirmed process launches: {m['local_actual_launches']}")
    lines.append(f"- terminal results: {m['terminal_results']}; missing results: {m['missing_results']}")
    lines.append("")
    lines.append("## Repeated-binding relationship classification (conservative)")
    lines.append(f"- repeated-binding groups: {m['repeated_binding_groups']}")
    lines.append(f"- candidate_transport_retry: {m['candidate_retries']} (candidates, NOT confirmed duplicates)")
    lines.append(f"- intentional_rerun_evidence: {m['intentional_rerun_evidence']}")
    lines.append(f"- independent_lifecycle: {m['independent_lifecycles']}")
    lines.append(f"- unclassifiable: {m['unclassifiable_groups']}")
    lines.append(f"- single: {m['single_groups']}")
    lines.append(f"- workspace coverage: {m['workspace_coverage_distribution']}")
    lines.append(f"- join confidence: {m['join_confidence_distribution']}")
    est = m["estimated_repeated_suite_wall_time_ms"]
    lines.append(f"- estimated repeated-suite wall time (ms): {est if est is not None else 'unavailable'}")
    lines.append("")
    lines.append("## Manual-review sample")
    lines.append(f"- seed: {sample['seed']}")
    lines.append(f"- eligible population: {len(sample['eligible_population'])} groups")
    lines.append(f"- selected IDs: {len(sample['selected_ids'])} (high_cost={len(sample['high_cost_ids'])}, remainder={len(sample['remainder_selected_ids'])})")
    lines.append("- reviewers see cited source-event evidence without analyzer relationship labels; record confirmed_retry_pattern / intentional_rerun / insufficient_evidence per group")
    lines.append("")
    lines.append("## Evidence limitations")
    lines.append("- This baseline states observed counts and candidate counts only. It does NOT claim launches avoided, terminal evidence reusable, command authorization safe, or active recovery justified.")
    lines.append("- Cloud rows are census/missingness-only (cloud launch analysis is excluded in Wave 1: no durable redacted execution-event source exists without changing workflows).")
    lines.append("- Captured-only rows are never presented as the eligible-lifecycle denominator; provisional and unknown rows are never promoted to confirmed and never silently omitted.")
    lines.append("")
    lines.append("## Active-recovery gate (later issue)")
    lines.append("- A later LOCAL active-recovery issue requires: a complete local census snapshot, at least 90% local source-status resolution, no local missingness stratum above 20%, and at least two independently adjudicated confirmed patterns in the same proposed consumer/checkpoint/binding target, plus measured cost and a separately reviewed trusted-command and lifecycle design. One confirmation remains exploratory.")
    lines.append("- Cloud active recovery requires a separate evidence-source design and issue. This baseline authorizes no active behavior.")
    lines.append("")
    return "\n".join(lines)


# --------------------------------------------------------------------------- #
# Output bounding (defense-in-depth: bound string lengths before serialization).
# --------------------------------------------------------------------------- #
def _bound_strings(obj: Any, limit: int = 4000) -> Any:
    if isinstance(obj, str):
        return obj if len(obj) <= limit else obj[:limit] + "…<truncated>"
    if isinstance(obj, dict):
        return {k: _bound_strings(v, limit) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_bound_strings(v, limit) for v in obj]
    return obj


# --------------------------------------------------------------------------- #
# Baseline record + main.
# --------------------------------------------------------------------------- #
@dataclass
class VerificationBaseline:
    # The envelope holds the TYPED, construction-validated records and converts
    # to serialized dicts only inside to_dict() — the analyzer's write boundary.
    # Holding pre-converted list[dict] here (the previous shape) erased every
    # __post_init__ guarantee at exactly the boundary the records exist to
    # protect: between construction and serialization nothing could tell a
    # validated row from a hand-built dict (PR #531 review, type-design
    # suggestion 1). The serialized output is byte-identical — only WHERE the
    # to_dict() conversion happens moved.
    created_at: str
    source_snapshot_hash: str
    expires_at: str
    census: dict[str, list[EligibleLifecycle]]  # {"local": [...], "cloud": [...]}
    cloud_coverage: dict[str, Any]
    verification_requests: list[VerificationRequest]
    verification_process_launches: list[VerificationProcessLaunch]
    relationship_groups: list[RelationshipGroup]
    metrics: dict[str, Any]
    manual_review_sample: dict[str, Any]
    stratification: dict[str, Any]
    performance: dict[str, Any]
    schema_version: int = VERIFICATION_BASELINE_SCHEMA

    def to_dict(self) -> dict[str, Any]:
        return _bound_strings({
            "schema_version": self.schema_version,
            "created_at": self.created_at,
            "source_snapshot_hash": self.source_snapshot_hash,
            "expires_at": self.expires_at,
            "census": {key: [r.to_dict() for r in rows] for key, rows in self.census.items()},
            "cloud_coverage": self.cloud_coverage,
            "verification_requests": [r.to_dict() for r in self.verification_requests],
            "verification_process_launches": [launch.to_dict() for launch in self.verification_process_launches],
            "relationship_groups": [g.to_dict() for g in self.relationship_groups],
            "metrics": self.metrics,
            "manual_review_sample": self.manual_review_sample,
            "stratification": self.stratification,
            "performance": self.performance,
        })


def _cleanup(out_dir: Path) -> "tuple[int, int]":
    """Delete baseline + manual-review artifacts without touching native sources.

    Returns (removed, failed). A per-artifact unlink/rmdir failure is COUNTED,
    not silently swallowed: these artifacts hold sensitive local data at 0600, so
    a failed deletion the caller reports as success would leave sensitive files
    behind while claiming the directory was purged (issue #527 review finding).
    """
    if not out_dir.exists():
        return 0, 0
    removed = 0
    failed = 0
    for child in sorted(out_dir.iterdir()):
        if child.is_symlink():
            # AC #61/#62: never FOLLOW a symlink during cleanup — is_dir()/
            # is_file() both follow, so a link planted in the agent-writable
            # out_dir pointing at a native source would have its TARGET's
            # files unlinked (PR #531 early-shadow final pass, Important).
            # Remove the link itself; the target is untouched.
            try:
                child.unlink()
                removed += 1
            except OSError:
                failed += 1
            continue
        if child.is_dir():
            for sub in sorted(child.iterdir()):
                if sub.is_symlink():
                    try:
                        sub.unlink()
                        removed += 1
                    except OSError:
                        failed += 1
                    continue
                if sub.is_file():
                    try:
                        sub.unlink()
                        removed += 1
                    except OSError:
                        failed += 1
            try:
                child.rmdir()
                removed += 1
            except OSError:
                failed += 1
        elif child.is_file():
            try:
                child.unlink()
                removed += 1
            except OSError:
                failed += 1
    return removed, failed


def _force_utf8_streams():
    """Force stdout/stderr to UTF-8. Never call this at import: doing so mutates the
    streams of any process that imports this module for tests. Tolerates a stream that
    has no usable `reconfigure` (issue #1762)."""
    for _stream in (sys.stdout, sys.stderr):
        try:
            _stream.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError, OSError):
            pass


def main(argv: "list[str] | None" = None) -> int:
    _force_utf8_streams()
    parser = argparse.ArgumentParser(description="Offline verification-launch baseline analyzer (issue #527, Wave 1).")
    parser.add_argument("--manifests-dir", default=DEFAULT_MANIFESTS_DIR)
    parser.add_argument("--bundles-dir", default=DEFAULT_BUNDLES_DIR)
    parser.add_argument("--registry", default=DEFAULT_REGISTRY)
    parser.add_argument("--cloud-census", default=DEFAULT_CLOUD_SNAPSHOT)
    parser.add_argument("--out-dir", default=DEFAULT_OUT_DIR)
    parser.add_argument("--max-source-bytes", type=int, default=DEFAULT_MAX_SOURCE_BYTES)
    def _nonneg_ttl(value: str) -> int:
        # A negative TTL yields an expires_at in the past — an instantly
        # "expired" 0600 artifact whose retention promise is nonsense.
        # Reject at the CLI boundary (PR #531 early-shadow).
        n = int(value)
        if n < 0:
            raise argparse.ArgumentTypeError(f"--ttl-seconds must be >= 0; got {n}")
        return n
    parser.add_argument("--ttl-seconds", type=_nonneg_ttl, default=DEFAULT_TTL_SECONDS)
    parser.add_argument("--cleanup", action="store_true", help="delete baseline + manual-review artifacts without touching native sources")
    args = parser.parse_args(argv)

    try:
        out_dir = _validate_admitted_path(args.out_dir)
        manifests_dir = _validate_admitted_path(args.manifests_dir)
        bundles_dir = _validate_admitted_path(args.bundles_dir)
        registry_path = _validate_admitted_path(args.registry, must_exist=True)
    except (ValueError, FileNotFoundError) as exc:
        print(f"devflow verification-baseline: path validation failed: {exc}", file=sys.stderr)
        return 2

    if args.cleanup:
        removed, failed = _cleanup(out_dir)
        if failed:
            # Never report an unqualified success while sensitive 0600 artifacts
            # survive: name the failure and exit non-zero (issue #527 review).
            print(
                f"devflow verification-baseline: cleanup removed {removed} artifact(s) but "
                f"FAILED to remove {failed} (still present under {out_dir}; native sources untouched)",
                file=sys.stderr,
            )
            return 1
        print(f"devflow verification-baseline: cleanup removed {removed} artifact(s) under {out_dir} (native sources untouched)")
        return 0

    tracemalloc.start()
    wall_start = time.monotonic()
    # input_bytes counts bytes actually READ from source inputs (registry,
    # manifests, bundle metadata, transcripts, stop-attempts logs, the cloud
    # census snapshot) — not the short per-row evidence strings the field
    # previously summed, which under-reported the tool's own measured input by
    # orders of magnitude (issue #527 review, Important 3).
    stats: dict[str, int] = {"input_bytes": 0}

    try:
        registry = wfr.load_registry(registry_path)
    except ValueError as exc:
        print(f"devflow verification-baseline: registry load failed: {exc}", file=sys.stderr)
        return 2
    cloud_mappings = load_cloud_mappings(registry_path)
    try:
        # The registry file is read twice (load_registry + load_cloud_mappings);
        # its size is counted once — the input is one file.
        _count_input_bytes(stats, registry_path.stat().st_size)
    except OSError as exc:
        # Breadcrumb, not a silent pass: input_bytes is best-effort telemetry
        # (it decides nothing), but every other degradation in this module names
        # itself on stderr, and an unexplained undercount in the tool's own
        # "measured input" line is the shape a reader cannot distinguish from a
        # correct small number (PR #531 review-and-fix, convergence shadow).
        print(f"devflow verification-baseline: could not stat {registry_path} for input-byte "
              f"accounting ({type(exc).__name__}); input_bytes undercounts by that file",
              file=sys.stderr)

    # 1. Local census (denominator, from start manifests).
    local_rows = build_local_census(manifests_dir, registry, stats)

    # 2. Left-join local native imports + source missingness.
    local_rows = join_local_imports(local_rows, bundles_dir, args.max_source_bytes, stats)

    # 3. Verification request + process-launch extraction (local-native only).
    requests, launches, local_rows = extract_verification_lifecycles(local_rows, bundles_dir, registry, args.max_source_bytes, stats)

    # 4. Relationship grouping + classification.
    groups = group_launches(launches)

    # 5. Cloud census (census/missingness only; no launch claims).
    cloud_snapshot = None
    if args.cloud_census:
        try:
            cloud_path = _validate_admitted_path(args.cloud_census, must_exist=True)
            # Byte accounting moved INTO read_cloud_census (counted only after a
            # successful read, as actual bytes read) so _count_input_bytes'
            # "none were read" universal holds for this reader too (PR #531
            # review-and-fix local iteration; the old stat()-size count here
            # charged unreadable snapshots their full size).
            cloud_snapshot, cloud_reason = read_cloud_census(cloud_path, stats)
            if cloud_snapshot is None and cloud_reason != "absent":
                # Distinguish a corrupt/schema-mismatch file from a missing flag so an
                # operator who passed --cloud-census can tell why coverage is unavailable.
                print(f"devflow verification-baseline: cloud census unreadable ({cloud_reason}); coverage reads unavailable", file=sys.stderr)
        except (ValueError, FileNotFoundError) as exc:
            print(f"devflow verification-baseline: cloud census read failed: {exc}", file=sys.stderr)
    cloud_rows, cloud_coverage = build_cloud_census(cloud_snapshot, cloud_mappings)

    all_rows = local_rows + cloud_rows
    has_cloud = cloud_snapshot is not None

    # 6. Metrics + sampling + stratification.
    metrics = compute_metrics(
        all_rows, requests, launches, groups, has_cloud,
        bool(cloud_coverage.get("unavailable")),
        cloud_attempted=bool(args.cloud_census),
    )
    snapshot_hash = compute_source_snapshot_hash(all_rows, cloud_snapshot)
    sample = manual_review_sample(groups, snapshot_hash)
    stratification = stratify(launches, all_rows)

    # 7. Performance reporting.
    current, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    wall_ms = int((time.monotonic() - wall_start) * 1000)
    performance = {
        "analyzer_wall_time_ms": wall_ms,
        "peak_memory_bytes": peak,
        "input_bytes": stats["input_bytes"],
        "output_bytes": None,  # filled after serialization
        "lifecycle_count": len(all_rows),
        # AC #64: events parsed at extraction across local transcripts (cloud
        # sources carry no native events). 0 is factual here — it means zero
        # events were parsed, not "unknown" (the tally rides the same stats
        # dict as every other counter).
        "event_count": stats.get("event_count", 0),
        # A source-available transcript in which no registered root occurrence
        # was detected (registry drift / detection regression — see the
        # extraction site's no_root_occurrence arm): surfaced in the artifact
        # so numerator blindness is visible, not just on stderr.
        "no_occurrence_count": stats.get("no_occurrence_count", 0),
        "skipped_unsupported_source_count": sum(1 for r in all_rows if r.source_status in (SOURCE_UNSUPPORTED, SOURCE_UNREADABLE)),
        # Extraction failures are counted separately from the other
        # source_unsupported producers so a systemic analyzer defect (every
        # transcript degrading) is visible in the artifact, not just stderr.
        "extraction_failure_count": stats.get("extraction_failure_count", 0),
    }
    # Denominator = transcripts extraction actually ATTEMPTED (counted at the
    # extraction site), not every unsupported row — schema-unknown/size-breach
    # rows extraction never reached must not dilute the all-attempts-failed
    # signal (PR #531 iteration-1 gate finding 7).
    if performance["extraction_failure_count"] and performance[
        "extraction_failure_count"
    ] >= stats.get("extraction_attempted_count", 0):
        print(
            "devflow verification-baseline: WARNING — extraction failed for EVERY "
            "attempted transcript; this baseline measured nothing (an analyzer-side "
            "defect, not a clean corpus)",
            file=sys.stderr,
        )

    created_at = _now_iso()
    expires_at = _expires_at(created_at, args.ttl_seconds)

    baseline = VerificationBaseline(
        created_at=created_at,
        source_snapshot_hash=snapshot_hash,
        expires_at=expires_at,
        census={
            "local": local_rows,
            "cloud": cloud_rows,
        },
        cloud_coverage=cloud_coverage,
        verification_requests=requests,
        verification_process_launches=launches,
        relationship_groups=groups,
        metrics=metrics,
        manual_review_sample=sample,
        stratification=stratification,
        performance=performance,
    )

    # output_bytes is self-referential (the field's value changes the payload
    # length): serialize once, set output_bytes on the serialized dict, and
    # re-serialize that — avoiding a second to_dict()/_bound_strings() walk of
    # the whole baseline. generate_report does not read baseline.performance, so
    # the live object's output_bytes is mirrored only for parity. The recorded
    # value is the FIRST serialization's length, so it can differ from the
    # written file's byte count by the few digits the field substitution adds —
    # a disclosed approximation (a fixed point is not chased).
    doc = baseline.to_dict()
    payload = json.dumps(doc, indent=2, sort_keys=True).encode("utf-8")
    performance["output_bytes"] = len(payload)
    doc["performance"]["output_bytes"] = len(payload)
    payload = json.dumps(doc, indent=2, sort_keys=True).encode("utf-8")

    report = generate_report(baseline)

    stamp = created_at.replace(":", "").replace(".", "").replace("-", "")[:14]
    out_subdir = out_dir / f"{stamp}-{snapshot_hash[:8]}"
    out_subdir.mkdir(parents=True, exist_ok=True)
    # Harden BOTH the per-run subdir AND its parent baseline dir to 0700: the
    # docstring promises "owner-only 0700 directories" (plural), and mkdir(parents)
    # otherwise leaves the parent at umask perms (issue #527 review, defense-in-depth).
    for _d in (out_dir, out_subdir):
        try:
            os.chmod(_d, DIR_MODE)
        except OSError as exc:
            print(f"devflow verification-baseline: could not chmod {_d} to 0700 ({exc}); artifacts may carry umask permissions", file=sys.stderr)
    _atomic_write(out_subdir / "verification_baseline.json", payload)
    _atomic_write(out_subdir / "report.md", report.encode("utf-8"))
    # Manual-review artifact (initially empty adjudication; reviewers fill it).
    # Carry the same created_at/source_snapshot_hash/expires_at the docstring and
    # docs promise for EVERY artifact — the sensitive manual-review file must also
    # carry the TTL/expiry so `--cleanup` and the retention promise hold for it
    # (PR #531 early-shadow: the promise was stated for all artifacts but two of
    # the three fields were absent from manual_review.json).
    manual_review_doc = {
        "created_at": created_at,
        "source_snapshot_hash": snapshot_hash,
        "expires_at": expires_at,
        **sample,
    }
    _atomic_write(out_subdir / "manual_review.json", json.dumps(manual_review_doc, indent=2, sort_keys=True).encode("utf-8"))

    print(f"devflow verification-baseline: wrote {out_subdir}/verification_baseline.json + report.md")
    # The stdout summary prints the headline figures with NO adjacent bounds
    # disclosure, so it carried the inflated denominator entirely uncorrected —
    # print the census total beside the eligible count here too (PR #531
    # review-and-fix iter-1, code-reviewer Important).
    print(f"  census rows: {metrics['census_rows']} | eligible lifecycles: {metrics['eligible_lifecycles']} | actual launches: {metrics['local_actual_launches']} | candidate retries: {metrics['candidate_retries']} | unclassifiable: {metrics['unclassifiable_groups']}")
    print(f"  wall {wall_ms}ms | peak {peak}B | output {len(payload)}B | skipped/unsupported {performance['skipped_unsupported_source_count']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
