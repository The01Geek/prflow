# Test-suite probe conventions

A **rendered-output probe** is a test that runs a command as a child process and matches
against the text that command renders — a `--help` surface, a usage line, a stderr
diagnostic, a formatted report. This page is the repository's single statement of the
colour convention for those probes.

## Neutralise terminal colour for the child process

**A rendered-output probe you add, and an existing one your change touches, neutralises
terminal colour for the child process it spawns.** Without it the probe reads whatever
the host's environment tells the child to render, so the same tree gives different
answers on a machine that forces colour and on one that does not.

The variables that do it are **`PYTHON_COLORS=0`** and **`NO_COLOR=1`**. Set both. Each
was measured to override a forced-colour setting on its own, and `PYTHON_COLORS` alone is
the narrower guard — it reaches Python's own rendering, while `NO_COLOR` is the
cross-language convention a non-Python child also honours. The repository's help probe in
`lib/test/modules/issue-audit-state.sh` sets both; the harness sites in
`lib/test/module-harness.sh` predate this convention and set `PYTHON_COLORS` only, which
suffices there because every child they neutralise is a Python one.

Neutralise by environment variable rather than by stripping escape sequences out of the
captured text. Two remedies in one file for one hazard is the confusion this page exists
to remove.

- **A shell probe** puts the assignment on the invocation, as
  `lib/test/modules/issue-audit-state.sh` does:
  `NO_COLOR=1 PYTHON_COLORS=0 python3 "$IAS" --help`.
- **A Python probe** assigns into `os.environ` at module scope, above the file's first
  child-process invocation, as `lib/test/test_python_scripts.py` does. Assigning into
  the mapping the children inherit — rather than passing `env=` on the individual
  calls — covers the file's existing probes and any added later, and it holds however
  the file was invoked. A statement placed below an earlier child leaves that child inheriting
  the host's setting, which is why the placement is asserted in that file and not only
  the values.
- **The shared harness** (`lib/test/module-harness.sh`) already exports `PYTHON_COLORS=0`
  around the Python suites it runs, so a suite is neutralised when run through a suite
  runner whether or not it neutralises itself. That is not a substitute: the direct
  invocation — the form the project's own instructions mandate for a focused Python
  test — bypasses the harness entirely.

## The sanctioned exception

`lib/test/modules/regenerate-artifacts.sh` deliberately does the opposite: its
`_ra_tool_has_flag` matcher **tolerates the escape byte** rather than removing it,
accepting either an escape or a space as the boundary character after a flag token. It
is a deliberate exception, not an oversight, and it is not to be converted.

## Scope

This convention governs **new** rendered-output probes and **existing ones a change
touches**. The rendered-output probes already in the tree were not audited when this page
was written, so a probe that predates it and that no change has touched may still read
colour from its host.
