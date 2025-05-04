#!/usr/bin/env bash
set -o errexit

# Configurações básicas
export FLASK_APP=app.py
export FLASK_ENV=production

# Atualiza pip e instala dependências
pip install --upgrade pip
pip install -r requirements.txt

# Inicializa e executa migrações do banco de dados
if [ ! -d "migrations" ]; then
    flask db init
fi

flask db migrate -m "Add is_prestador column"
flask db upgrade

# O Render executará automaticamente o gunicorn app:app
