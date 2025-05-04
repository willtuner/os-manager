#!/usr/bin/env bash
set -o errexit
export FLASK_APP=app.py
pip install --upgrade pip
pip install -r requirements.txt
flask db upgrade --no-input
python extract_prestadores.py
