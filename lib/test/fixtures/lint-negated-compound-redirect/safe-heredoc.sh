#!/usr/bin/env bash
if ! { cat; } <<EOF
hello
EOF
then echo fail; fi
