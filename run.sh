#!/bin/bash

# Get to a predictable directory, the directory of this script
cd "$(dirname "$0")"

[ -e environment ] && . ./environment

while true; do
    
    # Contributers should pull from the original repo & push to the forked one
    # if the cloned repo is forked & upstream branch doesn't exist -> add upstream branch to Cheran's repo to pull updates
    # else if the remote branch already exists -> pull updates from the current branch
    # else pull from the cloned repo
    
    if ! [[ $(git remote -v | grep -E 'origin.*https://github.com/cheran-senthil/TLE.git') ]]; then # cloned repo is forked
	    if ! [[ $(git remote show | grep upstream) ]]; then # upstream remote branch doesn't exixt
		    echo "Adding upstream branch to author's repo"
		    git remote add upstream https://github.com/cheran-senthil/TLE.git 
	    fi
	    if [[ $(git remote -v | grep -E 'upstream.*https://github.com/cheran-senthil/TLE.git') ]]; then # upstream remote branch exists
		    echo "Pulling updates from author's repo"
		    git pull upstream $(git symbolic-ref --short HEAD)
	    fi
    else # pull updates from cloned repo remote branches
	    echo "Pulling updates"
	    git pull
    fi
    poetry install
    FONTCONFIG_FILE=$PWD/extra/fonts.conf poetry run python -m tle

    (( $? != 42 )) && break

    echo '==================================================================='
    echo '=                       Restarting                                ='
    echo '==================================================================='
done
