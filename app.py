from flask import Flask, render_template, request, redirect, session, url_for, send_file, send_from_directory
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

# Rota para favicon
@app.route('/favicon.ico')
def favicon():
    return send_from_directory(os.path.join(app.root_path, 'static'),
                             'favicon.ico', mimetype='image/vnd.microsoft.icon')

# Filtro para formatar datas
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
        
        if os.path.exists(caminho_arquivo):
            with open(caminho_arquivo, 'r', encoding='utf-8') as f:
                dados = json.load(f)
            return dados
        return []
    except Exception as e:
        print(f"Erro ao ler arquivo: {str(e)}")
        return []

def contar_os_por_gerente():
    try:
        arquivos = [f for f in os.listdir("mensagens_por_gerente") if f.endswith('.json')]
        contagem = {}
        for arquivo in arquivos:
            gerente = arquivo.replace('.json', '').replace('_', ' ')
            caminho = os.path.join("mensagens_por_gerente", arquivo)
            with open(caminho, 'r', encoding='utf-8') as f:
                dados = json.load(f)
                contagem[gerente] = len(dados)
        return contagem
    except Exception as e:
        print(f"Erro ao contar OS por gerente: {str(e)}")
        return {}

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
        
        BASE_DIR = os.path.dirname(os.path.abspath(__file__))
        users_path = os.path.join(BASE_DIR, "users.json")
        
        try:
            with open(users_path, encoding="utf-8") as f:
                users = json.load(f)
            
            if gerente in users and users[gerente] == senha:
                session["gerente"] = gerente
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
        
        registrar_finalizacao(
            os_numero,
            gerente,
            data_finalizacao,
            hora_finalizacao,
            observacoes
        )
        
        os_pendentes = [os for os in os_pendentes if str(os.get("os")) != str(os_numero)]
        
        nome_arquivo = f"{gerente.upper().replace(' ', '_')}.json"
        caminho_arquivo = os.path.join("mensagens_por_gerente", nome_arquivo)
        with open(caminho_arquivo, 'w', encoding='utf-8') as f:
            json.dump(os_pendentes, f, indent=2, ensure_ascii=False)
        
        return redirect(url_for('painel'))
    
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

@app.route("/pendentes")
def pendentes():
    if "gerente" not in session:
        return redirect(url_for('login'))
    
    registros = []
    try:
        with open("finalizacoes_os.csv", mode='r', encoding='utf-8') as f:
            reader = csv.reader(f)
            next(reader)
            registros = list(reader)
    except FileNotFoundError:
        pass
    
    return render_template("pendentes.html",
                         lista=registros,
                         gerente=session["gerente"],
                         now=datetime.now())

@app.route("/admin")
def admin_panel():
    if "gerente" not in session:
        return redirect(url_for('login'))
    
    # Verifica se é admin
    with open("users.json", encoding="utf-8") as f:
        users = json.load(f)
        if users.get(session["gerente"]) != "admin123":
            return redirect(url_for('painel'))
    
    contagem_gerentes = contar_os_por_gerente()
    total_os = sum(contagem_gerentes.values())
    
    finalizacoes = []
    try:
        with open("finalizacoes_os.csv", mode='r', encoding='utf-8') as f:
            reader = csv.reader(f)
            next(reader)
            finalizacoes = list(reader)[-10:]
    except FileNotFoundError:
        pass
    
    return render_template("admin.html",
                         contagem_gerentes=contagem_gerentes,
                         total_os=total_os,
                         finalizacoes=finalizacoes,
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
    return exportar()

@app.route("/logout")
def logout():
    session.pop("gerente", None)
    return redirect(url_for('login'))

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port, debug=True)
