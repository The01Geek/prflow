# Release-note authoring is disabled in this repository

Skip the release-note authoring steps — Step 2 (Determine Customer-Visible Impact), Step 3 (Draft the Release Note Entry), Step 3b (Verify Every Factual Claim in the Draft Against the Code), and Step 4 (Append to Release Notes File): do not write a release note or modify the release notes file. Those entries are derived at merge time from `customer-visible: true` changesets by the version-consolidate workflow, so authoring one here would produce a duplicate.

Still run Step 4b (Reconcile the CHANGELOG Entry) — only the release-note-authoring half is disabled; skipping Step 4b would leave a stale CHANGELOG entry unreconciled.
