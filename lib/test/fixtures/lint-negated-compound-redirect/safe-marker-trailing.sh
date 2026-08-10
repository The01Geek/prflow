#!/usr/bin/env bash
f=/tmp/x
if ! { printf 'hi\n'; } > "$f"; then echo fail; fi  # negated-compound-redirect-ok: trailing-marker variant on the opener/close line
