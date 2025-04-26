from flask import Flask, render_template, request, redirect, session, url_for, flash, send_file
from flask_sqlalchemy import SQLAlchemy
import json
import os
from datetime import datetime
from fpdf import FPDF

# --- Configuração básica do Flask e SQLAlchemy ---
app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', os.urandom(24).hex())
app.config['SESSION_COOKIE_SECURE'] = True
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, 'app.db')
app.config['SQLALCHEMY_DATABASE_URI'] = f"sqlite:///{DB_PATH}"
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)

# --- Modelos ---
class User(db.Model):
    __tablename__ = 'users'
    id        = db.Column(db.Integer, primary_key=True)
    username  = db.Column(db.String(80), unique=True, nullable=False)
    password  = db.Column(db.String(128), nullable=False)
    is_admin  = db.Column(db.Boolean, default=False)

class Finalizacao(db.Model):
    __tablename__ = 'finalizacoes'
    id             = db.Column(db.Integer, primary_key=True)
    os_numero      = db.Column(db.String(50), nullable=False)
    gerente        = db.Column(db.String(80), nullable=False)
    data_fin       = db.Column(db.String(10), nullable=False)
    hora_fin       = db.Column(db.String(5), nullable=False)
    observacoes    = db.Column(db.Text)
    registrado_em  = db.Column(db.DateTime, default=datetime.utcnow)

# --- Diretórios de arquivos de OS pendentes (JSON) ---
MENSAGENS_DIR     = os.path.join(BASE_DIR, 'mensagens_por_gerente')
USERS_FILE        = os.path.join(BASE_DIR, 'users.json')
os.makedirs(MENSAGENS_DIR, exist_ok=True)

# --- Se não existir, cria o DB e popula a tabela de usuários do users.json ---
with app.app_context():
    db.create_all()
    if User.query.count() == 0 and os.path.exists(USERS_FILE):
        with open(USERS_FILE, encoding='utf-8') as f:
            users = json.load(f)
        for username, pwd in users.items():
            is_admin = False  # se quiser marcar alguns como admin, ajuste aqui
            db.session.add(User(username=username, password=pwd, is_admin=is_admin))
        db.session.commit()

# --- Funções auxiliares ---
def carregar_os_gerente(gerente):
    nome_base = gerente.upper().replace('.', '_') + "_GONZAGA.json"
    caminho = os.path.join(MENSAGENS_DIR, nome_base)
    if not os.path.exists(caminho):
        primeiro = gerente.split('.')[0].upper()
        for f in os.listdir(MENSAGENS_DIR):
            if f.upper().startswith(primeiro) and f.lower().endswith('.json'):
                caminho = os.path.join(MENSAGENS_DIR, f)
                break
    if not os.path.exists(caminho):
        return []
    with open(caminho, encoding='utf-8') as f:
        dados = json.load(f)
    resultado = []
    for item in dados:
        resultado.append({
            "os":        str(item.get("os") or item.get("OS", "")),
            "frota":     str(item.get("frota") or item.get("Frota", "")),
            "data":      str(item.get("data") or item.get("Data", "")),
            "dias":      str(item.get("dias") or item.get("Dias", "0")),
            "prestador": str(item.get("prestador") or item.get("Prestador", "Prestador não definido")),
            "servico":   str(item.get("servico") or item.get("Servico") or item.get("observacao") or item.get("Observacao", ""))
        })
    return resultado

# --- Rotas ---
@app.route("/")
def index():
    return redirect(url_for('login'))

@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        u = request.form["gerente"].strip().lower()
        pwd = request.form["senha"].strip()
        user = User.query.filter_by(username=u).first()
        if user and user.password == pwd:
            session["gerente"]  = u
            session["is_admin"] = user.is_admin
            return redirect(url_for('admin_panel' if user.is_admin else 'painel'))
        flash("Usuário ou senha inválidos", "danger")
    return render_template("login.html")

@app.route("/painel")
def painel():
    if "gerente" not in session:
        return redirect(url_for('login'))
    os_pendentes = carregar_os_gerente(session["gerente"])
    return render_template("painel.html",
                           os_pendentes=os_pendentes,
                           gerente=session["gerente"],
                           now=datetime.now())

@app.route("/finalizar_os/<os_numero>", methods=["POST"])
def finalizar_os(os_numero):
    if "gerente" not in session:
        return redirect(url_for('login'))
    data = request.form["data_finalizacao"]
    hora = request.form["hora_finalizacao"]
    obs  = request.form.get("observacoes","")
    # Salva no banco
    fin = Finalizacao(os_numero=os_numero,
                      gerente=session["gerente"],
                      data_fin=data,
                      hora_fin=hora,
                      observacoes=obs)
    db.session.add(fin)
    db.session.commit()
    # Remove do JSON pendente
    caminho = os.path.join(MENSAGENS_DIR, session["gerente"].upper().replace('.', '_') + "_GONZAGA.json")
    if not os.path.exists(caminho):
        primeiro = session["gerente"].split('.')[0].upper()
        for f in os.listdir(MENSAGENS_DIR):
            if f.upper().startswith(primeiro): caminho = os.path.join(MENSAGENS_DIR, f); break
    try:
        with open(caminho, encoding='utf-8') as f:
            lista = json.load(f)
        lista = [i for i in lista if str(i.get("os") or i.get("OS","")) != os_numero]
        with open(caminho, 'w', encoding='utf-8') as f:
            json.dump(lista, f, indent=2, ensure_ascii=False)
    except: pass
    flash(f"OS {os_numero} finalizada com sucesso", "success")
    return redirect(url_for('painel'))

@app.route("/admin")
def admin_panel():
    if not session.get("is_admin"):
        flash("Acesso não autorizado", "danger")
        return redirect(url_for('login'))
    finalizadas = Finalizacao.query.order_by(Finalizacao.registrado_em.desc())\
                                   .limit(100).all()
    gerentes    = [u.username for u in User.query.all()]
    contagem    = {g: Finalizacao.query.filter_by(gerente=g).count() for g in gerentes}
    os_abertas  = {g: len(carregar_os_gerente(g))        for g in gerentes}
    return render_template("admin.html",
                           finalizadas=finalizadas,
                           total_os=len(finalizadas),
                           gerentes=gerentes,
                           contagem_gerentes=contagem,
                           os_abertas=os_abertas,
                           now=datetime.now())

@app.route("/exportar_os_finalizadas")
def exportar_os_finalizadas():
    if not session.get("is_admin"):
        flash("Acesso não autorizado", "danger")
        return redirect(url_for('login'))
    finalizadas = Finalizacao.query.order_by(Finalizacao.registrado_em.desc()).all()
    if not finalizadas:
        flash("Nenhuma OS finalizada para exportar", "warning")
        return redirect(url_for('admin_panel'))
    # Gera PDF...
    pdf_path = os.path.join(BASE_DIR, 'relatorio.pdf')
    pdf = FPDF(); pdf.add_page(); pdf.set_font("Arial","B",12)
    pdf.cell(0,10,"Relatório de OS Finalizadas",ln=True,align='C'); pdf.ln(5)
    cols, widths = ["OS","Gerente","Data","Hora","Obs"], [20,40,30,25,75]
    pdf.set_font("Arial","B",10)
    for c,w in zip(cols,widths): pdf.cell(w,8,c,border=1)
    pdf.ln(); pdf.set_font("Arial","",9)
    for fz in finalizadas:
        pdf.cell(widths[0],6,fz.os_numero,border=1)
        pdf.cell(widths[1],6,fz.gerente,  border=1)
        pdf.cell(widths[2],6,fz.data_fin, border=1)
        pdf.cell(widths[3],6,fz.hora_fin, border=1)
        pdf.cell(widths[4],6,(fz.observacoes or "")[:40],border=1)
        pdf.ln()
    pdf.output(pdf_path)
    return send_file(pdf_path,
                     as_attachment=True,
                     download_name=f"relatorio_{datetime.now():%Y%m%d}.pdf",
                     mimetype='application/pdf')

@app.route("/logout")
def logout():
    session.clear()
    flash("Você foi desconectado com sucesso", "info")
    return redirect(url_for('login'))

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT",10000)), debug=True)
