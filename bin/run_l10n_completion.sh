#!/bin/bash

# Run this from the project root--not this directory!
#
# Usage: run_l10n_completion.sh [PYTHON-BIN]

PYTHONBIN=$1

# check if file and dir are there
if [[ ! -f "$PYTHONBIN" ]]; then 
    PYTHONBIN=/usr/bin/python
fi

# Update .po files in svn
cd ./locale && svn up && cd ..

# Run l10n completion to calculate percent completed and update .json
# file; keep 90 days of data
$PYTHONBIN ./bin/l10n_completion.py --truncate 90 ./media/l10_completion.json ./locale/
