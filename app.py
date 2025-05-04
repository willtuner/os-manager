import os
import json
from datetime import datetime
from flask import Flask, render_template, request, redirect, session, url_for, flash, send_file
from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate
from fpdf import FPDF

# --- Configurações de diretórios e banco ---
BASE_DIR         = os.path.dirname(os.path.abspath(__file__))
MENSAGENS_DIR    = os.path.join(BASE_DIR, 'mensagens_por_gerente')
PRESTADORES_DIR  = os.path.join(BASE_DIR, 'mensagens_por_prestador')
USERS_FILE       = os.path.join(BASE_DIR, 'users.json')
DATABASE_URL     = os.environ.get('DATABASE_URL', f"sqlite:///{os.path.join(BASE_DIR,'app.db')}")

os.makedirs(MENSAGENS_DIR,   exist_ok=True)
os.makedirs(PRESTADORES_DIR, exist_ok=True)

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', os.urandom(24).hex())
app.config.update(
    SQLALCHEMY_DATABASE_URI=DATABASE_URL,
    SQLALCHEMY_TRACK_MODIFICATIONS=False,
    SESSION_COOKIE_SECURE=True,
    SESSION_COOKIE_SAMESITE='Lax'
)

db      = SQLAlchemy(app)
migrate = Migrate(app, db)

# --- Models ---
class User(db.Model):
    id        = db.Column(db.Integer, primary_key=True)
    username  = db.Column(db.String(80), unique=True, nullable=False)
    password  = db.Column(db.String(128), nullable=False)
    is_admin  = db.Column(db.Boolean, default=False)

class Finalizacao(db.Model):
    id             = db.Column(db.Integer, primary_key=True)
    os_numero      = db.Column(db.String(50), nullable=False)
    gerente        = db.Column(db.String(80))  # pode ser null quando for prestador
    prestador      = db.Column(db.String(80))  # opcionalmente guardar quem finalizou
    data_fin       = db.Column(db.String(10), nullable=False)
    hora_fin       = db.Column(db.String(5), nullable=False)
    observacoes    = db.Column(db.Text)
    registrado_em  = db.Column(db.DateTime, default=datetime.utcnow)

class LoginEvent(db.Model):
    id            = db.Column(db.Integer, primary_key=True)
    username      = db.Column(db.String(80), nullable=False)
    login_time    = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    logout_time   = db.Column(db.DateTime)
    duration_secs = db.Column(db.Integer)

# --- Inicialização do banco e import de users.json ---
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

# --- Auxiliares de carregamento de OS ---
def carregar_os_gerente(gerente_key):
    """
    Lê o JSON de pendentes do gerente e calcula dias em aberto.
    """
    base = gerente_key.upper().replace('.', '_')
    # tenta GERENTE.json e GERENTE_GONZAGA.json
    candidatos = [f"{base}.json", f"{base}_GONZAGA.json"]
    caminho = None
    for nome in candidatos:
        p = os.path.join(MENSAGENS_DIR, nome)
        if os.path.exists(p):
            caminho = p; break
    # fallback: qualquer que comece com base_
    if not caminho:
        for fn in os.listdir(MENSAGENS_DIR):
            if fn.upper().startswith(base + '_') and fn.lower().endswith('.json'):
                caminho = os.path.join(MENSAGENS_DIR, fn)
                break
    if not caminho:
        return []

    with open(caminho, encoding='utf-8') as f:
        items = json.load(f)

    hoje = datetime.utcnow().date()
    resultado = []
    for it in items:
        data_str = it.get('data') or it.get('Data', '')
        aberto = None
        for fmt in ('%d/%m/%Y','%Y-%m-%d','%d-%m-%Y'):
            try:
                aberto = datetime.strptime(data_str, fmt).date()
                break
            except:
                continue
        dias = (hoje - aberto).days if aberto else 0

        resultado.append({
            'os':        str(it.get('os') or it.get('OS','')),
            'frota':     str(it.get('frota') or it.get('Frota','')),
            'data':      data_str,
            'dias':      str(dias),
            'prestador': str(it.get('prestador') or it.get('Prestador','Prestador não definido')),
            'servico':   str(it.get('servico') or it.get('Servico') or it.get('observacao') or it.get('Observacao',''))
        })
    return resultado

def carregar_os_prestador(prest_key):
    """
    Lê o JSON de pendentes do prestador (slug) e calcula dias em aberto.
    """
    caminho = os.path.join(PRESTADORES_DIR, f"{prest_key}.json")
    if not os.path.exists(caminho):
        return []
    with open(caminho, encoding='utf-8') as f:
        items = json.load(f)

    hoje = datetime.utcnow().date()
    resultado = []
    for it in items:
        data_str = it.get('data') or it.get('Data', '')
        aberto = None
        for fmt in ('%d/%m/%Y','%Y-%m-%d','%d-%m-%Y'):
            try:
                aberto = datetime.strptime(data_str, fmt).date()
                break
            except:
                continue
        dias = (hoje - aberto).days if aberto else 0

        resultado.append({
            'os':        str(it.get('os') or it.get('OS','')),
            'frota':     str(it.get('frota') or it.get('Frota','')),
            'data':      data_str,
            'dias':      str(dias),
            'servico':   str(it.get('servico') or it.get('Servico') or it.get('observacao') or it.get('Observacao',''))
        })
    return resultado

# --- Rotas de Gerente ---
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
            ev = LoginEvent(username=u)
            db.session.add(ev); db.session.commit()
            session['login_event_id'] = ev.id
            session['user_type'] = 'gerente'
            session['user']      = u
            return redirect(url_for('painel'))
        flash('Usuário ou senha inválidos','danger')
    return render_template('login.html', erro=erro)

@app.route('/painel')
def painel():
    if session.get('user_type') != 'gerente':
        return redirect(url_for('login'))
    u    = session['user']
    pend = carregar_os_gerente(u)
    return render_template('painel.html',
                           os_pendentes=pend,
                           gerente=u,
                           now=datetime.utcnow())

# --- Rotas de Prestador ---
@app.route('/login_prestador', methods=['GET','POST'])
def login_prestador():
    erro = None
    if request.method == 'POST':
        key   = request.form['prestador_key'].strip().lower()
        senha = request.form['senha'].strip()
        users = json.load(open(USERS_FILE, encoding='utf-8'))
        if users.get(key) == senha:
            session['user_type'] = 'prestador'
            session['user']      = key
            return redirect(url_for('painel_prestador'))
        flash('Chave ou senha inválidos','danger')
    return render_template('login_prestador.html', erro=erro)

@app.route('/painel_prestador')
def painel_prestador():
    if session.get('user_type') != 'prestador':
        return redirect(url_for('login_prestador'))
    key  = session['user']
    pend = carregar_os_prestador(key)
    return render_template('painel_prestador.html',
                           os_pendentes=pend,
                           prestador=key,
                           now=datetime.utcnow())

# --- Rota comum de finalizar OS ---
@app.route('/finalizar_os/<os_numero>', methods=['POST'])
def finalizar_os(os_numero):
    if 'user_type' not in session:
        return redirect(url_for('login'))
    tipo = session['user_type']
    usr  = session['user']
    d    = request.form['data_finalizacao']
    h    = request.form['hora_finalizacao']
    o    = request.form.get('observacoes','')
    fz   = Finalizacao(
        os_numero=os_numero,
        gerente  = usr if tipo == 'gerente' else None,
        prestador= usr if tipo == 'prestador' else None,
        data_fin = d,
        hora_fin = h,
        observacoes=o
    )
    db.session.add(fz); db.session.commit()
    flash(f'OS {os_numero} finalizada','success')
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

# --- main ---
if __name__ == '__main__':
    app.run(host='0.0.0.0',
            port=int(os.environ.get('PORT',10000)),
            debug=True)
