# Third-party components

PRFlow itself is MIT-licensed (see [`LICENSE`](../LICENSE), © 2026 Daniel Radman). It also
redistributes the files listed below, which were authored by others and remain under their own
upstream licenses. The full upstream license texts are retained verbatim in this directory.

**Every file listed here has been modified by PRFlow relative to its upstream version.** This
statement is the Apache License 2.0 §4(b) change notice for the Apache-licensed files below; each
of those files additionally carries its own in-file notice. PRFlow's first-party SPDX header (the
`2026 Daniel Radman` line carried by PRFlow-authored source) is deliberately **not** applied over
this third-party content.

These files are redistributed in two ways: the plugin is published from the repository root
(`.claude-plugin/marketplace.json` declares `"source": "./"`), and
`.github/actions/vendor-plugin/vendor-slice.sh` copies the tree — including this `LICENSES/`
directory — into consumer repositories.

The **Last reconciled against** column in each table below records the upstream revision the row's
vendored file was last compared against during a reconciliation pass — a `superpowers` release for the
superpowers-derived files, or a `claude-plugins-official` commit SHA for the Anthropic-plugin agents,
which ship no version field. Where a reconciliation adopted nothing, that revision doubles as the
explicit no-change record, and it is the starting point a future refresh diffs from. No automated
drift check maintains it; refreshing it is a manual pass.

## Apache License 2.0

Copyright © Anthropic PBC. Licensed under the Apache License, Version 2.0.

Upstream carries no per-file copyright notices and ships no `NOTICE` file, so §4(c) and §4(d)
impose no retained content; the holder is named here instead, since the Apache appendix boilerplate
in the license texts is unfilled.

| PRFlow path | Upstream project | Upstream license text | Last reconciled against |
|---|---|---|---|
| `agents/code-architect.md` | [`feature-dev`](https://github.com/anthropics/claude-plugins-official/tree/main/plugins/feature-dev) | [`feature-dev-LICENSE`](feature-dev-LICENSE) | `claude-plugins-official` `b819188d2eea14e0400556ca29dbd1179a7c595b` |
| `agents/code-explorer.md` | [`feature-dev`](https://github.com/anthropics/claude-plugins-official/tree/main/plugins/feature-dev) | [`feature-dev-LICENSE`](feature-dev-LICENSE) | `claude-plugins-official` `b819188d2eea14e0400556ca29dbd1179a7c595b` |
| `agents/code-reviewer.md` | [`pr-review-toolkit`](https://github.com/anthropics/claude-plugins-official/tree/main/plugins/pr-review-toolkit) | [`pr-review-toolkit-LICENSE`](pr-review-toolkit-LICENSE) | `claude-plugins-official` `b819188d2eea14e0400556ca29dbd1179a7c595b` |
| `agents/comment-analyzer.md` | [`pr-review-toolkit`](https://github.com/anthropics/claude-plugins-official/tree/main/plugins/pr-review-toolkit) | [`pr-review-toolkit-LICENSE`](pr-review-toolkit-LICENSE) | `claude-plugins-official` `b819188d2eea14e0400556ca29dbd1179a7c595b` |
| `agents/pr-test-analyzer.md` | [`pr-review-toolkit`](https://github.com/anthropics/claude-plugins-official/tree/main/plugins/pr-review-toolkit) | [`pr-review-toolkit-LICENSE`](pr-review-toolkit-LICENSE) | `claude-plugins-official` `b819188d2eea14e0400556ca29dbd1179a7c595b` |
| `agents/silent-failure-hunter.md` | [`pr-review-toolkit`](https://github.com/anthropics/claude-plugins-official/tree/main/plugins/pr-review-toolkit) | [`pr-review-toolkit-LICENSE`](pr-review-toolkit-LICENSE) | `claude-plugins-official` `b819188d2eea14e0400556ca29dbd1179a7c595b` |
| `agents/type-design-analyzer.md` | [`pr-review-toolkit`](https://github.com/anthropics/claude-plugins-official/tree/main/plugins/pr-review-toolkit) | [`pr-review-toolkit-LICENSE`](pr-review-toolkit-LICENSE) | `claude-plugins-official` `b819188d2eea14e0400556ca29dbd1179a7c595b` |

Both plugins live in [`anthropics/claude-plugins-official`](https://github.com/anthropics/claude-plugins-official).
`feature-dev-LICENSE` and `pr-review-toolkit-LICENSE` are byte-identical to each other and to that
repository's `LICENSE`; they are kept as two files so each vendored slice has a license text named
for its own upstream project.

## MIT License

Copyright © 2025 Jesse Vincent. Licensed under the MIT License.

| PRFlow path | Upstream project | Upstream license text | Last reconciled against |
|---|---|---|---|
| `skills/fix/SKILL.md` | [`superpowers`](https://github.com/obra/superpowers) | [`superpowers-LICENSE`](superpowers-LICENSE) | `superpowers 6.3.0` |
| `skills/requesting-code-review/SKILL.md` | [`superpowers`](https://github.com/obra/superpowers) | [`superpowers-LICENSE`](superpowers-LICENSE) | `superpowers 6.3.0` |
| `skills/requesting-code-review/code-reviewer.md` | [`superpowers`](https://github.com/obra/superpowers) | [`superpowers-LICENSE`](superpowers-LICENSE) | `superpowers 6.3.0` |
