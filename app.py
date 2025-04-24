from flask import Flask, render_template, request, redirect, session, url_for, send_file, flash
import json
import os
import csv
from datetime import datetime
from fpdf import FPDF
import pandas as pd
import fnmatch
from threading import Thread

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', os.urandom(24).hex())
app.config['SESSION_COOKIE_SECURE'] = True
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'

# Usuário administrativo
ADMIN_USERS = {
    "wilson.santana": "admin321"
}

def carregar_os_gerente(gerente):
    try:
        nome_base = gerente.upper().replace('.', '_')
        padroes = [
            f"{nome_base}.json",
            f"{nome_base}_GONZAGA.json",
            f"{nome_base.split('_')[0]}*.json"
        ]
        
        arquivo_encontrado = None
        for padrao in padroes:
            for arquivo in os.listdir("mensagens_por_gerente"):
                if arquivo.upper() == padrao.upper() or fnmatch.fnmatch(arquivo.upper(), padrao.upper()):
                    arquivo_encontrado = arquivo
                    break
            if arquivo_encontrado:
                break
        
        if arquivo_encontrado:
            caminho = os.path.join("mensagens_por_gerente", arquivo_encontrado)
            with open(caminho, 'r', encoding='utf-8') as f:
                dados = json.load(f)
            
            return [{
                "os": str(item.get("os") or item.get("OS", "")),
                "frota": str(item.get("frota") or item.get("Frota", "")),
                "data": str(item.get("data") or item.get("Data", "")),
                "dias": str(item.get("dias") or item.get("Dias", "0")),
                "prestador": str(item.get("prestador") or item.get("Prestador", "Prestador não definido")),
                "servico": str(item.get("servico") or item.get("Servico") or item.get("observacao") or item.get("Observacao", ""))
            } for item in dados]
        
        return []
    except Exception as e:
        print(f"Erro ao carregar OS: {str(e)}")
        return []

def contar_os_por_gerente():
    """Retorna um dicionário com a contagem de OS por gerente"""
    contagem = {}
    try:
        # Verifica se a pasta existe
        if not os.path.exists("mensagens_por_gerente"):
            print("Pasta mensagens_por_gerente não encontrada!")
            return contagem
        
        # Debug: lista os arquivos encontrados
        arquivos = os.listdir("mensagens_por_gerente")
        print(f"Arquivos encontrados na pasta: {arquivos}")
        
        for arquivo in arquivos:
            if arquivo.endswith('.json'):
                try:
                    # Extrai o nome do gerente do arquivo
                    nome_gerente = arquivo[:-5].replace('_', ' ').title()
                    
                    # Carrega o arquivo para contar
                    with open(os.path.join("mensagens_por_gerente", arquivo), 'r', encoding='utf-8') as f:
                        dados = json.load(f)
                    
                    # Adiciona ao dicionário
                    contagem[nome_gerente] = len(dados)
                    
                    # Debug: mostra o que está sendo contado
                    print(f"Gerente: {nome_gerente} - OS: {len(dados)}")
                    
                except Exception as e:
                    print(f"Erro ao processar {arquivo}: {str(e)}")
                    continue
        
        return dict(sorted(contagem.items(), key=lambda item: item[1], reverse=True))
    
    except Exception as e:
        print(f"Erro geral ao contar OS: {str(e)}")
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
        
        if gerente in ADMIN_USERS and ADMIN_USERS[gerente] == senha:
            session["gerente"] = gerente
            session["is_admin"] = True
            return redirect(url_for('admin_panel'))
        
        users_path = os.path.join(os.path.dirname(__file__), "users.json")
        try:
            with open(users_path, encoding="utf-8") as f:
                users = json.load(f)
            
            if gerente in users and users[gerente] == senha:
                session["gerente"] = gerente
                session["is_admin"] = False
                return redirect(url_for('painel'))
            else:
                flash("Credenciais inválidas", "danger")
        except Exception as e:
            print(f"Erro no login: {str(e)}")
            flash("Erro no sistema de autenticação", "danger")
    
    return render_template("login.html")

@app.route("/painel", methods=["GET", "POST"])
def painel():
    if "gerente" not in session:
        return redirect(url_for('login'))
    
    gerente = session["gerente"]
    os_pendentes = carregar_os_gerente(gerente)
    total_os = len(os_pendentes)
    
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
            flash(f"OS {os_numero} finalizada com sucesso", "success")
        
        os_pendentes = [os for os in os_pendentes if str(os.get("os")) != str(os_numero)]
        
        nome_arquivo = f"{gerente.upper().replace(' ', '_')}.json"
        caminho_arquivo = os.path.join("mensagens_por_gerente", nome_arquivo)
        with open(caminho_arquivo, 'w', encoding='utf-8') as f:
            json.dump(os_pendentes, f, indent=2, ensure_ascii=False)
        
        return redirect(url_for('painel'))
    
    return render_template("painel.html", 
                         os_pendentes=os_pendentes,
                         gerente=gerente,
                         now=datetime.now(),
                         total_os=total_os)

@app.route("/admin")
def admin_panel():
    if "gerente" not in session or not session.get("is_admin"):
        flash("Acesso não autorizado", "danger")
        return redirect(url_for('login'))
    
    finalizadas = []
    try:
        with open("finalizacoes_os.csv", mode='r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            finalizadas = list(reader)
    except FileNotFoundError:
        pass
    
    total_os = len(finalizadas)
    gerentes = set(os['Gerente'] for os in finalizadas)
    contagem_gerentes = contar_os_por_gerente()
    
    return render_template("admin.html",
                         finalizadas=finalizadas,
                         total_os=total_os,
                         gerentes=gerentes,
                         now=datetime.now(),
                         contagem_gerentes=contagem_gerentes)

@app.route("/exportar")
def exportar():
    if "gerente" not in session or not session.get("is_admin"):
        flash("Acesso não autorizado", "danger")
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

@app.route("/logout")
def logout():
    session.clear()
    flash("Você foi desconectado com sucesso", "info")
    return redirect(url_for('login'))

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port, debug=True)
