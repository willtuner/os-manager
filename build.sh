#!/usr/bin/env bash
# exit on error
set -o errexit

pip install --upgrade pip
pip install --force-reinstall numpy==1.24.3
pip install -r requirements.txt
