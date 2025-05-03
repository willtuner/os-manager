import os
import json
import re
from datetime import datetime
from flask import Flask, render_template, request, redirect, session, url_for, flash, send_file
from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate  # <--- importação do Flask-Migrate
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
migrate = Migrate(app, db)  # <--- inicialização do Flask-Migrate

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

# --- Paths e inicialização ---
BASE_DIR         = os.path.dirname(__file__)
GERENTES_DIR     = os.path.join(BASE_DIR, 'mensagens_por_gerente')
PRESTADORES_DIR  = os.path.join(BASE_DIR, 'mensagens_por_prestador')
USERS_FILE       = os.path.join(BASE_DIR, 'users.json')
os.makedirs(GERENTES_DIR, exist_ok=True)
os.makedirs(PRESTADORES_DIR, exist_ok=True)

# --- Helpers ---
def slugify(name):
    s = name.strip().upper()
    # remove acentos
    s = re.sub(r'[ÀÁÂÃÄÅ]', 'A', s)
    s = re.sub(r'[ÈÉÊË]',   'E', s)
    s = re.sub(r'[ÍÌÎÏ]',   'I', s)
    s = re.sub(r'[ÓÒÔÕÖ]',  'O', s)
    s = re.sub(r'[ÚÙÛÜ]',   'U', s)
    # tudo que não for letra/número vira ponto
    s = re.sub(r'[^A-Z0-9]+', '.', s)
    s = re.sub(r'\.+', '.', s).strip('.')
    return s.lower()

def carregar_os_gerente(gerente):
    base = gerente.upper().replace('.', '_')
    # tenta GERENTE.json e GERENTE_GONZAGA.json
    for suf in ('', '_GONZAGA'):
        p = os.path.join(GERENTES_DIR, f"{base}{suf}.json")
        if os.path.exists(p):
            return json.load(open(p, encoding='utf-8'))
    # fallback: qualquer que comece com base + '_'
    for fn in os.listdir(GERENTES_DIR):
        if fn.upper().startswith(base + '_') and fn.lower().endswith('.json'):
            return json.load(open(os.path.join(GERENTES_DIR, fn), encoding='utf-8'))
    return []

def carregar_os_prestador(prestador):
    slug = slugify(prestador)
    p = os.path.join(PRESTADORES_DIR, f"{slug}.json")
    if os.path.exists(p):
        return json.load(open(p, encoding='utf-8'))
    return []

def init_db():
    db.create_all()
    # importa usuários do JSON se tabela vazia
    if User.query.count() == 0 and os.path.exists(USERS_FILE):
        js = json.load(open(USERS_FILE, encoding='utf-8'))
        admins = {'wilson.santana'}
        for u,pwd in js.items():
            db.session.add(User(
                username=u.lower(),
                password=pwd,
                is_admin=(u.lower() in admins)
            ))
        db.session.commit()

# garante criação/interrupção
with app.app_context():
    init_db()

# --- Rotas ---
@app.route('/')
def index():
    return redirect(url_for('login'))

@app.route('/login', methods=['GET','POST'])
def login():
    if request.method == 'POST':
        u = request.form['gerente'].strip().lower()
        p = request.form['senha'].strip()
        user = User.query.filter_by(username=u).first()
        if user and user.password == p:
            # registra evento de login
            ev = LoginEvent(username=u)
            db.session.add(ev); db.session.commit()
            session['login_event_id'] = ev.id
            session['user'] = u
            session['is_admin'] = user.is_admin
            # define tipo de painel
            if user.is_admin:
                target = 'admin_panel'
            elif os.path.exists(os.path.join(PRESTADORES_DIR, f"{slugify(u)}.json")):
                session['tipo'] = 'prestador'
                target = 'prestador_painel'
            else:
                session['tipo'] = 'gerente'
                target = 'painel'
            return redirect(url_for(target))
        flash('Usuário ou senha inválidos','danger')
    return render_template('login.html')

@app.route('/painel')
def painel():
    if 'user' not in session or session.get('tipo') != 'gerente':
        return redirect(url_for('login'))
    pend = carregar_os_gerente(session['user'])
    return render_template('painel.html',
                           os_pendentes=pend,
                           gerente=session['user'],
                           now=datetime.utcnow())

@app.route('/prestador_painel')
def prestador_painel():
    if 'user' not in session or session.get('tipo') != 'prestador':
        return redirect(url_for('login'))
    pend = carregar_os_prestador(session['user'])
    return render_template('painel_prestador.html',
                           os_pendentes=pend,
                           prestador=session['user'],
                           now=datetime.utcnow())

@app.route('/finalizar_os/<os_numero>', methods=['POST'])
def finalizar_os(os_numero):
    if 'user' not in session:
        return redirect(url_for('login'))
    d = request.form['data_finalizacao']
    h = request.form['hora_finalizacao']
    o = request.form.get('observacoes','')
    fz = Finalizacao(
        os_numero=os_numero,
        usuario=session['user'],
        data_fin=d, hora_fin=h,
        observacoes=o
    )
    db.session.add(fz)
    # remove do JSON de acordo com tipo
    if session.get('tipo') == 'gerente':
        lista = carregar_os_gerente(session['user'])
        path  = os.path.join(GERENTES_DIR, f"{session['user'].upper().replace('.', '_')}.json")
    else:
        lista = carregar_os_prestador(session['user'])
        path  = os.path.join(PRESTADORES_DIR, f"{slugify(session['user'])}.json")
    # filtra e sobrescreve
    lista = [i for i in lista if str(i.get('os') or i.get('OS')) != os_numero]
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(lista, f, ensure_ascii=False, indent=2)
    db.session.commit()
    flash(f'OS {os_numero} finalizada','success')
    # redireciona ao painel correto
    if session.get('tipo') == 'prestador':
        return redirect(url_for('prestador_painel'))
    return redirect(url_for('painel'))

@app.route('/admin')
def admin_panel():
    if not session.get('is_admin'):
        flash('Acesso negado','danger')
        return redirect(url_for('login'))
    finalizadas  = Finalizacao.query.order_by(Finalizacao.registrado_em.desc()).limit(100).all()
    login_events = LoginEvent.query.order_by(LoginEvent.login_time.desc()).limit(50).all()
    users        = User.query.order_by(User.username).all()
    gerentes     = [u.username for u in users if not u.is_admin]
    contagem     = {g: Finalizacao.query.filter_by(usuario=g).count() for g in gerentes}
    abertas      = {g: len(carregar_os_gerente(g)) for g in gerentes}
    return render_template('admin.html',
                           finalizadas=finalizadas,
                           total_os=len(finalizadas),
                           gerentes=gerentes,
                           contagem_gerentes=contagem,
                           os_abertas=abertas,
                           login_events=login_events,
                           now=datetime.utcnow())

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

if __name__ == '__main__':
    app.run(host='0.0.0.0',
            port=int(os.environ.get('PORT',10000)),
            debug=True)
