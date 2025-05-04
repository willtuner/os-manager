#!/usr/bin/env bash
set -o errexit

# Configurações básicas
export FLASK_APP=app.py

# Atualiza pip e instala dependências
pip install --upgrade pip
pip install -r requirements.txt

# Executa migrações do banco de dados (opcional)
flask db upgrade

# O Render executará automaticamente o gunicorn app:app
