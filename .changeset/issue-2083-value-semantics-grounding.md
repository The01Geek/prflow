---
bump: patch
type: Fixed
---

- **`/prflow:create-issue` now requires a Verified bullet asserting a data value's semantics to cite the code that establishes them.** A Verified premise claiming what a value *means* — an on/off pair, its wider state set, an enumeration's admitted values, nullability, or units — must now be grounded in a code site that reads the value and branches on it (a definition site such as a schema column, field declaration, or form binding no longer suffices), and the drafter must search the value's consuming sites for a wider domain before writing the claim. It narrows one claim class in the verified-claims quality group and is re-applied in the Step 3.5 steelman pass. (#2090)
