#!/usr/bin/env bash
f=/tmp/x
rc=0; { printf 'hi\n'; } > "$f" || rc=$?
[ "$rc" -ne 0 ] && echo fail
