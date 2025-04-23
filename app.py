from flask import Flask, render_template, request, redirect, session, url_for, send_file
import json
import os
import csv
from datetime import datetime
from fpdf import FPDF
import pandas as pd

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', os.urandom(24).hex())

def formatar_data(data_str):
    """Formata a data para o padrão brasileiro"""
    try:
        if data_str:
            data = datetime.strptime(data_str, '%Y-%m-%d')
            return data.strftime('%d/%m/%Y')
        return "Sem data"
    except (ValueError, TypeError):
        return data_str

def carregar_os_gerente(gerente):
    """Carrega as OS de um gerente específico"""
    try:
        nome_arquivo = f"{gerente.upper().replace(' ', '_')}.json"
        caminho_arquivo = os.path.join("mensagens_por_gerente", nome_arquivo)
        
        if os.path.exists(caminho_arquivo):
            with open(caminho_arquivo, 'r', encoding='utf-8') as f:
                dados = json.load(f)
            
            os_list = []
            for item in dados:
                os_list.append({
                    "OS": item.get("os", "N/A"),
                    "DataFechamento": item.get("data", ""),
                    "Observacao": item.get("servico", ""),
                    "Frota": item.get("frota", "Não especificada"),
                    "Prestador": item.get("prestador", ""),
                    "Dias": item.get("dias", "0")
                })
            return os_list
        return []
    except Exception as e:
        print(f"Erro ao ler arquivo {nome_arquivo}: {str(e)}")
        return []

def registrar_finalizacao_csv(os_numero, gerente, data, hora, observacoes):
    """Registra a finalização em um arquivo CSV"""
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

def remover_os_gerente(gerente, os_numero):
    """Remove uma OS do arquivo JSON do gerente"""
    try:
        nome_arquivo = f"{gerente.upper().replace(' ', '_')}.json"
        caminho_arquivo = os.path.join("mensagens_por_gerente", nome_arquivo)
        
        if os.path.exists(caminho_arquivo):
            with open(caminho_arquivo, 'r', encoding='utf-8') as f:
                dados = json.load(f)
            
            dados_atualizados = [item for item in dados if str(item.get("os")) != str(os_numero)]
            
            with open(caminho_arquivo, 'w', encoding='utf-8') as f:
                json.dump(dados_atualizados, f, indent=2)
            
            return True
        return False
    except Exception as e:
        print(f"Erro ao remover OS: {str(e)}")
        return False

@app.route("/")
def index():
    return redirect(url_for('login'))

@app.route("/login", methods=["GET", "POST"])
def login():
    erro = None
    
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
                return redirect(url_for('relatorio'))
            else:
                erro = "Credenciais inválidas"
        except FileNotFoundError:
            erro = "Arquivo de usuários não encontrado"
        except json.JSONDecodeError:
            erro = "Erro ao ler arquivo de usuários"
    
    return render_template("login.html", erro=erro)

@app.route("/relatorio")
def relatorio():
    if "gerente" not in session:
        return redirect(url_for('login'))
    
    gerente = session["gerente"]
    lista_os = carregar_os_gerente(gerente)
    
    return render_template("relatorio.html", 
                         lista=lista_os, 
                         gerente=gerente,
                         now=datetime.now())

@app.route("/finalizar_os/<os_numero>", methods=["POST"])
def finalizar_os(os_numero):
    if "gerente" not in session:
        return redirect(url_for('login'))
    
    data_finalizacao = request.form.get("data_finalizacao")
    hora_finalizacao = request.form.get("hora_finalizacao")
    observacoes = request.form.get("observacoes")
    gerente = session["gerente"]

    registrar_finalizacao_csv(
        os_numero,
        gerente,
        data_finalizacao,
        hora_finalizacao,
        observacoes
    )

    remover_os_gerente(gerente, os_numero)
    
    return '', 204

@app.route("/exportar_relatorio")
def exportar_relatorio():
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

@app.route("/logout")
def logout():
    session.pop("gerente", None)
    return redirect(url_for('login'))

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port, debug=True)
