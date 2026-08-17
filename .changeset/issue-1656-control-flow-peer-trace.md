---
bump: patch
---

Phase 2.3.0a (peer-checkpoint completeness) now classifies the rule a change adds before enumerating its peer set, and enumerates a peer set defined by control flow by tracing the swept unit's call edges instead of searching for a shared marker.

A rule quantified over the paths through a unit of code — "every terminating path writes an outcome line" — has peers a shared-marker search structurally cannot reach, because a path terminating inside a helper the unit calls is spelled nowhere in that unit's own text. Enumerating by search alone and closing on a match count therefore produced positive evidence that no missing sites existed.

A step-0 classification now routes a control-flow property to the trace, a textually co-locatable peer set to the unchanged search, a rule that is both to both arms, and an unclassifiable rule to the trace bounded to direct call edges. The trace states its own bound, so a cycle and a mutually recursive pair terminate. An unresolvable call edge takes the existing unrunnable arm and suppresses the clean note, and the traced arm records the unit it ranged over plus the edge kinds reading the source cannot enumerate — so a traced note stays distinguishable from a searched one and neither reads as a closed set it has not established.
