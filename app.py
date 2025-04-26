import os
import json
from datetime import datetime
from flask import (
    Flask, render_template, request, redirect, session,
    url_for, flash, send_file
)
from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate
from fpdf import FPDF

# ─── Configurações iniciais ────────────────────────────────────────────────────
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "os_manager.db")

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", os.urandom(24).hex())
app.config["SESSION_COOKIE_SECURE"] = True
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"

# ─── Banco de Dados ────────────────────────────────────────────────────────────
app.config["SQLALCHEMY_DATABASE_URI"] = f"sqlite:///{DB_PATH}"
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

db = SQLAlchemy(app)
migrate = Migrate(app, db)

# ─── Models ───────────────────────────────────────────────────────────────────
class User(db.Model):
    __tablename__ = "users"
    id        = db.Column(db.Integer, primary_key=True)
    username  = db.Column(db.String(64), unique=True, nullable=False)
    password  = db.Column(db.String(128), nullable=False)
    is_admin  = db.Column(db.Boolean, default=False)

class OSMessage(db.Model):
    __tablename__ = "os_messages"
    id        = db.Column(db.Integer, primary_key=True)
    os_numero = db.Column(db.String(32), nullable=False)
    frota     = db.Column(db.String(32))
    data      = db.Column(db.String(32))
    dias      = db.Column(db.Integer)
    prestador = db.Column(db.String(64))
    servico   = db.Column(db.Text)
    gerente   = db.Column(db.String(64), nullable=False)

class Finalizacao(db.Model):
    __tablename__ = "finalizacoes"
    id             = db.Column(db.Integer, primary_key=True)
    os_numero      = db.Column(db.String(32), nullable=False)
    gerente        = db.Column(db.String(64), nullable=False)
    data_fin       = db.Column(db.String(32))
    hora_fin       = db.Column(db.String(16))
    observacoes    = db.Column(db.Text)
    registrado_em  = db.Column(db.DateTime, default=datetime.utcnow)

# ─── Usuários Admin Hard-code (apenas para seed inicial) ─────────────────────
ADMIN_USERS = {"wilson.santana": "admin321"}

# ─── Rotas ────────────────────────────────────────────────────────────────────
@app.route("/")
def index():
    return redirect(url_for("login"))

@app.route("/login", methods=["GET", "POST"])
def login():
    erro = None
    if request.method == "POST":
        u = request.form["gerente"].strip().lower()
        p = request.form["senha"].strip()

        # Admin hardcoded
        if ADMIN_USERS.get(u) == p:
            session["gerente"] = u
            session["is_admin"] = True
            return redirect(url_for("admin_panel"))

        # Usuário comum do banco
        user = User.query.filter_by(username=u).first()
        if user and user.password == p:
            session["gerente"] = u
            session["is_admin"] = False
            return redirect(url_for("painel"))

        erro = "Usuário ou senha inválidos"
        flash(erro, "danger")

    return render_template("login.html", erro=erro)

@app.route("/painel", methods=["GET"])
def painel():
    if "gerente" not in session:
        return redirect(url_for("login"))

    g = session["gerente"]
    pendentes = OSMessage.query.filter_by(gerente=g).all()
    return render_template(
        "painel.html",
        os_pendentes=pendentes,
        gerente=g,
        now=datetime.now()
    )

@app.route("/finalizar_os/<os_numero>", methods=["POST"])
def finalizar_os(os_numero):
    if "gerente" not in session:
        return redirect(url_for("login"))

    g    = session["gerente"]
    data = request.form.get("data_finalizacao")
    hora = request.form.get("hora_finalizacao")
    obs  = request.form.get("observacoes", "")

    # 1. Registra a finalização
    fim = Finalizacao(
        os_numero=os_numero,
        gerente=g,
        data_fin=data,
        hora_fin=hora,
        observacoes=obs
    )
    db.session.add(fim)

    # 2. Remove da tabela de mensagens pendentes
    OSMessage.query.filter_by(gerente=g, os_numero=os_numero).delete()

    db.session.commit()
    flash(f"OS {os_numero} finalizada com sucesso", "success")
    return redirect(url_for("painel"))

@app.route("/admin")
def admin_panel():
    if "gerente" not in session or not session.get("is_admin"):
        flash("Acesso não autorizado", "danger")
        return redirect(url_for("login"))

    finalizadas = Finalizacao.query.order_by(Finalizacao.registrado_em.desc()).limit(100).all()
    total_os    = Finalizacao.query.count()
    contagem    = {
        f.gerente: db.session.query(Finalizacao).filter_by(gerente=f.gerente).count()
        for f in finalizadas
    }
    ativos      = [u.username for u in User.query.all()]
    os_abertas  = {
        u: OSMessage.query.filter_by(gerente=u).count()
        for u in ativos
    }

    return render_template(
        "admin.html",
        finalizadas=finalizadas,
        total_os=total_os,
        gerentes=ativos,
        contagem_gerentes=contagem,
        os_abertas=os_abertas,
        now=datetime.now()
    )

@app.route("/exportar_os_finalizadas")
def exportar_os_finalizadas():
    if "gerente" not in session or not session.get("is_admin"):
        flash("Acesso não autorizado", "danger")
        return redirect(url_for("login"))

    todos = Finalizacao.query.order_by(Finalizacao.registrado_em).all()
    if not todos:
        flash("Nenhuma OS finalizada para exportar", "warning")
        return redirect(url_for("admin_panel"))

    # Gera PDF
    tmp_dir   = "/tmp/relatorios"
    os.makedirs(tmp_dir, exist_ok=True)
    pdf_path  = os.path.join(tmp_dir, "relatorio_finalizacoes.pdf")
    pdf       = FPDF()
    pdf.add_page()
    pdf.set_font("Arial", "B", 12)
    pdf.cell(0, 10, "Relatório de OS Finalizadas", ln=True, align="C")
    pdf.ln(5)

    cols   = ["OS","Gerente","Data","Hora","Observações"]
    widths = [20,40,30,25,75]
    pdf.set_font("Arial","B",10)
    for c,w in zip(cols,widths):
        pdf.cell(w, 8, c, border=1)
    pdf.ln()

    pdf.set_font("Arial","",9)
    for row in todos:
        pdf.cell(widths[0],6, row.os_numero, border=1)
        pdf.cell(widths[1],6, row.gerente,    border=1)
        pdf.cell(widths[2],6, row.data_fin,   border=1)
        pdf.cell(widths[3],6, row.hora_fin,   border=1)
        obs = (row.observacoes or "")[:40]
        pdf.cell(widths[4],6, obs, border=1)
        pdf.ln()

    pdf.output(pdf_path)
    return send_file(
        pdf_path,
        as_attachment=True,
        download_name=f"relatorio_os_{datetime.now():%Y%m%d}.pdf",
        mimetype="application/pdf"
    )

@app.route("/logout")
def logout():
    session.clear()
    flash("Você foi desconectado com sucesso", "info")
    return redirect(url_for("login"))

# ─── Run ───────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port, debug=True)
