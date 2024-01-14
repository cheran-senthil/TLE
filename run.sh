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
    poetry install
    FONTCONFIG_FILE=$PWD/extra/fonts.conf poetry run python -m tle

    (( $? != 42 )) && break

    echo '==================================================================='
    echo '=                       Restarting                                ='
    echo '==================================================================='
done
