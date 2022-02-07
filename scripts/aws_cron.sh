#!/bin/bash

# This is a script meant to run a full sync

declare -x HOMEDIR="/home/ec2-user/"
declare -x BASE_PATH="${HOMEDIR}snyk-sync/"
declare -x PYTHON="${BASE_PATH}.venv/bin/python"
declare -x SNYK_SYNC="${BASE_PATH}snyk_sync/cli.py"

declare -x SYNC_WORKING_DIR="${HOMEDIR}config/"

eval "$($PYTHON ${BASE_PATH}scripts/export_aws_secrets.py)"

if ! [[ -d $SYNC_WORKING_DIR ]]; then
    git clone --depth 1 "${SYNC_CONFIG_REPO}" $SYNC_WORKING_DIR
    cd $SYNC_WORKING_DIR || exit
else
    cd $SYNC_WORKING_DIR || exit
    git fetch --depth 1 origin
fi

function setup_crontab(){
    CRON_ENTRY=$(mktemp -d)

    cd "${CRON_ENTRY}" || exit
    
    crontab -l > temp_cron

    if ! grep -e "#snyk-sync-cron" temp_cron; then
        echo "#snyk-sync-cron" >> temp_cron
        cat "${SYNC_WORKING_DIR}crontab-entry" >> temp_cron
        crontab -u ec2-user temp_cron
    fi

    cd "${BASE_PATH}" || exit

    rm -rf "${CRON_ENTRY}"

}

function perform_sync(){
    "${PYTHON}" "${SNYK_SYNC}" sync
}

function generate_targets(){
    "${PYTHON}" "${SNYK_SYNC}" targets --save 
}

function update_tags(){
    "${PYTHON}" "${SNYK_SYNC}" tags --update
}

function perform_import(){

    readarray -t import_scripts < <(find "${SYNC_WORKING_DIR}scripts/imports" -type f -name "\*.sh")

    for import_script in "${import_scripts[@]}"; do
        /bin/bash "${import_script}"
    done

}


if [[ -f SYNC_WORKING_DIR="${SYNC_WORKING_DIR}cron.sh" ]]; then
    /bin/bash "${SYNC_WORKING_DIR}cron.sh"
else

    setup_crontab

    perform_sync
    
    generate_targets
    
    perform_import

    perform_sync

    update_tags

fi