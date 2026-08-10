#!/usr/bin/env bash
f=/tmp/x
if ! ( : > "$f" ) 2>/dev/null; then echo fail; fi
