import os
import json
import re
from collections import defaultdict

def slugify(name):
    s = name.strip().upper()
    s = re.sub(r'[ÀÁÂÃÄÅ]', 'A', s)
    s = re.sub(r'[ÈÉÊË]', 'E', s)
    s = re.sub(r'[ÍÌÎÏ]', 'I', s)
    s = re.sub(r'[ÓÒÔÕÖ]', 'O', s)
    s = re.sub(r'[ÚÙÛÜ]', 'U', s)
    s = re.sub(r'[^A-Z0-9]+', '.', s)
    s = re.sub(r'\.+', '.', s).strip('.')
    return s.lower()

def extract_prestadores():
    BASE = os.path.dirname(__file__)
    GERENTES_DIR = os.path.join(BASE, 'mensagens_por_gerente')
    PRESTADORES_DIR = os.path.join(BASE, 'mensagens_por_prestador')
    os.makedirs(PRESTADORES_DIR, exist_ok=True)

    por_prestador = defaultdict(list)
    for fn in os.listdir(GERENTES_DIR):
        if not fn.lower().endswith('.json'):
            continue
        path = os.path.join(GERENTES_DIR, fn)
        with open(path, encoding='utf-8') as f:
            dados = json.load(f)
        for item in dados:
            prest = item.get('prestador') or item.get('Prestador')
            if not prest:
                continue
            por_prestador[prest.strip().upper()].append(item)

    for prest, lista in por_prestador.items():
        slug = slugify(prest)
        out_path = os.path.join(PRESTADORES_DIR, f"{slug}.json")
        with open(out_path, 'w', encoding='utf-8') as f:
            json.dump(lista, f, ensure_ascii=False, indent=2)
        print(f"Gerado {out_path} com {len(lista)} OS")

# Permite executar o script diretamente
if __name__ == '__main__':
    extract_prestadores()
