#!/bin/bash

# This is a script meant to run a full sync

declare -x BASE_PATH="~ec2-user/snyk-sync/"
declare -x PYTHON="${BASE_PATH}.venv/bin/python"
declare -x SNYK_SYNC="${BASE_PATH}snyk_sync/cli.py"

declare -x SYNC_WORKING_DIR="~ec2-user/config/"

eval "$($PYTHON ${BASE_PATH}scripts/export_aws_secrets.py)"

if ! [[ -d $SYNC_WORKING_DIR ]]; then
    git clone --depth 1 "${SYNC_CONFIG_REPO}" $SYNC_WORKING_DIR
    cd $SYNC_WORKING_DIR || exit
else
    cd $SYNC_WORKING_DIR || exit
    git fetch --depth 1 origin
fi