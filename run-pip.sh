#!/bin/bash

# Get to a predictable directory, the directory of this script
cd "$(dirname "$0")"

[ -e environment ] && . ./environment
python3 -m venv .venv
. .venv/bin/activate

while true; do
    git pull
    poetry export --without-hashes > requirements.txt
    python -m pip install --requirement requirements.txt
    FONTCONFIG_FILE=$PWD/extra/fonts.conf python -m tle

    (( $? != 42 )) && break

    echo '==================================================================='
    echo '=                       Restarting                                ='
    echo '==================================================================='
done
