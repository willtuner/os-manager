from flask import Flask, render_template, request, redirect, session, url_for, flash, send_file
import json
import os
import csv
from datetime import datetime
from fpdf import FPDF

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', os.urandom(24).hex())
app.config['SESSION_COOKIE_SECURE'] = True
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
MENSAGENS_DIR = os.path.join(BASE_DIR, 'mensagens_por_gerente')
FINALIZACOES_FILE = os.path.join(BASE_DIR, 'finalizacoes_os.csv')
USERS_FILE = os.path.join(BASE_DIR, 'users.json')

os.makedirs(MENSAGENS_DIR, exist_ok=True)

ADMIN_USERS = {
    "wilson.santana": "admin321"
}

def carregar_os_gerente(gerente):
    nome_base = gerente.upper().replace('.', '_') + "_GONZAGA.json"
    caminho = os.path.join(MENSAGENS_DIR, nome_base)
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
    resultado = []
    for item in dados:
        resultado.append({
            "os": str(item.get("os") or item.get("OS", "")),
            "frota": str(item.get("frota") or item.get("Frota", "")),
            "data": str(item.get("data") or item.get("Data", "")),
            "dias": str(item.get("dias") or item.get("Dias", "0")),
            "prestador": str(item.get("prestador") or item.get("Prestador", "Prestador não definido")),
            "servico": str(item.get("servico") or item.get("Servico") or item.get("observacao") or item.get("Observacao", ""))
        })
    return resultado

def registrar_finalizacao(os_numero, gerente, data, hora, observacoes=""):
    cabecalho = ["OS", "Gerente", "Data_Finalizacao", "Hora_Finalizacao", "Observacoes", "Data_Registro"]
    if not os.path.exists(FINALIZACOES_FILE):
        with open(FINALIZACOES_FILE, 'w', newline='', encoding='utf-8') as f:
            csv.writer(f).writerow(cabecalho)
    with open(FINALIZACOES_FILE, 'a', newline='', encoding='utf-8') as f:
        csv.writer(f).writerow([
            os_numero,
            gerente,
            data,
            hora,
            observacoes,
            datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        ])

def contar_os_por_gerente():
    cont = {}
    if os.path.exists(FINALIZACOES_FILE):
        with open(FINALIZACOES_FILE, encoding='utf-8') as f:
            for row in csv.DictReader(f):
                g = row.get("Gerente", "Desconhecido")
                cont[g] = cont.get(g, 0) + 1
    return cont

def listar_gerentes_ativos():
    gerentes = set(contar_os_por_gerente().keys())
    for f in os.listdir(MENSAGENS_DIR):
        if f.lower().endswith('.json'):
            nome = f.replace('_GONZAGA.json', '').replace('_', '.').lower()
            gerentes.add(nome)
    return sorted(gerentes)

@app.route("/")
def index():
    return redirect(url_for('login'))

@app.route("/login", methods=["GET", "POST"])
def login():
    erro = None
    if request.method == "POST":
        gerente = request.form["gerente"].strip().lower()
        senha = request.form["senha"].strip()
        if ADMIN_USERS.get(gerente) == senha:
            session["gerente"] = gerente
            session["is_admin"] = True
            return redirect(url_for('admin_panel'))
        if os.path.exists(USERS_FILE):
            with open(USERS_FILE, encoding='utf-8') as f:
                users = json.load(f)
            if users.get(gerente) == senha:
                session["gerente"] = gerente
                session["is_admin"] = False
                return redirect(url_for('painel'))
        erro = "Usuário ou senha inválidos"
        flash(erro, "danger")
    return render_template("login.html", erro=erro)

@app.route("/painel")
def painel():
    if "gerente" not in session:
        return redirect(url_for('login'))
    gerente = session["gerente"]
    os_pendentes = carregar_os_gerente(gerente)
    return render_template("painel.html",
                           os_pendentes=os_pendentes,
                           gerente=gerente,
                           now=datetime.now())

@app.route("/finalizar_os/<os_numero>", methods=["POST"])
def finalizar_os(os_numero):
    if "gerente" not in session:
        return redirect(url_for('login'))
    gerente = session["gerente"]
    data = request.form.get("data_finalizacao")
    hora = request.form.get("hora_finalizacao")
    obs = request.form.get("observacoes", "")
    registrar_finalizacao(os_numero, gerente, data, hora, obs)

    nome_base = gerente.upper().replace('.', '_') + "_GONZAGA.json"
    caminho = os.path.join(MENSAGENS_DIR, nome_base)
    if not os.path.exists(caminho):
        primeiro = gerente.split('.')[0].upper()
        for f in os.listdir(MENSAGENS_DIR):
            if f.upper().startswith(primeiro) and f.lower().endswith('.json'):
                caminho = os.path.join(MENSAGENS_DIR, f)
                break
    try:
        with open(caminho, encoding='utf-8') as f:
            dados = json.load(f)
        dados = [i for i in dados if str(i.get("os") or i.get("OS", "")) != str(os_numero)]
        with open(caminho, 'w', encoding='utf-8') as f:
            json.dump(dados, f, indent=2, ensure_ascii=False)
    except Exception as e:
        print(f"Erro ao atualizar JSON: {e}")

    flash(f"OS {os_numero} finalizada com sucesso", "success")
    return redirect(url_for('painel'))

@app.route("/admin")
def admin_panel():
    if "gerente" not in session or not session.get("is_admin"):
        flash("Acesso não autorizado", "danger")
        return redirect(url_for('login'))

    finalizadas = []
    if os.path.exists(FINALIZACOES_FILE):
        with open(FINALIZACOES_FILE, encoding='utf-8') as f:
            finalizadas = list(csv.DictReader(f))

    contagem = contar_os_por_gerente()
    ativos = listar_gerentes_ativos()
    abertas = {g: len(carregar_os_gerente(g)) for g in ativos}

    return render_template("admin.html",
                           finalizadas=finalizadas[-100:],
                           total_os=len(finalizadas),
                           gerentes=ativos,
                           contagem_gerentes=contagem,
                           os_abertas=abertas,
                           now=datetime.now())

@app.route("/logout")
def logout():
    session.clear()
    flash("Você foi desconectado com sucesso", "info")
    return redirect(url_for('login'))

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port, debug=True)
