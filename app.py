import os
import json
import logging
from datetime import datetime, timedelta
import pytz
from flask import Flask, render_template, request, redirect, session, url_for, flash, send_file
from flask_sqlalchemy import SQLAlchemy
from fpdf import FPDF
from collections import Counter
from sqlalchemy.sql import text
from dateutil.parser import parse

# Configuração de logging para depuração
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

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

# --- Fuso horário de São Paulo ---
saopaulo_tz = pytz.timezone('America/Sao_Paulo')

# --- Filtro personalizado para capitalizar nomes ---
def capitalize_name(name):
    if not name:
        return name
    parts = name.replace('.', ' ').split()
    capitalized_parts = [part.capitalize() for part in parts]
    return '.'.join(capitalized_parts) if '.' in name else ' '.join(capitalized_parts)
app.jinja_env.filters['capitalize_name'] = capitalize_name

# --- Helper para formatar datas no horário de São Paulo ---
def format_datetime(dt):
    if dt:
        if dt.tzinfo is not None:
            return dt.astimezone(saopaulo_tz).strftime('%d/%m/%Y %H:%M:%S')
        return saopaulo_tz.localize(dt).strftime('%d/%m/%Y %H:%M:%S')
    return None

# --- Models ---
class User(db.Model):
    __tablename__ = 'users'
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password = db.Column(db.String(128), nullable=False)
    is_admin = db.Column(db.Boolean, default=False)

class Finalizacao(db.Model):
    __tablename__ = 'finalizacoes'
    id = db.Column(db.Integer, primary_key=True)
    os_numero = db.Column(db.String(50), nullable=False)
    gerente = db.Column(db.String(80), nullable=False)
    data_fin = db.Column(db.String(10), nullable=False)
    hora_fin = db.Column(db.String(5), nullable=False)
    observacoes = db.Column(db.Text)
    registrado_em = db.Column(db.DateTime, default=lambda: saopaulo_tz.localize(datetime.now()))

class LoginEvent(db.Model):
    __tablename__ = 'login_events'
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), nullable=False)
    user_type = db.Column(db.String(20), nullable=False)
    login_time = db.Column(db.DateTime, default=lambda: saopaulo_tz.localize(datetime.now()), nullable=False)
    logout_time = db.Column(db.DateTime)
    duration_secs = db.Column(db.Integer)

# --- Constantes de caminho e inicialização do JSON ---
BASE_DIR = os.path.dirname(__file__)
MENSAGENS_DIR = os.path.join(BASE_DIR, 'mensagens_por_gerente')
MENSAGENS_PRESTADOR_DIR = os.path.join(BASE_DIR, 'mensagens_por_prestador')
JSON_DIR = os.path.join(BASE_DIR, 'static', 'json')
USERS_FILE = os.path.join(BASE_DIR, 'users.json')
PRESTADORES_FILE = os.path.join(BASE_DIR, 'prestadores.json')
MANUTENCAO_FILE = os.path.join(BASE_DIR, 'manutencao.json')
os.makedirs(MENSAGENS_DIR, exist_ok=True)
os.makedirs(MENSAGENS_PRESTADOR_DIR, exist_ok=True)
os.makedirs(JSON_DIR, exist_ok=True)

def init_db():
    """Cria tabelas, importa users.json na tabela users e aplica migrações necessárias."""
    db.create_all()
    
    try:
        from sqlalchemy import inspect
        inspector = inspect(db.engine)
        columns = [col['name'] for col in inspector.get_columns('login_events')]
        if 'user_type' not in columns:
            logger.info("Adicionando coluna user_type à tabela login_events")
            db.session.execute(text('ALTER TABLE login_events ADD COLUMN user_type VARCHAR(20)'))
            db.session.execute(text("UPDATE login_events SET user_type = 'gerente' WHERE user_type IS NULL"))
            db.session.execute(text('ALTER TABLE login_events ALTER COLUMN user_type SET NOT NULL'))
            db.session.commit()
            logger.info("Coluna user_type adicionada com sucesso")
        else:
            logger.debug("Coluna user_type já existe em login_events")
    except Exception as e:
        logger.error(f"Erro ao verificar/adicionar coluna user_type: {e}")
        db.session.rollback()
    
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

def carregar_os_gerente(gerente):
    base = gerente.upper().replace('.', '_')
    caminho_encontrado = None
    for sufixo in ("", "_GONZAGA"):
        nome = f"{base}{sufixo}.json"
        p = os.path.join(MENSAGENS_DIR, nome)
        if os.path.exists(p):
            caminho_encontrado = p
            break
    if not caminho_encontrado:
        for nome_arquivo in os.listdir(MENSAGENS_DIR):
            if nome_arquivo.upper().startswith(base + "_") and nome_arquivo.lower().endswith(".json"):
                caminho_encontrado = os.path.join(MENSAGENS_DIR, nome_arquivo)
                break
    if not caminho_encontrado:
        return []
    with open(caminho_encontrado, encoding="utf-8") as f:
        dados = json.load(f)
    resultado = []
    hoje = saopaulo_tz.localize(datetime.now()).date()
    for item in dados:
        data_str = item.get("data") or item.get("Data") or ""
        for fmt in ("%d/%m/%Y", "%Y-%m-%d", "%d-%m-%Y"):
            try:
                data_abertura = datetime.strptime(data_str, fmt).date()
                break
            except Exception:
                data_abertura = None
        if data_abertura:
            dias_abertos = (hoje - data_abertura).days
        else:
            dias_abertos = 0
        resultado.append({
            "os": str(item.get("os") or item.get("OS", "")),
            "frota": str(item.get("frota") or item.get("Frota", "")),
            "data": data_str,
            "dias": str(dias_abertos),
            "prestador": str(item.get("prestador") or item.get("Prestador", "Prestador não definido")),
            "servico": str(
                item.get("servico")
                or item.get("Servico")
                or item.get("observacao")
                or item.get("Observacao", "")
            )
        })
    return resultado

def carregar_prestadores():
    if not os.path.exists(PRESTADORES_FILE):
        logger.error(f"Arquivo {PRESTADORES_FILE} não encontrado.")
        return []
    try:
        with open(PRESTADORES_FILE, "r", encoding="utf-8") as f:
            prestadores = json.load(f)
        usuarios = [p.get('usuario', '').lower() for p in prestadores]
        duplicatas = [item for item, count in Counter(usuarios).items() if count > 1]
        if duplicatas:
            logger.warning(f"Usuários duplicados encontrados em prestadores.json: {duplicatas}")
        logger.debug(f"Prestadores carregados: {[p['usuario'] for p in prestadores]}")
        return prestadores
    except json.JSONDecodeError as e:
        logger.error(f"Erro ao decodificar {PRESTADORES_FILE}: {e}")
        logger.error(f"Detalhes do erro: linha {e.lineno}, coluna {e.colno}, caractere {e.pos}")
        return []
    except Exception as e:
        logger.error(f"Erro ao carregar prestadores: {e}")
        return []

def carregar_manutencao():
    if not os.path.exists(MANUTENCAO_FILE):
        logger.error(f"Arquivo {MANUTENCAO_FILE} não encontrado.")
        return []
    try:
        with open(MANUTENCAO_FILE, "r", encoding="utf-8") as f:
            manutencao = json.load(f)
        usuarios = [p.get('usuario', '').lower() for p in manutencao]
        duplicatas = [item for item, count in Counter(usuarios).items() if count > 1]
        if duplicatas:
            logger.warning(f"Usuários duplicados encontrados em manutencao.json: {duplicatas}")
        logger.debug(f"Usuários de manutenção carregados: {[p['usuario'] for p in manutencao]}")
        return manutencao
    except json.JSONDecodeError as e:
        logger.error(f"Erro ao decodificar {MANUTENCAO_FILE}: {e}")
        logger.error(f"Detalhes do erro: linha {e.lineno}, coluna {e.colno}, caractere {e.pos}")
        return []
    except Exception as e:
        logger.error(f"Erro ao carregar manutencao: {e}")
        return []

def carregar_os_prestadores():
    prestadores = carregar_prestadores()
    os_por_prestador = {}
    for prestador in prestadores:
        usuario = prestador.get('usuario', '').lower()
        # Ignorar usuários de manutenção
        if prestador.get('tipo') == 'manutencao':
            continue
        arquivo_os = prestador.get('arquivo_os', '')
        caminho = os.path.join(MENSAGENS_PRESTADOR_DIR, arquivo_os)
        if not os.path.exists(caminho):
            logger.warning(f"Arquivo de OS não encontrado para {usuario}: {caminho}")
            os_por_prestador[usuario] = 0
            continue
        try:
            with open(caminho, 'r', encoding='utf-8') as f:
                os_list = json.load(f)
            os_por_prestador[usuario] = len(os_list)
        except json.JSONDecodeError as e:
            logger.error(f"Erro ao decodificar {caminho}: {e}")
            os_por_prestador[usuario] = 0
        except Exception as e:
            logger.error(f"Erro ao carregar OS para {usuario}: {e}")
            os_por_prestador[usuario] = 0
    ranking = sorted(os_por_prestador.items(), key=lambda x: x[1], reverse=True)
    return ranking

def carregar_os_manutencao(usuario):
    manutencao_users = carregar_manutencao()
    manutencao = next((p for p in manutencao_users if p.get('usuario', '').lower() == usuario.lower()), None)
    if not manutencao:
        logger.warning(f"Usuário {usuario} não é um usuário de manutenção")
        return []
    caminho = os.path.join(JSON_DIR, manutencao['arquivo_os'])
    if not os.path.exists(caminho):
        logger.warning(f"Arquivo de OS não encontrado: {caminho}")
        return []
    try:
        with open(caminho, 'r', encoding='utf-8') as f:
            os_list = json.load(f)
        hoje = saopaulo_tz.localize(datetime.now()).date()
        for item in os_list:
            try:
                data_entrada = datetime.strptime(item['data_entrada'], '%d/%m/%Y').date()
                item['dias_abertos'] = (hoje - data_entrada).days
            except Exception:
                item['dias_abertos'] = 0
        return os_list
    except json.JSONDecodeError as e:
        logger.error(f"Erro ao decodificar {caminho}: {e}")
        return []
    except Exception as e:
        logger.error(f"Erro ao carregar OS para {usuario}: {e}")
        return []

def carregar_os_sem_prestador():
    os_sem_prestador = []
    hoje = saopaulo_tz.localize(datetime.now()).date()
    for arquivo in os.listdir(MENSAGENS_DIR):
        if arquivo.lower().endswith('.json'):
            caminho = os.path.join(MENSAGENS_DIR, arquivo)
            try:
                with open(caminho, 'r', encoding='utf-8') as f:
                    dados = json.load(f)
                for item in dados:
                    prestador = str(item.get('prestador') or item.get('Prestador', '')).lower()
                    if prestador in ('nan', '', 'none', 'não definido', 'prestador não definido'):
                        data_str = str(item.get('data') or item.get('Data', ''))
                        try:
                            data_entrada = datetime.strptime(data_str, '%d/%m/%Y').date()
                            dias_abertos = (hoje - data_entrada).days
                        except Exception:
                            dias_abertos = 0
                        os_sem_prestador.append({
                            'os': str(item.get('os') or item.get('OS', '')),
                            'frota': str(item.get('frota') or item.get('Frota', '')),
                            'data_entrada': data_str,
                            'modelo': str(item.get('modelo') or item.get('Modelo', '')),
                            'servico': str(item.get('servico') or item.get('Servico') or item.get('observacao') or item.get('Observacao', '')),
                            'arquivo_origem': arquivo,
                            'dias_abertos': dias_abertos
                        })
            except Exception as e:
                logger.error(f"Erro ao carregar {caminho}: {e}")
    return os_sem_prestador

# --- Rotas ---
@app.route('/')
def index():
    return redirect(url_for('login'))

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form.get('username', '').strip().lower()
        senha = request.form.get('senha', '').strip()
        logger.debug(f"Tentativa de login: {username}, senha fornecida: {'*' * len(senha)}")

        user = User.query.filter_by(username=username).first()
        if user and user.password == senha:
            ev = LoginEvent(username=username, user_type='gerente')
            db.session.add(ev)
            db.session.commit()
            session['login_event_id'] = ev.id
            session['gerente'] = username
            session['is_admin'] = user.is_admin
            logger.info(f"Login bem-sucedido para gerente: {username}")
            return redirect(url_for('admin_panel' if user.is_admin else 'painel'))

        # Verificar usuários de manutenção (manutencao.json)
        manutencao_users = carregar_manutencao()
        if not manutencao_users and os.path.exists(MANUTENCAO_FILE):
            flash('Erro interno: Não foi possível carregar a lista de usuários de manutenção', 'danger')
            logger.warning(f"Falha no login: {username} - Problema ao carregar manutencao.json")
            return render_template('login.html')

        manutencao = next((p for p in manutencao_users if p.get('usuario', '').lower() == username and p.get('senha', '') == senha), None)
        if manutencao:
            ev = LoginEvent(username=username, user_type='manutencao')
            db.session.add(ev)
            db.session.commit()
            session['login_event_id'] = ev.id
            session['manutencao'] = manutencao['usuario']
            session['manutencao_nome'] = manutencao.get('nome_exibicao', username.capitalize())
            logger.info(f"Login bem-sucedido para usuário de manutenção: {username}")
            return redirect(url_for('painel_manutencao'))

        # Verificar prestadores (prestadores.json)
        prestadores = carregar_prestadores()
        if not prestadores and os.path.exists(PRESTADORES_FILE):
            flash('Erro interno: Não foi possível carregar a lista de prestadores', 'danger')
            logger.warning(f"Falha no login: {username} - Problema ao carregar prestadores.json")
            return render_template('login.html')

        prestador = next((p for p in prestadores if p.get('usuario', '').lower() == username and p.get('senha', '') == senha), None)
        if prestador:
            ev = LoginEvent(username=username, user_type=prestador.get('tipo', 'prestador'))
            db.session.add(ev)
            db.session.commit()
            session['login_event_id'] = ev.id
            session['prestador'] = prestador['usuario']
            session['prestador_nome'] = prestador.get('nome_exibicao', username.capitalize())
            logger.info(f"Login bem-sucedido para prestador: {username}")
            return redirect(url_for('painel_prestador'))

        flash('Senha incorreta', 'danger')
        logger.warning(f"Falha no login: {username}")
    return render_template('login.html')

@app.route('/painel')
def painel():
    if 'gerente' not in session:
        return redirect(url_for('login'))
    pend = carregar_os_gerente(session['gerente'])
    finalizadas = Finalizacao.query.filter_by(gerente=session['gerente']).order_by(Finalizacao.registrado_em.desc()).limit(100).all()
    return render_template('painel.html',
                         os_pendentes=pend,
                         finalizadas=finalizadas,
                         gerente=session['gerente'],
                         now=saopaulo_tz.localize(datetime.now()))

@app.route('/painel_prestador')
def painel_prestador():
    if 'prestador' not in session:
        return redirect(url_for('login'))
    prestadores = carregar_prestadores()
    if not prestadores and os.path.exists(PRESTADORES_FILE):
        flash('Erro interno: Não foi possível carregar a lista de prestadores', 'danger')
        logger.error(f"Erro ao carregar prestadores para painel_prestador: {session['prestador']}")
        return redirect(url_for('login'))
    
    prestador = next((p for p in prestadores if p.get('usuario', '').lower() == session['prestador']), None)
    if not prestador:
        flash('Prestador não encontrado', 'danger')
        logger.error(f"Prestador não encontrado na sessão: {session['prestador']}")
        return redirect(url_for('login'))
    caminho = os.path.join(MENSAGENS_PRESTADOR_DIR, prestador['arquivo_os'])
    if not os.path.exists(caminho):
        logger.warning(f"Arquivo de OS não encontrado: {caminho}")
        os_list = []
    else:
        try:
            with open(caminho, 'r', encoding='utf-8') as f:
                os_list = json.load(f)
        except json.JSONDecodeError as e:
            logger.error(f"Erro ao decodificar {caminho}: {e}")
            os_list = []
    return render_template('painel_prestador.html', nome=prestador['nome_exibicao'], os_list=os_list)

@app.route('/painel_manutencao')
def painel_manutencao():
    if 'manutencao' not in session:
        flash('Acesso negado. Faça login.', 'danger')
        return redirect(url_for('login'))
    manutencao_users = carregar_manutencao()
    if not manutencao_users and os.path.exists(MANUTENCAO_FILE):
        flash('Erro interno: Não foi possível carregar a lista de usuários de manutenção', 'danger')
        logger.error(f"Erro ao carregar manutencao para painel_manutencao: {session['manutencao']}")
        return redirect(url_for('login'))
    
    manutencao = next((p for p in manutencao_users if p.get('usuario', '').lower() == session['manutencao']), None)
    if not manutencao:
        flash('Usuário de manutenção não encontrado', 'danger')
        logger.error(f"Usuário de manutenção não encontrado na sessão: {session['manutencao']}")
        return redirect(url_for('login'))
    os_list = carregar_os_manutencao(session['manutencao'])
    total_os = len(os_list)
    os_sem_prestador = carregar_os_sem_prestador()
    
    # Ordenação
    ordenar = request.args.get('ordenar', 'data_desc')
    if ordenar == 'data_asc':
        os_list.sort(key=lambda x: datetime.strptime(x['data_entrada'], '%d/%m/%Y'))
    elif ordenar == 'data_desc':
        os_list.sort(key=lambda x: datetime.strptime(x['data_entrada'], '%d/%m/%Y'), reverse=True)
    elif ordenar == 'frota':
        os_list.sort(key=lambda x: x['frota'])
    
    return render_template('painel_manutencao.html', 
                         nome=manutencao['nome_exibicao'], 
                         os_list=os_list, 
                         total_os=total_os, 
                         os_sem_prestador=os_sem_prestador, 
                         ordenar=ordenar,
                         prestadores=carregar_prestadores(),
                         now=saopaulo_tz.localize(datetime.now()))

@app.route('/finalizar_os/<os_numero>', methods=['POST'])
def finalizar_os(os_numero):
    responsavel = session.get('gerente') or session.get('prestador') or session.get('manutencao')
    if not responsavel:
        return redirect(url_for('login'))
    d = request.form['data_finalizacao']
    h = request.form['hora_finalizacao']
    o = request.form.get('observacoes','')
    fz = Finalizacao(
        os_numero=os_numero,
        gerente=responsavel,
        data_fin=d,
        hora_fin=h,
        observacoes=o
    )
    db.session.add(fz)
    if 'gerente' in session:
        gerente = session['gerente']
        base = gerente.upper().replace('.', '_') + "_GONZAGA.json"
        caminho = os.path.join(MENSAGENS_DIR, base)
        if not os.path.exists(caminho):
            prefixo = gerente.split('.')[0].upper()
            for fn in os.listdir(MENSAGENS_DIR):
                if fn.upper().startswith(prefixo) and fn.lower().endswith(".json"):
                    caminho = os.path.join(MENSAGENS_DIR, fn)
                    break
        if os.path.exists(caminho):
            with open(caminho, 'r', encoding='utf-8') as f:
                data = json.load(f)
            data = [item for item in data if str(item.get('os') or item.get('OS','')) != os_numero]
            with open(caminho, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
    if 'prestador' in session or 'manutencao' in session:
        usuario = session.get('prestador') or session.get('manutencao')
        if 'prestador' in session:
            usuarios = carregar_prestadores()
            diretorio = MENSAGENS_PRESTADOR_DIR
        else:
            usuarios = carregar_manutencao()
            diretorio = JSON_DIR
        usuario_data = next((p for p in usuarios if p.get('usuario', '').lower() == usuario), None)
        if usuario_data:
            caminho = os.path.join(diretorio, usuario_data['arquivo_os'])
            if os.path.exists(caminho):
                with open(caminho, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                data = [item for item in data if str(item.get('os') or item.get('OS','')) != os_numero]
                with open(caminho, 'w', encoding='utf-8') as f:
                    json.dump(data, f, ensure_ascii=False, indent=2)
    db.session.commit()
    flash(f'OS {os_numero} finalizada','success')
    return redirect(url_for('painel' if 'gerente' in session else 'painel_manutencao' if 'manutencao' in session else 'painel_prestador'))

@app.route('/atribuir_prestador/<os_numero>', methods=['POST'])
def atribuir_prestador(os_numero):
    if 'manutencao' not in session:
        flash('Acesso negado. Faça login.', 'danger')
        return redirect(url_for('login'))
    usuario = session['manutencao']
    manutencao_users = carregar_manutencao()
    if not manutencao_users and os.path.exists(MANUTENCAO_FILE):
        flash('Erro interno: Não foi possível carregar a lista de usuários de manutenção', 'danger')
        logger.error(f"Erro ao carregar manutencao para atribuir_prestador: {usuario}")
        return redirect(url_for('login'))
    
    manutencao = next((p for p in manutencao_users if p.get('usuario', '').lower() == usuario), None)
    if not manutencao:
        flash('Usuário de manutenção não encontrado', 'danger')
        return redirect(url_for('login'))
    
    prestador_nome = request.form.get('prestador', '').strip()
    if not prestador_nome:
        flash('O nome do prestador não pode estar vazio', 'danger')
        return redirect(url_for('painel_manutencao'))
    
    os_sem_prestador = carregar_os_sem_prestador()
    os_target = next((os for os in os_sem_prestador if os['os'] == os_numero), None)
    if not os_target:
        flash('OS não encontrada ou já possui prestador', 'danger')
        return redirect(url_for('painel_manutencao'))
    
    # Atualizar o prestador no arquivo original
    caminho_origem = os.path.join(MENSAGENS_DIR, os_target['arquivo_origem'])
    try:
        with open(caminho_origem, 'r', encoding='utf-8') as f:
            dados = json.load(f)
        for item in dados:
            if str(item.get('os') or item.get('OS', '')) == os_numero:
                item['prestador'] = prestador_nome
                break
        with open(caminho_origem, 'w', encoding='utf-8') as f:
            json.dump(dados, f, ensure_ascii=False, indent=2)
        flash(f'Prestador {prestador_nome} atribuído à OS {os_numero} com sucesso', 'success')
    except Exception as e:
        logger.error(f"Erro ao atualizar {caminho_origem}: {e}")
        flash('Erro ao atribuir prestador', 'danger')
    return redirect(url_for('painel_manutencao'))

@app.route('/adicionar_comentario/<os_numero>', methods=['POST'])
def adicionar_comentario(os_numero):
    if 'manutencao' not in session:
        flash('Acesso negado. Faça login.', 'danger')
        return redirect(url_for('login'))
    usuario = session['manutencao']
    manutencao_users = carregar_manutencao()
    if not manutencao_users and os.path.exists(MANUTENCAO_FILE):
        flash('Erro interno: Não foi possível carregar a lista de usuários de manutenção', 'danger')
        logger.error(f"Erro ao carregar manutencao para adicionar_comentario: {usuario}")
        return redirect(url_for('login'))
    
    manutencao = next((p for p in manutencao_users if p.get('usuario', '').lower() == usuario), None)
    if not manutencao:
        flash('Usuário de manutenção não encontrado', 'danger')
        return redirect(url_for('login'))
    comentario = request.form.get('comentario', '').strip()
    if not comentario:
        flash('Comentário não pode estar vazio', 'danger')
        return redirect(url_for('painel_manutencao'))
    caminho = os.path.join(JSON_DIR, manutencao['arquivo_os'])
    try:
        with open(caminho, 'r', encoding='utf-8') as f:
            os_list = json.load(f)
        for item in os_list:
            if str(item.get('os', '')) == os_numero:
                item['comentarios'] = item.get('comentarios', []) + [{
                    'texto': comentario,
                    'data': saopaulo_tz.localize(datetime.now()).strftime('%d/%m/%Y %H:%M'),
                    'autor': usuario
                }]
                break
        with open(caminho, 'w', encoding='utf-8') as f:
            json.dump(os_list, f, ensure_ascii=False, indent=2)
        flash('Comentário adicionado com sucesso', 'success')
    except Exception as e:
        logger.error(f"Erro ao adicionar comentário em {caminho}: {e}")
        flash('Erro ao adicionar comentário', 'danger')
    return redirect(url_for('painel_manutencao'))

@app.route('/admin')
def admin_panel():
    if not session.get('is_admin'):
        flash('Acesso negado','danger')
        return redirect(url_for('login'))
    
    # Parâmetros de filtro
    periodo = request.args.get('periodo', 'todos')
    data_inicio = request.args.get('data_inicio')
    data_fim = request.args.get('data_fim')
    
    # Consulta base de finalizações
    query = Finalizacao.query.order_by(Finalizacao.registrado_em.desc())
    
    # Aplicar filtros de período
    if periodo != 'todos' or data_inicio or data_fim:
        if data_inicio and data_fim:
            try:
                inicio = saopaulo_tz.localize(parse(data_inicio).replace(hour=0, minute=0, second=0))
                fim = saopaulo_tz.localize(parse(data_fim).replace(hour=23, minute=59, second=59))
                query = query.filter(Finalizacao.registrado_em.between(inicio, fim))
            except ValueError:
                flash('Datas inválidas. Usando todas as OS.', 'warning')
        elif periodo != 'todos':
            hoje = saopaulo_tz.localize(datetime.now())
            if periodo == 'diario':
                inicio = hoje.replace(hour=0, minute=0, second=0)
                fim = hoje.replace(hour=23, minute=59, second=59)
            elif periodo == 'semanal':
                inicio = hoje - timedelta(days=hoje.weekday())
                inicio = inicio.replace(hour=0, minute=0, second=0)
                fim = inicio + timedelta(days=6, hours=23, minutes=59, seconds=59)
            elif periodo == 'mensal':
                inicio = hoje.replace(day=1, hour=0, minute=0, second=0)
                fim = (inicio + timedelta(days=31)).replace(day=1, hour=23, minute=59, second=59) - timedelta(seconds=1)
            elif periodo == 'anual':
                inicio = hoje.replace(month=1, day=1, hour=0, minute=0, second=0)
                fim = hoje.replace(month=12, day=31, hour=23, minute=59, second=59)
            query = query.filter(Finalizacao.registrado_em.between(inicio, fim))
    
    # Calcular o total de manutenções concluídas (sem limite)
    total_os = query.count()
    
    # Limitar apenas para exibição da tabela
    finalizadas = query.limit(100).all()
    login_events = LoginEvent.query.order_by(LoginEvent.login_time.desc()).limit(50).all()
    
    for event in login_events:
        event.login_time_formatted = format_datetime(event.login_time)
        event.logout_time_formatted = format_datetime(event.logout_time)
    
    users = User.query.order_by(User.username).all()
    gerentes = [u.username for u in users]
    contagem = {g: Finalizacao.query.filter_by(gerente=g).count() for g in gerentes}
    abertas = {g: len(carregar_os_gerente(g)) for g in gerentes}
    ranking_os_abertas = sorted(abertas.items(), key=lambda x: x[1], reverse=True)
    ranking_os_prestadores = carregar_os_prestadores()
    
    # Dados para gráficos
    chart_data = {
        'os_por_periodo': {},
        'os_por_gerente': Counter([f.gerente for f in finalizadas])
    }
    for f in finalizadas:
        data = parse(f.data_fin).strftime('%Y-%m' if periodo == 'anual' else '%Y-%m-%d')
        chart_data['os_por_periodo'][data] = chart_data['os_por_periodo'].get(data, 0) + 1
    
    return render_template('admin.html',
                         finalizadas=finalizadas,
                         total_os=total_os,
                         gerentes=gerentes,
                         contagem_gerentes=contagem,
                         os_abertas=abertas,
                         ranking_os_abertas=ranking_os_abertas,
                         ranking_os_prestadores=ranking_os_prestadores,
                         login_events=login_events,
                         now=saopaulo_tz.localize(datetime.now()),
                         chart_data=chart_data,
                         periodo=periodo,
                         data_inicio=data_inicio,
                         data_fim=data_fim)

@app.route('/exportar_os_finalizadas')
def exportar_os_finalizadas():
    if not session.get('is_admin'):
        flash('Acesso negado','danger')
        return redirect(url_for('login'))
    
    # Aplicar os mesmos filtros da rota admin
    periodo = request.args.get('periodo', 'todos')
    data_inicio = request.args.get('data_inicio')
    data_fim = request.args.get('data_fim')
    
    query = Finalizacao.query.order_by(Finalizacao.registrado_em.desc())
    
    if periodo != 'todos' or data_inicio or data_fim:
        if data_inicio and data_fim:
            try:
                inicio = saopaulo_tz.localize(parse(data_inicio).replace(hour=0, minute=0, second=0))
                fim = saopaulo_tz.localize(parse(data_fim).replace(hour=23, minute=59, second=59))
                query = query.filter(Finalizacao.registrado_em.between(inicio, fim))
            except ValueError:
                flash('Datas inválidas. Exportando todas as OS.', 'warning')
        elif periodo != 'todos':
            hoje = saopaulo_tz.localize(datetime.now())
            if periodo == 'diario':
                inicio = hoje.replace(hour=0, minute=0, second=0)
                fim = hoje.replace(hour=23, minute=59, second=59)
            elif periodo == 'semanal':
                inicio = hoje - timedelta(days=hoje.weekday())
                inicio = inicio.replace(hour=0, minute=0, second=0)
                fim = inicio + timedelta(days=6, hours=23, minutes=59, seconds=59)
            elif periodo == 'mensal':
                inicio = hoje.replace(day=1, hour=0, minute=0, second=0)
                fim = (inicio + timedelta(days=31)).replace(day=1, hour=23, minute=59, second=59) - timedelta(seconds=1)
            elif periodo == 'anual':
                inicio = hoje.replace(month=1, day=1, hour=0, minute=0, second=0)
                fim = hoje.replace(month=12, day=31, hour=23, minute=59, second=59)
            query = query.filter(Finalizacao.registrado_em.between(inicio, fim))
    
    allf = query.all()
    if not allf:
        flash('Nenhuma OS finalizada para o período selecionado','warning')
        return redirect(url_for('admin_panel'))
    
    pdf_path = os.path.join(BASE_DIR,'relatorio.pdf')
    pdf = FPDF()
    pdf.add_page()
    pdf.set_font('Arial','B',12)
    pdf.cell(0,10,f'Relatório de OS Finalizadas ({periodo.capitalize()})',ln=True,align='C')
    pdf.ln(5)
    cols, w = ['OS','Gerente','Data','Hora','Obs'], [20,40,30,25,75]
    pdf.set_font('Arial','B',10)
    for c,width in zip(cols,w):
        pdf.cell(width,8,c,border=1)
    pdf.ln()
    pdf.set_font('Arial','',9)
    for r in allf:
        pdf.cell(w[0],6,r.os_numero,border=1)
        pdf.cell(w[1],6,r.gerente, border=1)
        pdf.cell(w[2],6,r.data_fin, border=1)
        pdf.cell(w[3],6,r.hora_fin, border=1)
        pdf.cell(w[4],6,(r.observacoes or '')[:40],border=1)
        pdf.ln()
    pdf.output(pdf_path)
    return send_file(pdf_path,
                   as_attachment=True,
                   download_name=f'relatorio_{saopaulo_tz.localize(datetime.now()):%Y%m%d}.pdf',
                   mimetype='application/pdf')

@app.route('/logout')
def logout():
    ev_id = session.pop('login_event_id', None)
    if ev_id:
        ev = LoginEvent.query.get(ev_id)
        if ev:
            ev.logout_time = datetime.now(saopaulo_tz)
            if ev.login_time.tzinfo is None:
                ev.login_time = saopaulo_tz.localize(ev.login_time)
            ev.duration_secs = int((ev.logout_time - ev.login_time).total_seconds())
            db.session.commit()
    session.clear()
    flash('Desconectado', 'info')
    return redirect(url_for('login'))

with app.app_context():
    init_db()

if __name__ == '__main__':
    app.run(host='0.0.0.0',
           port=int(os.environ.get('PORT', 10000)),
           debug=True)
