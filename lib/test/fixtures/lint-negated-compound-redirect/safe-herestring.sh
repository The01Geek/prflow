#!/usr/bin/env bash
if ! { cat; } <<< "some in-memory data"; then echo fail; fi
