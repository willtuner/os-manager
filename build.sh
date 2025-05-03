#!/usr/bin/env bash
set -o errexit

# 1) Define a app
export FLASK_APP=app.py

# 2) Instala dependências
pip install --upgrade pip
pip install -r requirements.txt

# 3) Aplica migrations
flask db init 2>/dev/null || true
flask db migrate -m "Inicial: criar tabelas"
flask db upgrade

# 4) Extrai prestadores
python extract_prestadores.py
