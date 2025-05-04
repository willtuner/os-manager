import os
import json
import re
from datetime import datetime
from flask import Flask, render_template, request, redirect, session, url_for, flash, send_file
from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate               # ← import
from fpdf import FPDF

# --- Configuração do app e banco ---
app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', os.urandom(24).hex())
app.config.update(
    SESSION_COOKIE_SECURE=True,
    SESSION_COOKIE_SAMESITE='Lax',
    SQLALCHEMY_DATABASE_URI=os.environ.get(
        'DATABASE_URL',
        f"sqlite:///{os.path.join(os.path.dirname(__file__),'app.db')}"
    ),
    SQLALCHEMY_TRACK_MODIFICATIONS=False
)
db = SQLAlchemy(app)
migrate = Migrate(app, db)                      # ← inicializa as migrações

# --- Models ---
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

class LoginEvent(db.Model):
    __tablename__ = 'login_events'
    id            = db.Column(db.Integer, primary_key=True)
    username      = db.Column(db.String(80), nullable=False)
    login_time    = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    logout_time   = db.Column(db.DateTime)
    duration_secs = db.Column(db.Integer)



# --- Inicialização de diretórios ---
os.makedirs(MENSAGENS_DIR, exist_ok=True)
os.makedirs(PRESTADORES_DIR, exist_ok=True)

def init_db():
    # cria tabelas
    db.create_all()
    # importa users.json se tabela vazia
    if User.query.count() == 0 and os.path.exists(USERS_FILE):
        with open(USERS_FILE, encoding='utf-8') as f:
            js = json.load(f)
        admins = {'wilson.santana'}
        for u, pwd in js.items():
            db.session.add(User(
                username=u.lower(),
                password=pwd,
                is_admin=(u.lower() in admins)
            ))
        db.session.commit()

def extract_prestadores():
    """
    Varre todas as OS em mensagens_por_gerente e gera um JSON por prestador
    em mensagens_por_prestador/{prestador_key}.json
    """
    # limpa pasta de prestadores
    for fn in os.listdir(PRESTADORES_DIR):
        os.remove(os.path.join(PRESTADORES_DIR, fn))

    for arquivo in os.listdir(MENSAGENS_DIR):
        if not arquivo.lower().endswith('.json'):
            continue
        data = json.load(open(os.path.join(MENSAGENS_DIR,arquivo), encoding='utf-8'))
        for item in data:
            prest = item.get('prestador','').strip()
            if not prest:
                continue
            # normaliza o nome para filename
            key = re.sub(r'\W+', '.', prest.lower())
            path = os.path.join(PRESTADORES_DIR, f'{key}.json')
            arr = []
            if os.path.exists(path):
                arr = json.load(open(path, encoding='utf-8'))
            arr.append(item)
            with open(path, 'w', encoding='utf-8') as f:
                json.dump(arr, f, ensure_ascii=False, indent=2)

def carregar_os_gerente(gerente):
    """carrega apenas o JSON exato de um gerente"""
    base = gerente.upper().replace('.', '_')
    poss = [f"{base}.json", f"{base}_GONZAGA.json"]
    for nome in poss:
        p = os.path.join(MENSAGENS_DIR, nome)
        if os.path.exists(p):
            dados = json.load(open(p, encoding='utf-8'))
            return [{
                "os": str(i.get("os") or i.get("OS","")),
                "frota": str(i.get("frota") or i.get("Frota","")),
                "data": str(i.get("data") or i.get("Data","")),
                "dias": str(i.get("dias") or i.get("Dias","0")),
                "prestador": str(i.get("prestador") or i.get("Prestador","")),
                "servico": str(i.get("servico") or i.get("Servico") or i.get("Observacao",""))
            } for i in dados]
    return []

def carregar_os_prestador(prestador_key):
    """carrega o JSON do prestador normalizado (key gerada pelo extract_prestadores)"""
    p = os.path.join(PRESTADORES_DIR, f'{prestador_key}.json')
    if not os.path.exists(p):
        return []
    dados = json.load(open(p, encoding='utf-8'))
    return [{
        "os": str(i.get("os") or i.get("OS","")),
        "frota": str(i.get("frota") or i.get("Frota","")),
        "data": str(i.get("data") or i.get("Data","")),
        "dias": str(i.get("dias") or i.get("Dias","0")),
        "servico": str(i.get("servico") or i.get("Servico") or i.get("Observacao",""))
    } for i in dados]

# --- Rotas de login/painel gerente ---
@app.route('/')
def index():
    return redirect(url_for('login'))

@app.route('/login', methods=['GET','POST'])
def login():
    erro = None
    if request.method == 'POST':
        u = request.form['gerente'].strip().lower()
        p = request.form['senha'].strip()
        user = User.query.filter_by(username=u).first()
        if user and user.password == p:
            # evento de login
            ev = LoginEvent(username=u)
            db.session.add(ev); db.session.commit()
            session['login_event_id'] = ev.id
            session['user_type'] = 'gerente'
            session['user'] = u
            return redirect(url_for('painel'))
        flash('Usuário ou senha inválidos','danger')
    return render_template('login.html', erro=erro)

@app.route('/painel')
def painel():
    if session.get('user_type')!='gerente':
        return redirect(url_for('login'))
    u = session['user']
    pend = carregar_os_gerente(u)
    return render_template('painel.html',
                           os_pendentes=pend,
                           gerente=u,
                           now=datetime.utcnow())

# --- Rotas de login/painel prestador ---
@app.route('/login_prestador', methods=['GET','POST'])
def login_prestador():
    erro = None
    if request.method=='POST':
        key = request.form['prestador_key'].strip()
        senha = request.form['senha'].strip()
        # validador mínimo: checa trio [key,senha] no users.json
        users = json.load(open(USERS_FILE, encoding='utf-8'))
        if users.get(key)==senha:
            session['user_type'] = 'prestador'
            session['user'] = key
            return redirect(url_for('painel_prestador'))
        flash('Chave ou senha inválidos','danger')
    return render_template('login_prestador.html', erro=erro)

@app.route('/painel_prestador')
def painel_prestador():
    if session.get('user_type')!='prestador':
        return redirect(url_for('login_prestador'))
    key = session['user']
    pend = carregar_os_prestador(key)
    return render_template('painel_prestador.html',
                           os_pendentes=pend,
                           prestador=key,
                           now=datetime.utcnow())

# --- Finalizar OS (comum a ambos gerentes e prestadores) ---
@app.route('/finalizar_os/<os_numero>', methods=['POST'])
def finalizar_os(os_numero):
    if 'user_type' not in session:
        return redirect(url_for('login'))
    tipo = session['user_type']
    user = session['user']
    # lê dados do form
    d = request.form['data_finalizacao']
    h = request.form['hora_finalizacao']
    o = request.form.get('observacoes','')
    # grava no banco
    fz = Finalizacao(os_numero=os_numero,
                     gerente=(user if tipo=='gerente' else None),
                     data_fin=d, hora_fin=h,
                     observacoes=o)
    db.session.add(fz); db.session.commit()
    flash(f'OS {os_numero} finalizada','success')
    # redireciona de volta pro painel certo
    return redirect(url_for('painel' if tipo=='gerente' else 'painel_prestador'))

@app.route('/logout')
def logout():
    ev_id = session.pop('login_event_id', None)
    if ev_id:
        ev = LoginEvent.query.get(ev_id)
        ev.logout_time   = datetime.utcnow()
        ev.duration_secs = int((ev.logout_time - ev.login_time).total_seconds())
        db.session.commit()
    session.clear()
    flash('Desconectado','info')
    return redirect(url_for('login'))

# --- Boot ---
with app.app_context():
    init_db()
    extract_prestadores()

if __name__ == '__main__':
    app.run(host='0.0.0.0',
            port=int(os.environ.get('PORT',10000)),
            debug=True)
