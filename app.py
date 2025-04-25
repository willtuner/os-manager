from flask import Flask, render_template, request, redirect, session, url_for, flash, make_response
import json
import os
import csv
from datetime import datetime

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', os.urandom(24).hex())
app.config['SESSION_COOKIE_SECURE'] = True
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'

# Configuração de caminhos
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
MENSAGENS_DIR = os.path.join(BASE_DIR, 'mensagens_por_gerente')
FINALIZACOES_FILE = os.path.join(BASE_DIR, 'finalizacoes_os.csv')
USERS_FILE = os.path.join(BASE_DIR, 'users.json')

# Garante que a pasta exista
os.makedirs(MENSAGENS_DIR, exist_ok=True)

ADMIN_USERS = {
    "wilson.santana": "admin321"
}

def carregar_os_gerente(gerente):
    """Carrega a lista de OS pendentes do JSON do gerente."""
    nome_base = gerente.upper().replace('.', '_') + "_GONZAGA.json"
    caminho = os.path.join(MENSAGENS_DIR, nome_base)

    # fallback: qualquer arquivo que comece com o primeiro nome
    if not os.path.exists(caminho):
        primeiro = gerente.split('.')[0].upper()
        for f in os.listdir(MENSAGENS_DIR):
            if f.upper().startswith(primeiro) and f.lower().endswith('.json'):
                caminho = os.path.join(MENSAGENS_DIR, f)
                break

    if not os.path.exists(caminho):
        return []

    with open(caminho, encoding='utf-8') as f:
        dados = json.load(f)

    # normaliza nomes de campos
    os_list = []
    for item in dados:
        os_list.append({
            "os":          str(item.get("os") or item.get("OS", "")),
            "frota":       str(item.get("frota") or item.get("Frota", "")),
            "data":        str(item.get("data") or item.get("Data", "")),
            "dias":        str(item.get("dias") or item.get("Dias", "0")),
            "prestador":   str(item.get("prestador") or item.get("Prestador", "Prestador não definido")),
            "servico":     str(item.get("servico") or item.get("Servico") or item.get("observacao") or item.get("Observacao", ""))
        })
    return os_list

def salvar_os_gerente(gerente, lista_os):
    """Sobrescreve o JSON do gerente com a lista de OS pendentes."""
    nome_base = gerente.upper().replace('.', '_') + "_GONZAGA.json"
    caminho = os.path.join(MENSAGENS_DIR, nome_base)
    # tenta fallback também
    if not os.path.exists(caminho):
        primeiro = gerente.split('.')[0].upper()
        for f in os.listdir(MENSAGENS_DIR):
            if f.upper().startswith(primeiro) and f.lower().endswith('.json'):
                caminho = os.path.join(MENSAGENS_DIR, f)
                break

    with open(caminho, 'w', encoding='utf-8') as f:
        json.dump(lista_os, f, indent=2, ensure_ascii=False)

def registrar_finalizacao(os_numero, gerente, observacoes=""):
    """Anexa uma linha de finalização no CSV."""
    cabecalho = ["OS", "Gerente", "Data_Finalizacao", "Hora_Finalizacao", "Observacoes", "Data_Registro"]
    if not os.path.exists(FINALIZACOES_FILE):
        with open(FINALIZACOES_FILE, 'w', newline='', encoding='utf-8') as f:
            csv.writer(f).writerow(cabecalho)

    with open(FINALIZACOES_FILE, 'a', newline='', encoding='utf-8') as f:
        csv.writer(f).writerow([
            os_numero,
            gerente,
            datetime.now().strftime('%Y-%m-%d'),
            datetime.now().strftime('%H:%M'),
            observacoes,
            datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        ])

def contar_os_por_gerente():
    """Retorna um dict {gerente: total_finalizadas}."""
    cont = {}
    if os.path.exists(FINALIZACOES_FILE):
        with open(FINALIZACOES_FILE, encoding='utf-8') as f:
            for linha in csv.DictReader(f):
                g = linha.get("Gerente","Desconhecido")
                cont[g] = cont.get(g, 0) + 1
    return cont

def listar_gerentes_ativos():
    """Retorna lista de gerentes com JSON na pasta (mesmo sem finalizações)."""
    s = set(contar_os_por_gerente().keys())
    for f in os.listdir(MENSAGENS_DIR):
        if f.lower().endswith('.json'):
            nome = f.split('.json')[0].replace('_','.').lower()
            s.add(nome)
    return sorted(s)

@app.route("/")
def index():
    return redirect(url_for('login'))

@app.route("/login", methods=["GET","POST"])
def login():
    erro = None
    if request.method == "POST":
        gerente = request.form["gerente"].strip()
        senha   = request.form["senha"].strip()
        # admin?
        if ADMIN_USERS.get(gerente)==senha:
            session["gerente"] = gerente
            session["is_admin"] = True
            return redirect(url_for('admin_panel'))
        # usuários normais
        if os.path.exists(USERS_FILE):
            with open(USERS_FILE, encoding='utf-8') as f:
                users = json.load(f)
            if users.get(gerente)==senha:
                session["gerente"] = gerente
                session["is_admin"] = False
                return redirect(url_for('painel'))
        erro = "Credenciais inválidas"
        flash(erro, "danger")
    return render_template("login.html")

@app.route("/painel", methods=["GET","POST"])
def painel():
    if "gerente" not in session:
        return redirect(url_for('login'))
    gerente = session["gerente"]

    # POST = Finalizar OS
    if request.method=="POST":
        os_num  = request.form.get("os_numero")
        obs     = request.form.get("observacoes","")
        # registra no CSV
        registrar_finalizacao(os_num, gerente, obs)
        # remove da lista de pendentes
        pend = carregar_os_gerente(gerente)
        pend = [o for o in pend if str(o["os"])!=str(os_num)]
        salvar_os_gerente(gerente, pend)
        flash(f"OS {os_num} finalizada com sucesso","success")
        return redirect(url_for('painel'))

    # GET = exibir
    os_pendentes = carregar_os_gerente(gerente)
    return render_template("painel.html",
                           os_pendentes=os_pendentes,
                           gerente=gerente,
                           now=datetime.now())

@app.route("/admin")
def admin_panel():
    if "gerente" not in session or not session.get("is_admin"):
        flash("Acesso não autorizado","danger")
        return redirect(url_for('login'))
    # finalizadas
    finalizadas = []
    if os.path.exists(FINALIZACOES_FILE):
        with open(FINALIZACOES_FILE, encoding='utf-8') as f:
            finalizadas = list(csv.DictReader(f))
    return render_template("admin.html",
                           finalizadas=finalizadas,
                           total_os=len(finalizadas),
                           gerentes=listar_gerentes_ativos(),
                           contagem_gerentes=contar_os_por_gerente(),
                           os_abertas={g: len(carregar_os_gerente(g))
                                       for g in listar_gerentes_ativos()},
                           now=datetime.now())

@app.route("/exportar_os_finalizadas")
def exportar_os_finalizadas():
    if "gerente" not in session or not session.get("is_admin"):
        flash("Acesso não autorizado","danger")
        return redirect(url_for('login'))
    if not os.path.exists(FINALIZACOES_FILE):
        flash("Nenhuma OS finalizada para exportar","warning")
        return redirect(url_for('admin_panel'))
    with open(FINALIZACOES_FILE, encoding='utf-8') as f:
        dados = f.read()
    resp = make_response(dados)
    resp.headers["Content-Disposition"] = (
        f"attachment; filename=os_finalizadas_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
    )
    resp.headers["Content-Type"] = "text/csv"
    return resp

@app.route("/logout")
def logout():
    session.clear()
    flash("Você foi desconectado com sucesso","info")
    return redirect(url_for('login'))

if __name__ == "__main__":
    port = int(os.environ.get("PORT",10000))
    app.run(host="0.0.0.0", port=port, debug=True)
