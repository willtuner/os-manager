import os
import json
import re
from datetime import datetime
from flask import Flask, render_template, request, redirect, session, url_for, flash, send_file
from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate
from fpdf import FPDF
from werkzeug.security import generate_password_hash, check_password_hash

# --- Configuração do Flask e do banco ---
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
migrate = Migrate(app, db)

# --- Models ---
class User(db.Model):
    id        = db.Column(db.Integer, primary_key=True)
    username  = db.Column(db.String(80), unique=True, nullable=False)
    password  = db.Column(db.String(128), nullable=False)
    is_admin  = db.Column(db.Boolean, default=False)
    is_prestador = db.Column(db.Boolean, default=False)

class Finalizacao(db.Model):
    id            = db.Column(db.Integer, primary_key=True)
    os_numero     = db.Column(db.String(50), nullable=False)
    gerente       = db.Column(db.String(80))
    prestador     = db.Column(db.String(80))
    data_fin      = db.Column(db.String(10), nullable=False)
    hora_fin      = db.Column(db.String(5), nullable=False)
    observacoes   = db.Column(db.Text)
    registrado_em = db.Column(db.DateTime, default=datetime.utcnow)

class LoginEvent(db.Model):
    id            = db.Column(db.Integer, primary_key=True)
    username      = db.Column(db.String(80), nullable=False)
    login_time    = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    logout_time   = db.Column(db.DateTime)
    duration_secs = db.Column(db.Integer)

# --- Diretórios e arquivos ---
BASE_DIR         = os.path.dirname(__file__)
GERENTES_DIR     = os.path.join(BASE_DIR, 'mensagens_por_gerente')
PRESTADORES_DIR  = os.path.join(BASE_DIR, 'mensagens_por_prestador')
USERS_FILE       = os.path.join(BASE_DIR, 'users.json')
PRESTADORES_CRED_FILE = os.path.join(PRESTADORES_DIR, 'credenciais.json')

os.makedirs(GERENTES_DIR, exist_ok=True)
os.makedirs(PRESTADORES_DIR, exist_ok=True)

def init_db():
    """Cria tabelas e importa usuários se ainda não existirem"""
    db.create_all()
    
    # Criar usuários gerentes
    if User.query.filter_by(is_prestador=False).count() == 0 and os.path.exists(USERS_FILE):
        with open(USERS_FILE, encoding='utf-8') as f:
            users = json.load(f)
        admins = {'wilson.santana'}
        for u, pwd in users.items():
            db.session.add(User(
                username=u.lower(),
                password=generate_password_hash(pwd),
                is_admin=(u.lower() in admins),
                is_prestador=False
            ))
    
    # Criar usuários prestadores
    if User.query.filter_by(is_prestador=True).count() == 0 and os.path.exists(PRESTADORES_CRED_FILE):
        with open(PRESTADORES_CRED_FILE, encoding='utf-8') as f:
            prestadores = json.load(f)
        for u, pwd in prestadores.items():
            db.session.add(User(
                username=u.lower(),
                password=generate_password_hash(pwd),
                is_admin=False,
                is_prestador=True
            ))
    
    db.session.commit()

def carregar_os_gerente(gerente_key):
    """Carrega OS para gerentes"""
    base = gerente_key.upper().replace('.', '_')
    for fn in os.listdir(GERENTES_DIR):
        if fn.upper().startswith(base) and fn.lower().endswith('.json'):
            caminho = os.path.join(GERENTES_DIR, fn)
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
                    'os': str(it.get('os') or it.get('OS','')),
                    'frota': str(it.get('frota') or it.get('Frota','')),
                    'modelo': str(it.get('modelo') or it.get('Modelo','')),
                    'data': data_str,
                    'dias': str(dias),
                    'servico': str(it.get('servico') or it.get('Servico') or 
                               it.get('observacao') or it.get('Observacao','')),
                    'prestador': str(it.get('prestador') or it.get('Prestador','Prestador não definido'))
                })
            return resultado
    return []

def carregar_os_prestador(prestador_key):
    """Carrega OS para prestadores"""
    caminho = os.path.join(PRESTADORES_DIR, f"{prestador_key}.json")
    if not os.path.exists(caminho):
        return []
    
    with open(caminho, encoding='utf-8') as f:
        try:
            dados = json.load(f)
            hoje = datetime.utcnow().date()
            
            return [{
                'os': str(item.get('NO_SERVICO') or item.get('os') or ''),
                'frota': str(item.get('CD_EQT') or item.get('frota') or ''),
                'modelo': str(item.get('MODELO') or item.get('modelo') or ''),
                'data': item.get('DT_ENTRADA') or item.get('data') or '',
                'servico': str(item.get('SERVICO') or item.get('servico') or ''),
                'dias': str((hoje - datetime.strptime(item.get('DT_ENTRADA') or item.get('data'), '%d/%m/%Y').date()).days)
            } for item in dados.get('ORDENS_DE_SERVICO', []) if item]
        except Exception as e:
            print(f"Erro ao ler arquivo {caminho}: {str(e)}")
            return []

# --- Rotas de Autenticação ---
@app.route('/', methods=['GET'])
def home():
    return redirect(url_for('login'))

@app.route('/login', methods=['GET','POST'])
def login():
    if request.method == 'POST':
        username = request.form['username'].strip().lower()
        password = request.form['password'].strip()
        user = User.query.filter_by(username=username).first()
        
        if user and check_password_hash(user.password, password):
            # Registrar evento de login
            ev = LoginEvent(username=username)
            db.session.add(ev)
            db.session.commit()
            
            # Configurar sessão
            session['login_event_id'] = ev.id
            session['user_type'] = 'prestador' if user.is_prestador else 'gerente'
            session['user'] = username
            
            # Redirecionar para o painel apropriado
            if user.is_prestador:
                return redirect(url_for('painel_prestador'))
            return redirect(url_for('painel'))
        
        flash('Usuário ou senha inválidos', 'danger')
    return render_template('login.html'))

# --- Painéis ---
@app.route('/painel')
def painel():
    if session.get('user_type') != 'gerente':
        return redirect(url_for('login'))
    
    user = session['user']
    pendentes = carregar_os_gerente(user)
    finalizadas = Finalizacao.query.filter_by(gerente=user)\
                     .order_by(Finalizacao.registrado_em.desc())\
                     .limit(100).all()
    
    return render_template('painel.html',
                         os_pendentes=pendentes,
                         finalizadas=finalizadas,
                         gerente=user,
                         now=datetime.utcnow())

@app.route('/painel_prestador')
def painel_prestador():
    if session.get('user_type') != 'prestador':
        return redirect(url_for('login'))
    
    user = session['user']
    pendentes = carregar_os_prestador(user)
    finalizadas = Finalizacao.query.filter_by(prestador=user)\
                     .order_by(Finalizacao.registrado_em.desc())\
                     .limit(100).all()
    
    return render_template('painel_prestador.html',
                         os_pendentes=pendentes,
                         finalizadas=finalizadas,
                         prestador=user,
                         now=datetime.utcnow())

# --- Operações com OS ---
@app.route('/finalizar_os/<os_numero>', methods=['POST'])
def finalizar_os(os_numero):
    if session.get('user_type') not in ('gerente', 'prestador'):
        return redirect(url_for('login'))
    
    user = session['user']
    user_type = session['user_type']
    
    registro = Finalizacao(
        os_numero=os_numero,
        gerente=user if user_type == 'gerente' else None,
        prestador=user if user_type == 'prestador' else None,
        data_fin=request.form['data_finalizacao'],
        hora_fin=request.form['hora_finalizacao'],
        observacoes=request.form.get('observacoes', '')
    )
    
    db.session.add(registro)
    db.session.commit()
    flash(f'OS {os_numero} finalizada com sucesso!', 'success')
    
    return redirect(url_for('painel_prestador' if user_type == 'prestador' else 'painel'))

# --- Administração ---
@app.route('/admin')
def admin_panel():
    if not (session.get('user_type') == 'gerente' and 
           User.query.filter_by(username=session.get('user'), is_admin=True).first()):
        flash('Acesso não autorizado', 'danger')
        return redirect(url_for('login'))
    
    # Estatísticas
    gerentes = [u.username for u in User.query.filter_by(is_prestador=False).all()]
    prestadores = [u.username for u in User.query.filter_by(is_prestador=True).all()]
    
    return render_template('admin.html',
                         gerentes=gerentes,
                         prestadores=prestadores,
                         now=datetime.utcnow())

# --- Utilitários ---
@app.route('/logout')
def logout():
    # Registrar logout
    if 'login_event_id' in session:
        ev = LoginEvent.query.get(session['login_event_id'])
        if ev:
            ev.logout_time = datetime.utcnow()
            ev.duration_secs = (ev.logout_time - ev.login_time).seconds
            db.session.commit()
    
    # Limpar sessão
    session.clear()
    flash('Você foi desconectado com sucesso', 'info')
    return redirect(url_for('login'))

# --- Inicialização ---
with app.app_context():
    init_db()

if __name__ == '__main__':
    app.run(host='0.0.0.0',
            port=int(os.environ.get('PORT', 10000)),
            debug=True)
