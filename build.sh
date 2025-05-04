#!/usr/bin/env bash
set -o errexit

# 1) Exporta o FLASK_APP para que o CLI "flask db" funcione
export FLASK_APP=app.py

# 2) Instala dependências
pip install --upgrade pip
pip install -r requirements.txt

# 3) Executa migrações (só inicializa a pasta migrations se ainda não existir)
if [ ! -d migrations ]; then
  flask db init
fi
flask db migrate --no-input -m "Inicial: criar tabelas"
flask db upgrade --no-input

# 4) Extrai prestadores, se tiver script
python extract_prestadores.py
