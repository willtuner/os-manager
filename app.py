from flask import Flask, render_template, request, redirect, session, url_for
import json
import os
from datetime import datetime

app = Flask(__name__)
app.secret_key = "segredo_super_confidencial"

# Helper function to format dates
def formatar_data(data_str):
    try:
        data = datetime.strptime(data_str, '%Y-%m-%d')
        return data.strftime('%d/%m/%Y')
    except:
        return data_str

@app.route("/")
def index():
    return redirect(url_for('painel'))

@app.route("/painel")
def painel():
    if "usuario" not in session:
        return redirect(url_for('login'))
    return render_template("index.html")

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
                session["usuario"] = gerente
                return redirect(url_for('relatorio'))
            else:
                erro = "Usuário ou senha inválidos"
        except FileNotFoundError:
            erro = "Sistema indisponível no momento"

    return render_template("login.html", erro=erro)

@app.route("/logout")
def logout():
    session.pop("usuario", None)
    return redirect(url_for('login'))

@app.route("/relatorio")
def relatorio():
    if "usuario" not in session:
        return redirect(url_for('login'))

    gerente = session["usuario"]
    nome_arquivo = gerente.upper().replace(" ", "_") + ".json"
    caminho_arquivo = os.path.join("mensagens_por_gerente", nome_arquivo)

    os_list = []
    if os.path.exists(caminho_arquivo):
        try:
            with open(caminho_arquivo, encoding="utf-8") as f:
                dados = json.load(f)
                
                # Padroniza a estrutura dos dados
                for item in dados:
                    os_list.append({
                        "OS": item.get("OS", "N/A"),
                        "DataFechamento": formatar_data(item.get("DataFechamento", "")),
                        "Hora": item.get("Hora", ""),
                        "Observacao": item.get("Observacao", ""),
                        "RegistradoEm": item.get("RegistradoEm", ""),
                        "Prioridade": item.get("Prioridade", "Normal")
                    })
        except Exception as e:
            print(f"Erro ao ler arquivo {caminho_arquivo}: {str(e)}")

    return render_template("relatorio.html", lista=os_list, gerente=gerente)

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port, debug=True)
