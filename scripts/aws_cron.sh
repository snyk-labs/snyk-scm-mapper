#!/bin/bash

# This is a script meant to run a full sync in the context of an
# aws instance with sync installed in a python venv

declare -x HOMEDIR="/home/ec2-user/"
declare -x BASE_PATH="${HOMEDIR}snyk-scm-mapper/"
declare -x PYTHON="${BASE_PATH}.venv/bin/python"
declare -x SNYK_MAPPER="${BASE_PATH}snyk-scm-mapper/cli.py"

declare -x MAPPER_WORKING_DIR="${HOMEDIR}config/"

eval "$($PYTHON ${BASE_PATH}scripts/export_aws_secrets.py)"

if ! [[ -d $MAPPER_WORKING_DIR ]]; then
    git clone --depth 1 "${SYNC_CONFIG_REPO}" $MAPPER_WORKING_DIR
    cd $MAPPER_WORKING_DIR || exit
else
    cd $MAPPER_WORKING_DIR || exit
    git fetch --depth 1 origin
fi

function setup_crontab(){
    HERE=$PWD
    CRON_ENTRY=$(mktemp -d)

    cd "${CRON_ENTRY}" || exit
    
    crontab -l > temp_cron

    if ! grep -e "#snyk-scm-mapper-cron" temp_cron; then
        echo "#snyk-scm-mapper-cron" >> temp_cron
        cat "${MAPPER_WORKING_DIR}crontab-entry" >> temp_cron
        crontab temp_cron
    fi

    cd "${HERE}" || exit

    rm -rf "${CRON_ENTRY}"

}

function perform_sync(){
    cd "${MAPPER_WORKING_DIR}" || exit
    "${PYTHON}" "${SNYK_MAPPER}" sync
}

function generate_targets(){
    cd "${MAPPER_WORKING_DIR}" || exit
    "${PYTHON}" "${SNYK_MAPPER}" targets --save 
}

function update_tags(){
    cd "${MAPPER_WORKING_DIR}" || exit
    "${PYTHON}" "${SNYK_MAPPER}" tags --update
}

function perform_import(){

    readarray -t import_scripts < <(ls ${MAPPER_WORKING_DIR}scripts/imports/*.sh)

    for import_script in "${import_scripts[@]}"; do
        /bin/bash "${import_script}"
    done

}


if [[ -f "${MAPPER_WORKING_DIR}cron.sh" ]]; then
    /bin/bash "${MAPPER_WORKING_DIR}cron.sh"
else

    cd ${MAPPER_WORKING_DIR} || exit

    setup_crontab

    perform_sync
    
    generate_targets
    
    perform_import

    perform_sync

    update_tags

fi