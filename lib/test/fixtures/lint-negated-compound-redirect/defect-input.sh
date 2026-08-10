#!/usr/bin/env bash
f=/nonexistent/dir/x
if ! { IFS= read -r v; } < "$f" 2>/dev/null; then echo fail; fi
