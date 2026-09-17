#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2026 Daniel Radman
# SPDX-License-Identifier: MIT
# migrate-consumer-tier1.sh — the ATOMIC consumer-side devflow -> prflow migration
# (issue #1002). One helper, called by both entry points (`/prflow:init` and
# `install.sh`) so the two can never drift, exactly as scripts/scaffold-config.sh
# is the one scaffolder.
#
# WHAT IT MIGRATES — the four members of the atomic unit, enumerated in
# lib/rename-map.json's `atomic_unit` and NEVER transcribed here:
#   1. the state directory      .devflow/ -> .prflow/ (and vendor/devflow -> vendor/prflow)
#   2. the workflow contents    every .github/workflows/*.yml naming a superseded literal
#   3. the marketplace source   .claude-plugin/marketplace.json's local plugin source
#   4. the plugin version pin   devflow_version -> prflow_version, advanced to --pin
#
# WHY IT IS ALL-OR-NOTHING. The shipped workflows invoke bundled helpers at the
# vendored path as repo-relative LEADING TOKENS, and the cloud allowlist grants are
# per-literal-path. So a half-moved tree is not merely broken: every helper
# invocation is silently DENIED rather than loudly failing, and the run ends with no
# verdict. A migration that can half-apply is worse than no migration, because the
# consumer's next install.sh run deep-merges template defaults into the gap and
# makes the breakage permanent and quiet.
#
# THE FAIL DIRECTION IS DELIBERATELY INVERTED FOR THE APPLY. Most helpers in this
# repository are best-effort: they log and continue. This one refuses. Every
# precondition for ALL FOUR members is checked before anything is written, and a
# single unsatisfiable member refuses the whole set, leaving the repository
# byte-identical. That inversion is the acceptance criterion, not an oversight — do
# not "fix" it into log-and-continue. The REPORT stays best-effort: it never stops
# the caller, which keeps `/prflow:init`'s standing nothing-blocks-init ethos intact
# (init reads this helper's report and carries on either way).
#
# Usage: migrate-consumer-tier1.sh [--apply] [--pin REF] [TARGET_REPO_ROOT]
#   (no flag)   PREVIEW: classify, plan, validate, and report. Writes NOTHING.
#   --apply     perform the migration, or refuse and change nothing.
#   --pin REF   the ref to stamp into the migrated version pin. REQUIRED for
#               --apply when the pin member applies: a migrated tree against a
#               pre-rename pin vendors a plugin that resolves the superseded
#               layout, which is the exact skew this helper exists to prevent.
#   --pin-from-plugin
#               resolve that ref from THIS plugin tree's own .claude-plugin/plugin.json
#               version, as `v<version>`. This is the one operand the scaffolder could
#               not have: a running plugin knows its own published version, and a
#               version that contains this migration is by construction a ref that
#               contains the rename. Refuses (never guesses) when the manifest cannot
#               be read. `--pin` wins when both are given.
#   TARGET_REPO_ROOT  default: git toplevel, else cwd.
#
# Exit codes:
#   0  migrated, or a no-op (already migrated / not a consumer), or a clean preview
#   1  REFUSED — a member could not be applied; the repository is unchanged
#   2  bad arguments, or a prerequisite (python3, the rename map) is unavailable
set -euo pipefail

log() { printf 'prflow-migrate: %s\n' "$1"; }
die() { printf 'prflow-migrate: %s\n' "$1" >&2; exit 2; }

# Self-directory anchor, in the dirname-free spelling: `dirname` is not a preflight-
# guaranteed tool, and this form is also one the closure scanner can prove.
SELF_DIR="$(cd "${BASH_SOURCE[0]%/*}" && pwd)"
RENAME_MAP="$SELF_DIR/../lib/rename-map.json"

MODE=preview
PIN=""
PIN_FROM_PLUGIN=0
TARGET_ROOT=""
while [ $# -gt 0 ]; do
  case "$1" in
    --apply) MODE=apply ;;
    --preview) MODE=preview ;;
    --pin)
      [ $# -ge 2 ] || die "--pin needs a value"
      PIN="$2"; shift ;;
    --pin=*) PIN="${1#--pin=}" ;;
    --pin-from-plugin) PIN_FROM_PLUGIN=1 ;;
    -*) die "unknown argument $1 (accepted: --apply, --preview, --pin REF, --pin-from-plugin)" ;;
    *)
      [ -z "$TARGET_ROOT" ] || die "unexpected extra argument $1"
      TARGET_ROOT="$1" ;;
  esac
  shift
done
[ -n "$TARGET_ROOT" ] || TARGET_ROOT="$(git rev-parse --show-toplevel 2>/dev/null || pwd)"

# Resolve the pin from this plugin's own manifest when asked. An explicit --pin still
# wins; a manifest that cannot be read leaves PIN empty, and the validate stage then
# refuses the whole set rather than stamping a guess.
if [ "$PIN_FROM_PLUGIN" = "1" ] && [ -z "$PIN" ]; then
  PIN="$(PRFLOW_MANIFEST="$SELF_DIR/../.claude-plugin/plugin.json" python3 -c '
import json, os, sys
sys.stdout.reconfigure(newline="\n")
try:
    with open(os.environ["PRFLOW_MANIFEST"], encoding="utf-8") as fh:
        version = json.load(fh)["version"]
except Exception:
    sys.exit(0)
if isinstance(version, str) and version:
    sys.stdout.write("v" + version)
' 2>/dev/null || true)"
  if [ -z "$PIN" ]; then
    log "could not read this plugin manifest version for --pin-from-plugin; the version-pin member will refuse rather than stamp a guessed ref."
  fi
fi

# CLASSIFY IN BASH, BEFORE requiring anything. A repository with no superseded state
# directory has nothing to migrate, and that answer must not depend on python3 or on the
# rename map being readable: a FIRST-TIME install on a python3-less host would otherwise
# be refused here, and install.sh's shared fate would then skip the workflow copy loop
# for a repository that never needed migrating at all. `[ -d ]` is the whole test, and it
# is a shell builtin.
if [ ! -d "$TARGET_ROOT/.devflow" ]; then
  if [ -d "$TARGET_ROOT/.prflow" ]; then
    log "ALREADY MIGRATED $TARGET_ROOT/.prflow is present and no superseded .devflow/ remains; nothing was changed."
  else
    log "NOTHING TO MIGRATE no state directory at $TARGET_ROOT/.devflow or $TARGET_ROOT/.prflow — this is a first-time install, not an un-migrated consumer."
  fi
  exit 0
fi

[ -f "$RENAME_MAP" ] || die "rename map not found at $RENAME_MAP (is the plugin install complete?)"
command -v python3 >/dev/null 2>&1 || die "python3 is required to migrate; nothing was changed."

# The whole plan/validate/stage/commit engine. Kept in one python program because
# every step reads or writes structured data and the commit needs a rollback
# journal — expressing that in shell would fragment the one decision this helper
# exists to make. Bash owns only argument parsing and the exit code.
PRFLOW_MIGRATE_TIER1_PY='
import json, os, re, shutil, sys
sys.stdout.reconfigure(newline="\n")

root, mode, pin, map_path = sys.argv[1:5]

with open(map_path, encoding="utf-8") as fh:
    RMAP = json.load(fh)
STATE = RMAP["paths"]["state_dir"]
VENDOR = RMAP["paths"]["vendor_dir"]
RENAMES = RMAP["config_keys"]
MEMBERS = [row["id"] for row in RMAP["atomic_unit"]]
RETAINED = RMAP["retained_unshipped_workflows"]

OLD_DIR = os.path.join(root, STATE["superseded"])
NEW_DIR = os.path.join(root, STATE["current"])
STAGE = os.path.join(root, STATE["current"] + ".migrate-stage")
JOURNAL = os.path.join(root, STATE["current"] + ".migrate-journal")

report = []
blockers = []
unmigratable = []


def say(line):
    report.append(line)


# ---------------------------------------------------------------- rewrite rules
# The same closed rule set the repository-side rename used. Each carries explicit
# negative context so a name this text rewrite must not touch is never rewritten:
# the lookbehind on `workflows` leaves the workflows.devflow /
# workflows["devflow-review"] sub-keys ALONE, and the lookahead on the key rule
# rejects a longer identifier that merely STARTS with one of the six brand-named
# suffixes (devflow_review_thing, say). The workflows.* sub-keys are NOT frozen
# (issue #1041 renamed them to workflows.prflow / workflows.prflow-review), but
# they migrate ONLY under the fail-closed freshness gate in
# scripts/scaffold-config.sh, which coordinates the config rename with the
# workflow reads: a bare text rewrite here would move the config key while a stale
# workflow still read the old one and silently disable it. Two shapes need no guard
# because no rule can match them at all: workflows["devflow-review"] carries no
# literal `.devflow` for DIR_RE and does not close the quote right after devflow for
# BARE_RE, and the devflow_module_pin_* harness functions fall outside the closed
# alternation in KEY_RE. The genuinely frozen workflow FILENAMES are untouched too.
KEY_RE = re.compile(r"\bdevflow_(version|implement|runner|review_and_fix|review|retrospective)(?![A-Za-z0-9_])")
DIR_RE = re.compile(r"(?<!workflows)\.devflow(?![A-Za-z])")
VENDOR_RE = re.compile(re.escape(VENDOR["superseded"]))
BARE_RE = re.compile(r"(\"workflows\"\s*:\s*\{\s*)?\"devflow\"(\s*):")


def _bare(m):
    if m.group(1):
        return m.group(0)
    return "\"prflow\"" + m.group(2) + ":"


def rewrite(text):
    text = VENDOR_RE.sub(VENDOR["current"], text)
    text = KEY_RE.sub(lambda m: "prflow_" + m.group(1), text)
    text = DIR_RE.sub(STATE["current"], text)
    text = BARE_RE.sub(_bare, text)
    return text


def stale(text):
    return text != rewrite(text)


# ---------------------------------------------------------------- 1. classify
old_present = os.path.isdir(OLD_DIR)
new_present = os.path.exists(NEW_DIR) or os.path.islink(NEW_DIR)

if os.path.exists(JOURNAL):
    say("REFUSED a previous run left a commit journal at " + JOURNAL
        + " — it was interrupted between writes, so this tree is in an unknown"
        + " state. Inspect it, finish or undo the listed steps by hand, delete the"
        + " journal, then re-run.")
    print("\n".join(report))
    sys.exit(1)

if not old_present and not new_present:
    say("NOTHING TO MIGRATE no state directory at " + OLD_DIR + " or " + NEW_DIR
        + " — this is a first-time install, not an un-migrated consumer.")
    print("\n".join(report))
    sys.exit(0)

if not old_present and new_present:
    say("ALREADY MIGRATED " + NEW_DIR + " is present and no superseded "
        + STATE["superseded"] + "/ remains; nothing was changed.")
    print("\n".join(report))
    sys.exit(0)

if old_present and new_present:
    say("REFUSED both " + OLD_DIR + " and " + NEW_DIR + " are present, so this"
        + " tree is mid-migration or was migrated by hand. Refusing rather than"
        + " moving one inside the other. Resolve it by hand — merge the two"
        + " directories into " + NEW_DIR + " and delete " + OLD_DIR + ", or delete"
        + " the incomplete " + NEW_DIR + " and re-run.")
    print("\n".join(report))
    sys.exit(1)

# ---------------------------------------------------------------- 2. plan
plan = {}

plan["state-dir-move"] = {"from": OLD_DIR, "to": NEW_DIR}

wf_dir = os.path.join(root, ".github", "workflows")
wf_targets = []
if os.path.isdir(wf_dir):
    for name in sorted(os.listdir(wf_dir)):
        if not name.endswith((".yml", ".yaml")):
            continue
        path = os.path.join(wf_dir, name)
        if not os.path.isfile(path):
            continue
        try:
            with open(path, encoding="utf-8") as fh:
                text = fh.read()
        except Exception as exc:
            blockers.append("workflow-content-rewrite: cannot read " + path + " (" + str(exc) + ")")
            continue
        if stale(text):
            wf_targets.append((path, text))
if wf_targets:
    plan["workflow-content-rewrite"] = {"files": [p for p, _ in wf_targets]}

mkt = os.path.join(root, ".claude-plugin", "marketplace.json")
mkt_text = None
if os.path.isfile(mkt):
    try:
        with open(mkt, encoding="utf-8") as fh:
            mkt_text = fh.read()
    except Exception as exc:
        blockers.append("marketplace-source-rewrite: cannot read " + mkt + " (" + str(exc) + ")")
    else:
        if stale(mkt_text):
            plan["marketplace-source-rewrite"] = {"file": mkt}

cfg_path = os.path.join(OLD_DIR, "config.json")
cfg = None
if os.path.isfile(cfg_path):
    try:
        with open(cfg_path, encoding="utf-8") as fh:
            cfg = json.load(fh)
    except Exception as exc:
        blockers.append("version-pin-advance: cannot parse " + cfg_path + " (" + str(exc) + ")")
    else:
        if isinstance(cfg, dict) and ("devflow_version" in cfg or "prflow_version" in cfg):
            plan["version-pin-advance"] = {"file": cfg_path}

# ---------------------------------------------------------------- 3. validate
# Every applicable member, checked BEFORE anything is written. A single
# unsatisfiable member refuses the whole set.
def writable(path):
    return os.access(path, os.W_OK)


if "state-dir-move" in plan:
    if not writable(root):
        blockers.append("state-dir-move: " + root + " is not writable")
    if not writable(OLD_DIR):
        blockers.append("state-dir-move: " + OLD_DIR + " is not writable")
    if os.path.exists(STAGE):
        blockers.append("state-dir-move: a staging path already exists at " + STAGE
                        + " (a previous run left it behind) — remove it and re-run")

for path, _ in wf_targets:
    if not writable(path):
        blockers.append("workflow-content-rewrite: " + path + " is not writable")

if "marketplace-source-rewrite" in plan:
    if not writable(mkt):
        blockers.append("marketplace-source-rewrite: " + mkt + " is not writable")
    else:
        try:
            json.loads(mkt_text)
        except Exception as exc:
            blockers.append("marketplace-source-rewrite: " + mkt
                            + " is not valid JSON (" + str(exc) + ")")

if "version-pin-advance" in plan:
    if not writable(cfg_path):
        blockers.append("version-pin-advance: " + cfg_path + " is not writable")
    if mode == "apply" and not pin:
        blockers.append("version-pin-advance: no --pin ref was supplied. Migrating the"
                        + " tree while leaving the pin on a pre-rename ref would vendor a"
                        + " plugin that resolves the superseded layout against a migrated"
                        + " tree, so every bundled-helper invocation would fail to resolve")

# ---------------------------------------------------------------- report the plan
say(("PREVIEW " if mode != "apply" else "PLAN ")
    + "the atomic unit has " + str(len(MEMBERS)) + " members; "
    + str(len(plan)) + " apply to this repository.")
for member in MEMBERS:
    if member in plan:
        detail = plan[member]
        if member == "state-dir-move":
            say("  will migrate  " + member + ": " + detail["from"] + " -> " + detail["to"])
        elif member == "workflow-content-rewrite":
            say("  will migrate  " + member + ": " + ", ".join(detail["files"]))
        elif member == "marketplace-source-rewrite":
            say("  will migrate  " + member + ": " + detail["file"])
        else:
            # Name every key this member renames, not just the pin. The member also
            # carries the other six top-level renames across, and a report that
            # advertised only the pin would leave the largest part of the config diff
            # unannounced on the one step that asks the operator to review it.
            renamed = sorted(k for k in RENAMES if k in (cfg or {}))
            say("  will migrate  " + member + ": " + detail["file"])
            if renamed:
                say("      config keys renamed: "
                    + ", ".join(k + " -> " + RENAMES[k] for k in renamed))
            say("      version pin: devflow_version -> prflow_version"
                + (", value -> " + pin if pin else " (no --pin supplied)"))
    else:
        say("  not present   " + member + ": nothing in this repository carries it.")

# Items this helper cannot migrate, named individually (never as a class).
for name in RETAINED:
    path = os.path.join(wf_dir, name)
    if os.path.isfile(path):
        try:
            with open(path, encoding="utf-8") as fh:
                retained_text = fh.read()
        except Exception:
            retained_text = ""
        if retained_text and stale(retained_text):
            unmigratable.append(
                name + " is present in .github/workflows/ and names the superseded"
                + " layout. install.sh does not ship it, so no installer run can"
                + " refresh it; it is rewritten here with the other workflow files,"
                + " but nothing can keep it current afterwards. Review or remove it.")

if blockers:
    say("REFUSED " + str(len(blockers)) + " member(s) of the atomic unit cannot be"
        + " applied, so NONE of them were. The repository is unchanged.")
    for b in blockers:
        say("  blocked  " + b)
    for u in unmigratable:
        say("  could not migrate  " + u)
    print("\n".join(report))
    sys.exit(1)

if mode != "apply":
    say("PREVIEW COMPLETE nothing was written. Re-run with --apply to perform the"
        + " migration; it applies every member above or none of them.")
    for u in unmigratable:
        say("  could not migrate  " + u)
    print("\n".join(report))
    sys.exit(0)

# ---------------------------------------------------------------- 4. stage
# Render every new byte into a staging directory beside the destination. Beside,
# not in $TMPDIR: `os.replace` and `os.rename` are atomic only within one
# filesystem, and a staging root under /tmp with a target under $HOME can be two.
staged = {}
try:
    os.makedirs(STAGE, exist_ok=False)
    n = 0
    for path, text in wf_targets:
        dest = os.path.join(STAGE, "wf-%d" % n); n += 1
        with open(dest, "w", encoding="utf-8") as fh:
            fh.write(rewrite(text))
        staged[path] = dest
    if "marketplace-source-rewrite" in plan:
        dest = os.path.join(STAGE, "marketplace.json")
        with open(dest, "w", encoding="utf-8") as fh:
            fh.write(rewrite(mkt_text))
        staged[mkt] = dest
except Exception as exc:
    shutil.rmtree(STAGE, ignore_errors=True)
    say("REFUSED staging failed before anything was written to the repository ("
        + str(exc) + "). The repository is unchanged.")
    print("\n".join(report))
    sys.exit(1)

# Verify the staged bytes against the declared expectation before committing: a
# staged file that is still stale would commit the very skew this refuses.
for target, src in staged.items():
    with open(src, encoding="utf-8") as fh:
        if stale(fh.read()):
            shutil.rmtree(STAGE, ignore_errors=True)
            say("REFUSED the staged replacement for " + target + " still names the"
                + " superseded layout; refusing to commit a partial rewrite. The"
                + " repository is unchanged.")
            print("\n".join(report))
            sys.exit(1)

# ---------------------------------------------------------------- 5. commit
# The destructive window. Every step is recorded in a journal BEFORE it runs and
# the journal is removed only after the last step succeeds, so a crash inside the
# window is detectable (and refused) on the next run rather than silently half-done.
done = []


def journal(step):
    with open(JOURNAL, "a", encoding="utf-8") as fh:
        fh.write(step + "\n")


def rollback():
    for step, payload in reversed(done):
        try:
            if step == "move":
                os.rename(payload[1], payload[0])
            elif step == "swap":
                os.replace(payload[1], payload[0])
        except Exception:
            pass


try:
    journal("move " + OLD_DIR + " -> " + NEW_DIR)
    os.rename(OLD_DIR, NEW_DIR)
    done.append(("move", (OLD_DIR, NEW_DIR)))

    inner_old = os.path.join(root, VENDOR["superseded"].replace(
        STATE["superseded"], STATE["current"], 1))
    inner_new = os.path.join(root, VENDOR["current"])
    if os.path.isdir(inner_old) and not os.path.exists(inner_new):
        journal("move " + inner_old + " -> " + inner_new)
        os.rename(inner_old, inner_new)
        done.append(("move", (inner_old, inner_new)))

    for target, src in staged.items():
        backup = src + ".orig"
        shutil.copy2(target, backup)
        journal("swap " + target)
        os.replace(src, target)
        done.append(("swap", (target, backup)))

    if "version-pin-advance" in plan:
        migrated_cfg = os.path.join(NEW_DIR, "config.json")
        with open(migrated_cfg, encoding="utf-8") as fh:
            data = json.load(fh)
        out = {}
        for key, value in data.items():
            new_key = RENAMES.get(key, key)
            out[new_key] = value
        out["prflow_version"] = pin
        tmp = migrated_cfg + ".migrate-tmp"
        backup = os.path.join(STAGE, "config.json.orig")
        shutil.copy2(migrated_cfg, backup)
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(out, fh, indent=2)
            fh.write("\n")
        journal("swap " + migrated_cfg)
        os.replace(tmp, migrated_cfg)
        done.append(("swap", (migrated_cfg, backup)))
except Exception as exc:
    rollback()
    shutil.rmtree(STAGE, ignore_errors=True)
    try:
        os.remove(JOURNAL)
    except OSError:
        pass
    say("REFUSED a write failed mid-commit (" + str(exc) + "); every completed step"
        + " was undone and the repository is back at its pre-run state. Verify with"
        + " `git status` before re-running.")
    print("\n".join(report))
    sys.exit(1)

shutil.rmtree(STAGE, ignore_errors=True)
os.remove(JOURNAL)

say("APPLIED every member of the atomic unit landed together.")
for u in unmigratable:
    say("  could not migrate  " + u)
say("Review the diff before committing: the state directory moved, so this is a"
    + " large but purely mechanical rename.")
print("\n".join(report))
sys.exit(0)
'

set +e
OUT="$(python3 -c "$PRFLOW_MIGRATE_TIER1_PY" "$TARGET_ROOT" "$MODE" "$PIN" "$RENAME_MAP" 2>&1)"
RC=$?
set -e
printf '%s\n' "$OUT" | while IFS= read -r line; do
  [ -n "$line" ] && log "$line"
done
exit "$RC"
