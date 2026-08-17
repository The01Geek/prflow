---
bump: patch
---

Phase 2.3.0a (peer-checkpoint completeness) now classifies the rule a change adds before enumerating its peer set, and enumerates a peer set defined by control flow by tracing the swept unit's call edges instead of searching for a shared marker.

A rule quantified over the paths through a unit of code — "every terminating path writes an outcome line", "every early return releases the lock" — has peers a shared-marker search structurally cannot reach: a path that terminates inside a helper the unit calls is spelled nowhere in that unit's own text. The sweep previously enumerated by search alone and closed on a match count, so such a rule produced positive evidence that no missing sites existed.

The amended sweep adds a step-0 classification that routes a control-flow property to a call-edge trace, a textually co-locatable peer set to the unchanged shared-marker search, a rule that is both to both arms, and an unclassifiable rule to the trace bounded to direct call edges. The trace states its own bound, so a cycle and a mutually recursive pair terminate. An unresolvable call edge routes to the sweep's existing unrunnable record form, naming the covering backstop, and suppresses the clean evidence note. The traced arm records the unit it ranged over and the reach of the technique — including the edge kinds reading the source cannot enumerate — so a traced note is distinguishable from a searched one and neither reads as a closed set it has not established.
