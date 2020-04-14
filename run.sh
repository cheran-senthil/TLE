#!/bin/sh

# Get to a predictable directory, the directory of this script
cd "$(dirname "$0")"

[ -e environment ] && . ./environment

while true; do
    # Make sure the following command doesn't need credentials.
    # You can store your credentials using: git config --global credential.helper store
    git remote set-url origin "$ORIGIN_URI"
    git fetch origin
    git reset --hard "$COMMIT_HASH"

    FONTCONFIG_FILE=$PWD/extra/fonts.conf poetry run python -m tle

    (( $? != 42 )) && break

    echo '==================================================================='
    echo '=                       Restarting                                ='
    echo '==================================================================='
done
