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

def carregar_os_gerente(gerente):
    try:
        # Converte o login para o formato de arquivo esperado
        nome_arquivo = None
        
        # Primeiro tenta encontrar o arquivo com o nome completo
        nome_completo = gerente.upper().replace('.', '_') + "_GONZAGA.json"
        caminho_completo = os.path.join("mensagens_por_gerente", nome_completo)
        
        if os.path.exists(caminho_completo):
            nome_arquivo = nome_completo
        else:
            # Fallback: procura por qualquer arquivo que comece com o primeiro nome
            primeiro_nome = gerente.split('.')[0].upper()
            for arquivo in os.listdir("mensagens_por_gerente"):
                if arquivo.startswith(primeiro_nome) and arquivo.endswith('.json'):
                    nome_arquivo = arquivo
                    break
        
        if nome_arquivo:
            caminho = os.path.join("mensagens_por_gerente", nome_arquivo)
            print(f"Carregando arquivo: {caminho}")  # Debug
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
        
        print(f"Nenhum arquivo encontrado para o gerente: {gerente}")
        return []
    except Exception as e:
        print(f"Erro ao carregar OS para {gerente}: {str(e)}")
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
    
    # Carrega as OS usando a função corrigida
    os_pendentes = carregar_os_gerente(gerente)
    
    if request.method == "POST":
        os_numero = request.form.get("os_numero")
        
        # Remove a OS da lista
        os_pendentes = [os for os in os_pendentes if str(os.get("os")) != str(os_numero)]
        
        # Encontra o arquivo correto para salvar
        nome_arquivo = None
        primeiro_nome = gerente.split('.')[0].upper()
        for arquivo in os.listdir("mensagens_por_gerente"):
            if arquivo.startswith(primeiro_nome) and arquivo.endswith('.json'):
                nome_arquivo = arquivo
                break
        
        if nome_arquivo:
            caminho = os.path.join("mensagens_por_gerente", nome_arquivo)
            try:
                with open(caminho, 'w', encoding='utf-8') as f:
                    json.dump(os_pendentes, f, indent=2, ensure_ascii=False)
                
                if request.form.get("acao") == "fechar":
                    registrar_finalizacao(
                        os_numero,
                        gerente,
                        request.form.get("data_finalizacao"),
                        request.form.get("hora_finalizacao"),
                        request.form.get("observacoes")
                    )
                    flash(f"OS {os_numero} finalizada com sucesso", "success")
            except Exception as e:
                print(f"Erro ao salvar arquivo {caminho}: {str(e)}")
                flash("Erro ao salvar alterações", "danger")
        else:
            flash("Arquivo de OS não encontrado", "danger")
        
        return redirect(url_for('painel'))
    
    return render_template("painel.html",
                         os_pendentes=os_pendentes,
                         gerente=gerente,
                         now=datetime.now(),
                         total_os=len(os_pendentes))

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
    
    try:
        # No Render, precisamos usar /tmp para arquivos temporários
        os.makedirs("/tmp/relatorios", exist_ok=True)
        pdf_path = "/tmp/relatorios/relatorio_finalizacoes.pdf"
        
        pdf = FPDF()
        pdf.add_page()
        pdf.set_font("Arial", size=10)  # Tamanho menor para caber mais conteúdo
        
        # Título
        pdf.cell(200, 10, txt="Relatório de OS Finalizadas - " + datetime.now().strftime('%d/%m/%Y'), ln=1, align='C')
        pdf.ln(8)
        
        # Verifica se o arquivo CSV existe
        if not os.path.exists("finalizacoes_os.csv"):
            pdf.cell(200, 10, txt="Nenhuma OS finalizada ainda", ln=1, align='C')
        else:
            # Lê os dados com tratamento de erro
            try:
                df = pd.read_csv("finalizacoes_os.csv")
            except Exception as e:
                print(f"Erro ao ler CSV: {str(e)}")
                pdf.cell(200, 10, txt="Erro ao ler dados das OS", ln=1, align='C')
                pdf.output(pdf_path)
                return send_file(pdf_path, as_attachment=True)
            
            # Configurações da tabela
            colunas = ["OS", "Gerente", "Data", "Hora", "Observações"]
            larguras = [15, 30, 20, 15, 110]  # Ajuste as larguras
            
            # Cabeçalho
            for col, larg in zip(colunas, larguras):
                pdf.cell(larg, 10, txt=col, border=1, fill=True)
            pdf.ln()
            
            # Dados (limita a 100 linhas para evitar PDF muito grande)
            for _, row in df.head(100).iterrows():
                for i, col in enumerate(colunas):
                    valor = ""
                    if col == "OS":
                        valor = str(row["OS"])
                    elif col == "Gerente":
                        valor = str(row["Gerente"])
                    elif col == "Data":
                        valor = str(row["Data_Finalizacao"])
                    elif col == "Hora":
                        valor = str(row["Hora_Finalizacao"])
                    elif col == "Observações":
                        valor = str(row["Observacoes"])[:60]  # Limita o tamanho
                    
                    pdf.cell(larguras[i], 10, txt=valor, border=1)
                pdf.ln()
        
        pdf.output(pdf_path)
        return send_file(
            pdf_path,
            as_attachment=True,
            download_name=f"relatorio_os_{datetime.now().strftime('%Y%m%d')}.pdf",
            mimetype='application/pdf'
        )
        
    except Exception as e:
        print(f"Erro ao gerar PDF: {str(e)}")
        flash(f"Erro ao gerar PDF: {str(e)}", "danger")
        return redirect(url_for('admin_panel'))
@app.route("/logout")
def logout():
    session.clear()
    flash("Você foi desconectado com sucesso", "info")
    return redirect(url_for('login'))

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port, debug=True)
