#!/usr/bin/env bash
set -o errexit

# Configurações básicas
export FLASK_APP=app.py
export PYTHONPATH=/opt/render/project/src

# Atualiza pip e instala dependências
pip install --upgrade pip
pip install -r requirements.txt

# Executa migrações do banco de dados
if [ -d "migrations" ]; then
    flask db upgrade
else
    flask db init
    flask db migrate -m "Initial migration"
    flask db upgrade
fi
