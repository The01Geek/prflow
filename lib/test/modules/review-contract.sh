# SPDX-FileCopyrightText: 2026 Daniel Radman
# SPDX-License-Identifier: MIT
# shellcheck shell=bash
# Sourceable review-contract contract module (issue #1934).
# Contract: the caller sets LIB and RESULTS_FILE, defines assert_eq, and sources
# lib/test/module-harness.sh first. The module owns its private fixture root and
# cleanup; it never invokes the runner or the full-suite boundary. Modules may not
# self-skip. The inventory in review-contract.inventory.md maps the extracted coverage to its
# former lib/test/run.sh locations.
# Coverage (extracted from lib/test/run.sh, issue #1934):
#   skills/review render-time probe-verdict helpers: scripts/placeholder-probe-verdict.py (#1264) and scripts/skill-body-load-probe-verdict.py (#1618/#1897), driven inline as self-contained executable probe blocks.
#
# The trap below relies on the sourcing contract: both callers (module-harness.sh and
# run-module.sh) source this module inside a ( ... ) subshell, so the EXIT trap fires
# at subshell exit and cannot clobber the runner's own EXIT handling.
_m1934_root="$(mktemp -d "${TMPDIR:-/tmp}/devflow-review-contract.XXXXXX")" || {
  printf 'could not allocate review-contract fixture root\n' >&2
  return 1
}
_m1934_cleanup() { rm -rf "$_m1934_root"; }
trap _m1934_cleanup EXIT
# Redirect every `mktemp`/`mktemp -d` the extracted blocks allocate under the module's
# owned root, so all block fixtures are cleaned by the single trap above.
TMPDIR="$_m1934_root"
export TMPDIR

# ────────────────────────────────────────────────────────────────────────────
echo "#1264 render-time placeholder probe verdict helper"
# ────────────────────────────────────────────────────────────────────────────
# scripts/placeholder-probe-verdict.py is a branch-selecting core: its verdict ROUTES
# issue #1264's design (a negative limb sends the work to workflow-side composition
# instead of the placeholder mechanism), so every arm is driven here rather than left to
# a paid probe run to exercise. Same treatment, and same rationale, as the #858/#874/#812
# probe-verdict siblings: unmodularized, no focused_test, driven inline from run.sh.
PPV="$LIB/../scripts/placeholder-probe-verdict.py"
PPV_TMP="$(mktemp -d)"
ppv_build() {  # $1 scenario -> writes $PPV_TMP/exec.jsonl; rc 0 AND non-empty on success
  python3 - "$PPV_TMP/exec.jsonl" "$1" <<'PY_PPV'
import json, sys
out, scen = sys.argv[1], sys.argv[2]
BEFORE = "PHPROBE_SKILL_REACHED"
AFTER = "PHPROBE_CONTROL_AFTER"
def tu(cmd):
    return {"type": "tool_use", "name": "Bash", "input": {"command": cmd}}
def echo(payload):
    return tu("printf '%s\\n' '" + payload + "'")
controls = [echo(BEFORE), echo(AFTER)]
# The echo-back the agent is instructed to produce, one shape per scenario.
shapes = {
    "visible":      [echo("PHPROBE_SAW PHPROBE_ENV DEVFLOW_PHPROBE_SENTINEL_1264")],
    "unset":        [echo("PHPROBE_SAW PHPROBE_ENV UNSET")],
    # The placeholder survived verbatim: the echo-back carries the raw backtick-bang and
    # the script path, neither of which can appear in the script's own stdout.
    "unexecuted":   [echo("PHPROBE_SAW !`.github/probe-plugin/phprobe-read-env.sh`")],
    "line_absent":  [echo("PHPROBE_LINE_A_ABSENT")],
    "no_marker":    [],
    # A marker-shaped entry with NO SAW prefix: not the measurement, so it must not be
    # read as a report. Both readers are scoped to the SAW token for exactly this reason.
    "template_only": [tu("printf 'PHPROBE_ENV %s\\n' \"$DEVFLOW_PROMPT_EXTENSION_ROOT\"")],
    # A real sentinel report PLUS an unrelated command mentioning the script path. The
    # unexecuted-form test is scoped to the SAW echo-back, so this must stay
    # SUBSTITUTED_ENV_VISIBLE rather than flipping to NOT_SUBSTITUTED.
    "incidental":   [echo("PHPROBE_SAW PHPROBE_ENV DEVFLOW_PHPROBE_SENTINEL_1264"),
                     tu("ls .github/probe-plugin/phprobe-read-env.sh")],
}
if scen == "no_controls":
    recs = shapes["visible"]
elif scen == "empty":
    recs = []
elif scen in shapes:
    recs = [controls[0]] + shapes[scen] + [controls[1]]
elif scen in ("unparseable", "partial_corrupt"):
    recs = [controls[0]] + shapes["visible"] + [controls[1]]
else:
    raise SystemExit("unrecognised scenario: %s" % scen)
with open(out, "w", encoding="utf-8") as fh:
    if scen == "unparseable":
        fh.write("{ not json at all\n")
    else:
        for r in recs:
            fh.write(json.dumps(r) + "\n")
        if scen == "partial_corrupt":
            fh.write("{ this line is not valid json\n")
        if scen == "empty":
            # A file that PARSES cleanly but holds no tool_use records — distinct from
            # unparseable, and it must reach the no-tool_uses arm rather than the parse arm.
            fh.write(json.dumps({"type": "system", "note": "no tool uses here"}) + "\n")
PY_PPV
  _ppv_rc=$?
  [ "$_ppv_rc" -eq 0 ] && [ -s "$PPV_TMP/exec.jsonl" ]
}
ppv() {  # $1 scenario -> the VERDICT token, or a build sentinel the extractor cannot forge
  if ! ppv_build "$1"; then printf 'FIXTURE_BUILD_FAILED'; return 0; fi
  local _out; _out="$(python3 "$PPV" "$PPV_TMP/exec.jsonl" 2>/dev/null)"
  # Pure parameter expansion (CLAUDE.md guard-class 2: no tr/sed/cut, whose absence
  # would fail OPEN and hand every assertion an empty string to compare).
  case "$_out" in
    *'VERDICT: '*) local _v="${_out#*'VERDICT: '}"; printf '%s' "${_v%%$'\n'*}" ;;
    *) printf 'NO_VERDICT' ;;
  esac
}
# NEGATIVE CONTROL — the assertion that makes the scenario sweep non-vacuous. An
# unrecognised scenario must FAIL the build rather than leave an empty fixture that the
# helper would read as unparseable, passing every arm below for the wrong reason.
assert_eq "#1264 placeholder: an unrecognised fixture scenario fails the build" "failed" \
  "$(ppv_build __no_such_scenario__ 2>/dev/null && echo built || echo failed)"
assert_eq "#1264 placeholder: a recognised fixture scenario still builds" "built" \
  "$(ppv_build visible 2>/dev/null && echo built || echo failed)"

# The three real measurements.
assert_eq "#1264 placeholder: substituted + sentinel observed -> SUBSTITUTED_ENV_VISIBLE" \
  "SUBSTITUTED_ENV_VISIBLE" "$(ppv visible)"
assert_eq "#1264 placeholder: substituted but env UNSET -> SUBSTITUTED_ENV_UNSET (limb b negative)" \
  "SUBSTITUTED_ENV_UNSET" "$(ppv unset)"
assert_eq "#1264 placeholder: unexecuted placeholder text -> NOT_SUBSTITUTED (limb a negative, routes the design)" \
  "NOT_SUBSTITUTED" "$(ppv unexecuted)"

# Every degraded arm resolves INCONCLUSIVE — never a confident negative. Collapsing
# "could not look" onto "does not substitute" would route issue #1264 away from its
# selected direction on no evidence, which is the whole reason the arms are ordered
# degraded-first in the helper.
assert_eq "#1264 placeholder: agent reported the line absent -> INCONCLUSIVE" \
  "INCONCLUSIVE" "$(ppv line_absent)"
assert_eq "#1264 placeholder: no marker reported at all -> INCONCLUSIVE (unestablished, not negative)" \
  "INCONCLUSIVE" "$(ppv no_marker)"
assert_eq "#1264 placeholder: controls missing -> INCONCLUSIVE" \
  "INCONCLUSIVE" "$(ppv no_controls)"
assert_eq "#1264 placeholder: file parses but records nothing -> INCONCLUSIVE" \
  "INCONCLUSIVE" "$(ppv empty)"
assert_eq "#1264 placeholder: unparseable execution file -> INCONCLUSIVE" \
  "INCONCLUSIVE" "$(ppv unparseable)"
assert_eq "#1264 placeholder: PARTIALLY corrupt file -> INCONCLUSIVE (a dropped line is not a clean read)" \
  "INCONCLUSIVE" "$(ppv partial_corrupt)"
assert_eq "#1264 placeholder: an absent execution file -> INCONCLUSIVE" \
  "INCONCLUSIVE" \
  "$(_o="$(python3 "$PPV" "$PPV_TMP/definitely-not-here.jsonl" 2>/dev/null)"; case "$_o" in *'VERDICT: '*) _v="${_o#*'VERDICT: '}"; printf '%s' "${_v%%$'\n'*}" ;; *) printf 'NO_VERDICT' ;; esac)"

# The two discrimination guards. Each pins a way the helper could report a measurement
# it never made.
assert_eq "#1264 placeholder: the marker in TEMPLATE form is not counted as a report" \
  "INCONCLUSIVE" "$(ppv template_only)"
assert_eq "#1264 placeholder: an incidental /bin/echo elsewhere does not forge NOT_SUBSTITUTED" \
  "SUBSTITUTED_ENV_VISIBLE" "$(ppv incidental)"

# The routing line is what a maintainer transcribes into the #1264 thread, so pin that a
# cleared verdict says so and a negative one does not.
assert_eq "#1264 placeholder: a cleared verdict routes to the placeholder mechanism" "yes" \
  "$(ppv_build visible >/dev/null 2>&1 && python3 "$PPV" "$PPV_TMP/exec.jsonl" 2>/dev/null | grep -q 'ROUTES TO: the placeholder mechanism' && echo yes || echo no)"
assert_eq "#1264 placeholder: a NOT_SUBSTITUTED verdict routes AWAY from the placeholder mechanism" "yes" \
  "$(ppv_build unexecuted >/dev/null 2>&1 && python3 "$PPV" "$PPV_TMP/exec.jsonl" 2>/dev/null | grep -q 'ROUTES TO: workflow-side composition' && echo yes || echo no)"

# COUPLED SITES: the workflow job and the helper's constants are one contract. The
# sentinel must match, and — the load-bearing one — the job's --allowed-tools must NOT
# grant the placeholder's own head. Widening that list would leave limb (c) measuring
# nothing while every assertion above still passed, which is exactly the silently-vacuous
# probe the #858 coupling assertion exists to prevent for its own markers.
assert_eq "#1264 placeholder: workflow sentinel and probe markers are coupled to the helper's constants" "coupled" \
  "$(python3 - "$LIB/../.github/workflows/matcher-probe.yml" "$LIB/../scripts/placeholder-probe-verdict.py" "$LIB/../.github/probe-plugin/skills/placeholder-probe/SKILL.md" <<'PY_PPV_COUPLED'
import re, sys, yaml
wf_path, helper_path, skill_path = sys.argv[1], sys.argv[2], sys.argv[3]
src = open(helper_path, encoding="utf-8").read()
def const(name):
    m = re.search(r'^%s = "([^"]+)"' % name, src, re.M)
    return m.group(1) if m else None
names = ("SENTINEL", "MARKER", "LINE_ABSENT", "CONTROL_BEFORE", "CONTROL_AFTER", "SAW")
vals = {n: const(n) for n in names}
if not all(vals.values()):
    print("helper constants not readable: %r" % (vals,)); sys.exit(0)
job = (yaml.safe_load(open(wf_path, encoding="utf-8"))["jobs"] or {}).get("placeholder-probe")
if not job:
    print("matcher-probe.yml has no placeholder-probe job"); sys.exit(0)
steps = job.get("steps") or []
claude = [s for s in steps if isinstance(s.get("with"), dict) and "claude_args" in s["with"]]
if not claude:
    print("placeholder-probe job has no claude-code-action step"); sys.exit(0)
step = claude[0]
if (step.get("env") or {}).get("DEVFLOW_PROMPT_EXTENSION_ROOT") != vals["SENTINEL"]:
    print("job env sentinel does not match the helper's SENTINEL"); sys.exit(0)
args = step["with"]["claude_args"]
# The placeholder's head must be GRANTED. This assertion is INVERTED from its original
# form, and the inversion is the record of a completed measurement rather than a
# loosening: while limb (c) ("is rendering refused by --allowed-tools?") was open, the
# head was deliberately withheld and the answer came back NEGATIVE — run 31058504896
# refused the placeholder with `This command requires approval`. With (c) answered, the
# grant is what makes limbs (a) and (b) reachable at all; four consecutive runs were
# refused before substitution could ever be observed. Read the head from the skill body
# rather than restating it here, so the grant cannot drift from the command it covers.
body = open(skill_path, encoding="utf-8").read()
m = re.search(r'!`([^\s`]+)', body)
if not m:
    print("skill body carries no `!` placeholder"); sys.exit(0)
head = m.group(1)
if head not in args:
    print("--allowed-tools does not grant the placeholder head %r, so every run is "
          "refused before limbs (a)/(b) can be observed" % head)
    sys.exit(0)
# The skill body must carry both controls, the absent-line token and the SAW prefix the
# helper scopes its readers to. MARKER is deliberately NOT required here: since the
# expansion moved into the script, the body no longer names it — the SCRIPT emits it, and
# the coupling to that producer is asserted just below.
for n in ("CONTROL_BEFORE", "CONTROL_AFTER", "LINE_ABSENT", "SAW"):
    if vals[n] not in body:
        print("skill body does not carry %s (%s)" % (n, vals[n])); sys.exit(0)
# The injected command must exist, be executable, and emit the helper's MARKER — an
# injected command that cannot run is the zero-turn abort hazard, and one that emits a
# different token would make every future run INCONCLUSIVE with the suite still green.
import os, subprocess
script = os.path.normpath(os.path.join(os.path.dirname(wf_path), "..", "probe-plugin", "phprobe-read-env.sh"))
if not os.path.isfile(script):
    print("the injected command %s does not exist" % script); sys.exit(0)
if not os.access(script, os.X_OK):
    print("the injected command %s is not executable" % script); sys.exit(0)
env = dict(os.environ); env.pop("DEVFLOW_PROMPT_EXTENSION_ROOT", None)
r = subprocess.run([script], capture_output=True, text=True, env=env)
if r.returncode != 0:
    print("the injected command exits %d on an UNSET variable — the abort hazard" % r.returncode)
    sys.exit(0)
if vals["MARKER"] not in r.stdout:
    print("the injected command does not emit %s" % vals["MARKER"]); sys.exit(0)
prompt = step["with"].get("prompt", "")
# The PRODUCTION prompt shape, and both halves are load-bearing. The slash command must be
# the LAST line (that is what limb (a) measures), and there must be leading prose before it:
# a prompt consisting of a bare slash command naming a plugin SKILL returns num_turns 0 in
# ~37ms with an empty result — the CLI resolves it as a slash command, finds no matching
# COMMAND, and exits before the model is called. Measured on the bare CLI and in this job's
# own first run (31057622518 / job 92478457854). A regression to the bare form would make
# every paid probe run resolve INCONCLUSIVE while this suite stayed green, and the zero-turn
# signature is indistinguishable from the abort hazard the probe is built to avoid.
lines = [ln for ln in prompt.strip().splitlines() if ln.strip()]
if not lines or lines[-1].strip() != "/phprobe:placeholder-probe":
    print("the probe prompt does not END with the slash command limb (a) measures"); sys.exit(0)
if len(lines) < 2:
    print("the probe prompt is a BARE slash command, which dispatches nothing (num_turns 0)")
    sys.exit(0)
print("coupled")
PY_PPV_COUPLED
)"
rm -rf "$PPV_TMP"

# ────────────────────────────────────────────────────────────────────────────
echo "#1618 skill-body-load-probe verdict deriver"
# ────────────────────────────────────────────────────────────────────────────
# scripts/skill-body-load-probe-verdict.py derives, per engine root, whether the Skill
# tool delivered that root's SKILL.md body WHOLE — from the body record that FOLLOWS the
# Skill tool_result in a claude-code-action execution file, never model text. Its verdict is what a maintainer
# transcribes into docs/internal/skill-body-load-delivery.md, so every arm is driven here
# rather than left to a paid probe run. Same treatment as the #1264 sibling above:
# unmodularized, no focused_test, driven inline from run.sh.
SBL="$LIB/../scripts/skill-body-load-probe-verdict.py"
SBL_REVIEW="$LIB/../skills/review/SKILL.md"
SBL_IMPLEMENT="$LIB/../skills/implement/SKILL.md"
# review-and-fix is the root whose NAME PROPERLY CONTAINS prflow:review. Do not swap in a
# root with an unrelated name: the containment is what arms the binding fixtures below.
SBL_RAF="$LIB/../skills/review-and-fix/SKILL.md"
SBL_TMP="$(mktemp -d)"
# Every child spawned below carries NO_COLOR/PYTHON_COLORS, per
# docs/internal/test-suite-probe-conventions.md: without them an escape sequence from a
# colour-forcing host lands inside a matched token and the match silently fails.
sbl_build() {  # $1 scenario -> writes $SBL_TMP/exec.jsonl; rc 0 AND non-empty on success
  # Truncate FIRST. The builder writes in place, so without this a failed build leaves the
  # previous scenario's fixture on disk and the next assertion measures that one instead —
  # green, against a fixture it never built.
  rm -f "$SBL_TMP/exec.jsonl"
  NO_COLOR=1 PYTHON_COLORS=0 python3 - "$SBL_TMP/exec.jsonl" "$1" "$SBL_REVIEW" "$SBL_IMPLEMENT" "$SBL_RAF" <<'PY_SBL'
import json, os, sys
out, scen, path, impl_path, raf_path = sys.argv[1:6]
body = open(path, encoding="utf-8").read()
impl_body = open(impl_path, encoding="utf-8").read()
raf_body = open(raf_path, encoding="utf-8").read()
tail = [ln.strip() for ln in body.splitlines() if ln.strip()][-1]
review_dir = os.path.dirname(path)
impl_dir = os.path.dirname(impl_path)
raf_dir = os.path.dirname(raf_path)
other_dir = os.path.join(os.path.dirname(review_dir), "implement")
# The runner's own ABSOLUTE base directory, as a real transcript records it. Do not rewrite
# these to on-disk paths: an identical pair on both sides drives only dirs_match's equality
# branch, leaving the suffix branch every production reading takes unexercised.
runner_dir = "/home/runner/work/prflow/prflow/skills/review"
boundary_dir = "/home/runner/work/prflow/prflow/myskills/review"
PREFIX = "Base directory for this skill: "
# These fixtures reproduce the RECORD LAYOUT of a real claude-code-action transcript: the
# Skill tool_result is a ~30-byte launch STUB and the body arrives in the NEXT, user-role
# record. Writing the body into the tool_result would make every assertion below vacuous.
_UNSET = object()
def skill_use(name="prflow:review", uid="su1", input_obj=_UNSET):
    inp = {"skill": name} if input_obj is _UNSET else input_obj
    return {"type": "assistant", "message": {"role": "assistant", "content": [
        {"type": "tool_use", "name": "Skill", "id": uid, "input": inp}]}}
def stub(uid="su1", is_error=False, content=None):
    if content is None:
        content = "Launching skill: prflow:review"
    return {"type": "user", "message": {"role": "user", "content": [
        {"type": "tool_result", "tool_use_id": uid, "content": content,
         "is_error": is_error}]}}
def body_rec(text, base=None, role="user"):
    base = review_dir if base is None else base
    return {"type": role, "message": {"role": role, "content": [
        {"type": "text", "text": PREFIX + base + "\n\n" + text}]}}
# Each scenario maps to a list of records, EXCEPT the fixture-free ones (absent/unparseable),
# which are handled by the caller. An unrecognised scenario raises, so the build fails rather
# than leaving an empty fixture the helper would read as unparseable and pass for the wrong reason.
scenarios = {
    "whole":       [skill_use(), stub(), body_rec(body)],
    # tool_result content as a list of text blocks — the other real stub serialization.
    "whole_blocks":[skill_use(),
                    stub(content=[{"type": "text", "text": "Launching skill: prflow:review"}]),
                    body_rec(body)],
    # Body missing its final line: the tail control cannot be found.
    "short_tail":  [skill_use(), stub(), body_rec(body.rsplit("\n", 2)[0])],
    # Only the tail line survives: tail present, a real interior line absent.
    "mid_gap":     [skill_use(), stub(), body_rec(tail)],
    # A whole body that ALSO carries a cap notice — the marker arm fires before the tail check.
    "trunc_marker":[skill_use(), stub(), body_rec(body + "\nshowing lines 1-10 of 343 (cap 25000)")],
    # The load happened but NO body record followed — measuring the stub alone must not
    # adjudicate anything, so this is unestablished rather than a short delivery.
    "stub_only":   [skill_use(), stub()],
    # A body record naming a DIFFERENT skill's directory: another root's body must not be
    # adjudicated as this one's.
    "wrong_dir_body":[skill_use(), stub(), body_rec(body, base=other_dir)],
    # PRODUCTION DIRECTORY SHAPE: an absolute runner base dir against a repo-relative --root,
    # which only dirs_match's SUFFIX branch resolves.
    "abs_suffix_dir":[skill_use(), stub(), body_rec(body, base=runner_dir)],
    # SEPARATOR BOUNDARY: `myskills/review` is a bare suffix of `skills/review` but not a
    # component-boundary one. Do not swap in a non-suffix directory — the refusal would then
    # come from the directory differing at all, and the `/` guard would go unpinned.
    "boundary_dir": [skill_use(), stub(), body_rec(body, base=boundary_dir)],
    # The prefix in an ASSISTANT record is the model talking about a delivery, not one.
    "assistant_body":[skill_use(), stub(), body_rec(body, role="assistant")],
    # No Skill tool_use at all — the body was never loaded by this channel.
    "no_skill":    [{"type": "assistant", "message": {"role": "assistant", "content": [
                        {"type": "tool_use", "name": "Bash", "id": "b1",
                         "input": {"command": "true"}}]}}],
    # A Skill load that returned an error (refused/aborted) — the abort mode, not truncation.
    "err_result":  [skill_use(), stub(is_error=True, content="permission denied")],
    # A Skill tool_use recorded with NO paired result — nothing was delivered to measure.
    "no_result":   [skill_use()],
    # Parses cleanly but records no tool_use of any kind.
    "wrong_shape": [{"type": "system", "note": "no tool uses here"}],
    # TWO Skill loads in one transcript, each with its OWN body. Do not collapse this to a
    # single load: it is the only fixture that closes the position window's upper bound, and
    # a window narrowed by one drops the FIRST load's body while every single-load arm stays green.
    "two_skill_loads": [skill_use("prflow:review", "su1"), stub("su1"), body_rec(body),
                        skill_use("prflow:implement", "su2"),
                        stub("su2", content="Launching skill: prflow:implement"),
                        body_rec(impl_body, base=impl_dir)],
    # The review body arrives AFTER a LATER Skill tool_use. Do not move it before that tool_use:
    # its position is what proves the window STOPS there, so a window widened to the end of the
    # transcript mis-credits this body to the earlier load and reports a delivery it cannot attribute.
    "late_body":   [skill_use("prflow:review", "su1"), stub("su1"),
                    skill_use("prflow:implement", "su2"),
                    stub("su2", content="Launching skill: prflow:implement"),
                    body_rec(body)],
    # Do not collapse this to one load: the containing name recorded FIRST is what a
    # bare-substring first-match binds the review root to, and nothing else exhibits it.
    "contains_name_first": [skill_use("prflow:review-and-fix", "su1"),
                            stub("su1", content="Launching skill: prflow:review-and-fix"),
                            body_rec(raf_body, base=raf_dir),
                            skill_use("prflow:review", "su2"), stub("su2"), body_rec(body)],
    # The same pair in the OTHER order. Keep both: a match that scanned in reverse, or kept the
    # LAST match rather than the first, would resolve one order and fail the other.
    "contains_name_second": [skill_use("prflow:review", "su1"), stub("su1"), body_rec(body),
                             skill_use("prflow:review-and-fix", "su2"),
                             stub("su2", content="Launching skill: prflow:review-and-fix"),
                             body_rec(raf_body, base=raf_dir)],
    # An ARGUMENT string that is exactly another root's name.
    "arg_equals_other_root": [skill_use("prflow:implement", "su1",
                                        input_obj={"skill": "prflow:implement",
                                                   "args": "prflow:review"}),
                              stub("su1", content="Launching skill: prflow:implement"),
                              body_rec(impl_body, base=impl_dir)],
    # A root recorded TWICE, the first load errored and the second delivering a whole body.
    "retry_after_error": [skill_use("prflow:review", "su1"),
                          stub("su1", is_error=True, content="permission denied"),
                          skill_use("prflow:review", "su2"), stub("su2"), body_rec(body)],
    # THREE recorded loads of which TWO match, so the ambiguity reason's count operand is
    # distinguishable from the total: swap it for len(pairs) and the digit renders 3, not 2.
    "ambiguous_among_three": [skill_use("prflow:review", "su1"), stub("su1"), body_rec(body),
                              skill_use("prflow:implement", "su2"),
                              stub("su2", content="Launching skill: prflow:implement"),
                              body_rec(impl_body, base=impl_dir),
                              skill_use("prflow:review", "su3"), stub("su3"), body_rec(body)],
    # Two body records in one window, both naming the review directory, the second truncated:
    # keeping the first answers delivered-whole and keeping the last short-delivery.
    "two_bodies_one_window": [skill_use("prflow:review", "su1"), stub("su1"),
                              body_rec(body), body_rec(body.rsplit("\n", 2)[0])],
    # A successful load plus a load whose argument text mentions this root's name: two matches.
    "success_plus_arg_mention": [skill_use("prflow:review", "su1"), stub("su1"), body_rec(body),
                                 skill_use("prflow:implement", "su2",
                                           input_obj={"skill": "prflow:implement",
                                                      "args": "prflow:review"}),
                                 stub("su2", content="Launching skill: prflow:implement")],
    # A duplicated tool_use_id whose second result is clean: last-write-wins would erase the
    # first result's error flag.
    "duplicate_result_id": [skill_use("prflow:review", "su1"),
                            stub("su1", is_error=True, content="permission denied"),
                            stub("su1"), body_rec(body)],
    # A Skill tool_use carrying NO input at all.
    "null_input":  [skill_use("prflow:review", "su1", input_obj=None), stub("su1"),
                    body_rec(body)],
}
if scen == "unparseable":
    open(out, "w", encoding="utf-8").write("{ not json at all\n")
elif scen == "leading_comment":
    # The PUBLISHED artifact shape: scripts/scrub-transcript.sh prepends one `#` caveat line
    # to the pretty-printed array, which strict json.loads rejects.
    open(out, "w", encoding="utf-8").write(
        "# DEVFLOW SCRUB CAVEAT: best-effort blocklist redaction. Treat as sensitive.\n"
        + json.dumps(scenarios["whole"], indent=2) + "\n")
elif scen == "interior_comment":
    # Only the LEADING blank/`#` run is stripped. Do not move the trailing `#` line to the top:
    # its position is what proves an interior `#` still counts as unparseable, and a stripper
    # that dropped every `#` line would hide the corruption and report a clean read.
    with open(out, "w", encoding="utf-8") as fh:
        fh.write("# DEVFLOW SCRUB CAVEAT: best-effort blocklist redaction.\n\n")
        for r in scenarios["whole"]:
            fh.write(json.dumps(r) + "\n")
        fh.write("# not a record\n")
elif scen == "whole_json":
    # A single whole-file JSON document (not JSONL) — exercises parse_execution_file's
    # json.loads(raw) success path, which the line-by-line fixtures never reach.
    open(out, "w", encoding="utf-8").write(json.dumps(scenarios["whole"]))
elif scen == "partial_corrupt":
    # Some lines parse, one does not: parse_execution_file returns a non-empty note_top, which
    # forces every root to unestablished even though a valid Skill pair was recovered.
    with open(out, "w", encoding="utf-8") as fh:
        for r in scenarios["whole"]:
            fh.write(json.dumps(r) + "\n")
        fh.write("{ this line is not valid json\n")
elif scen in scenarios:
    with open(out, "w", encoding="utf-8") as fh:
        for r in scenarios[scen]:
            fh.write(json.dumps(r) + "\n")
else:
    raise SystemExit("unrecognised scenario: %s" % scen)
PY_SBL
  _sbl_rc=$?
  [ "$_sbl_rc" -eq 0 ] && [ -s "$SBL_TMP/exec.jsonl" ]
}
sbl_run() {  # the single invocation point for spawning THE HELPER: audit args -> its stdout
  # Route helper spawns through this one point so a site added later cannot omit the colour
  # neutralisation, and do not discard stderr in a caller that reads stdout — a traceback would
  # vanish and the crash read as a grep miss. A caller reading only the exit status may discard.
  NO_COLOR=1 PYTHON_COLORS=0 python3 "$SBL" "$@"
}
sbl_verdict_token() {  # $1 the helper's stdout -> the FIRST per-root VERDICT token
  # Pure parameter expansion (CLAUDE.md guard-class 2: no tr/sed/cut, which would fail OPEN).
  # The audit summary line is `AUDIT: …` (not `AUDIT VERDICT:`), so the first `VERDICT: `
  # match is a per-root verdict, never the summary.
  case "$1" in
    *'VERDICT: '*) local _v="${1#*'VERDICT: '}"; printf '%s' "${_v%%$'\n'*}" ;;
    *) printf 'NO_VERDICT' ;;
  esac
}
sbl_says() {  # $1 scenario, $2 pattern -> yes|no, whether the review root's report carries $2
  # A build OR helper failure prints its OWN token, never 'no': inverted by sbl_denies, a 'no'
  # would become the expected 'yes' and turn a fixture or a crash into a green assertion. Gate
  # on the helper's exit status BEFORE the grep — a crash produces no stdout, which greps as a
  # plain miss.
  if ! sbl_build "$1"; then printf 'FIXTURE_BUILD_FAILED'; return 0; fi
  local _out
  if ! _out="$(sbl_run "$SBL_TMP/exec.jsonl" --tier review --root "prflow:review=$SBL_REVIEW")"; then
    printf 'HELPER_FAILED'; return 0
  fi
  printf '%s' "$_out" | grep -q "$2" && printf 'yes' || printf 'no'
}
sbl_denies() {  # the NEGATED sbl_says. A separate name, never an inverted echo pair inline:
                # a reader must not have to spot `echo no || echo yes` to see the inversion.
  local _r
  _r="$(sbl_says "$1" "$2")"
  case "$_r" in yes) printf 'no' ;; no) printf 'yes' ;; *) printf '%s' "$_r" ;; esac
}
sbl_rel_denies() {  # $1 scenario, $2 pattern -> yes when the REPO-RELATIVE-root report lacks $2
  # Never `grep -q … && echo no || echo yes` inline: that expects grep's FAILURE arm, so a helper
  # crash greps as a miss and passes the assertion green. Gate on the exit status first.
  if ! sbl_build "$1"; then printf 'FIXTURE_BUILD_FAILED'; return 0; fi
  local _out
  if ! _out="$(cd "$LIB/.." && sbl_run "$SBL_TMP/exec.jsonl" --tier review --root "prflow:review=skills/review/SKILL.md")"; then
    printf 'HELPER_FAILED'; return 0
  fi
  printf '%s' "$_out" | grep -q "$2" && printf 'no' || printf 'yes'
}
sbl() {  # $1 scenario -> the first per-root VERDICT token (single-root fixtures)
  if ! sbl_build "$1"; then printf 'FIXTURE_BUILD_FAILED'; return 0; fi
  sbl_verdict_token "$(sbl_run "$SBL_TMP/exec.jsonl" --tier review --root "prflow:review=$SBL_REVIEW")"
}
sbl_rel() {  # $1 scenario -> first VERDICT token, run from the repo root with a REPO-RELATIVE
             # --root. Do not switch this to an absolute --root: the relative form is what makes
             # dirs_match take its production suffix branch instead of the equality branch.
  if ! sbl_build "$1"; then printf 'FIXTURE_BUILD_FAILED'; return 0; fi
  local _out
  _out="$(cd "$LIB/.." && sbl_run "$SBL_TMP/exec.jsonl" --tier review --root "prflow:review=skills/review/SKILL.md")"
  sbl_verdict_token "$_out"
}
# NEGATIVE CONTROL — an unrecognised scenario must FAIL the build, or the sweep is vacuous.
assert_eq "#1618 skill-body: an unrecognised fixture scenario fails the build" "failed" \
  "$(sbl_build __no_such_scenario__ 2>/dev/null && echo built || echo failed)"
assert_eq "#1618 skill-body: a recognised fixture scenario still builds" "built" \
  "$(sbl_build whole 2>/dev/null && echo built || echo failed)"

# The two real measurements: a body delivered whole, and a tail loss. The whole-body arm is
# the regression guard for the wrong-record defect — the body lives in the record AFTER the
# Skill tool_result, so a helper measuring the ~30-byte launch stub reads short-delivery here.
assert_eq "#1618 skill-body: whole body in the following record -> delivered-whole" \
  "delivered-whole" "$(sbl whole)"
assert_eq "#1618 skill-body: tail line missing -> short-delivery (tail lost)" \
  "short-delivery" "$(sbl short_tail)"
assert_eq "#1618 skill-body: tail present but interior gone -> short-delivery" \
  "short-delivery" "$(sbl mid_gap)"
assert_eq "#1618 skill-body: a cap/truncation notice in the body -> short-delivery" \
  "short-delivery" "$(sbl trunc_marker)"

# Each degraded arm asserted below reads `unestablished`, never `delivered-whole`; the
# helper's docstring enumerates the arms. Collapsing any onto delivered-whole is the
# fail-open the arm ordering exists to prevent.
assert_eq "#1618 skill-body: no Skill tool_use -> unestablished (never loaded)" \
  "unestablished" "$(sbl no_skill)"
assert_eq "#1618 skill-body: Skill load returned an error -> unestablished (abort mode)" \
  "unestablished" "$(sbl err_result)"
assert_eq "#1618 skill-body: Skill call with no paired result -> unestablished" \
  "unestablished" "$(sbl no_result)"
assert_eq "#1618 skill-body: well-formed JSON of the wrong shape -> unestablished" \
  "unestablished" "$(sbl wrong_shape)"
assert_eq "#1618 skill-body: launch stub with no body record -> unestablished" \
  "unestablished" "$(sbl stub_only)"
assert_eq "#1618 skill-body: body record naming another skill's directory -> unestablished" \
  "unestablished" "$(sbl wrong_dir_body)"
assert_eq "#1618 skill-body: the prefix in an assistant record is not a delivery" \
  "unestablished" "$(sbl assistant_body)"
assert_eq "#1618 skill-body: unparseable execution file -> unestablished" \
  "unestablished" "$(sbl unparseable)"
assert_eq "#1618 skill-body: an absent execution file -> unestablished" \
  "unestablished" \
  "$(_o="$(sbl_run "$SBL_TMP/definitely-not-here.jsonl" --tier review --root "prflow:review=$SBL_REVIEW")"; case "$_o" in *'VERDICT: '*) _v="${_o#*'VERDICT: '}"; printf '%s' "${_v%%$'\n'*}" ;; *) printf 'NO_VERDICT' ;; esac)"

# A tool_result whose content is a list of text blocks is still only the launch stub; the
# following body record is what carries the delivery.
assert_eq "#1618 skill-body: tool_result content as a list of text blocks -> delivered-whole" \
  "delivered-whole" "$(sbl whole_blocks)"
# The PUBLISHED transcript artifact carries one leading `#` caveat line, which strict JSON
# rejects; without comment tolerance every line falls to the JSONL path and is dropped.
assert_eq "#1618 skill-body: published artifact (leading # caveat) -> delivered-whole" \
  "delivered-whole" "$(sbl leading_comment)"
# A single whole-file JSON document (not JSONL) still resolves — the whole-file json.loads path.
assert_eq "#1618 skill-body: whole-file JSON (not JSONL) -> delivered-whole" \
  "delivered-whole" "$(sbl whole_json)"
# A partially-corrupt file (some lines parse, one does not) forces unestablished — a recovered
# Skill pair must NOT be adjudicated as delivered-whole when the file could not be read cleanly.
assert_eq "#1618 skill-body: partially-corrupt execution file -> unestablished (not a clean read)" \
  "unestablished" "$(sbl partial_corrupt)"
# The on-disk control file is unreadable: read_controls fails, so the delivered body cannot be
# checked -> unestablished, never collapsed onto delivered-whole. The bogus --root names a
# MISSING FILE INSIDE the delivered body's own directory; a path in another directory would be
# refused one arm earlier by the base-directory match and never reach read_controls.
assert_eq "#1618 skill-body: unreadable on-disk control file -> unestablished" \
  "unestablished" \
  "$(sbl_build whole >/dev/null 2>&1; _o="$(sbl_run "$SBL_TMP/exec.jsonl" --tier review --root "prflow:review=$LIB/../skills/review/DEFINITELY-NOT-HERE.md")"; case "$_o" in *'VERDICT: '*) _v="${_o#*'VERDICT: '}"; printf '%s' "${_v%%$'\n'*}" ;; *) printf 'NO_VERDICT' ;; esac)"
assert_eq "#1618 skill-body: the control-file arm is reached, not the missing-body arm" "yes" \
  "$(sbl_build whole >/dev/null 2>&1; sbl_run "$SBL_TMP/exec.jsonl" --tier review --root "prflow:review=$LIB/../skills/review/DEFINITELY-NOT-HERE.md" | grep -q 'could not be read for controls' && echo yes || echo no)"
# Multi-root audit (the shape both workflow jobs actually use): two --root operands emit two
# per-root VERDICT lines. The `whole` fixture carries a prflow:review pair only, so review reads
# delivered-whole and implement (no pair) reads unestablished — proving the loop runs per root
# rather than short-circuiting on the first. Counted with grep -c (a missing count fails the
# assert loudly), never a selection-determining tr/sed pipeline.
assert_eq "#1618 skill-body: multi-root audit emits a delivered-whole for the present root" "1" \
  "$(sbl_build whole >/dev/null 2>&1; sbl_run "$SBL_TMP/exec.jsonl" --tier review --root "prflow:review=$SBL_REVIEW" --root "prflow:implement=/definitely/not/here/SKILL.md" | grep -c 'VERDICT: delivered-whole')"
assert_eq "#1618 skill-body: multi-root audit emits an unestablished for the absent root" "1" \
  "$(sbl_build whole >/dev/null 2>&1; sbl_run "$SBL_TMP/exec.jsonl" --tier review --root "prflow:review=$SBL_REVIEW" --root "prflow:implement=/definitely/not/here/SKILL.md" | grep -c 'VERDICT: unestablished')"

# MULTI-LOAD ATTRIBUTION — the position window (stop = use_positions[n+1]) claims every body
# record between one Skill tool_use and the NEXT. Both bounds are driven here: every other
# fixture carries a single load and leaves an off-by-one or an unbounded window green.
assert_eq "#1618 skill-body: two Skill loads in one transcript -> each root delivered-whole" "2" \
  "$(sbl_build two_skill_loads >/dev/null 2>&1; sbl_run "$SBL_TMP/exec.jsonl" --tier review --root "prflow:review=$SBL_REVIEW" --root "prflow:implement=$SBL_IMPLEMENT" | grep -c 'VERDICT: delivered-whole')"
# Stop bound: a body arriving after a LATER tool_use belongs to neither load — the earlier load's
# window has closed and the later load's own window holds a body naming another skill's directory.
# An unbounded window credits it to the earlier load and this count rises to 1.
assert_eq "#1618 skill-body: a body after a later Skill tool_use is credited to neither load" "0" \
  "$(sbl_build late_body >/dev/null 2>&1; sbl_run "$SBL_TMP/exec.jsonl" --tier review --root "prflow:review=$SBL_REVIEW" --root "prflow:implement=$SBL_IMPLEMENT" | grep -c 'VERDICT: delivered-whole')"
# ATTRIBUTED REJECTION: the review root must be refused by the no-following-body arm specifically,
# not by an unrelated precondition (never-loaded / no-result / error) upstream of it.
assert_eq "#1618 skill-body: the late body is refused by the no-following-body arm" "yes" \
  "$(sbl_says late_body 'no following body record naming its own')"
# POSITIVE CONTROL on that same fixture: both loads WERE recorded and paired, so the refusal above
# is the window closing rather than a fixture the helper could not read.
assert_eq "#1618 skill-body: the late-body fixture still records both Skill loads" "yes" \
  "$(sbl_says late_body 'recorded Skill tool_use pairs: 2')"

# NAME BINDING (#1897) — do not narrow this to one load order: a bare-substring match binds
# the review root to the `prflow:review-and-fix` load and answers `unestablished`, and a fix
# that scanned in reverse would resolve one order while leaving the other broken.
for _sbl_order in contains_name_first contains_name_second; do
  assert_eq "#1618/#1897 skill-body: a containing name does not claim the root's load ($_sbl_order)" "2" \
    "$(sbl_build "$_sbl_order" >/dev/null 2>&1; sbl_run "$SBL_TMP/exec.jsonl" --tier review --root "prflow:review=$SBL_REVIEW" --root "prflow:review-and-fix=$SBL_RAF" | grep -c 'VERDICT: delivered-whole')"
  # POSITIVE CONTROL: both loads WERE recorded, so a red above is the binding rather than a
  # fixture the helper could not read.
  assert_eq "#1618/#1897 skill-body: the $_sbl_order fixture records both Skill loads" "yes" \
    "$(sbl_says "$_sbl_order" 'recorded Skill tool_use pairs: 2')"
done
# RESIDUE the quoted form does not remove: an argument equal to another root's name is
# quote-delimited like the skill name, so that load still matches. Do not "fix" it by reading a
# named input field: one committed transcript is a dated observation, not a schema contract.
assert_eq "#1618/#1897 skill-body: an argument equal to another root's name yields no verdict for it" \
  "unestablished" "$(sbl arg_equals_other_root)"
assert_eq "#1618/#1897 skill-body: that root is refused by the no-following-body arm" "yes" \
  "$(sbl_says arg_equals_other_root 'no following body record naming its own')"
# POSITIVE CONTROL on that same fixture: the load's OWN root resolves, so the refusal above is
# the argument string failing to bind rather than a fixture the helper could not read.
assert_eq "#1618/#1897 skill-body: that fixture's own root still resolves" "1" \
  "$(sbl_build arg_equals_other_root >/dev/null 2>&1; sbl_run "$SBL_TMP/exec.jsonl" --tier review --root "prflow:implement=$SBL_IMPLEMENT" | grep -c 'VERDICT: delivered-whole')"
# AMBIGUITY — more than one recorded load matches, so the root resolves to none of them. The
# reason must NAME the ambiguity: an unestablished that reads like a genuine non-result is the
# defect class this arm exists to end.
assert_eq "#1618/#1897 skill-body: a root recorded twice -> unestablished" "unestablished" \
  "$(sbl retry_after_error)"
assert_eq "#1618/#1897 skill-body: the twice-recorded root's reason names the ambiguity" "yes" \
  "$(sbl_says retry_after_error 'recorded Skill loads name prflow:review')"
# The ambiguity reason counts the loads that MATCHED, not the transcript's total. This fixture
# records three loads of which two match, so swapping the operand for len(pairs) renders 3 here
# and goes RED — on retry_after_error the two counts coincide and the swap is invisible.
assert_eq "#1618/#1897 skill-body: the ambiguity reason counts the matching loads, not the total" "yes" \
  "$(sbl_says ambiguous_among_three '2 recorded Skill loads name prflow:review')"
assert_eq "#1618/#1897 skill-body: that fixture records three loads in total" "yes" \
  "$(sbl_says ambiguous_among_three 'recorded Skill tool_use pairs: 3')"
# ATTRIBUTED REJECTION: the refusal is the ambiguity arm, not the error arm one step above it.
assert_eq "#1618/#1897 skill-body: the twice-recorded root is not refused by the error arm" "yes" \
  "$(sbl_denies retry_after_error 'returned an error tool_result')"
# Do not revert either selection half to a first-match: keeping the first of several makes the
# verdict depend on record order.
assert_eq "#1618/#1897 skill-body: two bodies naming one directory -> unestablished" "unestablished" \
  "$(sbl two_bodies_one_window)"
assert_eq "#1618/#1897 skill-body: that reason names the body-record ambiguity, not a missing body" "yes" \
  "$(sbl_says two_bodies_one_window '2 body records in the Skill load bound to prflow:review')"
# The disclosed residue of matching a quoted name against the serialised input: report the
# collision, never measure one of the colliding loads.
assert_eq "#1618/#1897 skill-body: a successful load plus an argument mention -> unestablished" "unestablished" \
  "$(sbl success_plus_arg_mention)"
assert_eq "#1618/#1897 skill-body: that pair is refused by the ambiguity arm" "yes" \
  "$(sbl_says success_plus_arg_mention '2 recorded Skill loads name prflow:review')"
# A duplicated tool_use_id must not let a later clean result erase an earlier error flag.
assert_eq "#1618/#1897 skill-body: a duplicated tool_use_id keeps the error flag" "unestablished" \
  "$(sbl duplicate_result_id)"
assert_eq "#1618/#1897 skill-body: that load is refused by the error arm, not measured" "yes" \
  "$(sbl_says duplicate_result_id 'returned an error tool_result')"
# A tool_use with NO input serialises to the bare literal `null`, which no quoted name occurs
# inside — the fail-closed direction is never-loaded, never a body credited to it.
assert_eq "#1618/#1897 skill-body: a Skill tool_use with no input -> unestablished" "unestablished" \
  "$(sbl null_input)"
assert_eq "#1618/#1897 skill-body: the no-input load is refused by the never-loaded arm" "yes" \
  "$(sbl_says null_input 'no recorded Skill tool_use names prflow:review')"
# The never-loaded reason carries the TOTAL recorded load count, which is what separates a
# transcript that recorded nothing from one whose loads all bound another name. Swap the operand
# for the match count and both assertions below go RED.
assert_eq "#1618/#1897 skill-body: the never-loaded reason reports one recorded load for null_input" "yes" \
  "$(sbl_says null_input '1 Skill load(s) were recorded in total')"
assert_eq "#1618/#1897 skill-body: the never-loaded reason reports zero recorded loads for no_skill" "yes" \
  "$(sbl_says no_skill '0 Skill load(s) were recorded in total')"
# The same --root supplied TWICE: argparse append accepts it with no uniqueness check, so the
# audit reports that root once per operand. Two identical operands must not read as two roots
# measured, nor make either reading disagree with the single-operand one.
assert_eq "#1618/#1897 skill-body: a duplicated --root emits one verdict per operand" "2" \
  "$(sbl_build whole >/dev/null 2>&1; sbl_run "$SBL_TMP/exec.jsonl" --tier review --root "prflow:review=$SBL_REVIEW" --root "prflow:review=$SBL_REVIEW" | grep -c 'VERDICT: delivered-whole')"
# The no-following-body reason names the DIRECTORY it compared. Do not revert the operand to the
# --root path: the sentence says directory, and the pair below pins that it is one.
assert_eq "#1618/#1897 skill-body: the no-following-body reason names the compared directory" "yes" \
  "$(sbl_build boundary_dir >/dev/null 2>&1; (cd "$LIB/.." && sbl_run "$SBL_TMP/exec.jsonl" --tier review --root "prflow:review=skills/review/SKILL.md") | grep -q "directory ('skills/review')" && echo yes || echo no)"
assert_eq "#1618/#1897 skill-body: that reason no longer names the SKILL.md file path" "yes" \
  "$(sbl_rel_denies boundary_dir "directory ('skills/review/SKILL.md')")"  # raw-guard-ok: sbl_rel_denies greps the helper's rendered stdout, not a SKILL file's text; the SKILL.md token is the operand under test
# Do not rebuild this fixture from the builder above: it is a REAL captured transcript, and a
# fixture built from the instrument's own assumptions cannot contradict the instrument — which
# is how this file's defect family survived a green suite. Provenance is in the fixture header.
SBL_OBS="$LIB/test/fixtures/skill-body-load-transcript.observed.txt"
assert_eq "#1618/#1897 skill-body: the committed real transcript records exactly one Skill load" "yes" \
  "$(sbl_run "$SBL_OBS" --tier review --root "prflow:review=$SBL_REVIEW" | grep -q 'recorded Skill tool_use pairs: 1' && echo yes || echo no)"
# AC8's promise is that the recorded measurement is re-derivable from committed bytes, so drive
# the documented recipe: the review body AT THE MEASURED HEAD, laid out as skills/review/, must
# still read delivered-whole. A shallow clone lacking that blob prints its own token rather than
# a silent pass.
assert_eq "#1618/#1897 skill-body: the committed transcript re-derives delivered-whole at the measured head" "delivered-whole" \
  "$(mkdir -p "$SBL_TMP/rederive/skills/review" && NO_COLOR=1 PYTHON_COLORS=0 git -C "$LIB/.." show 668a78990c810b0318d7fdbf5de8a95c043eda71:skills/review/SKILL.md > "$SBL_TMP/rederive/skills/review/SKILL.md" 2>/dev/null || { printf 'GIT_OBJECT_MISSING'; false; } && sbl_verdict_token "$(cd "$SBL_TMP/rederive" && sbl_run "$SBL_OBS" --tier review --root "prflow:review=skills/review/SKILL.md")")"
# Do not point this at a path outside the matching directory: the controls arm is reached only
# after the name binding and the directory selection both resolve, so a root elsewhere would be
# refused upstream and prove neither.
assert_eq "#1618/#1897 skill-body: the real transcript binds the review root and selects its body" "yes" \
  "$(cd "$LIB/.." && sbl_run "$SBL_OBS" --tier review --root "prflow:review=skills/review/DEFINITELY-NOT-HERE.md" | grep -q 'could not be read for controls' && echo yes || echo no)"
# ONE-CONTROL ARM. read_controls finds no interior control when every non-tail line is under 20
# characters, so the delivered-whole reason must say only the tail was checked. Drop the
# conditional and this goes RED — nothing else reaches that arm, since every engine root has a
# long interior line. The scratch root lives beside the fixture's own base directory so the
# directory match resolves.
assert_eq "#1618/#1897 skill-body: a root with no interior control says only the tail was checked" "yes" \
  "$(mkdir -p "$SBL_TMP/skills/review" && printf 'a\nb\nTHE FINAL LINE OF THE ONE-CONTROL FIXTURE\n' > "$SBL_TMP/skills/review/SKILL.md" && NO_COLOR=1 PYTHON_COLORS=0 python3 - "$SBL_TMP" <<'PY_SBL_ONE'
import json, os, sys
root = sys.argv[1]
body = open(os.path.join(root, "skills", "review", "SKILL.md"), encoding="utf-8").read()
PREFIX = "Base directory for this skill: "
recs = [
    {"type": "assistant", "message": {"role": "assistant", "content": [
        {"type": "tool_use", "name": "Skill", "id": "s1", "input": {"skill": "prflow:review"}}]}},
    {"type": "user", "message": {"role": "user", "content": [
        {"type": "tool_result", "tool_use_id": "s1", "content": "Launching skill: prflow:review"}]}},
    {"type": "user", "message": {"role": "user", "content": [
        {"type": "text", "text": PREFIX + os.path.join(root, "skills", "review") + "\n\n" + body}]}},
]
with open(os.path.join(root, "one-control.jsonl"), "w", encoding="utf-8") as fh:
    for r in recs:
        fh.write(json.dumps(r) + "\n")
PY_SBL_ONE
sbl_run "$SBL_TMP/one-control.jsonl" --tier review --root "prflow:review=$SBL_TMP/skills/review/SKILL.md" | grep -q 'only the tail was checked' && echo yes || echo no)"
# POSITIVE CONTROL: that same fixture reaches delivered-whole, so the assertion above is the
# one-control wording rather than a fixture the helper could not read.
assert_eq "#1618/#1897 skill-body: the one-control fixture still reads delivered-whole" "1" \
  "$(sbl_run "$SBL_TMP/one-control.jsonl" --tier review --root "prflow:review=$SBL_TMP/skills/review/SKILL.md" | grep -c 'VERDICT: delivered-whole')"
# dirs_match under the WINDOWS path module. Every fixture above runs under the host's own
# os.path, so a POSIX-only host leaves the ntpath reading unexercised — and there the
# separator cleanup was undone by normpath, so every root read unestablished.
sbl_dirs_match_both_modules() {  # $1 body base dir, $2 root dir (default skills/review)
                                 #   -> "<posixpath result> <ntpath result>"
  # dirs_match reads the module-level os.path, so swapping it is what exercises the Windows
  # reading on a POSIX host. Keep each call site below its own assertion: one spawn each buys
  # a per-case label that a fused multi-value print would cost.
  NO_COLOR=1 PYTHON_COLORS=0 python3 - "$SBL" "$1" "${2:-skills/review}" <<'PY_SBL_NT'
import importlib.util, ntpath, posixpath, sys
spec = importlib.util.spec_from_file_location("sbl", sys.argv[1])
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)
out = []
for mod in (posixpath, ntpath):
    m.os.path = mod
    out.append(str(m.dirs_match(sys.argv[2], sys.argv[3])))
print(" ".join(out))
PY_SBL_NT
}
assert_eq "#1618/#1897 skill-body: dirs_match resolves identically under posixpath and ntpath" "True True" \
  "$(sbl_dirs_match_both_modules /home/runner/work/prflow/prflow/skills/review)"
# The component-boundary guard must survive that fix under each of the two stdlib path modules
# `os.path` can resolve to, or the ntpath repair resolves `myskills/review` against `skills/review`.
assert_eq "#1618/#1897 skill-body: the component-boundary guard holds under both path modules" "False False" \
  "$(sbl_dirs_match_both_modules /home/runner/work/prflow/prflow/myskills/review)"
# A backslash-bearing base dir is the form a real Windows runner records. Keep it alongside the
# forward-slash probe rather than in place of it: that one reaches the same normalisation via
# ntpath.normpath, while this one pins the input shape production actually sees.
assert_eq "#1618/#1897 skill-body: a backslash-bearing runner directory resolves under both modules" "True True" \
  "$(sbl_dirs_match_both_modules 'C:\runners\work\prflow\prflow\skills\review')"
# EMPTY-OPERAND GUARD. `.` is what root_dir_for returns for a bare-filename --root, so a blank
# base directory against it is reachable from production. Move the emptiness test back after
# normpath and this returns True — normpath maps "" to "." — crediting an unrelated body.
assert_eq "#1618/#1897 skill-body: a blank base directory matches no root under either module" "False False" \
  "$(sbl_dirs_match_both_modules '' '.')"

# DIRECTORY MATCH — every fixture above builds the body's base dir from the same on-disk path
# the --root spec names, so they drive dirs_match's equality branch only. Production never takes
# it: the transcript carries an absolute runner dir while --root is repo-relative.
assert_eq "#1618 skill-body: absolute runner base dir vs repo-relative root -> delivered-whole" \
  "delivered-whole" "$(sbl_rel abs_suffix_dir)"
# Separator boundary: a bare-suffix directory (`myskills/review`) is not a component-boundary
# suffix of `skills/review`, so it must NOT be adjudicated as this root's body.
assert_eq "#1618 skill-body: a bare-suffix directory does not satisfy the root -> unestablished" \
  "unestablished" "$(sbl_rel boundary_dir)"
# ATTRIBUTED REJECTION: the refusal must come from the directory-match arm, not an upstream
# precondition. abs_suffix_dir is the same fixture shape one directory component apart and it
# resolves, so it is the positive control proving the `/` guard is what refused this one.
assert_eq "#1618 skill-body: the bare-suffix body is refused by the no-following-body arm" "yes" \
  "$(sbl_build boundary_dir >/dev/null 2>&1; (cd "$LIB/.." && sbl_run "$SBL_TMP/exec.jsonl" --tier review --root "prflow:review=skills/review/SKILL.md") | grep -q 'no following body record naming its own' && echo yes || echo no)"

# Only the LEADING blank/`#` run is stripped: the caveat line and the blank after it go, while a
# `#` line INSIDE the file stays unparseable and forces unestablished. A stripper that dropped
# every `#` line would hide that corruption and report a clean read.
assert_eq "#1618 skill-body: a # line inside the file is not stripped -> unestablished" \
  "unestablished" "$(sbl interior_comment)"

# Empty selection MUST fail rather than report a clean pass — an audit that audited nothing
# reading as an audit that found nothing is this defect one level up. No --root -> exit !=0,
# NO-ROOTS, and never a delivered-whole line.
assert_eq "#1618 skill-body: empty selection (no --root) exits non-zero" "nonzero" \
  "$(sbl_run "$SBL_TMP/exec.jsonl" >/dev/null 2>&1 && echo zero || echo nonzero)"
assert_eq "#1618 skill-body: empty selection prints NO-ROOTS, not a clean pass" "yes" \
  "$(sbl_run "$SBL_TMP/exec.jsonl" | grep -q 'AUDIT: NO-ROOTS' && echo yes || echo no)"
# Exit-status gating is unavailable here (the no-roots path deliberately exits 2), so require the
# header PRESENT and the verdict line ABSENT from ONE capture: a traceback prints neither, so it
# fails the present half rather than passing on the absent one.
assert_eq "#1618 skill-body: empty selection prints NO-ROOTS and no delivered-whole verdict" "yes" \
  "$(_o="$(sbl_run "$SBL_TMP/exec.jsonl" 2>/dev/null)"; case "$_o" in *'AUDIT: NO-ROOTS'*) case "$_o" in *'VERDICT: delivered-whole'*) echo no ;; *) echo yes ;; esac ;; *) echo no ;; esac)"

# COUPLED SITES: the two workflow jobs and the helper are one contract. Each job must load
# the prflow plugin, capture the full output, invoke the helper, and audit BOTH engine roots
# at their real on-disk paths — a job that dropped a --root would silently measure nothing
# for that root while the suite stayed green.
assert_eq "#1618 skill-body: matcher-probe jobs and helper are coupled" "coupled" \
  "$(NO_COLOR=1 PYTHON_COLORS=0 python3 - "$LIB/../.github/workflows/matcher-probe.yml" <<'PY_SBL_COUPLED'
import sys, yaml
wf_path = sys.argv[1]
jobs = yaml.safe_load(open(wf_path, encoding="utf-8"))["jobs"] or {}
roots = {"prflow:review": "skills/review/SKILL.md", "prflow:implement": "skills/implement/SKILL.md"}
for job_name, tier in (("skill-body-load-review-probe", "review"),
                       ("skill-body-load-implement-probe", "implement")):
    job = jobs.get(job_name)
    if not job:
        print("matcher-probe.yml has no %s job" % job_name); sys.exit(0)
    steps = job.get("steps") or []
    claude = [s for s in steps if isinstance(s.get("with"), dict) and "claude_args" in s["with"]]
    if not claude:
        print("%s has no claude-code-action step" % job_name); sys.exit(0)
    with_ = claude[0]["with"]
    if with_.get("show_full_output") is not True:
        print("%s does not set show_full_output: true — the tool_result is not captured" % job_name)
        sys.exit(0)
    plugins = str(with_.get("plugins", ""))
    if "prflow@" not in plugins:
        print("%s does not load the prflow plugin, so the engine roots never load" % job_name)
        sys.exit(0)
    verdict_steps = [s for s in steps if "skill-body-load-probe-verdict.py" in str(s.get("run", ""))]
    if not verdict_steps:
        print("%s never invokes the verdict helper" % job_name); sys.exit(0)
    run = str(verdict_steps[0]["run"])
    for name, path in roots.items():
        if ("%s=%s" % (name, path)) not in run:
            print("%s verdict step does not audit root %s at %s" % (job_name, name, path))
            sys.exit(0)
    if ("--tier %s" % tier) not in run and ("--tier=%s" % tier) not in run:
        print("%s verdict step does not name its tier %s" % (job_name, tier)); sys.exit(0)
# The audited paths must be real files, or the on-disk control read is vacuous. Derive the
# repo root from the (normalized) workflow path: .github/workflows/matcher-probe.yml is three
# levels below the root.
import os
base = os.path.dirname(os.path.dirname(os.path.dirname(os.path.normpath(wf_path))))
for path in roots.values():
    if not os.path.isfile(os.path.join(base, path)):
        print("audited root path does not exist on disk: %s" % path); sys.exit(0)
print("coupled")
PY_SBL_COUPLED
)"
rm -rf "$SBL_TMP"

