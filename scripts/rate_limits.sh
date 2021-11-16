#!/bin/bash

# this gets around how github actions pass us an args as just a single string

read -ra args <<< "$*"

/usr/local/bin/python /usr/local/bin/rate_limit_debug.py "${args[@]}"