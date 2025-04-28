#!/usr/bin/env bash
set -o errexit

# 1) Cria / ativa o ambiente
export FLASK_APP=app.py

# 2) Instala o pip e deps
pip install --upgrade pip
pip install -r requirements.txt

# 3) Inicializa e aplica migrations (sem erro se já inicializado)
flask db init 2>/dev/null || true
flask db migrate -m "Inicial: criar tabelas"
flask db upgrade
