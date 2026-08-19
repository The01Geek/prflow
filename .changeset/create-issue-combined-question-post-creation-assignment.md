---
bump: patch
---

Restructure the create-issue Step 4 question flow: the former sub-steps 3a/3b/3c (audit-round offer, file-anyway election, approve-and-assign) collapse into one combined decision question whose mutually exclusive options are run-a-fresh-context-audit-round, create-it-as-is (which is the explicit approval, and carries any file-anyway election as a named ground when a gate refuses the bytes), and change-something-first. Self-assignment moves after creation: issues are always created unassigned, and the assignment question is asked once in sub-step 6's single post-creation pause — alongside the implement offer when its gate holds, alone when it is withheld — assigning best-effort via REST on an explicit yes and never stalling on silence.
