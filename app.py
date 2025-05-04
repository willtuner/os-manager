import os
import json
import re
from datetime import datetime
from flask import Flask, render_template, request, redirect, session, url_for, flash, send_file
from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate
from fpdf import FPDF

# --- Configuração do app e banco ---
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
MENSAGENS_DIR = os.path.join(BASE_DIR, 'mensagens_por_gerente')
USERS_FILE = os.path.join(BASE_DIR, 'users.json')
DATABASE_URL = os.environ.get('DATABASE_URL', f"sqlite:///{os.path.join(BASE_DIR,'app.db')}")

os.makedirs(MENSAGENS_DIR, exist_ok=True)

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', os.urandom(24).hex())
app.config.update(
    SQLALCHEMY_DATABASE_URI=DATABASE_URL,
    SQLALCHEMY_TRACK_MODIFICATIONS=False,
    SESSION_COOKIE_SECURE=True,
    SESSION_COOKIE_SAMESITE='Lax'
)

# Extensões
db = SQLAlchemy(app)
migrate = Migrate(app, db)

# --- Models ---
class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password = db.Column(db.String(128), nullable=False)
    is_admin = db.Column(db.Boolean, default=False)

class Finalizacao(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    os_numero = db.Column(db.String(50), nullable=False)
    gerente = db.Column(db.String(80), nullable=False)
    data_fin = db.Column(db.String(10), nullable=False)
    hora_fin = db.Column(db.String(5), nullable=False)
    observacoes = db.Column(db.Text)
    registrado_em = db.Column(db.DateTime, default=datetime.utcnow)

class LoginEvent(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), nullable=False)
    login_time = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    logout_time = db.Column(db.DateTime)
    duration_secs = db.Column(db.Integer)

# --- Inicialização do DB e import de users.json ---
with app.app_context():
    db.create_all()
    if User.query.count() == 0 and os.path.exists(USERS_FILE):
        with open(USERS_FILE, encoding='utf-8') as f:
            data = json.load(f)
        admins = {'wilson.santana'}
        for u, pwd in data.items():
            db.session.add(User(
                username=u.lower(),
                password=pwd,
                is_admin=(u.lower() in admins)
            ))
        db.session.commit()

# --- Funções auxiliares ---
def carregar_os_gerente(gerente):
    # tenta GERENTE.json e GERENTE_GONZAGA.json
    base = gerente.upper().replace('.', '_')
    candidates = [f"{base}.json", f"{base}_GONZAGA.json"]
    path = None
    for name in candidates:
        p = os.path.join(MENSAGENS_DIR, name)
        if os.path.exists(p):
            path = p
            break
    if not path:
        # fallback: qualquer que inicie com base_
        for fn in os.listdir(MENSAGENS_DIR):
            if fn.upper().startswith(base + '_') and fn.lower().endswith('.json'):
                path = os.path.join(MENSAGENS_DIR, fn)
                break
    if not path:
        return []
    # lê JSON e calcula dias em aberto
    with open(path, encoding='utf-8') as f:
        items = json.load(f)
    result = []
    today = datetime.utcnow().date()
    for it in items:
        date_str = it.get('data') or it.get('Data', '')
        opened = None
        for fmt in ('%d/%m/%Y', '%Y-%m-%d', '%d-%m-%Y'):
            try:
                opened = datetime.strptime(date_str, fmt).date()
                break
            except:
                continue
        days_open = (today - opened).days if opened else 0
        result.append({
            'os': str(it.get('os') or it.get('OS', '')),
            'frota': str(it.get('frota') or it.get('Frota', '')),
            'data': date_str,
            'dias': str(days_open),
            'prestador': str(it.get('prestador') or it.get('Prestador', 'Prestador não definido')),
            'servico': str(it.get('servico') or it.get('Servico') or it.get('observacao') or it.get('Observacao', ''))
        })
    return result

# restantes das rotas (login, painel, finalizar, admin, exportar) seguem inalteradas...


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
