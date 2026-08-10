#!/usr/bin/env bash
if ! { printf 'oops\n'; } >&2; then echo fail; fi
