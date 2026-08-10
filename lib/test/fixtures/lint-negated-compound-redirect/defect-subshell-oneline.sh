#!/usr/bin/env bash
f=/nonexistent/dir/x
if ! ( printf 'hi\n' ) >"$f"; then echo fail; fi
