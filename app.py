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

# Diretórios e arquivos
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
MENSAGENS_DIR = os.path.join(BASE_DIR, 'mensagens_por_gerente')
FINALIZACOES_FILE = os.path.join(BASE_DIR, 'finalizacoes_os.csv')
USERS_FILE = os.path.join(BASE_DIR, 'users.json')

# Garante que a pasta de mensagens exista
os.makedirs(MENSAGENS_DIR, exist_ok=True)

ADMIN_USERS = {
    "wilson.santana": "admin321"
}

def carregar_os_gerente(gerente):
    """
    Busca o arquivo JSON do gerente, tenta variações de nome,
    e carrega a lista de OS.
    """
    try:
        nome_base = gerente.upper().replace('.', '_') + "_GONZAGA.json"
        caminho = os.path.join(MENSAGENS_DIR, nome_base)

        if not os.path.exists(caminho):
            primeiro_nome = gerente.split('.')[0].upper()
            for f in os.listdir(MENSAGENS_DIR):
                if f.startswith(primeiro_nome) and f.endswith('.json'):
                    caminho = os.path.join(MENSAGENS_DIR, f)
                    break

        if os.path.exists(caminho):
            with open(caminho, 'r', encoding='utf-8') as f:
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
    except Exception as e:
        print(f"Erro ao carregar OS para {gerente}: {e}")
    return []

def registrar_finalizacao(os_numero, gerente, observacoes=""):
    """
    Anexa uma linha de finalização no CSV.
    """
    cabeçalho = ["OS", "Gerente", "Data_Finalizacao", "Hora_Finalizacao", "Observacoes", "Data_Registro"]
    if not os.path.exists(FINALIZACOES_FILE):
        with open(FINALIZACOES_FILE, 'w', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            writer.writerow(cabeçalho)

    with open(FINALIZACOES_FILE, 'a', newline='', encoding='utf-8') as f:
        writer = csv.writer(f)
        writer.writerow([
            os_numero,
            gerente,
            datetime.now().strftime('%Y-%m-%d'),
            datetime.now().strftime('%H:%M'),
            observacoes,
            datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        ])

def contar_os_por_gerente():
    """
    Conta quantas OS cada gerente finalizou.
    """
    contagem = {}
    if os.path.exists(FINALIZACOES_FILE):
        with open(FINALIZACOES_FILE, encoding='utf-8') as f:
            reader = csv.DictReader(f)
            for row in reader:
                g = row.get("Gerente", "Desconhecido")
                contagem[g] = contagem.get(g, 0) + 1
    return contagem

def listar_gerentes_ativos():
    """
    Lista gerentes que possuem JSON ou já finalizaram ao menos uma OS.
    """
    gerentes = set(contar_os_por_gerente().keys())
    for f in os.listdir(MENSAGENS_DIR):
        if f.endswith('.json'):
            nome = f.replace('_GONZAGA.json', '').replace('_', '.').lower()
            gerentes.add(nome)
    return sorted(gerentes)

@app.route("/")
def index():
    return redirect(url_for('login'))

@app.route("/login", methods=["GET","POST"])
def login():
    erro = None
    if request.method == "POST":
        gerente = request.form["gerente"].strip()
        senha = request.form["senha"].strip()

        # Admin?
        if gerente in ADMIN_USERS and ADMIN_USERS[gerente] == senha:
            session["gerente"] = gerente
            session["is_admin"] = True
            return redirect(url_for('admin_panel'))

        # Usuário normal
        if os.path.exists(USERS_FILE):
            with open(USERS_FILE, encoding='utf-8') as f:
                users = json.load(f)
            if users.get(gerente) == senha:
                session["gerente"] = gerente
                session["is_admin"] = False
                return redirect(url_for('painel'))

        erro = "Usuário ou senha inválidos"
    return render_template("login.html", erro=erro)

@app.route("/painel", methods=["GET","POST"])
def painel():
    if "gerente" not in session:
        return redirect(url_for('login'))
    gerente = session["gerente"]
    os_pendentes = carregar_os_gerente(gerente)

    # exibe sem botão de exportar, data/hora em branco no template
    return render_template("painel.html", os_pendentes=os_pendentes, gerente=gerente, now=datetime.now())

@app.route("/finalizar_os/<os_numero>", methods=["POST"])
def finalizar_os(os_numero):
    if "gerente" not in session:
        return redirect(url_for('login'))

    gerente = session["gerente"]

    # 1) Registrar no CSV
    registrar_finalizacao(os_numero, gerente, request.form.get("observacoes", ""))

    # 2) Remover a OS do JSON do gerente
    # localiza o arquivo JSON
    nome_base = gerente.upper().replace('.', '_') + "_GONZAGA.json"
    caminho = os.path.join(MENSAGENS_DIR, nome_base)
    if not os.path.exists(caminho):
        primeiro = gerente.split('.')[0].upper()
        for f in os.listdir(MENSAGENS_DIR):
            if f.startswith(primeiro) and f.endswith('.json'):
                caminho = os.path.join(MENSAGENS_DIR, f)
                break

    try:
        with open(caminho, 'r', encoding='utf-8') as f:
            dados = json.load(f)
        # filtra a OS removendo a finalizada
        dados = [item for item in dados if str(item.get("os") or item.get("OS","")) != str(os_numero)]
        with open(caminho, 'w', encoding='utf-8') as f:
            json.dump(dados, f, indent=2, ensure_ascii=False)
    except Exception as e:
        print(f"Erro ao atualizar JSON após finalizar OS: {e}")

    flash(f"OS {os_numero} finalizada com sucesso", "success")
    return redirect(url_for('painel'))


@app.route("/admin")
def admin_panel():
    if "gerente" not in session or not session.get("is_admin"):
        flash("Acesso não autorizado", "danger")
        return redirect(url_for('login'))

    # carrega finalizações e contagens
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

@app.route("/exportar_os_finalizadas")
def exportar_os_finalizadas():
    if "gerente" not in session or not session.get("is_admin"):
        flash("Acesso não autorizado", "danger")
        return redirect(url_for('login'))

    # lê todas as finalizações
    finalizadas = []
    if os.path.exists(FINALIZACOES_FILE):
        with open(FINALIZACOES_FILE, encoding='utf-8') as f:
            finalizadas = list(csv.DictReader(f))

    if not finalizadas:
        flash("Nenhuma OS finalizada para exportar", "warning")
        return redirect(url_for('admin_panel'))

    # gera PDF
    os.makedirs("/tmp/relatorios", exist_ok=True)
    pdf_path = "/tmp/relatorios/relatorio_finalizacoes.pdf"

    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Arial", "B", 12)
    pdf.cell(0, 10, "Relatório de OS Finalizadas", ln=True, align='C')
    pdf.ln(5)

    # cabeçalho da tabela
    cols = ["OS","Gerente","Data_Finalizacao","Hora_Finalizacao","Observacoes"]
    widths = [20, 40, 30, 25, 75]
    pdf.set_font("Arial","B",10)
    for col, w in zip(cols, widths):
        pdf.cell(w, 8, col.replace("_"," "), border=1)
    pdf.ln()

    pdf.set_font("Arial","",9)
    for row in finalizadas:
        pdf.cell(widths[0], 6, row["OS"], border=1)
        pdf.cell(widths[1], 6, row["Gerente"], border=1)
        pdf.cell(widths[2], 6, row["Data_Finalizacao"], border=1)
        pdf.cell(widths[3], 6, row["Hora_Finalizacao"], border=1)
        obs = (row["Observacoes"] or "")[:40]
        pdf.cell(widths[4], 6, obs, border=1)
        pdf.ln()

    pdf.output(pdf_path)

    return send_file(
        pdf_path,
        as_attachment=True,
        download_name=f"relatorio_os_{datetime.now().strftime('%Y%m%d')}.pdf",
        mimetype='application/pdf'
    )

@app.route("/logout")
def logout():
    session.clear()
    flash("Você foi desconectado com sucesso", "info")
    return redirect(url_for('login'))

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port, debug=True)
