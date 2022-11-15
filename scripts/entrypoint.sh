#!/bin/bash

# this gets around how github actions pass us an args as just a single string

read -ra args <<< "$*"

if [[ -f "${PWD}/custom-ca.crt" ]]; then
    export REQUESTS_CA_BUNDLE="${PWD}/custom-ca.crt"
    export NODE_EXTRA_CA_CERTS="${PWD}/custom-ca.crt"
fi

/usr/local/bin/python /app/snyk_scm_mapper/cli.py "${args[@]}"