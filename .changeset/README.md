# Changesets

PRFlow versions itself with **changesets** instead of editing `.claude-plugin/plugin.json`
and `CHANGELOG.md` directly in every PR. Because each changeset is a uniquely-named file,
two concurrent PRs never touch a shared line, so the version/CHANGELOG merge conflicts that
used to tax every concurrent PR are gone.

## How to add a changeset

Any PR that reaches consumer repos as an update — a fix, feature, or breaking change to the
engine surface (`skills/`, `agents/`, `lib/`, `scripts/`, the workflows, the config schema) —
adds **one** file here and does **not** edit `plugin.json` or `CHANGELOG.md`. Internal-only
changes (tests, CI, dev-only docs) add no changeset.

Create `.changeset/<unique-name>.md` — name it after the branch or issue so it never collides,
e.g. `issue-290-changeset-versioning.md`:

```markdown
---
bump: patch
type: Fixed
---

- **One-line summary of the change.** A short paragraph of Keep-a-Changelog prose describing
  what changed and why, ending with the PR citation. (#290)
```

### Frontmatter

- `bump` (**required**) — one of `patch`, `minor`, `major`. Use the smallest step; choose
  `minor`/`major` only when the issue explicitly authorizes the larger increment. There is no
  package name — PRFlow ships one plugin, so the npm `"pkg": patch` form is not used.
- `type` (optional, default `Changed`) — the Keep-a-Changelog section the prose lands under:
  `Added`, `Changed`, `Deprecated`, `Removed`, `Fixed`, or `Security`.

### Body

Everything after the closing `---` is the changelog prose, copied verbatim into the entry.
Write it as one or more `-` bullets and cite the PR number (`(#123)`) so the assembled
CHANGELOG entry stays PR-cited.

## What happens on merge

When your PR merges to `main`, the `version-consolidate` GitHub Action
([`.github/workflows/version-consolidate.yml`](../.github/workflows/version-consolidate.yml)) runs
[`scripts/consolidate-changesets.py`](../scripts/consolidate-changesets.py). The script:

1. reads every pending `.changeset/*.md` (only this `README.md` is ignored — every other
   `*.md` here is treated as a changeset, so a stray file with no valid frontmatter fails
   the run loudly rather than being silently skipped),
2. bumps `plugin.json`'s `version` by the **highest** pending bump type (patch < minor < major)
   — one increment even when several changesets are pending,
3. prepends a dated, PR-cited Keep-a-Changelog entry assembled from all the pending prose, and
4. deletes the consumed changeset files.

The workflow then stages those changes and commits them back to `main` with a
`chore: bump version` subject (the script itself makes no `git` calls).

A malformed changeset (missing/invalid `bump`, unparseable frontmatter, empty prose) fails the
Action loudly, naming the offending file — it is never silently skipped, and no partial write
lands.

The test suite catches such a malformed changeset **before** merge, too: it parses every tracked
`.changeset/*.md` with the same parser the consolidator uses, so a bad frontmatter (e.g. the npm
`"pkg": patch` form) turns the suite RED at the desk and in CI rather than only aborting
`version-consolidate` after merge.
