#!/bin/bash

CWD=$(pwd)
# We want to safely delete only this scripts temp files, so we name them
TMP_DIR=$(mktemp -d -t install_snyk_tools.XXXXXXXXXX)


cd "${TMP_DIR}" || exit

curl -O -s -L "https://static.snyk.io/cli/latest/snyk-linux"
curl -O -s -L "https://static.snyk.io/cli/latest/snyk-linux.sha256"

if sha256sum -c snyk-linux.sha256; then
  mv snyk-linux /usr/local/bin/snyk
  chmod +x /usr/local/bin/snyk
else
  echo "Snyk Binary Download failed, exiting"
  exit 1
fi

curl -s https://api.github.com/repos/snyk-tech-services/snyk-api-import/releases/latest \
    | jq -c '.assets[] | select (.browser_download_url | contains ("linux")) | .browser_download_url' \
    | xargs -I snyk_url curl -s -L -O snyk_url 
    
if sha256sum -c snyk-api-import-linux.sha256; then
  mv snyk-api-import-linux /usr/local/bin/snyk-api-import
  chmod +x /usr/local/bin/snyk-api-import
else
  echo "Snyk API Import Binary Download failed, exiting"
  exit 1
fi


cd "${CWD}" || exit
