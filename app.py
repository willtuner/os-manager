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

# Criar diretórios se não existirem
os.makedirs(MENSAGENS_DIR, exist_ok=True)

ADMIN_USERS = {
    "wilson.santana": "admin321"
}

def carregar_os_gerente(gerente):
    try:
        nome_arquivo = None
        nome_completo = gerente.upper().replace('.', '_') + "_GONZAGA.json"
        caminho_completo = os.path.join(MENSAGENS_DIR, nome_completo)

        if os.path.exists(caminho_completo):
            nome_arquivo = nome_completo
        else:
            primeiro_nome = gerente.split('.')[0].upper()
            for arquivo in os.listdir(MENSAGENS_DIR):
                if arquivo.startswith(primeiro_nome) and arquivo.endswith('.json'):
                    nome_arquivo = arquivo
                    break

        if nome_arquivo:
            caminho = os.path.join(MENSAGENS_DIR, nome_arquivo)
            with open(caminho, 'r', encoding='utf-8') as f:
                dados = json.load(f)
            return [{
                "OS": str(item.get("os") or item.get("OS", "")),
                "Frota": str(item.get("frota") or item.get("Frota", "")),
                "DataFechamento": str(item.get("data") or item.get("Data", "")),
                "Dias": str(item.get("dias") or item.get("Dias", "0")),
                "Prestador": str(item.get("prestador") or item.get("Prestador", "Prestador não definido")),
                "Observacao": str(item.get("servico") or item.get("Servico") or 
                            item.get("observacao") or item.get("Observacao", ""))
            } for item in dados]

        return []
    except Exception as e:
        print(f"Erro ao carregar OS para {gerente}: {str(e)}")
        return []

def registrar_finalizacao(os_numero, gerente, observacoes=""):
    cabecalho = ["OS", "Gerente", "Data_Finalizacao", "Hora_Finalizacao", "Observacoes", "Data_Registro"]
    
    if not os.path.exists(FINALIZACOES_FILE):
        with open(FINALIZACOES_FILE, mode='w', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            writer.writerow(cabecalho)
    
    with open(FINALIZACOES_FILE, mode='a', newline='', encoding='utf-8') as f:
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
    contagem = {}
    try:
        if os.path.exists(FINALIZACOES_FILE):
            with open(FINALIZACOES_FILE, mode='r', encoding='utf-8') as f:
                reader = csv.DictReader(f)
                for linha in reader:
                    gerente = linha.get("Gerente", "Desconhecido")
                    contagem[gerente] = contagem.get(gerente, 0) + 1
    except Exception as e:
        print(f"Erro ao contar OS por gerente: {str(e)}")
    return contagem

def listar_gerentes_ativos():
    gerentes = set()
    try:
        if os.path.exists(FINALIZACOES_FILE):
            with open(FINALIZACOES_FILE, mode='r', encoding='utf-8') as f:
                reader = csv.DictReader(f)
                for linha in reader:
                    gerentes.add(linha.get("Gerente", "Desconhecido"))
        
        # Adiciona também gerentes que tem arquivo de mensagens mas não finalizaram OS ainda
        for arquivo in os.listdir(MENSAGENS_DIR):
            if arquivo.endswith('.json'):
                gerente = arquivo.split('_GONZAGA.json')[0].replace('_', '.').lower()
                gerentes.add(gerente)
                
    except Exception as e:
        print(f"Erro ao listar gerentes ativos: {str(e)}")
    return sorted(gerentes)

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

        try:
            if os.path.exists(USERS_FILE):
                with open(USERS_FILE, encoding="utf-8") as f:
                    users = json.load(f)

                if gerente in users and users[gerente] == senha:
                    session["gerente"] = gerente
                    session["is_admin"] = False
                    return redirect(url_for('painel'))
            
            flash("Credenciais inválidas", "danger")
        except Exception as e:
            print(f"Erro no login: {str(e)}")
            flash("Erro no sistema de autenticação", "danger")

    return render_template("login.html")

@app.route("/painel")
def painel():
    if "gerente" not in session:
        return redirect(url_for('login'))

    gerente = session["gerente"]
    lista_os = carregar_os_gerente(gerente)
    
    return render_template("painel.html",
                         lista=lista_os,
                         gerente=gerente,
                         now=datetime.now())

@app.route("/finalizar_os/<os_numero>", methods=["POST"])
def finalizar_os(os_numero):
    if "gerente" not in session:
        return redirect(url_for('login'))

    gerente = session["gerente"]
    registrar_finalizacao(os_numero, gerente, request.form.get("observacoes", ""))
    
    flash(f"OS {os_numero} finalizada com sucesso", "success")
    return redirect(url_for('painel'))

@app.route("/admin")
def admin_panel():
    if "gerente" not in session or not session.get("is_admin"):
        flash("Acesso não autorizado", "danger")
        return redirect(url_for('login'))

    # Carrega OS finalizadas
    finalizadas = []
    if os.path.exists(FINALIZACOES_FILE):
        with open(FINALIZACOES_FILE, mode='r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            finalizadas = list(reader)

    # Conta OS por gerente
    contagem_gerentes = contar_os_por_gerente()
    
    # Lista de gerentes ativos
    gerentes_ativos = listar_gerentes_ativos()
    
    # Lista de OS abertas por gerente
    os_abertas_por_gerente = {}
    for gerente in gerentes_ativos:
        os_pendentes = carregar_os_gerente(gerente)
        if os_pendentes:
            os_abertas_por_gerente[gerente] = len(os_pendentes)

    return render_template("admin.html",
                         finalizadas=finalizadas[-100:],  # Mostra apenas as 100 últimas
                         total_os=len(finalizadas),
                         gerentes=gerentes_ativos,
                         contagem_gerentes=contagem_gerentes,
                         os_abertas=os_abertas_por_gerente,
                         now=datetime.now())

@app.route("/exportar_os_finalizadas")
def exportar_os_finalizadas():
    if "gerente" not in session or not session.get("is_admin"):
        flash("Acesso não autorizado", "danger")
        return redirect(url_for('login'))

    if not os.path.exists(FINALIZACOES_FILE):
        flash("Nenhuma OS finalizada para exportar", "warning")
        return redirect(url_for('admin_panel'))

    # Lê o arquivo CSV diretamente para manter todos os dados
    with open(FINALIZACOES_FILE, mode='r', encoding='utf-8') as f:
        csv_data = f.read()

    # Cria a resposta com o CSV
    response = make_response(csv_data)
    response.headers["Content-Disposition"] = f"attachment; filename=os_finalizadas_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
    response.headers["Content-type"] = "text/csv"
    
    return response

@app.route("/logout")
def logout():
    session.clear()
    flash("Você foi desconectado com sucesso", "info")
    return redirect(url_for('login'))

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port, debug=True)
