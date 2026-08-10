#!/usr/bin/env bash
f=/tmp/x
if ! { printf 'hi\n' > "$f"; }; then echo fail; fi
