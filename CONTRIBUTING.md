# Contributing to PRFlow

Thank you for wanting to help. Please read this first, because the mechanics here
differ from most repositories.

## This repository is a generated release

`main` in this repository is a **release projection**, not the development tree.
Every file here is produced by a deterministic exporter from a private canonical
source repository and published as a reviewed, versioned release. Nothing is
authored directly on this branch.

That has one practical consequence: **a pull request that edits these files
cannot be merged as-is.** The next release would overwrite it. This is not a
judgement about the change — it is how the publication pipeline works.

The required `distribution-verify` check runs on your pull request and should be
green. It verifies published releases against the digests in `.release/`, and an
ordinary pull request is not a release — so a passing check says nothing about
whether the change will be accepted.

## What to do instead

**Report a bug, ask a question, or request a feature.** Open an issue. Issues are
read, triaged and acted on here. This is the most useful thing you can do, and
it is the supported channel.

**Propose a specific code change.** Open a pull request anyway, and say in the
description what problem it solves. A maintainer will reproduce the change in the
canonical source, credit you, and ship it in a subsequent release. The PR itself
will then be closed with a link to the release that carries your change. Please
do not take the close as a rejection.

**Report a security vulnerability.** Do not open a public issue. Follow
[SECURITY.md](./SECURITY.md).

## What you can verify here

Everything shipped here is readable source. Each release also carries its own
provenance and integrity data under `.release/`:

- `.release/source.json` — the release's version, the source commit it was built
  from, and the payload's file and byte counts.
- `.release/files.sha256` — a SHA-256 for every published file.

You can check any published tree against those digests yourself, and the
repository's own verification workflow does exactly that on every release.

## Releases

Releases are periodic and human-approved rather than continuous. Every version
gets an immutable `vX.Y.Z` tag. Release notes are published at
<https://prflow.ai> and in this repository's GitHub Releases.
