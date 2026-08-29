# Documentation

This directory holds the source for **<https://prflow.ai>** under `external/`, plus
the note below.

## Why this file exists

This file is not optional.

Every released version of PRFlow's cloud vendoring action copies a fixed set of
root members out of a clone of this repository before pruning the ones it does
not need:

```
.claude-plugin/  agents/  docs/  lib/  scripts/  skills/  LICENSES/
```

`docs/` is copied and then deleted. That copy is unconditional in every
generation of the action shipped to date, so removing `docs/` from this
repository would make an already-installed consumer's vendoring step fail before
it ever reaches its own prune. This file keeps that path present.

Do not delete this directory.
