import os
import json
import logging
from datetime import datetime
from flask import Flask, request, redirect, url_for, render_template, session, send_file
from flask_sqlalchemy import SQLAlchemy
from functools import wraps
from collections import defaultdict
import pytz
import io
import csv
from sqlalchemy.sql import text  # Importar text para queries SQL

# Configuração de logging
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'your-secret-key')
app.config['SQLALCHEMY_DATABASE_URI'] = os.environ.get('DATABASE_URL', 'sqlite:///os_manager.db')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db = SQLAlchemy(app)

# Fuso horário de Brasília
BRASILIA_TZ = pytz.timezone('America/Sao_Paulo')

# Filtro customizado para capitalizar nomes compostos
def capitalize_name(name):
    if not name:
        return name
    parts = name.replace('.', ' ').split()
    capitalized_parts = [part.capitalize() for part in parts]
    return '.'.join(capitalized_parts) if '.' in name else ' '.join(capitalized_parts)

app.jinja_env.filters['capitalize_name'] = capitalize_name

# Modelo para eventos de login
class LoginEvent(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), nullable=False)
    user_type = db.Column(db.String(20), nullable=False)
    login_time = db.Column(db.DateTime, nullable=False)
    logout_time = db.Column(db.DateTime)
    duration_secs = db.Column(db.Integer)

# Modelo para ordens de serviço finalizadas
class OrdemServico(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    os_numero = db.Column(db.String(20), nullable=False)
    gerente = db.Column(db.String(80), nullable=False)
    data_fin = db.Column(db.String(10), nullable=False)
    hora_fin = db.Column(db.String(8), nullable=False)
    observacoes = db.Column(db.Text)

# Função para carregar usuários
def load_users():
    try:
        with open('users.json', 'r') as f:
            return json.load(f)
    except Exception as e:
        logger.error(f"Erro ao carregar users.json: {e}")
        return {}

# Decorador para verificar login
def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'username' not in session:
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function

# Rota de login
@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username'].strip().lower()
        password = request.form['password']
        logger.debug(f"Tentativa de login: {username}, senha fornecida: {'*' * len(password)}")
        
        users = load_users()
        user = users.get(username)
        
        if user and user['password'] == password:
            session['username'] = username
            session['user_type'] = user['type']
            session['is_admin'] = user.get('is_admin', False)
            
            login_event = LoginEvent(
                username=username,
                user_type=user['type'],
                login_time=datetime.utcnow()
            )
            db.session.add(login_event)
            db.session.commit()
            
            logger.info(f"Login bem-sucedido para {user['type']}: {username}")
            if user['type'] == 'gerente':
                return redirect(url_for('painel_gerente'))
            else:
                return redirect(url_for('painel_prestador'))
        else:
            logger.warning(f"Falha no login para {username}")
            return render_template('login.html', error="Usuário ou senha inválidos")
    
    return render_template('login.html')

# Rota de logout
@app.route('/logout')
@login_required
def logout():
    username = session['username']
    user_type = session['user_type']
    
    login_event = LoginEvent.query.filter_by(
        username=username,
        user_type=user_type,
        logout_time=None
    ).order_by(LoginEvent.login_time.desc()).first()
    
    if login_event:
        logout_time = datetime.utcnow()
        duration = (logout_time - login_event.login_time).total_seconds()
        login_event.logout_time = logout_time
        login_event.duration_secs = int(duration)
        db.session.commit()
    
    session.clear()
    logger.info(f"Logout bem-sucedido para {user_type}: {username}")
    return redirect(url_for('login'))

# Rota do painel admin
@app.route('/admin')
@login_required
def admin_panel():
    if not session.get('is_admin'):
        return redirect(url_for('painel_gerente'))
    
    users = load_users()
    gerentes = [u for u, data in users.items() if data['type'] == 'gerente']
    
    # Carregar prestadores
    try:
        with open('prestadores.json', 'r') as f:
            prestadores = json.load(f)
        logger.debug(f"Prestadores carregados: {prestadores}")
    except Exception as e:
        logger.error(f"Erro ao carregar prestadores.json: {e}")
        prestadores = []
    
    # Contagem de OS finalizadas por gerente
    finalizadas = OrdemServico.query.all()
    contagem_gerentes = defaultdict(int)
    for os in finalizadas:
        contagem_gerentes[os.gerente] += 1
    
    # Contagem de OS abertas por gerente e prestador
    os_abertas = defaultdict(int)
    ranking_os_prestadores = defaultdict(int)
    
    for gerente in gerentes:
        try:
            with open(f'mensagens_por_gerente/{gerente}.json', 'r') as f:
                ordens = json.load(f)
            for ordem in ordens:
                if 'status' in ordem and ordem['status'].upper() == 'ABERTO':
                    os_abertas[gerente] += 1
                    prestador = ordem.get('prestador', '').strip()
                    if prestador in prestadores:
                        ranking_os_prestadores[prestador] += 1
        except FileNotFoundError:
            continue
    
    # Rankings
    ranking_os_abertas = sorted(os_abertas.items(), key=lambda x: x[1], reverse=True)
    ranking_os_prestadores = sorted(ranking_os_prestadores.items(), key=lambda x: x[1], reverse=True)
    
    # Logs para depuração
    logger.debug(f"ranking_os_abertas: {ranking_os_abertas}")
    logger.debug(f"ranking_os_prestadores: {ranking_os_prestadores}")
    
    # Eventos de login com conversão para Brasília
    login_events = LoginEvent.query.order_by(LoginEvent.login_time.desc()).limit(50).all()
    login_events_adjusted = []
    for ev in login_events:
        login_time_br = ev.login_time.replace(tzinfo=pytz.UTC).astimezone(BRASILIA_TZ)
        logout_time_br = ev.logout_time.replace(tzinfo=pytz.UTC).astimezone(BRASILIA_TZ) if ev.logout_time else None
        login_events_adjusted.append({
            'username': ev.username,
            'user_type': ev.user_type,
            'login_time': login_time_br,
            'logout_time': logout_time_br,
            'duration_secs': ev.duration_secs
        })
    
    return render_template('admin.html',
                         total_os=len(finalizadas),
                         gerentes=gerentes,
                         contagem_gerentes=contagem_gerentes,
                         os_abertas=os_abertas,
                         ranking_os_abertas=ranking_os_abertas,
                         ranking_os_prestadores=ranking_os_prestadores,
                         finalizadas=finalizadas,
                         login_events=login_events_adjusted,
                         now=datetime.utcnow())

# Outras rotas (mantidas inalteradas)
@app.route('/painel', methods=['GET', 'POST'])
@login_required
def painel_gerente():
    if session['user_type'] != 'gerente':
        return redirect(url_for('painel_prestador'))
    
    username = session['username']
    try:
        with open(f'mensagens_por_gerente/{username}.json', 'r') as f:
            ordens = json.load(f)
    except FileNotFoundError:
        ordens = []
    
    if request.method == 'POST':
        os_numero = request.form['os_numero']
        observacoes = request.form.get('observacoes', '')
        
        ordem = OrdemServico(
            os_numero=os_numero,
            gerente=username,
            data_fin=datetime.utcnow().strftime('%d/%m/%Y'),
            hora_fin=datetime.utcnow().strftime('%H:%M:%S'),
            observacoes=observacoes
        )
        db.session.add(ordem)
        db.session.commit()
        
        # Atualizar status no arquivo JSON
        for ordem in ordens:
            if ordem['os'] == os_numero:
                ordem['status'] = 'FECHADO'
                break
        with open(f'mensagens_por_gerente/{username}.json', 'w') as f:
            json.dump(ordens, f, indent=2)
        
        logger.info(f"OS {os_numero} finalizada por {username}")
        return redirect(url_for('painel_gerente'))
    
    return render_template('painel.html', ordens=ordens, username=username)

@app.route('/painel_prestador')
@login_required
def painel_prestador():
    if session['user_type'] != 'prestador':
        return redirect(url_for('painel_gerente'))
    
    username = session['username']
    try:
        with open(f'mensagens_por_prestador/{username}.json', 'r') as f:
            ordens = json.load(f)
    except FileNotFoundError:
        ordens = []
    
    return render_template('painel.html', ordens=ordens, username=username)

@app.route('/exportar_os_finalizadas')
@login_required
def exportar_os_finalizadas():
    if not session.get('is_admin'):
        return redirect(url_for('painel_gerente'))
    
    finalizadas = OrdemServico.query.all()
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(['OS', 'Gerente', 'Data', 'Hora', 'Observações'])
    for os in finalizadas:
        writer.writerow([os.os_numero, os.gerente, os.data_fin, os.hora_fin, os.observacoes or ''])
    
    output.seek(0)
    return send_file(
        io.BytesIO(output.getvalue().encode('utf-8')),
        mimetype='text/csv',
        as_attachment=True,
        download_name=f'os_finalizadas_{datetime.utcnow().strftime("%Y%m%d")}.csv'
    )

# Inicialização do banco de dados
with app.app_context():
    db.create_all()
    
    # Verificar e adicionar coluna user_type se não existir
    from sqlalchemy import inspect
    inspector = inspect(db.engine)
    columns = [col['name'] for col in inspector.get_columns('login_event')]
    if 'user_type' not in columns:
        logger.debug("Adicionando coluna user_type à tabela login_event")
        db.session.execute(text('ALTER TABLE login_event ADD COLUMN user_type VARCHAR(20) NOT NULL DEFAULT "gerente"'))
        db.session.commit()
    else:
        logger.debug("Coluna user_type já existe em login_events")

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 10000)))
