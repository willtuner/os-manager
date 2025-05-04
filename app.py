import os
import json
from datetime import datetime
from flask import Flask, render_template, request, redirect, session, url_for, flash
from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate
from werkzeug.security import generate_password_hash, check_password_hash

# --- Configuração do App ---
app = Flask(__name__)

# Configuração para o Render (com fallback para SQLite local)
app.config['SQLALCHEMY_DATABASE_URI'] = os.environ.get('DATABASE_URL', 'sqlite:///app.db').replace('postgres://', 'postgresql://')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.secret_key = os.environ.get('SECRET_KEY', os.urandom(24).hex())

db = SQLAlchemy(app)
migrate = Migrate(app, db)

# --- Modelos do Banco de Dados ---
class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password = db.Column(db.String(128), nullable=False)
    is_admin = db.Column(db.Boolean, default=False)
    is_prestador = db.Column(db.Boolean, default=False)
    nome_exibicao = db.Column(db.String(100))

class OS(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    numero = db.Column(db.String(50), nullable=False)
    frota = db.Column(db.String(50))
    modelo = db.Column(db.String(100))
    data_abertura = db.Column(db.String(10))
    servico = db.Column(db.Text)
    status = db.Column(db.String(20), default='aberta')
    prestador = db.Column(db.String(80))
    gerente_responsavel = db.Column(db.String(80))

class Finalizacao(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    os_numero = db.Column(db.String(50), nullable=False)
    gerente = db.Column(db.String(80))
    prestador = db.Column(db.String(80))
    data_fin = db.Column(db.String(10), nullable=False)
    hora_fin = db.Column(db.String(5), nullable=False)
    observacoes = db.Column(db.Text)
    registrado_em = db.Column(db.DateTime, default=datetime.utcnow)

# --- Diretórios e Configurações ---
BASE_DIR = os.path.dirname(__file__)
GERENTES_DIR = os.path.join(BASE_DIR, 'mensagens_por_gerente')
PRESTADORES_DIR = os.path.join(BASE_DIR, 'mensagens_por_prestador')
os.makedirs(GERENTES_DIR, exist_ok=True)
os.makedirs(PRESTADORES_DIR, exist_ok=True)

# --- Funções Auxiliares ---
def init_db():
    """Inicializa o banco de dados com dados padrão"""
    with app.app_context():
        db.create_all()

        # Criar admin padrão se não existir
        if not User.query.filter_by(username='admin').first():
            admin = User(
                username='admin',
                password=generate_password_hash('admin123'),
                is_admin=True,
                nome_exibicao='Administrador'
            )
            db.session.add(admin)
            db.session.commit()

def carregar_os_para_prestador(prestador_username):
    """Carrega as OS de um prestador específico"""
    try:
        # Verifica se é um prestador válido
        prestador = User.query.filter_by(username=prestador_username, is_prestador=True).first()
        if not prestador:
            return []

        # Carrega do banco de dados (prioritário) ou do JSON (fallback)
        os_do_banco = OS.query.filter_by(prestador=prestador_username, status='aberta').all()
        if os_do_banco:
            return [{
                'numero': os.numero,
                'frota': os.frota,
                'modelo': os.modelo,
                'data_abertura': os.data_abertura,
                'servico': os.servico
            } for os in os_do_banco]

        # Fallback para arquivo JSON
        arquivo_json = os.path.join(PRESTADORES_DIR, f"{prestador_username}.json")
        if os.path.exists(arquivo_json):
            with open(arquivo_json, encoding='utf-8') as f:
                dados = json.load(f)
                return dados.get('ORDENS_DE_SERVICO', [])
        
        return []
    except Exception as e:
        print(f"Erro ao carregar OS: {str(e)}")
        return []

def registrar_finalizacao(os_numero, data, hora, observacoes):
    """Registra a finalização de uma OS"""
    try:
        # Verifica se a OS existe
        os_existente = OS.query.filter_by(numero=os_numero).first()
        if os_existente:
            os_existente.status = 'finalizada'
            db.session.add(os_existente)

        # Cria registro de finalização
        nova_finalizacao = Finalizacao(
            os_numero=os_numero,
            gerente=session.get('user') if session.get('user_type') == 'gerente' else None,
            prestador=session.get('user') if session.get('user_type') == 'prestador' else None,
            data_fin=data,
            hora_fin=hora,
            observacoes=observacoes
        )
        db.session.add(nova_finalizacao)
        db.session.commit()
        return True
    except Exception as e:
        print(f"Erro ao registrar finalização: {str(e)}")
        db.session.rollback()
        return False

# --- Rotas Principais ---
@app.route('/')
def home():
    if 'user' in session:
        return redirect(url_for('painel_prestador' if session.get('user_type') == 'prestador' else 'painel'))
    return redirect(url_for('login'))

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form.get('username', '').strip().lower()
        password = request.form.get('password', '').strip()
        
        user = User.query.filter_by(username=username).first()
        if user and check_password_hash(user.password, password):
            session['user'] = username
            session['user_type'] = 'prestador' if user.is_prestador else 'gerente'
            session['nome_exibicao'] = user.nome_exibicao or username
            
            flash('Login realizado com sucesso!', 'success')
            return redirect(url_for('painel_prestador' if user.is_prestador else 'painel'))
        
        flash('Usuário ou senha inválidos', 'danger')
    return render_template('login.html')

@app.route('/logout')
def logout():
    session.clear()
    flash('Você foi desconectado com sucesso', 'info')
    return redirect(url_for('login'))

# --- Rotas de Prestadores ---
@app.route('/painel_prestador')
def painel_prestador():
    if 'user' not in session or session.get('user_type') != 'prestador':
        return redirect(url_for('login'))
    
    prestador = session['user']
    os_pendentes = carregar_os_para_prestador(prestador)
    finalizadas = Finalizacao.query.filter_by(prestador=prestador).order_by(Finalizacao.registrado_em.desc()).limit(5).all()
    
    return render_template('painel_prestador.html',
                         os_pendentes=os_pendentes,
                         finalizadas=finalizadas,
                         prestador=session.get('nome_exibicao', prestador))

@app.route('/finalizar_os/<os_numero>', methods=['POST'])
def finalizar_os(os_numero):
    if 'user' not in session or session.get('user_type') != 'prestador':
        return redirect(url_for('login'))
    
    data = request.form.get('data_finalizacao', '')
    hora = request.form.get('hora_finalizacao', '')
    observacoes = request.form.get('observacoes', '')
    
    if not data or not hora:
        flash('Data e hora são obrigatórias', 'danger')
        return redirect(url_for('painel_prestador'))
    
    if registrar_finalizacao(os_numero, data, hora, observacoes):
        flash(f'OS {os_numero} finalizada com sucesso!', 'success')
    else:
        flash('Erro ao finalizar a OS', 'danger')
    
    return redirect(url_for('painel_prestador'))

# --- Rotas de Administração ---
@app.route('/admin')
def admin_panel():
    if 'user' not in session or not User.query.filter_by(username=session['user'], is_admin=True).first():
        flash('Acesso não autorizado', 'danger')
        return redirect(url_for('login'))
    
    prestadores = User.query.filter_by(is_prestador=True).all()
    os_abertas = OS.query.filter_by(status='aberta').count()
    os_finalizadas = Finalizacao.query.count()
    
    return render_template('admin.html',
                         prestadores=prestadores,
                         os_abertas=os_abertas,
                         os_finalizadas=os_finalizadas)

# --- Inicialização ---
if __name__ == '__main__':
    init_db()
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 10000)))
