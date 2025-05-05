import os
import json
from datetime import datetime
from flask import Flask, render_template, request, redirect, session, url_for, flash
from flask_sqlalchemy import SQLAlchemy
from fpdf import FPDF

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

# --- Models ---
class User(db.Model):
    __tablename__ = 'user'
    id        = db.Column(db.Integer,   primary_key=True)
    username  = db.Column(db.String(80), unique=True, nullable=False)
    password  = db.Column(db.String(128), nullable=False)
    is_admin  = db.Column(db.Boolean,    default=False)

class Finalizacao(db.Model):
    __tablename__ = 'finalizacao'
    id            = db.Column(db.Integer,   primary_key=True)
    os_numero     = db.Column(db.String(50), nullable=False)
    prestador     = db.Column(db.String(80))
    gerente       = db.Column(db.String(80))
    data_fin      = db.Column(db.String(10), nullable=False)
    hora_fin      = db.Column(db.String(5),  nullable=False)
    observacoes   = db.Column(db.Text)
    registrado_em = db.Column(db.DateTime, default=datetime.utcnow)

# --- Diretórios e arquivos ---
BASE_DIR        = os.path.dirname(__file__)
GERENTES_DIR    = os.path.join(BASE_DIR, 'mensagens_por_gerente')
PRESTADORES_DIR = os.path.join(BASE_DIR, 'mensagens_por_prestador')
USERS_FILE      = os.path.join(BASE_DIR, 'users.json')

os.makedirs(GERENTES_DIR, exist_ok=True)
os.makedirs(PRESTADORES_DIR, exist_ok=True)

def init_db():
    db.create_all()
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

def carregar_json(dirpath, key):
    """
    Carrega todo JSON*.json do diretório, filtrando pelo nome de usuário.
    """
    data = []
    user_parts = key.lower().split('.')

    for filename in os.listdir(dirpath):
        if not filename.lower().endswith('.json'):
            continue

        # chave do arquivo sem extensão
        file_key = filename[:-5].lower().replace('_',' ').split()
        
        # cada parte do usuário deve aparecer em algum token do file_key
        if all(any(up in fk for fk in file_key) for up in user_parts):
            try:
                with open(os.path.join(dirpath, filename), encoding='utf-8') as f:
                    content = json.load(f)
                if isinstance(content, dict) and 'ORDENS_DE_SERVICO' in content:
                    data.extend(content['ORDENS_DE_SERVICO'])
                else:
                    data.extend(content)
            except Exception as e:
                app.logger.error(f"Falha ao ler {filename}: {e}")
    return data

def montar_lista(items):
    out = []
    hoje = datetime.utcnow().date()

    for it in items:
        os_num  = it.get('os') or it.get('OS') or it.get('NO-SERVIÇO','')
        frota   = it.get('frota') or it.get('Frota') or it.get('CD_EQT','')
        serv    = it.get('servico') or it.get('Servico') or it.get('SERVIÇO','')
        prest   = it.get('prestador') or it.get('Prestador') or it.get('PREST_SERVIÇO','Prestador não definido')
        data_str= it.get('data') or it.get('Data') or it.get('DT_ENTRADA','')
        
        # parse data
        data_dt = None
        for fmt in ('%d/%m/%Y','%Y-%m-%d','%d-%m-%Y'):
            try:
                data_dt = datetime.strptime(data_str, fmt).date()
                break
            except:
                pass
        dias = (hoje - data_dt).days if data_dt else 0

        out.append({
            'os':        str(os_num),
            'frota':     str(frota),
            'data':      data_str,
            'dias':      dias,
            'servico':   str(serv),
            'prestador': str(prest)
        })
    return out

# --- Rotas comuns ---
@app.route('/')
def home():
    return redirect(url_for('login'))

@app.route('/login', methods=['GET','POST'])
def login():
    erro = None
    if request.method == 'POST':
        u = request.form['gerente'].strip().lower()
        p = request.form['senha'].strip()
        user = User.query.filter_by(username=u).first()
        if user and user.password == p:
            session['user'] = u
            if user.is_admin:
                session['type'] = 'admin'
                return redirect(url_for('admin_panel'))
            session['type'] = 'gerente'
            return redirect(url_for('painel_gerente'))
        flash('Credenciais inválidas','danger')
    return render_template('login.html', erro=erro)

@app.route('/logout')
def logout():
    session.clear()
    flash('Desconectado com sucesso','info')
    return redirect(url_for('login'))

# --- Painel Gerente ---
@app.route('/painel_gerente')
def painel_gerente():
    if session.get('type') != 'gerente':
        return redirect(url_for('login'))
    raw = carregar_json(GERENTES_DIR, session['user'])
    pend = montar_lista(raw)
    return render_template('painel.html', os_pendentes=pend, gerente=session['user'])

# --- Painel Prestador ---
@app.route('/login_prestador', methods=['GET','POST'])
def login_prestador():
    erro = None
    if request.method == 'POST':
        key = request.form['prestador_key'].strip().lower()
        p   = request.form['senha'].strip()
        users = json.load(open(USERS_FILE, encoding='utf-8'))
        if users.get(key) == p:
            session['type'] = 'prestador'
            session['user'] = key
            return redirect(url_for('painel_prestador'))
        flash('Chave ou senha inválidos','danger')
    return render_template('login_prestador.html', erro=erro)

@app.route('/painel_prestador')
def painel_prestador():
    if session.get('type') != 'prestador':
        return redirect(url_for('login_prestador'))
    raw = carregar_json(PRESTADORES_DIR, session['user'])
    pend = montar_lista(raw)
    return render_template('painel_prestador.html',
                           os_pendentes=pend,
                           prestador=session['user'])

# --- Finalizar OS (comum) ---
@app.route('/finalizar/<os_numero>', methods=['POST'])
def finalizar(os_numero):
    tipo = session.get('type')
    if tipo not in ('gerente','prestador'):
        return redirect(url_for('login'))
    f = Finalizacao(
        os_numero=os_numero,
        gerente   = session['user'] if tipo=='gerente' else None,
        prestador = session['user'] if tipo=='prestador' else None,
        data_fin  = request.form['data_finalizacao'],
        hora_fin  = request.form['hora_finalizacao'],
        observacoes=request.form.get('observacoes','')
    )
    db.session.add(f)
    db.session.commit()
    flash(f'OS {os_numero} finalizada','success')
    return redirect(url_for('painel_gerente' if tipo=='gerente' else 'painel_prestador'))

# --- Painel Admin ---
@app.route('/admin')
def admin_panel():
    if session.get('type') != 'admin':
        return redirect(url_for('login'))
    finalizadas = Finalizacao.query.order_by(Finalizacao.registrado_em.desc()).all()
    contagem    = {}
    for fz in finalizadas:
        contagem[fz.gerente or fz.prestador] = contagem.get(fz.gerente or fz.prestador, 0) + 1
    return render_template('admin.html',
                           finalizadas=finalizadas,
                           contagem_gerentes=contagem,
                           total_os=len(finalizadas))

# --- Inicializa banco ---
with app.app_context():
    init_db()

if __name__ == '__main__':
    app.run(debug=True)
