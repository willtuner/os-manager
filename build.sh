#!/usr/bin/env bash
set -o errexit

# 1) Aponta o Flask para o seu app
export FLASK_APP=app.py

# 2) Instala deps
pip install --upgrade pip
pip install -r requirements.txt

# 3) Executa migrations (cria tabelas na primeira vez e aplica futuras alterações)
flask db upgrade

# 4) Extrai OS dos prestadores
python extract_prestadores.py
