from flask import Flask, render_template, request, redirect, session
import json
import os

app = Flask(__name__)
app.secret_key = "segredo_super_confidencial"

@app.route("/")
def index():
    return redirect("/painel")

@app.route("/painel")
def painel():
    return render_template("index.html")

@app.route("/login", methods=["GET", "POST"])
def login():
    erro = None

    if request.method == "POST":
        gerente = request.form["gerente"]

        senha = request.form["senha"]

        BASE_DIR = os.path.dirname(os.path.abspath(__file__))
        with open(os.path.join(BASE_DIR, "users.json"), encoding="utf-8") as f:
            users = json.load(f)

        if gerente in users and users[gerente] == senha:
            session["usuario"] = gerente
            return redirect("/relatorio")
        else:
            erro = "Usuário ou senha inválidos"

    return render_template("login.html", erro=erro)

@app.route("/relatorio")
def relatorio():
    if "usuario" not in session:
        return redirect("/login")

    gerente = session["usuario"]
    nome_arquivo = gerente.upper().replace(" ", "_") + ".json"
    caminho_arquivo = os.path.join("mensagens_por_gerente", nome_arquivo)

    os_list = []
    if os.path.exists(caminho_arquivo):
        with open(caminho_arquivo, encoding="utf-8") as f:
            os_list = json.load(f)

    return render_template("relatorio.html", os_list=os_list)

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
