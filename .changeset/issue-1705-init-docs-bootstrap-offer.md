---
bump: patch
---

`/prflow:init` now checks the documentation tree and offers to bootstrap internal docs (#1707).

A new consent-gated step, placed immediately before the advisory project-memory check, reads the `.docs.internal` and `.docs.external` locations from config, classifies each (holds real content / empty / absent / could-not-establish) by reading the working tree, and — when internal docs are missing — explains what internal and external documentation are and offers to dispatch one subagent running `/prflow:docs-bootstrap-internal` in the checkout, scoped to write only under the internal docs location and to run no version-control command. It never runs the external bootstrap and commits nothing. The rename-sweep and setup-enrichment prose were condensed to keep the skill under its size ceiling.
