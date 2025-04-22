from flask import Flask, render_template, request, redirect, url_for, session
import os, csv
from datetime import datetime
import json

app = Flask(__name__)
app.secret_key = "os_secretinha"

USERS_PATH = os.path.join(os.path.dirname(__file__), "users.json")

PASTA_DADOS = os.path.join(os.path.dirname(__file__), "mensagens_por_gerente")
FECHAMENTOS_PATH = os.path.join(os.path.dirname(__file__), "fechamentos.csv")
PENDENTES_PATH = os.path.join(os.path.dirname(__file__), "pendentes.csv")

def carregar_dados(gerente):
    nome = gerente.upper().replace(" ", "_") + ".json"
    caminho = os.path.join(PASTA_DADOS, nome)
    if not os.path.exists(caminho):
        return []
    with open(caminho, encoding="utf-8") as f:
        return json.load(f)

def carregar_fechadas():
    if not os.path.exists(FECHAMENTOS_PATH):
        return set()
    with open(FECHAMENTOS_PATH, encoding="utf-8") as f:
        return set(l.split(",")[0].strip() for l in f.readlines()[1:] if l.strip())

def carregar_pendentes():
    if not os.path.exists(PENDENTES_PATH):
        return set()
    with open(PENDENTES_PATH, encoding="utf-8") as f:
        return set(l.split(",")[0].strip() for l in f.readlines()[1:] if l.strip())

@app.route("/")
def home():
    if "gerente" in session:
        return redirect(url_for("painel"))
    return redirect(url_for("login"))

@app.route("/login", methods=["GET", "POST"])
def login():
    erro = ""
    if request.method == "POST":
        gerente = request.form.get("gerente", "").strip().lower()
        senha = request.form.get("senha", "").strip()
        
        import os

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
with open(os.path.join(BASE_DIR, "users.json"), encoding="utf-8") as f:
    users = json.load(f)


 if gerente in users and users[gerente] == senha:
            session["gerente"] = gerente
            return redirect(url_for("painel"))
        else:
            erro = "Usuário ou senha inválidos. Tente novamente."
    
    return render_template("login.html", erro=erro)

@app.route("/painel")
def painel():
    if "gerente" not in session:
        return redirect(url_for("login"))
    gerente = session["gerente"]
    ordens = carregar_dados(gerente)
    bloqueadas = carregar_fechadas().union(carregar_pendentes())
    pendentes = [o for o in ordens if o.get("os") not in bloqueadas]
    return render_template("index.html", gerente=gerente.upper(), ordens=pendentes)

@app.route("/fechar", methods=["POST"])
def fechar():
    linha = [
        request.form["os"],
        request.form["data"],
        request.form["hora"],
        request.form["obs"],
        datetime.now().strftime("%d/%m/%Y %H:%M:%S")
    ]
    escrever_csv(FECHAMENTOS_PATH, linha)
    return redirect(url_for("painel"))

@app.route("/pendente", methods=["POST"])
def pendente():
    linha = [
        request.form["os"],
        request.form["data"],
        request.form["hora"],
        request.form["obs"],
        datetime.now().strftime("%d/%m/%Y %H:%M:%S")
    ]
    escrever_csv(PENDENTES_PATH, linha)
    return redirect(url_for("painel"))

@app.route("/relatorio")
def relatorio():
    return render_template("relatorio.html", lista=ler_csv(FECHAMENTOS_PATH))

@app.route("/pendentes")
def relatorio_pendentes():
    return render_template("pendentes.html", lista=ler_csv(PENDENTES_PATH))

@app.route("/logout")
def logout():
    session.pop("gerente", None)
    return redirect(url_for("login"))

def escrever_csv(caminho, linha):
    cabecalho = not os.path.exists(caminho)
    with open(caminho, "a", encoding="utf-8") as f:
        if cabecalho:
            f.write("OS,DataFechamento,Hora,Observacao,RegistradoEm\n")
        f.write(",".join(linha) + "\n")

def ler_csv(caminho):
    if not os.path.exists(caminho):
        return []
    with open(caminho, encoding="utf-8") as f:
        return list(csv.DictReader(f))

import os

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)



