from flask import Flask, render_template, request, redirect, session, url_for
import json
import os
from datetime import datetime

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'segredo_super_confidencial')

def formatar_data(data_str):
    """Formata a data para o padrão brasileiro"""
    try:
        if data_str:  # Verifica se não está vazio
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
            
            # Debug: Mostra os dados lidos do arquivo
            print(f"Dados lidos do arquivo {nome_arquivo}:")
            print(json.dumps(dados, indent=2))
            
            # Processa os dados
            os_list = []
            for item in dados:
                os_list.append({
                    "OS": item.get("OS", "N/A"),
                    "DataFechamento": formatar_data(item.get("DataFechamento")),
                    "Hora": item.get("Hora", ""),
                    "Observacao": item.get("Observacao", ""),
                    "RegistradoEm": item.get("RegistradoEm", ""),
                    "Frota": item.get("Frota", "Não especificada"),
                    "Prioridade": item.get("Prioridade", "Normal")
                })
            return os_list
        return []
    except Exception as e:
        print(f"Erro ao ler arquivo {nome_arquivo}: {str(e)}")
        return []

@app.route("/")
def index():
    return redirect(url_for('login'))

@app.route("/login", methods=["GET", "POST"])
def login():
    erro = None
    
    if request.method == "POST":
        gerente = request.form.get("gerente", "").strip()
        senha = request.form.get("senha", "").strip()
        
        # Verificação simplificada (substitua por sua lógica real)
        if gerente == "DANILO MULARI GONZAGA" and senha == "1234":
            session["gerente"] = gerente
            return redirect(url_for('relatorio'))
        else:
            erro = "Credenciais inválidas"
    
    return render_template("login.html", erro=erro)

@app.route("/relatorio")
def relatorio():
    if "gerente" not in session:
        return redirect(url_for('login'))
    
    gerente = session["gerente"]
    lista_os = carregar_os_gerente(gerente)
    
    # Debug: Mostra os dados que serão enviados para o template
    print(f"Dados enviados para o template:")
    print(json.dumps(lista_os, indent=2))
    
    return render_template("relatorio.html", 
                         lista=lista_os, 
                         gerente=gerente,
                         now=datetime.now())

@app.route("/logout")
def logout():
    session.pop("gerente", None)
    return redirect(url_for('login'))

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=10000, debug=True)
