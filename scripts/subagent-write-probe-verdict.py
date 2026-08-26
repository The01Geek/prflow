#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Daniel Radman
# SPDX-License-Identifier: MIT
"""subagent-write-probe-verdict.py — derive the "does a dispatched subagent's Write
into `.prflow/tmp/**` succeed?" probe verdict from a `claude-code-action` execution
file, per tier (issue #858).

Why a helper rather than inline Python in matcher-probe.yml: this verdict is a
branch-selecting core (a three-outcome PERMITTED / DENIED / unestablished selection,
where a state outside the measurable pair routes to `unestablished` rather than to
DENIED — a permission finding must never be published about a run that never attempted
the permission). The one disclosed residual is stated with the DENIED bullet below: a
denial entry recording no `tool_name` at all and naming the side-effect filename is read
as the write denial, because the per-entry denial shape is not yet recorded and no
narrower attribution channel exists for it. Inline-in-YAML it cannot be unit-tested, so a regressed arm
would silently misfire while the workflow still "runs" — the same rationale as
scripts/background-tasks-probe-verdict.py (#812), scripts/env-propagation-probe-verdict.py
(#874), scripts/agents-seam-probe-verdict.py (#610), and scripts/describe-denial-count.sh
(PR #367).

THE PREMISE UNDER TEST. `Write(.prflow/tmp/**)` is granted in the review profile and
unrestricted `Write` in the implement profile, but every shipped instruction that authors
into that tree is addressed to the ORCHESTRATOR. Whether a DISPATCHED subagent's Write
lands is unestablished: a grant proven for the dispatcher is not inherited by the
dispatchee (CLAUDE.md: "Unknown is not zero"). Each tier gets its OWN dedicated job whose
prompt contains NO orchestrator write, so a Write record in its execution file has exactly
one possible author — the subagent.

HOW THE MEASUREMENT IS MADE ATTRIBUTABLE. The subagent makes a positive-control call on an
unambiguously granted head BEFORE the write attempt and one AFTER it (mirroring the #812
before/after pair). The two control facts are reported INDEPENDENTLY, never conjoined:

  recorded_at_all     did any subagent-issued call (a control or the write) appear in the
                      execution file at all? A no means the file does not surface
                      dispatchee actions, and nothing about the write can be concluded.
  chain_attributable  did those calls carry a `parent_tool_use_id` chain to a dispatch
                      recorded in this file? A no, WITH calls nonetheless recorded, is a
                      distinct THIRD schema world (dispatchee actions recorded but not
                      attributable by chain) — reported as its own `unestablished` reason,
                      not as "no dispatchee actions recorded".

Conjoining the two would misreport that third world as the first and — because a null
parent chain otherwise routes to `unestablished` — make PERMITTED unreachable by
construction, so the probe could not return the outcome it was filed to obtain.

A subagent-issued call is identified by carrying one of the probe markers in a tool_use
whose own name is NOT the dispatch tool (Task/Agent) — the dispatch's OWN input necessarily
quotes the marker vocabulary (it names what it asks the subagent to emit), so counting the
dispatch entry would credit a subagent call that never happened. This is the same
"the dispatch prompt unavoidably carries the marker" trap the #812 helper guards.

The ORCHESTRATOR is excluded by the same reasoning, but only where the file proves it can
be: this job's top-level session is granted heads whose inputs may also quote the marker
vocabulary (it reports whether the dispatch happened), and a top-level call carries no
`parent_tool_use_id`. So when THIS file records a parent chain on any entry at all, the
harness demonstrably surfaces the chain and a parent-less marker call is orchestrator-issued
and excluded. When NO entry in the file carries a parent, the schema does not surface chains
at all — excluding parent-less calls would then collapse the distinct third world below onto
"no dispatchee actions recorded", so they are retained and the third world's own reason
discloses that they cannot be told apart from orchestrator-issued calls.

Deterministic three-outcome verdict, execution-file + on-disk side-effect only (the
model's prose is NEVER read — only harness-recorded `tool_use` inputs, their
`parent_tool_use_id`, and `permission_denials`):

  PERMITTED       a subagent `Write` tool_use naming the tier's side-effect filename was
                  recorded, its parent chains to a dispatch recorded in this file, AND the
                  on-disk side-effect file carries the probe's payload marker (presence
                  alone is NOT corroboration — an empty, truncated, or foreign-authored
                  file does not establish that the write landed). The verdict cites that
                  chain by its
                  `tool_use` id and `parent_tool_use_id`, so a reader can re-verify it.
  DENIED          a permission_denials entry attributable to the subagent's Write was
                  recorded, AND a dispatch is recorded in this file (with no dispatchee to
                  attribute it to the denial is not the subagent's), AND — where this file
                  records parent chains at all — no parent-less, orchestrator-issued Write
                  names the same file (such a Write falsifies the single-author premise the
                  attribution rests on). All three conjuncts are required; each missing one
                  routes to its own named `unestablished` reason below, never to DENIED.
                  DENIED wins over a present side-effect file (an earlier run's
                  leftover): the denial signal is authoritative. Attribution rests on the
                  job's prompt containing NO orchestrator write, so a Write denial has
                  exactly one possible author; the run's observed denial-entry shape is
                  recorded alongside the verdict, which is what upgrades the denial side
                  from by-construction to measured.
                  Denial entries are classified ONE AT A TIME, never over their
                  concatenation: an entry is a DISPATCH refusal first (its own tool_name is
                  Task/Agent, or — with no tool_name recorded — it carries the quoted
                  `"subagent_type"` key or the `general-purpose` type name), otherwise a
                  WRITE denial (its own tool_name is Write and it names the side-effect
                  filename, or — with no tool_name recorded — it names the side-effect
                  filename), otherwise a FOREIGN write denial (a `Write`, or an entry
                  recording no tool_name, carrying the PAYLOAD but naming another path),
                  otherwise an UNATTRIBUTABLE refusal (its own tool_name is Write, OR no
                  tool_name is recorded, and it names neither) — the RESIDUAL bucket, so it
                  also absorbs a name-less refusal of some other tool, which costs a true
                  "did not attempt" measurement but never states a falsehood. Only the
                  WRITE-denial bucket can produce DENIED; the two buckets after it route to
                  their own named `unestablished` reasons, so no denial entry is silently
                  dropped.
                  Per-entry classification is what lets a
                  multi-entry list holding BOTH a dispatch refusal and a real Write denial
                  resolve DENIED, while a lone dispatch refusal whose recorded input echoes
                  the subagent prompt verbatim (naming the path and the payload) still routes
                  to `unestablished` rather than a false DENIED. A denial naming some OTHER
                  tool is neither, so a Bash/Read refusal quoting the payload can no longer
                  publish a permission finding about a permission that was granted.
                  Residual, disclosed: an entry recording no tool_name at all and naming the
                  side-effect path is read as the write denial — the per-entry shape is not
                  yet recorded, so no narrower attribution is available for it.
  unestablished   EVERY other state, each with its own named reason (never DENIED):
                  the consumed upstream allowlist was empty/absent/unresolved (the upstream
                  tier job, or the step composing its literal, did not complete),
                  execution file absent/unreadable/unparseable/nested too deeply to walk,
                  an execution file that
                  read cleanly but holds NO records at all (zero bytes, or a cleanly-parsed
                  empty container — the
                  session recorded nothing, which is what an engine failure before the
                  first record looks like; this helper reads no engine-error field, so it
                  reports the emptiness it can observe and never the cause it cannot),
                  a `permission_denials`
                  key present in a shape that is not a list (the denials could not be
                  enumerated, so their absence is unknown rather than zero), a `--tier`
                  outside the closed set (the tier-derived write marker then names no real
                  side-effect file, so nothing measurable is being looked for), a Write
                  denial recorded with NO dispatch recorded in this file (no dispatchee to
                  attribute it to), a Write denial recorded beside a parent-less
                  orchestrator-issued Write naming the same file (the single-author premise
                  is falsified), a `Write` denial naming only the PAYLOAD and not the tier's
                  side-effect filename (a denied write to some OTHER path — reporting it as
                  the probe's write denial would be a false statement about the run), a
                  `Write` denial naming NEITHER the side-effect filename NOR the payload
                  (the entry shape does not establish what was refused, so the run must not
                  instead assert that no write was attempted),
                  dispatch refused
                  (cause NOT named — the entry shape does not establish it), no dispatch
                  recorded,
                  no subagent-issued call recorded at all, subagent calls recorded but not
                  chain-attributable, a Write recorded but not chain-attributable to this
                  job's dispatch, a chain-attributable subagent call recorded but the write
                  neither recorded nor denied (the subagent ran but did not attempt it), a
                  chain-attributable Write with no corroborating on-disk file, a derived
                  verdict string outside this closed vocabulary (the fail-closed guard at the
                  end of compute()), or an unexpected exception anywhere in the derivation
                  (main()'s always-exit-0 catch-all). The enumeration is exhaustive over the
                  arms this file ships; every one of them names its own reason.

Markers, kept in lockstep with matcher-probe.yml's subagent-write probe prompts:
  SUBWRITE_CONTROL_BEFORE   positive control, before the write attempt
  SUBWRITE_CONTROL_AFTER    positive control, after the write attempt
  SUBWRITE_PAYLOAD          the fixed content the subagent writes into the side-effect file
The tier's side-effect FILENAME (`subwrite-<tier>.txt`, written into `.prflow/tmp/`) is
the write marker, matched as a substring: a `Write` tool_use, or a denial, naming that
filename is the write signal. It is the filename and not the full path because the recorded
`file_path` spelling is not established — a relative and an absolute recording of the same
file both carry the filename.

Usage: subagent-write-probe-verdict.py [EXECUTION_FILE] --tier {review|implement}
                                       [--side-effect-file PATH] [--upstream-tools-empty]
                                       [--allowlist STR] [--permission-mode STR]
                                       [--model STR] [--effort STR] [--ref STR]
                                       [--head-commit STR]
  EXECUTION_FILE       path to the action's execution file; if omitted, read from the
                       EXECUTION_FILE env var. Empty/absent -> unestablished.
  --tier               review or implement (machine-consumed `tier` field in the output).
                       Any other value (including a missing one) emits a stderr breadcrumb
                       naming it and routes the run to `unestablished`.
  --side-effect-file   the tier's `.prflow/tmp/subwrite-<tier>.txt`. Corroborates a
                       PERMITTED only when it is present AND carries the payload marker;
                       reported as absent / wrong-content / unreadable otherwise, each with
                       its own reason. Presence alone is not corroboration.
  --upstream-tools-empty  the consumed upstream allowlist output was empty, absent or
                       unresolved (the upstream tier job did not complete, or the step that
                       composes its literal did not) -> unestablished (never a skipped job
                       silently emitting no verdict). The workflow passes it on every state
                       that is not an affirmative "resolved", so an unset output fails closed
                       onto this arm rather than onto a parse note about a file no run made.
  --allowlist / --permission-mode / --model / --effort / --ref / --head-commit
                       recorded verbatim in the emitted table so the measured condition and
                       every permission-decision parameter travels with the verdict.
Prints the markdown verdict table to stdout (and appends it to GITHUB_STEP_SUMMARY when
set). Always exits 0.
"""

import json
import os
import sys

CONTROL_BEFORE = "SUBWRITE_CONTROL_BEFORE"
CONTROL_AFTER = "SUBWRITE_CONTROL_AFTER"
PAYLOAD = "SUBWRITE_PAYLOAD"
# Lowered once at module scope — every match below is case-insensitive, so recomputing
# `.lower()` on these fixed constants inside the per-entry loops is pure repeated work.
_CONTROL_BEFORE_L = CONTROL_BEFORE.lower()
_CONTROL_AFTER_L = CONTROL_AFTER.lower()
_PAYLOAD_L = PAYLOAD.lower()

# Names of the built-in dispatch tools. A tool_use with one of these names is the
# ORCHESTRATOR'S dispatch, whose input quotes the marker vocabulary — so a marker in such
# an entry is NOT evidence of a subagent-issued call.
DISPATCH_TOOL_NAMES = ("task", "agent")

VALID_TIERS = ("review", "implement")

# Sentinel distinguishing "permission_denials key absent" from "present and holding null" —
# a plain `.get()` default of None would conflate the two, and only the second is a
# wrong-type shape worth a breadcrumb.
_ABSENT = object()

# The closed three-outcome vocabulary. Checked at the end of compute() so a typo in any one
# verdict arm cannot silently ship an invalid verdict into the machine-consumed table; the
# check is an ordinary branch (a breadcrumb plus a fall back to `unestablished`), not an
# `assert`, because `python3 -O` strips asserts and a raising check would break the
# "Always exits 0" contract exactly when it fired.
_VERDICTS = ("PERMITTED", "DENIED", "unestablished")

# Internal sentinel returned by parse_execution_file for a file that READ cleanly but holds
# no records at all (zero bytes / whitespace only). It is not a parse note — render() routes
# it to the records_note arm rather than to the "could not be read cleanly" prefix, so an
# engine death before the first record is never reported as a corrupt file.
RECORDS_EMPTY = object()

VERSION_CAVEAT = (
    "This verdict is a dated observation of one `claude-code-action` version and one "
    "subagent definition (the built-in general-purpose type dispatched by the probe's own "
    "prompt under the tier's generated baseline at the recorded commit) — not a platform "
    "contract, and it establishes nothing for a differently-defined subagent type or a "
    "later claude-code-action version. SCOPE: the run carries `--permission-mode "
    "acceptEdits`, so a `PERMITTED` answers \"did the dispatched subagent's Write land "
    "under that permission mode?\" — it does not isolate the allowlist from the permission "
    "mode as the sole reason the write was allowed. Re-probe (dispatch matcher-probe.yml, or push to a "
    "same-repo PR touching it) after a claude-code-action / CLI upgrade before trusting it."
)


def parse_execution_file(exec_file):
    """Return (parsed, note_top). parsed is a JSON value — an empty list on every failure
    path, so callers need no None-guard — and note_top is a non-empty diagnostic when the
    file was absent/empty/unparseable/partially corrupt (which forces unestablished)."""
    if not (exec_file and os.path.isfile(exec_file)):
        return [], f"execution file path absent or not a regular file at '{exec_file}'"
    try:
        with open(exec_file, encoding="utf-8", errors="replace") as fh:
            raw = fh.read()
    except OSError as e:
        return [], f"execution file present but unreadable ({e.__class__.__name__})"
    if not raw.strip():
        # A ZERO-BYTE (or whitespace-only) file is the most likely product of a
        # claude-code-action step dying before it wrote the first record — the session
        # recorded nothing. It read perfectly; calling it "present but unparseable" blames
        # the read and steers the maintainer at a corruption that did not happen. The
        # RECORDS_EMPTY sentinel routes it to render()'s records_note arm — the arm added
        # precisely so a session that recorded nothing is not described as a read failure.
        return [], RECORDS_EMPTY
    try:
        doc = json.loads(raw)
    except Exception:
        pass
    else:
        # A bare JSON scalar (null / a number / a string) parses cleanly, then walks to
        # nothing — which previously rendered the positively-stated "the dispatch never
        # occurred" about a file that is not an execution record at all. The container check
        # is the external format's own boundary row: unknown is not zero.
        if isinstance(doc, (list, dict)):
            return doc, ""
        return [], (
            f"execution file parsed as JSON but its top level is a {type(doc).__name__}, not an object or "
            "array — it is not an execution record"
        )
    # Not a single JSON document — try JSONL, counting unparseable lines. A PARTIAL
    # corruption (some lines parse but the write/marker record does not) would otherwise
    # read as a clean measurement, so any drop forces unestablished.
    parsed = []
    dropped = 0
    for line in raw.splitlines():
        s = line.strip()
        if not s:
            continue
        try:
            parsed.append(json.loads(s))
        except Exception:
            dropped += 1
    if not parsed:
        return [], "execution file present but unparseable"
    if dropped:
        return parsed, (
            f"{dropped} execution-file line(s) were unparseable — verdict may be incomplete"
        )
    return parsed, ""


def collect(parsed):
    """Walk the parsed structure and return (denials, tool_uses, shape_notes).

    denials is a list of dicts {text, tool_name}, where text is the json-encoded
    permission_denials entry and tool_name is that entry's own lower-cased `tool_name`
    (or "" when the entry records none, or is not an object at all). tool_uses is a list of
    dicts {text, text_lower, name, id, parent} where text is the json-encoded input, name is
    the lower-cased tool name, id is the tool_use id (or ""), and parent is the
    `parent_tool_use_id` (or None). A tool_use node is recorded even when it carries no
    `input` key, so an input-less entry is not silently dropped. shape_notes is a list of
    specific breadcrumbs for malformed shapes the walk could not enumerate; a non-empty
    shape_notes forces `unestablished` — an unenumerable denial list is unknown, never zero.
    """
    denials = []
    tool_uses = []
    shape_notes = []

    def walk(o, inherited=None):
        if isinstance(o, dict):
            # `parent_tool_use_id` is recorded on the MESSAGE ENVELOPE, not on the
            # `tool_use` block: the observed stream-json record is
            # `{"type": "assistant", "parent_tool_use_id": …, "message": {"content": [
            # {"type": "tool_use", …}]}}`, so the block itself carries only
            # type/id/name/input. Reading the field off the same dict that carries
            # `type == "tool_use"` therefore yields None on every real record — which would
            # make `write_chain_ok` (and so PERMITTED) unreachable by construction, and would
            # silently disarm the orchestrator exclusion that keys off the same field. The
            # committed census cannot settle this: its flattened, uniqued key set
            # "erases parentage".
            #
            # So the enclosing record's value is threaded DOWN as an inherited default and a
            # node's own value still wins where present, which resolves the chain on the
            # envelope-nested shape AND on a flat one. A present-but-unusable spelling (null,
            # empty string, a non-string) normalizes to None here, so every downstream reader
            # shares one definition of "no parent" rather than each re-deriving it.
            own = o.get("parent_tool_use_id", _ABSENT)
            if own is _ABSENT:
                here = inherited
            else:
                here = own if isinstance(own, str) and own else None
            if o.get("type") == "tool_use":
                text = json.dumps(o.get("input"))
                tool_uses.append(
                    {
                        "text": text,
                        # Lowered once here so the per-entry marker matches below never
                        # re-lower the same string two-to-four times.
                        "text_lower": text.lower(),
                        # NON-STRING NORMALIZES TO THE EMPTY SENTINEL, never to str()'s
                        # rendering of it. This side is currently BEHAVIOR-INERT — every
                        # consumer of `name` tests for a positive ("write", a dispatch name),
                        # and "" and "none" both decline all of them identically. It is kept
                        # for symmetry with the denial-side `tool_name` normalization, where
                        # "" IS an accepted sentinel and the same coercion was load-bearing,
                        # so the two sides cannot drift into disagreeing about what
                        # "not recorded" means.
                        "name": o.get("name", "").lower() if isinstance(o.get("name"), str) else "",
                        "id": o.get("id") if isinstance(o.get("id"), str) else "",
                        "parent": here,
                    }
                )
            pd = o.get("permission_denials", _ABSENT)
            if pd is not _ABSENT and not isinstance(pd, list):
                # WRONG-TYPE row of the external-format shape matrix (CLAUDE.md): the key is
                # present but not a list, so the entries cannot be enumerated. Silently
                # skipping it would render a run whose Write was denied as PERMITTED —
                # collapsing an unestablished measurement onto "no denials". Emit a SPECIFIC
                # breadcrumb naming the observed type; the caller folds it into note_top,
                # which forces unestablished.
                shape_notes.append(
                    f"a permission_denials key is present but is a {type(pd).__name__}, not a list — the "
                    "denial entries could not be enumerated"
                )
            if isinstance(pd, list):
                for d in pd:
                    # Retain each denial's own tool_name (lower-cased): compute()'s per-entry
                    # classification routes on it, so a denied DISPATCH (whose recorded
                    # tool_input echoes the subagent prompt, naming the side-effect path and
                    # payload) and a denied THIRD TOOL are both kept off the write bucket.
                    # A non-object entry records no name, which is the disclosed residual the
                    # write classifier attributes by the side-effect path alone.
                    #
                    # A NON-STRING tool_name (JSON null, a number) normalizes to that SAME
                    # empty sentinel — never to `str()`'s rendering of it. `str(None).lower()`
                    # is "none", a third value that is neither a recorded name nor "not
                    # recorded", so every classifier below would decline it and the entry
                    # would leave no signal at all: the run would then reach the trailing arm
                    # and positively assert the write was never attempted, about a run whose
                    # Write was recorded as refused. JSON null is the likeliest spelling of an
                    # unrecorded field in a shape this file records as not yet observed, so
                    # this is the wrong-type row of the external-format shape matrix, not a
                    # contrived input.
                    _tn = d.get("tool_name") if isinstance(d, dict) else None
                    tn = _tn.lower() if isinstance(_tn, str) else ""
                    denials.append({"text": json.dumps(d), "tool_name": tn})
            # `here`, not `inherited`: the envelope's own parent_tool_use_id must reach the
            # tool_use blocks nested under `message.content[]`, which is the whole point of
            # threading it. Dropping it here would leave every real record parent-less.
            #
            # `permission_denials` is EXCLUDED from the descent: its entries were harvested
            # above, and an entry that embeds the refused call (a `tool_use` block inside the
            # denial) would otherwise be walked into `tool_uses` and become indistinguishable
            # from a call the harness ALLOWED. That fails open toward "something was recorded"
            # — recorded_at_all, the two controls, and write_recorded could all be satisfied by
            # refusals alone, so the control facts the record calls the attributable
            # measurement would describe calls that never ran.
            for k, v in o.items():
                if k == "permission_denials":
                    continue
                walk(v, here)
        elif isinstance(o, list):
            for it in o:
                walk(it, inherited)

    walk(parsed)
    return denials, tool_uses, shape_notes


def compute(denials, tool_uses, note_top, side_path, side_present, upstream_empty,
            tier_note="", records_note="", side_state="absent", side_note=""):
    """Return a dict of every field the table reports plus the final verdict/reason.

    All marker matches are case-insensitive so a decorated recording still reads present.
    `side_path` is the tier's side-effect FILENAME (`subwrite-<tier>.txt`, extension
    included) used as the write marker — the substring match depends on the suffix."""
    write_marker = side_path.lower()

    # ── Denial classification, ONE ENTRY AT A TIME.
    # Joining the entries and substring-testing the concatenation is what made both denial
    # signals fire on the wrong run: a marker anywhere in ANY entry answered for every
    # entry, so a third tool's refusal that merely quoted the payload published DENIED, and
    # the bare token "agent" (a substring of "subagent_type", "agent_id", and of ordinary
    # prose) made every such list read as a refused dispatch. Each entry is therefore
    # classified on its OWN recorded text and its OWN tool_name, into exactly one bucket.
    #
    # A dispatch refusal is decided first FOR AN ENTRY (not for the run): its recorded
    # tool_input echoes the subagent prompt verbatim — naming `subwrite-<tier>.txt` and
    # SUBWRITE_PAYLOAD — so classifying it as the write denial would publish a permission
    # finding about a permission that was never attempted. With no tool_name recorded (the
    # per-entry shape is not yet recorded) the fingerprint is the quoted `"subagent_type"`
    # key or the `general-purpose` type name, both anchored forms rather than bare tokens.
    def _is_dispatch_denial(d):
        if d["tool_name"] in DISPATCH_TOOL_NAMES:
            return True
        if d["tool_name"]:
            return False  # a denial naming some OTHER tool is not a dispatch refusal
        t = d["text"].lower()
        return '"subagent_type"' in t or "general-purpose" in t

    # A write denial: an entry whose own tool_name is Write and which names the tier's
    # side-effect FILENAME. The filename is required and the PAYLOAD marker alone is not
    # enough — this is the exact twin of the guard the permit side already carries: a Write
    # of that payload to some OTHER path is a write the probe never asked about, so
    # reporting its denial as "a permission_denials entry for the subagent's Write into
    # subwrite-<tier>.txt" would be a positively-stated permission finding about a
    # permission that was never attempted for that target — the one outcome the
    # three-outcome contract forbids. On the review tier the shape is live: `Write` is
    # granted only as `Write(.prflow/tmp/**)`, so any subagent deviation produces exactly
    # such an entry. It is not silently dropped either — `_is_foreign_write_denial` below
    # routes it to its OWN named `unestablished` arm, so the run does not instead assert
    # "the subagent ran but did not attempt the write" about a write it demonstrably tried.
    # An entry naming any OTHER tool is NOT the write denial, however its text quotes the
    # markers. Residual, disclosed: an entry recording no tool_name at
    # all is attributed by the side-effect path alone, because no narrower channel exists.
    def _is_write_denial(d):
        t = d["text"].lower()
        if d["tool_name"] == "write":
            return write_marker in t
        if d["tool_name"]:
            return False
        return write_marker in t

    # A denied `Write` carrying the probe's payload but NOT the tier's side-effect filename:
    # a real write attempt, refused, to a path the probe never asked about. Its own arm
    # rather than the "neither" bucket, so the emitted reason describes what the file shows.
    # `tool_name` "" is accepted alongside "write" for the SAME disclosed reason the write
    # classifier accepts it: the per-entry denial shape is not recorded, so an entry may omit
    # the field entirely. Requiring `== "write"` here left a payload-carrying, name-less
    # denial in no bucket at all, and the run then asserted "the subagent ran but did not
    # attempt the write" about a write it demonstrably tried.
    def _is_foreign_write_denial(d):
        return d["tool_name"] in ("write", "") and _PAYLOAD_L in d["text"].lower()

    # A denied `Write` naming NEITHER the side-effect filename NOR the payload — e.g.
    # `{"tool_name": "Write", "tool_input": {}}`, or a message-only entry. Reached only after
    # the three classifiers above have all declined, so by construction it is a `Write`
    # refusal whose recorded text establishes nothing about its target. Without this bucket
    # the entry was silently dropped and the verdict fell through to the trailing arm, which
    # positively asserts "the subagent ran but did not attempt the write" about a run in
    # which a Write WAS attempted and refused — the arm-misattribution class
    # describe-denial-count.sh was extracted to prevent, on the very entry shape this file
    # elsewhere records as not yet observed. It gets its own named `unestablished` reason
    # instead: unknown is not zero, and it is emphatically not "no write was attempted".
    #
    # This is the RESIDUAL bucket, so it accepts a name-less entry (`tool_name` "") alongside
    # `"write"` — the same acceptance `_is_write_denial` and `_is_foreign_write_denial` already
    # make, and for the same disclosed reason: the per-entry denial shape is not recorded, so
    # an entry may omit the field entirely. Requiring `== "write"` here left the shape the
    # helper considers MOST likely in production — a name-less entry naming neither marker,
    # e.g. `{"message": "Permission to use the tool was denied", "rule": "Write"}` — in no
    # bucket at all, defeating this very arm on its most probable input. Because the three
    # narrower classifiers have already declined, accepting "" here cannot steal an entry from
    # them; it only stops one falling through to the trailing arm's false claim.
    def _is_unclassified_write_denial(d):
        return d["tool_name"] in ("write", "")

    # One pass, one bucket per entry — never an identity/equality lookup back into a list,
    # which would misroute the second of two byte-identical entries.
    dispatch_denials = []
    write_denials = []
    foreign_write_denials = []
    unclassified_write_denials = []
    for _d in denials:
        if _is_dispatch_denial(_d):
            dispatch_denials.append(_d)
        elif _is_write_denial(_d):
            write_denials.append(_d)
        elif _is_foreign_write_denial(_d):
            foreign_write_denials.append(_d)
        elif _is_unclassified_write_denial(_d):
            unclassified_write_denials.append(_d)
    dispatch_denied = bool(dispatch_denials)
    write_denied = bool(write_denials)
    foreign_write_denied = bool(foreign_write_denials)
    unclassified_write_denied = bool(unclassified_write_denials)
    # NOTE — no cause discriminator. An earlier revision split the refusal reason into
    # "unknown subagent type" vs "dispatch head not granted" by scanning the denial text for
    # `"subagent_type"` / `general-purpose`. That cannot separate the two causes: a refusal of
    # an UNGRANTED DISPATCH HEAD still records the attempted tool_input, which necessarily
    # carries `"subagent_type": "general-purpose"` — so every head refusal read as "unknown
    # subagent type" and the other arm was unreachable in production. Worse, the scan joined
    # every dispatch entry, so one entry's tokens answered for another — the same
    # concatenation class this helper eliminated elsewhere. The recorded per-entry denial
    # shape is not yet established, so no field distinguishes the causes: report ONE honest
    # refusal reason rather than a confidently-wrong cause (unknown is not zero).

    # Ids of the recorded dispatches (Task/Agent tool_use entries). A subagent call is
    # chain-attributable when its parent_tool_use_id is one of these.
    dispatch_ids = {
        tu["id"] for tu in tool_uses if tu["name"] in DISPATCH_TOOL_NAMES and tu["id"]
    }
    dispatch_recorded = any(tu["name"] in DISPATCH_TOOL_NAMES for tu in tool_uses)

    # Does THIS file surface parent chains at all? A top-level (orchestrator-issued) call
    # carries no parent_tool_use_id, so when some entry does carry one the harness
    # demonstrably records the field and a parent-less marker call is the orchestrator's —
    # excluded, because this job's orchestrator is granted heads whose inputs may quote the
    # marker vocabulary while reporting on the dispatch. When NO entry carries a parent the
    # schema does not surface chains at all; excluding parent-less calls would then collapse
    # the distinct "recorded but not chain-attributable" third world onto "no dispatchee
    # action recorded", so they are retained and that arm's reason discloses the ambiguity.
    chains_are_recorded = any(tu["parent"] is not None for tu in tool_uses)

    # Subagent-issued calls: a probe marker in a tool_use whose OWN name is not the
    # dispatch tool (the dispatch's own input quotes the marker vocabulary — counting it
    # would credit a call that never happened).
    def is_subagent_marker(tu):
        if tu["name"] in DISPATCH_TOOL_NAMES:
            return False
        if chains_are_recorded and tu["parent"] is None:
            return False
        t = tu["text_lower"]
        return (
            _CONTROL_BEFORE_L in t
            or _CONTROL_AFTER_L in t
            or write_marker in t
            or _PAYLOAD_L in t
        )

    subagent_calls = [tu for tu in tool_uses if is_subagent_marker(tu)]
    recorded_at_all = bool(subagent_calls)
    # `x in dispatch_ids` is already False for every element when the set is empty, so an
    # explicit `and bool(dispatch_ids)` conjunct would guard nothing — a True `any(...)`
    # here already proves a recorded dispatch was chained to.
    chain_attributable = any(
        (tu["parent"] in dispatch_ids) for tu in subagent_calls if tu["parent"] is not None
    )

    control_before = any(_CONTROL_BEFORE_L in tu["text_lower"] for tu in subagent_calls)
    control_after = any(_CONTROL_AFTER_L in tu["text_lower"] for tu in subagent_calls)

    # The Write tool_use targeting the tier's side-effect file. BOTH conjuncts are required
    # and each fails CLOSED on its own:
    #   the recorded tool's OWN name must be `write` — naming the file is not issuing the
    #   write, and any granted head can name it, so a subagent reading its work back
    #   (`Bash: cat .prflow/tmp/subwrite-*.txt`) with a leftover file on disk would
    #   otherwise publish PERMITTED for a run in which no Write was ever issued;
    #   and the recorded input must name the tier's side-effect FILENAME — the payload
    #   marker alone is not enough, because a Write of that payload to some OTHER path is a
    #   write that landed somewhere the probe never asked about, and reporting it as
    #   "a Write targeting subwrite-<tier>.txt" would be a false statement about the run.
    # A Write whose input carries the payload but not the filename therefore routes to an
    # `unestablished` arm rather than to a PERMITTED the emitted reason misdescribes.
    write_calls = [
        tu for tu in tool_uses if tu["name"] == "write" and write_marker in tu["text_lower"]
    ]
    write_recorded = bool(write_calls)
    # The chaining pair is retained, not just its boolean: the AC requires a PERMITTED to
    # CITE the chain that ties the Write to this job's own dispatch, and a bare yes/no cites
    # nothing a reader could re-verify against the execution file.
    write_chain_pair = next(
        (
            (tu["id"], tu["parent"])
            for tu in write_calls
            if tu["parent"] is not None and tu["parent"] in dispatch_ids
        ),
        None,
    )
    write_chain_ok = write_chain_pair is not None
    # A parent-less Write naming the side-effect file is the ORCHESTRATOR's, and its presence
    # falsifies the no-orchestrator-write premise every DENIED attribution rests on. Only
    # meaningful where the file records chains at all — otherwise a genuine subagent Write is
    # parent-less too and this would fire on the very run it must not.
    orchestrator_write_recorded = chains_are_recorded and any(
        tu["parent"] is None for tu in write_calls
    )

    # ── Verdict, degraded arms FIRST (a measurement that did not run must never read as
    # one that came back negative — the unknown-is-not-zero collapse this ordering stops).
    if upstream_empty:
        verdict, reason = "unestablished", (
            "the consumed upstream allowlist output was empty, absent or unresolved — the "
            "upstream tier job did not complete (fail/cancel/skip), or the step that "
            "composes its literal did not — so the engine step never ran and nothing was "
            "measured"
        )
    elif tier_note:
        # Its OWN arm, never folded into note_top's "could not be read cleanly" prefix: the
        # execution file may be perfectly readable and the TIER the thing that is wrong, and
        # a reason that blames the file is a positively-stated misdiagnosis — the
        # arm-misattribution class describe-denial-count.sh was extracted to prevent.
        verdict, reason = "unestablished", tier_note
    elif note_top:
        verdict, reason = "unestablished", (
            "the execution file could not be read cleanly: " + note_top
        )
    elif records_note:
        # Its OWN arm, and ahead of every signal-bearing arm below. A file that parses
        # cleanly into an EMPTY container (`[]` / `{}`) carries no records at all, and both
        # probe jobs run this verdict step under `if: always()` — so a claude-code-action
        # step failing mid-session is exactly the path that produces one. Without this arm
        # it fell through to "no dispatch was recorded and no subagent-issued call appeared
        # — the dispatch never occurred", a positively-stated claim about a dispatch, from a
        # file that is not evidence about the dispatch at all (the reason-misattribution
        # class describe-denial-count.sh was extracted to prevent). The reason states the
        # observable — the file holds no records — and NOT a cause: this helper reads no
        # engine-error field, so naming an engine failure would be an unmeasured claim.
        verdict, reason = "unestablished", records_note
    elif write_denied and not dispatch_recorded:
        # DENIED's attribution rests entirely on "the dispatched subagent is the only
        # possible author of a Write". With NO dispatch recorded in this file there is no
        # dispatchee to attribute one to, so publishing DENIED would be a permission finding
        # about a run that demonstrably never attempted the permission — the one outcome the
        # docstring's three-outcome contract forbids. The PERMITTED side has always carried
        # the corresponding guard (it requires write_chain_ok); this closes the asymmetry.
        verdict, reason = "unestablished", (
            f"a permission_denials entry naming the Write into {side_path} was recorded, but NO "
            "dispatch appears in this file — with no dispatchee to attribute it to, the "
            "denial cannot be read as the subagent's"
        )
    elif write_denied and orchestrator_write_recorded:
        # The premise is falsified by the file itself: a parent-less (orchestrator-issued)
        # Write naming the same side-effect file is recorded, so the denial has more than one
        # possible author and the no-orchestrator-write attribution does not hold.
        verdict, reason = "unestablished", (
            f"a permission_denials entry naming the Write into {side_path} was recorded, but a "
            "parent-less (orchestrator-issued) Write naming the same file was recorded too — "
            "the no-orchestrator-write premise the denial attribution rests on is falsified, "
            "so the denial is not attributable to the dispatched subagent"
        )
    elif write_denied:
        # Checked BEFORE the dispatch-refused arm, and safely so: the dispatch-echo hazard
        # is handled per ENTRY above (an entry classified as a dispatch refusal never lands
        # in write_denials), so reaching this arm means some entry is attributable to the
        # write itself. Ordering it first is what lets a multi-entry list holding both a
        # dispatch refusal and a real Write denial resolve DENIED instead of reporting
        # `unestablished` with a positively-stated claim that no write was attempted.
        # The orchestrator-write clause is stated ONLY where this file records parent chains
        # at all. Without chains `orchestrator_write_recorded` is False for a reason of
        # IGNORANCE — a parent-less Write cannot be told from a subagent's — so asserting
        # "no orchestrator-issued Write names that file" would publish an unknown as a
        # measured zero, the very collapse the surrounding arms exist to prevent.
        verdict, reason = "DENIED", (
            "a permission_denials entry for the subagent's Write into {} was recorded, a "
            "dispatch is recorded in this file, and {}; attribution rests on this job's "
            "prompt containing no orchestrator write, so the denial has exactly one "
            "possible author".format(
                side_path,
                "no orchestrator-issued Write names that file"
                if chains_are_recorded
                else "this file records no parent_tool_use_id at all, so whether an "
                     "orchestrator-issued Write names that file is unestablished rather "
                     "than ruled out",
            )
        )
    elif dispatch_denied and not dispatch_recorded:
        # Gated on `not dispatch_recorded`: a refusal co-recorded with a dispatch that DID
        # happen (the model retried with a different subagent_type) must not preempt a
        # successful measurement — the arms below would otherwise be unreachable and the
        # emitted reason would assert "no write permission was even attempted" beside a table
        # reporting the write recorded, chain-attributable and corroborated on disk.
        # The cause is deliberately NOT named (see the discriminator note above).
        verdict, reason = "unestablished", (
            "a dispatch was refused by the matcher and no dispatch was recorded in this "
            "file, so no subagent existed to attempt the write; the refusal's recorded cause "
            "is not established by the entry shape, and no denial entry is attributable to "
            "the write"
        )
    elif write_recorded and write_chain_ok and side_present:
        # The chain is CITED by its ids, not merely asserted: the AC requires a PERMITTED to
        # name the parent_tool_use_id chain tying the Write to this job's own dispatch, and
        # a reader can re-verify the two ids against the execution file.
        verdict, reason = "PERMITTED", (
            f"a subagent Write tool_use targeting {side_path} was recorded, its parent chains to a "
            f"dispatch recorded in this file (tool_use id '{write_chain_pair[0]}' -> parent_tool_use_id '{write_chain_pair[1]}'), "
            "and the on-disk side-effect file carries the probe's payload marker"
        )
    elif not dispatch_recorded and not recorded_at_all:
        verdict, reason = "unestablished", (
            "no dispatch was recorded and no subagent-issued call appeared — the dispatch "
            "never occurred"
        )
    elif not recorded_at_all:
        verdict, reason = "unestablished", (
            "a dispatch was recorded but no subagent-issued call appeared at all — the "
            "execution file does not surface dispatchee actions, so nothing about the write "
            "can be concluded"
        )
    elif not chain_attributable:
        verdict, reason = "unestablished", (
            "marker-carrying calls were recorded but carried no parent chain to a dispatch "
            "in this file — a distinct third schema world: dispatchee actions recorded but "
            "not chain-attributable, so the attribution channel does not exist"
            + (
                ""
                if chains_are_recorded
                else " (and because no entry in this file carries a parent_tool_use_id at "
                "all, these calls cannot be distinguished from orchestrator-issued ones)"
            )
        )
    elif write_recorded and not write_chain_ok:
        verdict, reason = "unestablished", (
            "a Write was recorded but its parent chain does not tie it to this job's "
            "dispatch, so it cannot be attributed to the dispatched subagent"
        )
    elif foreign_write_denied:
        # Placed exactly where the arm below would otherwise assert "the write was neither
        # recorded nor denied — the subagent ran but did not attempt the write", which is
        # false about this run: a Write WAS attempted and refused, just to a path the probe
        # never asked about. The verdict stays `unestablished` (nothing is established about
        # the write into side_path), but the reason describes what the file actually shows.
        verdict, reason = "unestablished", (
            "a permission_denials entry for a `Write` carrying the probe's payload was "
            f"recorded, but it does not name {side_path} — the refused write targeted some OTHER "
            "path, so it establishes nothing about the write this probe measures and is "
            "not reported as its denial"
        )
    elif unclassified_write_denied:
        # Same placement rationale as the arm above, for the entry shape that names neither
        # the side-effect filename nor the payload: a Write WAS refused, so the arm below
        # would state a falsehood about this run. The reason reports exactly what the entry
        # establishes — that a Write refusal was recorded and that its text does not say
        # what was refused — and never a permission finding about the probe's target.
        # The wording says "a Write refusal" rather than "recording tool_name `Write`":
        # this residual bucket also accepts an entry recording NO tool_name, so naming the
        # field would be false about exactly the shape the helper considers most likely.
        verdict, reason = "unestablished", (
            "a permission_denials entry was recorded that the three narrower classifiers "
            f"all declined — it names neither {side_path} nor the probe's payload marker, and it is "
            "not attributable to the dispatch — so the per-entry denial shape leaves it "
            "neither attributable to nor ruled out of the write this probe measures"
        )
    elif not write_recorded:
        verdict, reason = "unestablished", (
            "a chain-attributable subagent call was recorded but the write was neither "
            "recorded nor denied — the subagent ran but did not attempt the write"
        )
    else:  # write_recorded and write_chain_ok and not side_present
        # THREE distinct states reach here, and the reason names which one. Hardcoding
        # "absent" made the prose — the half a human actually reads — positively assert the
        # file was missing on a run whose table said `wrong-content`, so the record
        # contradicted itself. Each state gets its own sentence.
        if side_state == "wrong-content":
            _why = (
                "the on-disk side-effect file is present but does not carry the probe's "
                "payload marker — a truncated, empty, or foreign-authored file is not "
                "corroboration that the subagent's write landed"
            )
        elif side_state == "unreadable":
            _why = "the on-disk side-effect file is present but could not be read"
        else:
            _why = "the on-disk side-effect file is absent"
        verdict, reason = "unestablished", (
            f"a chain-attributable Write tool_use was recorded but {_why}, so the permit is "
            "uncorroborated"
        )

    # A RECORDED dispatch wins over a co-recorded refusal: the table must not report
    # `denied` about a dispatch that demonstrably happened (the retry case).
    dispatch_outcome = (
        "recorded" if dispatch_recorded else ("denied" if dispatch_denied else "absent")
    )
    write_outcome = "denied" if write_denied else ("recorded" if write_recorded else "absent")

    # A typo in any verdict arm above would otherwise ship an invalid string into the
    # machine-consumed table. An `assert` is not the instrument: `python3 -O` strips it, and
    # were it ever to fire it would raise through main() against the "Always exits 0"
    # contract. An ordinary branch is always live and fails closed onto `unestablished`.
    if verdict not in _VERDICTS:
        sys.stderr.write(
            f"subagent-write-probe-verdict: internal error — verdict {verdict!r} is outside the "
            f"closed vocabulary {list(_VERDICTS)}; reporting unestablished\n"
        )
        verdict, reason = "unestablished", (
            "the verdict derivation produced a value outside the closed three-outcome "
            "vocabulary, so nothing about the write is established (see stderr)"
        )
    return {
        "verdict": verdict,
        "reason": reason,
        "dispatch_outcome": dispatch_outcome,
        "recorded_at_all": recorded_at_all,
        "chain_attributable": chain_attributable,
        "control_before": control_before,
        "control_after": control_after,
        "write_outcome": write_outcome,
        "write_chain_ok": write_chain_ok,
        "side_present": side_present,
        "denials": denials,
    }


def render(exec_file, tier, side_effect_file, upstream_empty, params):
    tier_note = ""
    notes = []
    if tier not in VALID_TIERS:
        # A tier outside the closed set is not coerced silently: the write marker is derived
        # FROM the tier, so `unknown` makes the helper look for `subwrite-unknown.txt`, a
        # file no probe job writes — every write-side signal would then read absent and the
        # run would render a confident-looking negative about a marker that never existed.
        tier_note = (
            "--tier value '{}' is not one of {}, so the tier-derived write marker names no "
            "side-effect file any probe job writes and nothing measurable was looked for".format(tier, "/".join(VALID_TIERS))
        )
        sys.stderr.write(
            f"subagent-write-probe-verdict: {tier_note}; reporting unestablished\n"
        )
        tier = "unknown"
    # Kept as `"…%s…" % tier`, not an f-string: run.sh's #858 coupling check greps this exact shape.
    side_path = "subwrite-%s.txt" % tier  # noqa: UP031
    # VERIFY THE OUTCOME, NOT THE PRECONDITION. `isfile` proves a path exists; it proves
    # nothing about whether the subagent's write LANDED — which is the corroboration the
    # PERMITTED reason rests on. A zero-byte file, a truncated write, or a file authored by
    # anything else all satisfy mere existence, so the one place this helper accepts an
    # outcome on trust would be the place a false PERMITTED enters. The prompt fixes the
    # file's content, so the payload marker is checkable: require it. A present-but-wrong
    # content file is NOT corroboration and is NOT silently absent either — it gets its own
    # named reason below (`side_effect_state`), because unknown is not zero.
    side_state = "absent"
    side_note = ""
    if side_effect_file and os.path.isfile(side_effect_file):
        try:
            with open(side_effect_file, encoding="utf-8", errors="replace") as _fh:
                side_state = "corroborated" if PAYLOAD.lower() in _fh.read().lower() else "wrong-content"
        except OSError as exc:
            # Present but unreadable: an established file whose content could not be checked
            # is unknown, never corroboration — and never silently "absent" either.
            #
            # This note does NOT go into `notes`/`note_top`. note_top is consumed by the arm
            # that prefixes "the execution file could not be read cleanly:", so routing a
            # SIDE-EFFECT read failure there blames the wrong file — and, because note_top is
            # tested ahead of every signal-bearing arm, it would also mask a genuinely
            # measurable DENIED. It travels on its own channel instead.
            side_state = "unreadable"
            side_note = (
                f"the on-disk side-effect file {side_effect_file} is present but could not be read ({exc}), so "
                "its content could not corroborate the write"
            )
    side_present = side_state == "corroborated"

    parsed, parse_note = parse_execution_file(exec_file)
    # The zero-byte sentinel is neither a read failure nor a parsed container: normalize it
    # to "no parse note, empty container" so the single records_note derivation below owns
    # both no-records shapes (zero-byte file and cleanly-parsed empty container).
    file_was_empty = parse_note is RECORDS_EMPTY
    if file_was_empty:
        parse_note = ""
    if parse_note:
        notes.append(parse_note)
    # A cleanly-parsed but EMPTY container is not a read failure (nothing to append to
    # `notes`, whose arm blames the file's readability) and not evidence about the dispatch
    # either — it gets its own reason in compute(). Only meaningful when the parse itself
    # succeeded: on a failure path parse_execution_file already returns [] with a note.
    records_note = ""
    if file_was_empty:
        records_note = (
            "the execution file read cleanly but holds no records at all (it is empty) — "
            "the session recorded nothing, so neither the dispatch nor the write is "
            "established; this helper reads no engine-error field, so the cause is not named"
        )
    elif not parse_note and isinstance(parsed, (list, dict)) and len(parsed) == 0:
        records_note = (
            "the execution file parsed cleanly but holds no records at all (an empty %s) — "
            "the session recorded nothing, so neither the dispatch nor the write is "
            "established; this helper reads no engine-error field, so the cause is not "
            "named" % ("array" if isinstance(parsed, list) else "object")
        )
    try:
        denials, tool_uses, shape_notes = collect(parsed)
    except RecursionError:
        denials, tool_uses, shape_notes = [], [], []
        notes.append("execution file nested too deeply to walk")
    notes.extend(shape_notes)
    # Any non-empty note forces unestablished in compute()'s second arm — an execution file
    # this helper could not read cleanly, in whole or in part, is unknown, never zero.
    note_top = "; ".join(notes)

    r = compute(
        denials, tool_uses, note_top, side_path, side_present, upstream_empty, tier_note,
        records_note, side_state, side_note,
    )

    out = []
    out.append(f"## Dispatched-subagent Write probe — {tier} tier (issue #858)")
    out.append("")
    out.append("**Verdict: `{}`**".format(r["verdict"]))
    out.append("")
    out.append(r["reason"] + ".")
    out.append("")
    out.append(
        "Deterministic verdict from the execution file's recorded `tool_use` inputs, their "
        "`parent_tool_use_id`, and `permission_denials`, corroborated by the on-disk "
        "side-effect file this run actually stat'ed: `%s`. The model's prose is never the "
        "measurement." % (side_effect_file or "(none supplied)")
    )
    out.append("")
    out.append("> [!IMPORTANT]")
    out.append(f"> {VERSION_CAVEAT}")
    out.append("")
    # The two control facts, reported INDEPENDENTLY (never conjoined), plus dispatch and
    # write as separate fields so a reader can tell a denied write from an absent dispatch.
    out.append("| Field | Value |")
    out.append("|-------|-------|")
    out.append(f"| tier | `{tier}` |")
    out.append("| verdict | **{}** |".format(r["verdict"]))
    out.append("| dispatch_outcome | {} |".format(r["dispatch_outcome"]))
    out.append("| recorded_at_all | %s |" % ("yes" if r["recorded_at_all"] else "no"))
    out.append("| chain_attributable | %s |" % ("yes" if r["chain_attributable"] else "no"))
    out.append("| control_before | %s |" % ("yes" if r["control_before"] else "no"))
    out.append("| control_after | %s |" % ("yes" if r["control_after"] else "no"))
    out.append("| write_outcome | {} |".format(r["write_outcome"]))
    out.append("| write_chain_ok | %s |" % ("yes" if r["write_chain_ok"] else "no"))
    # Four-valued, not a yes/no: `absent` (no file), `corroborated` (present AND carrying the
    # payload), `wrong-content` (present but NOT carrying it — an established negative, never
    # laundered into "absent"), `unreadable` (present, content unestablished). Collapsing the
    # last three onto "no" would report an established wrong-content file and an unmeasurable
    # one as the same thing as no file at all.
    out.append(f"| side_effect_state | {side_state} |")
    out.append("")
    # Every permission-decision parameter travels with the verdict — the resolved literal
    # verbatim, not a prose summary of the composition.
    for label, key in (
        ("permission_mode", "permission_mode"),
        ("model", "model"),
        ("effort", "effort"),
        ("ref", "ref"),
        ("head_commit", "head_commit"),
    ):
        val = params.get(key)
        if val:
            out.append(f"**{label}:** `{val}`")
            out.append("")
    allowlist = params.get("allowlist")
    if allowlist:
        out.append("**Resolved `--allowed-tools` literal (the measured condition, verbatim):**")
        out.append("")
        out.append("```")
        out.append(allowlist)
        out.append("```")
        out.append("")
    # The observed denial-entry shape — the read that upgrades the DENIED side from
    # by-construction to measured.
    out.append(f"### Observed `permission_denials` entries ({len(r['denials'])})")
    out.append("")
    if r["denials"]:
        out.append("```")
        for d in r["denials"]:
            out.append(d["text"][:400])
        out.append("```")
    else:
        out.append("_No permission_denials entries found in the execution file._")
    return "\n".join(out)


def _force_utf8_streams():
    """Force stdout/stderr to UTF-8. Never call this at import: doing so mutates the
    streams of any process that imports this module for tests. Tolerates a stream that
    has no usable `reconfigure` (issue #1762)."""
    for _stream in (sys.stdout, sys.stderr):
        try:
            _stream.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError, OSError):
            pass


def main():
    _force_utf8_streams()
    exec_file = ""
    tier = ""
    side_effect_file = ""
    upstream_empty = False
    params = {}
    args = sys.argv[1:]
    i = 0
    flag_keys = {
        "--tier": "tier",
        "--side-effect-file": "side_effect_file",
        "--allowlist": "allowlist",
        "--permission-mode": "permission_mode",
        "--model": "model",
        "--effort": "effort",
        "--ref": "ref",
        "--head-commit": "head_commit",
    }
    positional = []
    while i < len(args):
        a = args[i]
        if a == "--upstream-tools-empty":
            upstream_empty = True
            i += 1
        elif a in flag_keys:
            # A value-taking flag whose value is missing must not silently swallow the next
            # FLAG as data: `--tier --allowlist X` would otherwise bind tier="--allowlist"
            # and drop the allowlist entirely from the record that is meant to carry "the
            # measured condition, verbatim". Both shapes get a specific breadcrumb and an
            # empty value; an empty --tier then routes to unestablished via render().
            nxt = args[i + 1] if i + 1 < len(args) else None
            if nxt is None or nxt in flag_keys or nxt == "--upstream-tools-empty":
                sys.stderr.write(
                    "subagent-write-probe-verdict: {} was given no value ({}); treating it "
                    "as empty\n".format(a, "end of arguments" if nxt is None else f"next argument is {nxt}")
                )
                val = ""
                consumed = 1
            else:
                val = nxt
                consumed = 2
            if a == "--tier":
                tier = val
            elif a == "--side-effect-file":
                side_effect_file = val
            else:
                params[flag_keys[a]] = val
            i += consumed
        elif a.startswith("--"):
            # An UNRECOGNISED flag is never silently dropped. A workflow typo such as
            # `--side-effect-fil <path>` would otherwise leave side_effect_file empty and the
            # run would render `unestablished` with the reason "the on-disk side-effect file
            # is absent" about a file that is present — a positively-stated falsehood about
            # the run. The same swallow would drop --allowlist/--model from a record whose
            # whole purpose is that every permission-decision parameter travels with the
            # verdict. Breadcrumb and continue: the always-exit-0 contract still holds, and
            # the operator can see which flag the helper did not understand.
            sys.stderr.write(
                "subagent-write-probe-verdict: unrecognised argument {!r} was ignored "
                "(recognised flags: {}, --upstream-tools-empty)\n".format(a, ", ".join(sorted(flag_keys)))
            )
            i += 1
        else:
            positional.append(a)
            i += 1
    if positional:
        exec_file = positional[0]
        if len(positional) > 1:
            # Only the FIRST positional is the execution file. Extra positionals are usually
            # a value that lost its flag; dropping them silently hides that.
            sys.stderr.write(
                f"subagent-write-probe-verdict: {len(positional) - 1} extra positional argument(s) after the "
                f"execution file were ignored: {', '.join(repr(p) for p in positional[1:])}\n"
            )
    if not exec_file:
        exec_file = os.environ.get("EXECUTION_FILE", "") or ""

    # The "Always exits 0" contract is closed HERE, at the boundary, rather than by every
    # internal path individually: parse_execution_file catches only OSError, so a
    # MemoryError on an oversized file or a RecursionError from json.loads on a deeply
    # nested document would otherwise propagate out and the job would die with a traceback
    # and NO verdict table — the one outcome the three-outcome design says cannot happen.
    try:
        table = render(exec_file, tier, side_effect_file, upstream_empty, params)
    except Exception as e:
        sys.stderr.write(
            f"subagent-write-probe-verdict: unexpected {e.__class__.__name__} while deriving the verdict; "
            "reporting unestablished\n"
        )
        table = (
            "## Dispatched-subagent Write probe (issue #858)\n\n"
            "**Verdict: `unestablished`**\n\n"
            f"the verdict could not be derived ({e.__class__.__name__} while reading or walking the execution "
            "file); nothing about the write is established (see stderr).\n"
        )
    print(table)
    summary = os.environ.get("GITHUB_STEP_SUMMARY", "")
    if summary:
        # Best-effort side-output: an unwritable GITHUB_STEP_SUMMARY must not raise through
        # main() and break the "Always exits 0" contract — the verdict already went to
        # stdout, the authoritative surface.
        try:
            with open(summary, "a", encoding="utf-8") as fh:
                fh.write(table + "\n")
        except OSError as e:
            sys.stderr.write(
                "subagent-write-probe-verdict: could not append to GITHUB_STEP_SUMMARY "
                f"({e.__class__.__name__}); verdict is on stdout\n"
            )
    return 0


if __name__ == "__main__":
    sys.exit(main())
