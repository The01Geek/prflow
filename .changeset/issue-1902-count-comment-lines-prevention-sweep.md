---
bump: patch
type: Changed
---

- **The Prevention comment sweep now counts comment lines on its normal path.** Section 2.3.4a
  item 7 of the implement skill applies the section 2.3 line-count procedure to every comment a
  change adds or changes and logs each comment's line count beside its disposition, so a comment
  that names a wrong change it prevents but exceeds the three-line cap is caught while it is still
  being written rather than shipped over the cap. The cap and its counting procedure keep their
  single definition in the section 2.3 preamble, cited by pointer; the three absolute carve-outs
  stay binding and a carve-out-covered comment is exempt from the count. (#1924)
