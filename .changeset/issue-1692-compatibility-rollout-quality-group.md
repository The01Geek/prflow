---
bump: patch
type: Added
---

- **Gate compatibility and rollout decisions by applicability in `/prflow:create-issue`.** Added a sixth conditionally-loaded quality group, `references/quality-group-compatibility.md`, registered with the #1693 quality-guidance router. It loads only when a grounded change moves a supported-version boundary, alters a contract already used by existing data/config/consumers, spans independently upgraded components that can run at mixed versions, or introduces rollout behavior — resolving each touched support-boundary, transition, mixed-version, and rollback decision through the existing issue sections, with one consolidated clarification question reserved for a remaining load-bearing policy choice. Ordinary issues load no compatibility reference, gain no body section, and pay no added prompt bytes; the generic migration/coexistence evidence axis and the deployment-variance steelman keep their existing roles and forward compatibility *decisions* to the new group. (#1712)
