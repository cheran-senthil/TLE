#!/bin/bash

# Get to a predictable directory, the directory of this script
cd "$(dirname "$0")"

[ -e environment ] && . ./environment

if [[ -n "${VENV_DIR}" ]]; then
    echo "Activating virtual environment in ${VENV_DIR}."
    python3 -m venv "${VENV_DIR}"
    . "${VENV_DIR}/bin/activate"
fi

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
