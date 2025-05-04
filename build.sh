#!/usr/bin/env bash
set -o errexit

export FLASK_APP=app.py

pip install --upgrade pip
pip install -r requirements.txt

# extrai prestadores se tiver esse script
python extract_prestadores.py

# o Render vai chamar gunicorn app:app automaticamente
