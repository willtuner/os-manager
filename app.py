from flask import Flask, render_template, request, redirect, session, url_for, send_file
import json
import os
import csv
from datetime import datetime
from fpdf import FPDF
import pandas as pd

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', os.urandom(24).hex())
app.config['SESSION_COOKIE_SECURE'] = True
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'

# Usuários administrativos
ADMIN_USERS = {
    "zylton": "admin123",
    "mauricio": "senha456"
}

# Registra a função como filtro do Jinja2
@app.template_filter('formatar_data')
def formatar_data(data_str, formato_entrada='%d/%m/%Y', formato_saida='%d/%m/%Y'):
    try:
        if data_str:
            data = datetime.strptime(data_str, formato_entrada)
            return data.strftime(formato_saida)
        return "Sem data"
    except (ValueError, TypeError):
        return data_str

def carregar_os_gerente(gerente):
    try:
        nome_arquivo = f"{gerente.upper().replace(' ', '_')}.json"
        caminho_arquivo = os.path.join("mensagens_por_gerente", nome_arquivo)
        print(f"Tentando ler arquivo: {caminho_arquivo}")  # Debug
        
        if os.path.exists(caminho_arquivo):
            print("Arquivo encontrado!")  # Debug
            with open(caminho_arquivo, 'r', encoding='utf-8') as f:
                dados = json.load(f)
            print(f"Dados lidos: {dados}")  # Debug
            return dados
        else:
            print("Arquivo NÃO encontrado!")  # Debug
        return []
    except Exception as e:
        print(f"Erro ao ler arquivo: {str(e)}")  # Debug
        return []

def registrar_finalizacao(os_numero, gerente, data, hora, observacoes):
    arquivo_csv = "finalizacoes_os.csv"
    cabecalho = ["OS", "Gerente", "Data_Finalizacao", "Hora_Finalizacao", "Observacoes", "Data_Registro"]
    
    if not os.path.exists(arquivo_csv):
        with open(arquivo_csv, mode='w', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            writer.writerow(cabecalho)
    
    with open(arquivo_csv, mode='a', newline='', encoding='utf-8') as f:
        writer = csv.writer(f)
        writer.writerow([
            os_numero,
            gerente,
            data,
            hora,
            observacoes,
            datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        ])

@app.route("/")
def index():
    return redirect(url_for('login'))

@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        gerente = request.form.get("gerente", "").strip()
        senha = request.form.get("senha", "").strip()
        
        # Verificar se é admin
        if gerente in ADMIN_USERS and ADMIN_USERS[gerente] == senha:
            session["gerente"] = gerente
            session["is_admin"] = True
            return redirect(url_for('admin_panel'))
        
        # Verificar se é gerente normal
        BASE_DIR = os.path.dirname(os.path.abspath(__file__))
        users_path = os.path.join(BASE_DIR, "users.json")
        
        try:
            with open(users_path, encoding="utf-8") as f:
                users = json.load(f)
            
            if gerente in users and users[gerente] == senha:
                session["gerente"] = gerente
                session["is_admin"] = False
                return redirect(url_for('painel'))
            else:
                return render_template("login.html", erro="Credenciais inválidas")
        except Exception as e:
            print(f"Erro no login: {str(e)}")
            return render_template("login.html", erro="Erro no sistema de autenticação")
    
    return render_template("login.html")

@app.route("/painel", methods=["GET", "POST"])
def painel():
    if "gerente" not in session:
        return redirect(url_for('login'))
    
    gerente = session["gerente"]
    os_pendentes = carregar_os_gerente(gerente)
    
    if request.method == "POST":
        os_numero = request.form.get("os_numero")
        data_finalizacao = request.form.get("data_finalizacao")
        hora_finalizacao = request.form.get("hora_finalizacao")
        observacoes = request.form.get("observacoes")
        acao = request.form.get("acao")
        
        if acao == "fechar":
            registrar_finalizacao(
                os_numero,
                gerente,
                data_finalizacao,
                hora_finalizacao,
                observacoes
            )
        
        # Atualiza a lista removendo a OS finalizada
        os_pendentes = [os for os in os_pendentes if str(os.get("os")) != str(os_numero)]
        
        # Salva a lista atualizada
        nome_arquivo = f"{gerente.upper().replace(' ', '_')}.json"
        caminho_arquivo = os.path.join("mensagens_por_gerente", nome_arquivo)
        with open(caminho_arquivo, 'w', encoding='utf-8') as f:
            json.dump(os_pendentes, f, indent=2, ensure_ascii=False)
        
        return redirect(url_for('painel'))
    
    # Adapta a estrutura dos dados para o template
    os_pendentes_adaptado = []
    for os_item in os_pendentes:
        os_pendentes_adaptado.append({
            "os": os_item.get("os"),
            "frota": os_item.get("frota"),
            "data": os_item.get("data"),
            "dias": os_item.get("dias"),
            "prestador": os_item.get("prestador"),
            "servico": os_item.get("servico")
        })
    
    return render_template("painel.html", 
                         os_pendentes=os_pendentes_adaptado,
                         gerente=gerente,
                         now=datetime.now())

@app.route("/admin")
def admin_panel():
    if "gerente" not in session or session["gerente"] not in ADMIN_USERS:
        return redirect(url_for('login'))
    
    # Carregar todas as OS finalizadas
    finalizadas = []
    try:
        with open("finalizacoes_os.csv", mode='r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            finalizadas = list(reader)
    except FileNotFoundError:
        pass
    
    # Estatísticas
    total_os = len(finalizadas)
    gerentes = set(os['Gerente'] for os in finalizadas)
    
    return render_template("admin.html",
                         finalizadas=finalizadas,
                         total_os=total_os,
                         gerentes=gerentes,
                         now=datetime.now())

@app.route("/pendentes")
def pendentes():
    if "gerente" not in session:
        return redirect(url_for('login'))
    
    # Carrega as OS pendentes do arquivo CSV
    registros = []
    try:
        with open("finalizacoes_os.csv", mode='r', encoding='utf-8') as f:
            reader = csv.reader(f)
            next(reader)  # Pula cabeçalho
            registros = list(reader)
    except FileNotFoundError:
        pass
    
    return render_template("pendentes.html",
                         lista=registros,
                         gerente=session["gerente"],
                         now=datetime.now())

@app.route("/exportar")
def exportar():
    if "gerente" not in session:
        return redirect(url_for('login'))
    
    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Arial", size=12)
    
    pdf.cell(200, 10, txt="Relatório de OS Finalizadas", ln=1, align='C')
    pdf.ln(10)
    
    try:
        df = pd.read_csv("finalizacoes_os.csv")
        
        colunas = ["OS", "Data Finalização", "Hora", "Observações"]
        larguras = [30, 40, 30, 90]
        
        for col, larg in zip(colunas, larguras):
            pdf.cell(larg, 10, txt=col, border=1)
        pdf.ln()
        
        for _, row in df.iterrows():
            pdf.cell(larguras[0], 10, txt=str(row["OS"]), border=1)
            pdf.cell(larguras[1], 10, txt=row["Data_Finalizacao"], border=1)
            pdf.cell(larguras[2], 10, txt=row["Hora_Finalizacao"], border=1)
            pdf.cell(larguras[3], 10, txt=row["Observacoes"], border=1)
            pdf.ln()
            
    except FileNotFoundError:
        pdf.cell(200, 10, txt="Nenhuma OS finalizada ainda", ln=1, align='C')
    
    pdf_path = "relatorio_finalizacoes.pdf"
    pdf.output(pdf_path)
    
    return send_file(
        pdf_path,
        as_attachment=True,
        download_name=f"relatorio_os_{datetime.now().strftime('%Y%m%d')}.pdf"
    )

@app.route("/exportar_relatorio")
def exportar_relatorio():
    """Alias para /exportar para compatibilidade com os templates"""
    return exportar()

@app.route("/logout")
def logout():
    session.pop("gerente", None)
    session.pop("is_admin", None)
    return redirect(url_for('login'))

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port, debug=True)
