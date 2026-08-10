#!/usr/bin/env bash
f=/tmp/x
# negated-compound-redirect-ok: fixture demonstrating the escape hatch
if ! { printf 'hi\n'; } > "$f"; then echo fail; fi
