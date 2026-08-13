# Canonical eligibility predicate for issue-body projection records.
def projection_eligible:
  (.projection_disposition == "represented")
  and ((.unmatched_desired_behavior | type) == "array")
  and ((.unmatched_desired_behavior | length) == 0);

projection_eligible
