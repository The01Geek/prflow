#!/usr/bin/env bash
f=/nonexistent/dir/x
if ! { printf 'hi\n'; } 2>/dev/null > "$f"; then echo fail; fi
