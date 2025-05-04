#!/usr/bin/env bash
set -o errexit

# 1) Exporta o FLASK_APP para que o CLI "flask db" funcione
export FLASK_APP=app.py

# 2) Instala dependências
pip install --upgrade pip
pip install -r requirements.txt

# 3) Executa migrações (no primeiro deploy cria a pasta migrations)
flask db init 2>/dev/null || true
flask db migrate -m "Inicial: criar tabelas"
flask db upgrade

# 4) Extrai prestadores, se tiver script
python extract_prestadores.py

# 5) Pronto — o Render vai rodar 'gunicorn app:app' automaticamente
