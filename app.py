import os
import json
from datetime import datetime
from flask import Flask, render_template, request, redirect, session, url_for, flash
from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate
from werkzeug.security import generate_password_hash, check_password_hash

# --- Configuração do App ---
app = Flask(__name__)

# Configuração para o Render (com fallback para SQLite)
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
    numero = db.Column(db.String(50), unique=True, nullable=False)
    frota = db.Column(db.String(50))
    modelo = db.Column(db.String(100))
    data_abertura = db.Column(db.String(10))
    servico = db.Column(db.Text)
    status = db.Column(db.String(20), default='aberta')
    prestador = db.Column(db.String(80))
    observacoes = db.Column(db.Text)

class Finalizacao(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    os_numero = db.Column(db.String(50), nullable=False)
    prestador = db.Column(db.String(80))
    data_finalizacao = db.Column(db.String(10), nullable=False)
    hora_finalizacao = db.Column(db.String(5), nullable=False)
    observacoes = db.Column(db.Text)
    registrado_em = db.Column(db.DateTime, default=datetime.utcnow)

# --- Inicialização do Banco de Dados ---
def init_db():
    """Inicializa o banco de dados com dados padrão"""
    with app.app_context():
        db.create_all()

        # Criar admin padrão se não existir
        if not User.query.filter_by(is_admin=True).first():
            admin = User(
                username='admin',
                password=generate_password_hash('admin123'),
                is_admin=True,
                nome_exibicao='Administrador'
            )
            db.session.add(admin)
            db.session.commit()

# --- Funções Auxiliares ---
def carregar_os_prestador(prestador_username):
    """Carrega as OS atribuídas a um prestador"""
    return OS.query.filter_by(prestador=prestador_username, status='aberta').all()

def finalizar_os_service(os_numero, prestador, data, hora, observacoes):
    """Registra a finalização de uma OS"""
    try:
        # Atualiza a OS para status 'finalizada'
        os_obj = OS.query.filter_by(numero=os_numero, prestador=prestador).first()
        if not os_obj:
            return False
        
        os_obj.status = 'finalizada'
        
        # Cria registro de finalização
        nova_finalizacao = Finalizacao(
            os_numero=os_numero,
            prestador=prestador,
            data_finalizacao=data,
            hora_finalizacao=hora,
            observacoes=observacoes
        )
        
        db.session.add(nova_finalizacao)
        db.session.commit()
        return True
    except Exception as e:
        db.session.rollback()
        print(f"Erro ao finalizar OS: {str(e)}")
        return False

# --- Rotas de Autenticação ---
@app.route('/')
def home():
    if 'user' in session:
        return redirect(url_for('painel'))
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
            session['nome'] = user.nome_exibicao or username
            return redirect(url_for('painel'))
        
        flash('Credenciais inválidas', 'danger')
    return render_template('login.html'))

@app.route('/logout')
def logout():
    session.clear()
    flash('Você foi desconectado', 'info')
    return redirect(url_for('login'))

# --- Rotas do Painel ---
@app.route('/painel')
def painel():
    if 'user' not in session:
        return redirect(url_for('login'))
    
    if session.get('user_type') == 'prestador':
        os_pendentes = carregar_os_prestador(session['user'])
        finalizadas = Finalizacao.query.filter_by(prestador=session['user']).order_by(Finalizacao.registrado_em.desc()).limit(5).all()
        
        return render_template('painel_prestador.html',
                            os_pendentes=os_pendentes,
                            finalizadas=finalizadas,
                            nome=session.get('nome'))
    
    # Painel do gerente/admin
    return redirect(url_for('admin_panel'))

@app.route('/finalizar_os', methods=['POST'])
def finalizar_os():
    if 'user' not in session or session.get('user_type') != 'prestador':
        return redirect(url_for('login'))
    
    os_numero = request.form.get('os_numero')
    data = request.form.get('data_finalizacao')
    hora = request.form.get('hora_finalizacao')
    observacoes = request.form.get('observacoes', '')
    
    if not all([os_numero, data, hora]):
        flash('Preencha todos os campos obrigatórios', 'danger')
        return redirect(url_for('painel'))
    
    if finalizar_os_service(os_numero, session['user'], data, hora, observacoes):
        flash('OS finalizada com sucesso!', 'success')
    else:
        flash('Erro ao finalizar a OS', 'danger')
    
    return redirect(url_for('painel'))

# --- Rotas de Administração ---
@app.route('/admin')
def admin_panel():
    if 'user' not in session or not User.query.filter_by(username=session['user'], is_admin=True).first():
        flash('Acesso não autorizado', 'danger')
        return redirect(url_for('login'))
    
    # Estatísticas para o painel admin
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
