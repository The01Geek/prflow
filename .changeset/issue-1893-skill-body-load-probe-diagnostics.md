---
bump: patch
type: Changed
---

- **The skill-body-load probe verdict helper now names the cause of a short delivery.**
  `scripts/skill-body-load-probe-verdict.py` gained a fourth verdict, `no-body`, ordered
  ahead of the tail-loss arm so a body-less tool result (such as the documented
  already-loaded short note) is no longer misreported as a lost tail. Each per-root report
  now also carries the delivered length, the first-divergence offset against the on-disk
  file, a present/absent result for each control line, and a byte-comparison of the served
  `SKILL.md` against the checkout copy (identical/differing/unreadable) — so a maintainer
  can read the cause from the probe log alone. (#1894)
