---
title: "Review Settings"
description: "Configure review verdicts, fix routing, progress and legacy automatic-review controls."
---

Tune the shared review engine and the local review-and-fix loop to match your repository's risk and verification needs.

## Review Engine

| **Setting** | **Type and accepted values** | **Fallback or scaffold** | **Tier and security note** | **Example** |
| --- | --- | --- | --- | --- |
| `prflow_review.verdict_severity_threshold` | `critical`, `important` or `suggestion` | `critical` | Standalone review and review-and-fix review pass. Lowering the threshold makes more findings reject. | `"verdict_severity_threshold": "critical"` |
| `prflow_review.live_progress_comment_enabled` | Boolean | `true` | Pull-request review. When true, each run maintains its own progress comment. Comment writes are best effort. | `"live_progress_comment_enabled": true` |
| `prflow_review.stale_prose.enabled` | Boolean | Fallback `true`; scaffold: `false`. Anything except explicit false enables | Shared review engine. Fresh installs scaffold this off, because the check is tuned to prose idioms that are common in the PRFlow repository itself and its false-positive suppression channel only works for bot-authored review comments. Set it to true to enable the automatic check for prose that contains stale numeric claims. | `"enabled": false` |
| `prflow_review.stale_prose.severity` | `critical`, `important` or `suggestion` | `important` | Shared review engine. The chosen severity participates in verdict computation. | `"severity": "important"` |
| `review_status_labels.enabled` | Boolean | `false`; only the JSON boolean `true` or the string `"true"` enables | Cloud pull-request review. Off by default, so no label request is made unless you opt in. When on, a cloud review keeps one managed label — `PRFlow:Reviewing`, `PRFlow:Approved`, `PRFlow:ChangesRequested` or `PRFlow:ReviewFailed` — on the pull request and each issue it closes, so review state is visible from the issue and pull-request lists. Best-effort: label errors never change a run's outcome, and unmanaged labels are left in place. Local reviews and review-and-fix runs write no label. | `"review_status_labels": { "enabled": true }` |

<Note>
  `prflow_review.stale_prose.enabled` is the second place where the scaffolded file and the fallback disagree. `/prflow:init` writes `false`, while an absent key resolves to `true`. Set the value explicitly rather than deleting the key.
</Note>

## Review and Fix

| **Setting** | **Type and accepted values** | **Fallback or scaffold** | **Tier and security note** | **Example** |
| --- | --- | --- | --- | --- |
| `prflow_review_and_fix.fix_severity_threshold` | `critical`, `important` or `suggestion` | `important` | Local review-and-fix and implementation's inline fix loop. Findings severe enough to cause a rejection remain eligible for correction at every value. | `"fix_severity_threshold": "important"` |
| `prflow_review_and_fix.fix_below_threshold_iterations` | Integer zero or greater | `1` | Local review-and-fix and implementation's inline fix loop. Only affects a repository that set `fix_severity_threshold` to `suggestion`; at the default threshold no below-`important` findings are admitted, so this key has no effect. Below-`important` findings route to the fixer only during this many leading iterations; after that window, an iteration with no Critical or Important finding parks each below-`important` finding as advisory. Set at or above `max_iterations` to restore the previous behavior; set `0` to park below-`important` findings from the first iteration. Findings that drove a rejection always route regardless. | `"fix_below_threshold_iterations": 1` |
| `prflow_review_and_fix.max_iterations` | Integer one or greater | `5`; values below one clamp to one | Review-and-fix. Higher values can increase cost. | `"max_iterations": 5` |
| `prflow_review_and_fix.efficiency_telemetry_enabled` | Boolean | `true` | Review-and-fix. False disables the effectiveness record and prevents denied-command records from being persisted on the telemetry branch. | `"efficiency_telemetry_enabled": true` |
| `prflow_review_and_fix.efficiency_cut_candidate_min_dispatch` | Integer one or greater | `3` | Cross-run analysis. It is recorded for later analysis and does not cut an agent during the current run. | `"efficiency_cut_candidate_min_dispatch": 3` |
| `receiving_review.fix_severity_threshold` | `critical`, `important` or `suggestion` | `critical` | Direct use of the fix skill only. The review-and-fix loop uses its own threshold. | `"fix_severity_threshold": "critical"` |

## Valid Review Example

```json
{
  "prflow_review": {
    "verdict_severity_threshold": "critical",
    "live_progress_comment_enabled": true,
    "stale_prose": {
      "enabled": false,
      "severity": "important"
    }
  },
  "prflow_review_and_fix": {
    "fix_severity_threshold": "important",
    "fix_below_threshold_iterations": 1,
    "max_iterations": 5,
    "efficiency_telemetry_enabled": true
  },
  "receiving_review": {
    "fix_severity_threshold": "critical"
  }
}
```

Expected result: a review rejects only on a critical finding, the fix loop corrects findings of important severity or worse and stops after at most five iterations, and each run keeps its own progress comment on the pull request.

To add house review rules that no setting expresses, such as a pattern your reviewers must always flag, write a [prompt extension](/docs/configuration/skill-extensions) for `review` and `review-and-fix`.

## Removed Automatic-Review Settings and the Retained Backstop

Fresh installs do not include automatic pull-request-triggered review. The `prflow_review.require_up_to_date`, `prflow_review.require_ci_green`, and every `prflow_runner` setting were removed from the shipped schema and example (issue #2071), and `install.sh` strips them from a consumer's `.prflow/config.json` on every apply. They are read only in a repository that still carries the withheld tier, and only until its next installer apply removes them. The `prflow_review.stall_backstop` settings are **not** part of that removed set — they remain, because the stall backstop is live.

| **Setting** | **Type and accepted values** | **Fallback** | **Status and security note** | **Example** |
| --- | --- | --- | --- | --- |
| `prflow_review.require_up_to_date` | Boolean | `true` | **Removed** (issue #2071): gone from the shipped schema/example and stripped on the next installer apply. Read only where the withheld tier remains installed. | `"require_up_to_date": true` |
| `prflow_review.require_ci_green` | Boolean | `true` | **Removed** (issue #2071): gone from the shipped schema/example and stripped on the next installer apply. Read only where the withheld tier remains installed. | `"require_ci_green": true` |
| `prflow_review.stall_backstop.enabled` | Boolean | `true` | Retained and live. Failure-recovery resume also needs an App and allowed bot identity. | `"enabled": true` |
| `prflow_review.stall_backstop.max_resume_attempts` | Integer zero or greater | `2` | Retained and live. `0` disables resume while retaining detection. | `"max_resume_attempts": 2` |
| `prflow_runner.effort` | `low`, `medium`, `high`, `xhigh` or `max` | absent runtime fallback: `high` | **Removed** (issue #2071): the whole `prflow_runner` section left the schema/example and is stripped on the next installer apply. Where the withheld runner is still installed, an absent key resolves to `high`. | `"effort": "low"` |
| `prflow_runner.provision_env` | Boolean | Runtime false | **Removed** (issue #2071); stripped on the next installer apply. Where the withheld runner is still installed, enabling it runs pull-request code with provisioned tools under a privileged workflow. | `"provision_env": false` |

The other `prflow_runner` settings — provider and allowed-tool — were removed by the same change; they are listed in [Model Providers](/docs/configuration/providers) and [Tool Permissions](/docs/configuration/tool-permissions).

## Remove the Withdrawn Automatic-Review Tier

If your repository installed PRFlow before this tier was withdrawn, the workflow files are still there and still run. The installer leaves them alone by default and prints a notice about them on every upgrade.

<Warning>
  While those files remain and the review toggle is true, the withdrawn tier keeps running. It triggers on pull-request events, calls a reusable workflow with inherited secrets, checks out the pull request's own code and applies no check on who started the run. Remove it unless you have a specific reason to keep it.
</Warning>

To remove it, re-run the installer with the opt-in flag. An upgrade run is a preview by default, so pass `--apply` as well:

```bash
DEVFLOW_REF=<ref> bash devflow-install.sh --apply --remove-withheld-review-tier
```

For a `curl | bash` invocation that cannot pass arguments, set `DEVFLOW_REMOVE_WITHHELD_REVIEW_TIER=1` instead.

Expected result: the installer deletes the withdrawn workflow files and sets the review toggle to `false` under whichever spelling your config carries.

<Warning>
  One step is yours, and no installer can do it. Remove the `Devflow Review` context from every branch protection rule or ruleset that requires it. If you leave it required, every later pull request waits forever on a check that nothing will report.
</Warning>

Do the branch-protection change in the same sitting as the removal. See [Automatic Review](/docs/runs/cloud/auto-review) for what the shipped alternative looks like, and [Human Control](/docs/concepts/human-control) for who may start a review today.
