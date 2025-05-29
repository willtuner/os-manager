import os
import json
import logging
from datetime import datetime, timedelta
import pytz
from flask import Flask, render_template, request, redirect, session, url_for, flash, send_file
from flask_sqlalchemy import SQLAlchemy
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import A4
from collections import Counter
from sqlalchemy.sql import text
from dateutil.parser import parse
from werkzeug.utils import secure_filename
from PIL import Image

# Configuração de logging para depuração
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

# ----------- PATCH: Função para remover OS em todos os JSONs -----------
def remover_os_de_todos_json(diretorio, os_numero):
    removido_de = []
    for arquivo in os.listdir(diretorio):
        if arquivo.lower().endswith('.json'):
            caminho = os.path.join(diretorio, arquivo)
            try:
                with open(caminho, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                original_len = len(data)
                data = [item for item in data if str(item.get('os') or item.get('OS', '')) != os_numero]
                if len(data) < original_len:
                    with open(caminho, 'w', encoding='utf-8') as f:
                        json.dump(data, f, ensure_ascii=False, indent=2)
                    removido_de.append(arquivo)
                    logger.info(f"OS {os_numero} removida do arquivo: {caminho}")
            except Exception as e:
                logger.error(f"Erro ao atualizar {caminho}: {e}")
    if not removido_de:
        logger.warning(f"OS {os_numero} não encontrada em nenhum arquivo JSON de {diretorio}")
    else:
        logger.info(f"OS {os_numero} removida dos arquivos: {removido_de}")
    return removido_de

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

# --- Configuração para upload de fotos ---
UPLOAD_FOLDER = os.path.join('static', 'uploads')
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif'}

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
        if dt.tzinfo is None:
            dt = saopaulo_tz.localize(dt)
        else:
            dt = dt.astimezone(saopaulo_tz)
        return dt.strftime('%d/%m/%Y %H:%M:%S')
    return None

# --- Models ---
class User(db.Model):
    __tablename__ = 'users'
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password = db.Column(db.String(128), nullable=False)
    is_admin = db.Column(db.Boolean, default=False)
    profile_picture = db.Column(db.String(256), nullable=True)

class Finalizacao(db.Model):
    __tablename__ = 'finalizacoes'
    id = db.Column(db.Integer, primary_key=True)
    os_numero = db.Column(db.String(50), nullable=False)
    gerente = db.Column(db.String(80), nullable=False)
    data_fin = db.Column(db.String(10), nullable=False)
    hora_fin = db.Column(db.String(5), nullable=False)
    observacoes = db.Column(db.Text)
    registrado_em = db.Column(db.DateTime, default=lambda: saopaulo_tz.localize(datetime.now()))

# Updated: Added timezone=True for explicit timezone-aware storage
class LoginEvent(db.Model):
    __tablename__ = 'login_events'
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), nullable=False)
    user_type = db.Column(db.String(20), nullable=False)
    login_time = db.Column(db.DateTime(timezone=True), default=lambda: saopaulo_tz.localize(datetime.now()), nullable=False)
    logout_time = db.Column(db.DateTime(timezone=True))
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

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def init_db():
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

        columns = [col['name'] for col in inspector.get_columns('users')]
        if 'profile_picture' not in columns:
            logger.info("Adicionando coluna profile_picture à tabela users")
            db.session.execute(text('ALTER TABLE users ADD COLUMN profile_picture VARCHAR(256)'))
            db.session.commit()
            logger.info("Coluna profile_picture adicionada com sucesso")
    except Exception as e:
        logger.error(f"Erro ao verificar/adicionar colunas: {e}")
        db.session.rollback()

    if User.query.count() == 0 and os.path.exists(USERS_FILE):
        with open(USERS_FILE, encoding='utf-8') as f:
            js = json.load(f)
        admins = {'wilson.santana'}
        for u, valor in js.items():
            if isinstance(valor, dict):
                senha = valor.get("senha", "")
                profile_picture = valor.get("profile_picture", None)
            else:
                senha = valor
                profile_picture = None
            db.session.add(User(
                username=u.lower(),
                password=senha,
                is_admin=(u.lower() in admins),
                profile_picture=profile_picture
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
        logger.warning(f"Arquivo {PRESTADORES_FILE} não encontrado. Criando arquivo vazio.")
        os.makedirs(os.path.dirname(PRESTADORES_FILE), exist_ok=True)
        with open(PRESTADORES_FILE, 'w', encoding='utf-8') as f:
            json.dump([], f, ensure_ascii=False, indent=2)
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
        logger.warning(f"Arquivo {MANUTENCAO_FILE} não encontrado. Criando arquivo vazio.")
        os.makedirs(os.path.dirname(MANUTENCAO_FILE), exist_ok=True)
        with open(MANUTENCAO_FILE, 'w', encoding='utf-8') as f:
            json.dump([], f, ensure_ascii=False, indent=2)
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
                item['modelo'] = str(item.get('modelo', 'Desconhecido') or 'Desconhecido')
            except Exception:
                item['dias_abertos'] = 0
                item['modelo'] = 'Desconhecido'
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
                            data_entrada = hoje
                            dias_abertos = 0
                        os_sem_prestador.append({
                            'os': str(item.get('os') or item.get('OS', '')),
                            'frota': str(item.get('frota') or item.get('Frota', '')),
                            'data_entrada': data_str,
                            'modelo': str(item.get('modelo') or item.get('Modelo', 'Desconhecido') or 'Desconhecido'),
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
            login_time = saopaulo_tz.localize(datetime.now())
            logger.debug(f"Setting login_time for {username}: {login_time}")
            ev = LoginEvent(username=username, user_type='gerente', login_time=login_time)
            db.session.add(ev)
            db.session.commit()
            session['login_event_id'] = ev.id
            session['gerente'] = username
            session['is_admin'] = user.is_admin
            logger.info(f"Login bem-sucedido para gerente: {username} às {format_datetime(login_time)}")
            return redirect(url_for('admin_panel' if user.is_admin else 'painel'))

        manutencao_users = carregar_manutencao()
        if not manutencao_users and os.path.exists(MANUTENCAO_FILE):
            flash('Erro interno: Não foi possível carregar a lista de usuários de manutenção', 'danger')
            logger.warning(f"Falha no login: {username} - Problema ao carregar manutencao.json")
            return render_template('login.html')

        manutencao = next((p for p in manutencao_users if p.get('usuario', '').lower() == username and p.get('senha', '') == senha), None)
        if manutencao:
            login_time = saopaulo_tz.localize(datetime.now())
            logger.debug(f"Setting login_time for {username}: {login_time}")
            ev = LoginEvent(username=username, user_type='manutencao', login_time=login_time)
            db.session.add(ev)
            db.session.commit()
            session['login_event_id'] = ev.id
            session['manutencao'] = manutencao['usuario']
            session['manutencao_nome'] = manutencao.get('nome_exibicao', username.capitalize())
            logger.info(f"Login bem-sucedido para usuário de manutenção: {username} às {format_datetime(login_time)}")
            return redirect(url_for('painel_manutencao'))

        prestadores = carregar_prestadores()
        if not prestadores and os.path.exists(PRESTADORES_FILE):
            flash('Erro interno: Não foi possível carregar a lista de prestadores', 'danger')
            logger.warning(f"Falha no login: {username} - Problema ao carregar prestadores.json")
            return render_template('login.html')

        prestador = next((p for p in prestadores if p.get('usuario', '').lower() == username and p.get('senha', '') == senha), None)
        if prestador:
            login_time = saopaulo_tz.localize(datetime.now())
            logger.debug(f"Setting login_time for {username}: {login_time}")
            ev = LoginEvent(username=username, user_type=prestador.get('tipo', 'prestador'), login_time=login_time)
            db.session.add(ev)
            db.session.commit()
            session['login_event_id'] = ev.id
            session['prestador'] = prestador['usuario']
            session['prestador_nome'] = prestador.get('nome_exibicao', username.capitalize())
            logger.info(f"Login bem-sucedido para prestador: {username} às {format_datetime(login_time)}")
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
    
    user = User.query.filter_by(username=session['gerente']).first()
    profile_picture = user.profile_picture if user else None
    
    return render_template('painel.html',
                         os_pendentes=pend,
                         finalizadas=finalizadas,
                         gerente=session['gerente'],
                         profile_picture=profile_picture,
                         now=saopaulo_tz.localize(datetime.now()))

@app.route('/upload_profile_picture', methods=['POST'])
def upload_profile_picture():
    responsavel = session.get('gerente') or session.get('manutencao')
    if not responsavel:
        return redirect(url_for('login'))

    username = responsavel.lower()
    # Removida a restrição de 'arthur' e 'mauricio' para permitir que qualquer gerente ou manutencao logado adicione foto.
    # Se quiser restringir, descomente e ajuste a lógica abaixo:
    # if username not in ['arthur', 'mauricio']: 
    #     flash('Apenas usuários autorizados podem adicionar uma foto de perfil.', 'danger')
    #     return redirect(url_for('painel_manutencao' if 'manutencao' in session else 'painel' if 'gerente' in session else 'login'))

    if 'profile_picture' not in request.files:
        flash('Nenhuma foto selecionada.', 'danger')
        return redirect(url_for('painel_manutencao' if 'manutencao' in session else 'painel' if 'gerente' in session else 'login'))

    file = request.files['profile_picture']
    if file.filename == '':
        flash('Nenhuma foto selecionada.', 'danger')
        return redirect(url_for('painel_manutencao' if 'manutencao' in session else 'painel' if 'gerente' in session else 'login'))

    if file and allowed_file(file.filename):
        filename = secure_filename(f"{username}_{datetime.now().strftime('%Y%m%d%H%M%S')}.{file.filename.rsplit('.', 1)[1].lower()}")
        file_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
        file.save(file_path)

        try:
            img = Image.open(file_path)
            img = img.resize((100, 100), Image.Resampling.LANCZOS)
            img.save(file_path)
        except Exception as e:
            logger.error(f"Erro ao redimensionar imagem: {e}")
            flash('Erro ao processar a imagem.', 'danger')
            return redirect(url_for('painel_manutencao' if 'manutencao' in session else 'painel' if 'gerente' in session else 'login'))

        user = User.query.filter_by(username=username).first()
        if user: # Se for um gerente (usuário do BD)
            user.profile_picture = f"uploads/{filename}"
            db.session.commit()
            flash('Foto de perfil atualizada com sucesso!', 'success')
        # Se for um usuário de manutenção (que não está na tabela User, mas em manutencao.json)
        # a lógica de salvar a foto de perfil pode precisar ser diferente,
        # por exemplo, atualizando o manutencao.json.
        # Por ora, estamos apenas atualizando para usuários da tabela User.
        elif 'manutencao' in session and session['manutencao'] == username:
             # Aqui você poderia adicionar lógica para salvar o caminho da foto para usuários de manutenção
             # Por exemplo, em uma coluna 'profile_picture' no manutencao.json ou em um novo arquivo/BD.
             # Como não há essa estrutura, apenas piscamos uma mensagem genérica.
             flash('Foto de perfil carregada. Atualização visual pode depender da configuração do usuário de manutenção.', 'info')

        else:
            flash('Usuário não encontrado para associar a foto.', 'danger')
    else:
        flash('Formato de arquivo não permitido. Use PNG, JPG, JPEG ou GIF.', 'danger')

    return redirect(url_for('painel_manutencao' if 'manutencao' in session else 'painel' if 'gerente' in session else 'login'))


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
            # INÍCIO DA CORREÇÃO: Calcular dias_abertos para a lista de OS do prestador
            hoje = saopaulo_tz.localize(datetime.now()).date()
            for item in os_list:
                data_str = item.get('data') or item.get('Data', '')
                dias_abertos = 0
                if data_str:
                    for fmt in ("%d/%m/%Y", "%Y-%m-%d"):
                        try:
                            data_abertura = datetime.strptime(data_str, fmt).date()
                            dias_abertos = (hoje - data_abertura).days
                            break
                        except ValueError:
                            continue
                item['dias_abertos'] = dias_abertos
            # FIM DA CORREÇÃO
        except json.JSONDecodeError as e:
            logger.error(f"Erro ao decodificar {caminho}: {e}")
            os_list = []
        except Exception as e: # Captura genérica para outros erros de carregamento/processamento
            logger.error(f"Erro ao processar arquivo de OS {caminho} para {session['prestador']}: {e}")
            os_list = []
            flash(f"Erro ao carregar algumas OS. Verifique o arquivo {prestador['arquivo_os']}.", 'warning')

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
    os_sem_prestador = carregar_os_sem_prestador()
    total_os = len(os_list)
    total_os_sem_prestador = len(os_sem_prestador)

    ordenar = request.args.get('ordenar', 'data_desc')
    if ordenar == 'data_asc':
        os_list.sort(key=lambda x: datetime.strptime(x['data_entrada'], '%d/%m/%Y'))
    elif ordenar == 'data_desc':
        os_list.sort(key=lambda x: datetime.strptime(x['data_entrada'], '%d/%m/%Y'), reverse=True)
    elif ordenar == 'frota':
        os_list.sort(key=lambda x: x['frota'])

    finalizadas = Finalizacao.query.order_by(Finalizacao.registrado_em.desc()).limit(100).all()

    # Tenta carregar a foto de perfil para usuários de manutenção (se existir na tabela User)
    # Idealmente, usuários de manutenção também teriam um registro em `User` ou um mecanismo similar
    # para armazenar profile_picture se eles puderem fazer upload.
    profile_picture = None
    user_manutencao_db = User.query.filter_by(username=session['manutencao']).first()
    if user_manutencao_db:
        profile_picture = user_manutencao_db.profile_picture
    # Se não houver user no DB, mas quisermos mostrar uma foto padrão ou de um arquivo JSON,
    # a lógica seria adicionada aqui. Por exemplo:
    # elif 'profile_picture' in manutencao: # Supondo que manutencao.json possa ter a chave
    #     profile_picture = url_for('static', filename=manutencao['profile_picture'])


    return render_template('painel_manutencao.html', 
                         nome=manutencao['nome_exibicao'], 
                         manutencao=session['manutencao'], 
                         os_list=os_list, 
                         total_os=total_os, 
                         os_sem_prestador=os_sem_prestador, 
                         total_os_sem_prestador=total_os_sem_prestador,
                         finalizadas=finalizadas,
                         ordenar=ordenar,
                         prestadores=carregar_prestadores(),
                         now=saopaulo_tz.localize(datetime.now()),
                         profile_picture=profile_picture)

@app.route('/finalizar_os/<os_numero>', methods=['GET', 'POST'])
def finalizar_os(os_numero):
    responsavel = session.get('gerente') or session.get('prestador') or session.get('manutencao')
    if not responsavel:
        flash('Acesso negado. Faça login.', 'danger')
        return redirect(url_for('login'))

    # Determine which list to load based on the user type
    all_relevant_os = []
    os_data_to_finalize = None

    if 'manutencao' in session:
        all_relevant_os = carregar_os_manutencao(session['manutencao'])
        os_data_to_finalize = next((os_item for os_item in all_relevant_os if str(os_item.get('os') or os_item.get('OS', '')) == str(os_numero)), None)
    elif 'gerente' in session:
        all_relevant_os = carregar_os_gerente(session['gerente'])
        os_data_to_finalize = next((os_item for os_item in all_relevant_os if str(os_item.get('os') or os_item.get('OS', '')) == str(os_numero)), None)
    elif 'prestador' in session:
        prestadores_list = carregar_prestadores()
        prestador_data = next((p for p in prestadores_list if p.get('usuario', '').lower() == session['prestador']), None)
        if prestador_data and 'arquivo_os' in prestador_data:
            caminho = os.path.join(MENSAGENS_PRESTADOR_DIR, prestador_data['arquivo_os'])
            if os.path.exists(caminho):
                try:
                    with open(caminho, 'r', encoding='utf-8') as f:
                        all_relevant_os_prestador = json.load(f)
                    # Calculate dias_abertos for prestador's OS list
                    hoje = saopaulo_tz.localize(datetime.now()).date()
                    for item in all_relevant_os_prestador:
                        data_str = item.get('data') or item.get('Data', '') # Use 'data' or 'Data'
                        item['os'] = str(item.get('os') or item.get('OS', '')) # Garantir que OS seja string
                        dias_abertos = 0
                        if data_str:
                            for fmt in ("%d/%m/%Y", "%Y-%m-%d"):
                                try:
                                    data_abertura = datetime.strptime(data_str, fmt).date()
                                    dias_abertos = (hoje - data_abertura).days
                                    break
                                except ValueError:
                                    continue
                        item['dias_abertos'] = dias_abertos
                    all_relevant_os = all_relevant_os_prestador # Atribui a lista processada
                    os_data_to_finalize = next((os_item for os_item in all_relevant_os if str(os_item.get('os') or os_item.get('OS', '')) == str(os_numero)), None)

                except json.JSONDecodeError as e:
                    logger.error(f"Erro ao decodificar {caminho}: {e}")
                except Exception as e:
                    logger.error(f"Erro ao processar OS do prestador {caminho}: {e}")
            else:
                 logger.warning(f"Arquivo OS do prestador não encontrado: {caminho}")
        else:
            logger.warning(f"Dados do prestador ou arquivo OS não encontrado para {session.get('prestador')}")


    if request.method == 'GET':
        # Render the form, potentially pre-filling with OS data
        profile_picture_path = None
        user_db_entry = User.query.filter_by(username=responsavel.lower()).first()
        if user_db_entry and user_db_entry.profile_picture:
            profile_picture_path = url_for('static', filename=user_db_entry.profile_picture)
        # Se for usuário de manutenção e não tiver entrada em User, ou se a foto estiver em outro lugar:
        elif 'manutencao' in session:
            manutencao_users_list = carregar_manutencao()
            manutencao_user_data = next((p for p in manutencao_users_list if p.get('usuario', '').lower() == responsavel.lower()), None)
            if manutencao_user_data and manutencao_user_data.get('profile_picture'): # Supondo que manutencao.json pode ter
                profile_picture_path = url_for('static', filename=manutencao_user_data['profile_picture'])


        # Determina o template e contexto baseados no tipo de usuário
        template_to_render = 'painel_manutencao.html' # Padrão
        context = {
            'nome': session.get('manutencao_nome') or session.get('gerente') or session.get('prestador_nome'),
            'os_list': all_relevant_os, # Lista de OS do usuário
            'os_numero_a_finalizar': os_numero,
            'os_data': os_data_to_finalize, # Dados da OS específica a ser finalizada
            'now': saopaulo_tz.localize(datetime.now()),
            'profile_picture': profile_picture_path
        }

        if 'manutencao' in session:
            context.update({
                'manutencao': session['manutencao'],
                'total_os': len(all_relevant_os),
                'os_sem_prestador': carregar_os_sem_prestador(),
                'total_os_sem_prestador': len(carregar_os_sem_prestador()),
                'finalizadas': Finalizacao.query.order_by(Finalizacao.registrado_em.desc()).limit(100).all(),
                'ordenar': 'data_desc', # ou o que for relevante
                'prestadores': carregar_prestadores()
            })
        elif 'gerente' in session:
            template_to_render = 'painel.html'
            context.update({
                'os_pendentes': all_relevant_os, # Para gerentes, as OS pendentes são 'all_relevant_os'
                'finalizadas': Finalizacao.query.filter_by(gerente=session['gerente']).order_by(Finalizacao.registrado_em.desc()).limit(100).all(),
                'gerente': session['gerente']
            })
        elif 'prestador' in session:
            template_to_render = 'painel_prestador.html'
            # 'os_list' já está no contexto para prestador
            # 'nome' já está no contexto

        return render_template(template_to_render, **context)


    if request.method == 'POST':
        data_fin_str = request.form.get('data_finalizacao')
        hora_fin = request.form.get('hora_finalizacao')
        observacoes = request.form.get('observacoes', '')

        if not data_fin_str or not hora_fin:
            flash('Data e hora de finalização são obrigatórias.', 'danger')
            return redirect(url_for('finalizar_os', os_numero=os_numero))

        data_abertura_str = None
        if os_data_to_finalize:
            data_abertura_str = os_data_to_finalize.get('data_entrada') or os_data_to_finalize.get('data')

        data_abertura_obj = None
        if data_abertura_str:
            for fmt in ("%d/%m/%Y", "%Y-%m-%d", "%d-%m-%Y"):
                try:
                    data_abertura_obj = datetime.strptime(data_abertura_str, fmt).date()
                    break
                except ValueError:
                    continue

        data_fin_obj = None
        data_fin_formatted = ""
        for fmt in ('%Y-%m-%d', '%d/%m/%Y'): # O input date HTML geralmente envia YYYY-MM-DD
            try:
                data_fin_obj = datetime.strptime(data_fin_str, fmt).date()
                data_fin_formatted = data_fin_obj.strftime('%d/%m/%Y') # Salvar sempre como DD/MM/YYYY
                break
            except ValueError:
                continue

        if not data_fin_obj:
            flash('Formato de data de finalização inválido. Use DD/MM/AAAA ou selecione no calendário.', 'danger')
            return redirect(url_for('finalizar_os', os_numero=os_numero))

        if data_abertura_obj and data_fin_obj < data_abertura_obj:
            flash(f'A data de finalização ({data_fin_formatted}) não pode ser anterior à data de abertura da OS ({data_abertura_obj.strftime("%d/%m/%Y")}).', 'danger')
            return redirect(url_for('finalizar_os', os_numero=os_numero))

        fz = Finalizacao(
            os_numero=str(os_numero), # Garantir que seja string
            gerente=responsavel,
            data_fin=data_fin_formatted,
            hora_fin=hora_fin,
            observacoes=observacoes,
            registrado_em=saopaulo_tz.localize(datetime.now()) # Adicionar fuso horário ao registrar
        )
        db.session.add(fz)
        try:
            db.session.commit()
        except Exception as e:
            db.session.rollback()
            logger.error(f"Erro ao salvar no banco: {e}")
            flash('Erro ao finalizar a OS. Verifique os logs.', 'danger')
            return redirect(url_for('finalizar_os', os_numero=os_numero))

        # Remover OS de todos os arquivos JSON relevantes
        removidos_msg = []
        if 'gerente' in session:
            removidos = remover_os_de_todos_json(MENSAGENS_DIR, str(os_numero))
            if removidos: removidos_msg.append(f'OS {os_numero} removida dos arquivos de gerente: {", ".join(removidos)}')
        if 'prestador' in session:
            removidos = remover_os_de_todos_json(MENSAGENS_PRESTADOR_DIR, str(os_numero))
            if removidos: removidos_msg.append(f'OS {os_numero} removida dos arquivos de prestador: {", ".join(removidos)}')
        if 'manutencao' in session:
            # Para manutenção, verificar se a OS estava em algum arquivo JSON específico de manutenção
            manutencao_users_list = carregar_manutencao()
            manutencao_user_data = next((p for p in manutencao_users_list if p.get('usuario', '').lower() == session['manutencao']), None)
            if manutencao_user_data and manutencao_user_data.get('arquivo_os'):
                # Assume que o arquivo_os está no JSON_DIR
                arquivo_manutencao_especifico = os.path.join(JSON_DIR, manutencao_user_data['arquivo_os'])
                if os.path.exists(arquivo_manutencao_especifico):
                    removido_manutencao_especifico = remover_os_de_todos_json(os.path.dirname(arquivo_manutencao_especifico), str(os_numero)) # Passa o diretório
                    if removido_manutencao_especifico: removidos_msg.append(f'OS {os_numero} removida do arquivo de manutenção: {os.path.basename(arquivo_manutencao_especifico)}')
            # Também verificar no diretório JSON_DIR geral se necessário (se a OS puder estar lá sem ser específica do usuário)
            # removidos_json_dir = remover_os_de_todos_json(JSON_DIR, str(os_numero))
            # if removidos_json_dir: removidos_msg.append(f'OS {os_numero} removida de arquivos em static/json: {", ".join(removidos_json_dir)}')


        if removidos_msg:
            flash(". ".join(removidos_msg), 'info')
        else:
            flash(f'OS {os_numero} não encontrada em arquivos JSON para remoção ou já removida.', 'warning')

        flash(f'OS {os_numero} finalizada e registrada com sucesso!', 'success')
        
        if 'prestador' in session:
            return redirect(url_for('painel_prestador'))
        elif 'manutencao' in session:
            return redirect(url_for('painel_manutencao'))
        elif 'gerente' in session:
            return redirect(url_for('painel'))
        else:
            return redirect(url_for('login'))


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
    os_target = next((os_item for os_item in os_sem_prestador if os_item['os'] == os_numero), None)
    if not os_target:
        flash('OS não encontrada ou já possui prestador', 'danger')
        return redirect(url_for('painel_manutencao'))

    caminho_origem = os.path.join(MENSAGENS_DIR, os_target['arquivo_origem'])
    try:
        with open(caminho_origem, 'r', encoding='utf-8') as f:
            dados = json.load(f)
        
        os_atualizada = False
        for item in dados:
            if str(item.get('os') or item.get('OS', '')) == os_numero:
                item['prestador'] = prestador_nome
                os_atualizada = True
                break
        
        if os_atualizada:
            with open(caminho_origem, 'w', encoding='utf-8') as f:
                json.dump(dados, f, ensure_ascii=False, indent=2)
            flash(f'Prestador {prestador_nome} atribuído à OS {os_numero} com sucesso', 'success')
        else:
            flash(f'OS {os_numero} não encontrada no arquivo de origem para atualização.', 'warning')

    except Exception as e:
        logger.error(f"Erro ao atualizar {caminho_origem}: {e}")
        flash('Erro ao atribuir prestador', 'danger')
    return redirect(url_for('painel_manutencao'))

# Updated: Simplified timezone handling for login_events
@app.route('/admin')
def admin_panel():
    if not session.get('is_admin'):
        flash('Acesso negado', 'danger')
        return redirect(url_for('login'))

    periodo = request.args.get('periodo', 'todos')
    data_inicio_str = request.args.get('data_inicio')
    data_fim_str = request.args.get('data_fim')

    query = Finalizacao.query.order_by(Finalizacao.registrado_em.desc())
    
    # Filtro de data para OS Finalizadas
    # Garantir que a coluna `registrado_em` seja comparada como DateTime com timezone
    if data_inicio_str and data_fim_str:
        try:
            inicio = saopaulo_tz.localize(parse(data_inicio_str).replace(hour=0, minute=0, second=0, microsecond=0))
            fim = saopaulo_tz.localize(parse(data_fim_str).replace(hour=23, minute=59, second=59, microsecond=999999))
            query = query.filter(Finalizacao.registrado_em.between(inicio, fim))
        except ValueError:
            flash('Datas inválidas para filtro de OS Finalizadas. Usando todas as OS.', 'warning')
    elif periodo != 'todos':
        hoje_tz = saopaulo_tz.localize(datetime.now())
        if periodo == 'diario':
            inicio = hoje_tz.replace(hour=0, minute=0, second=0, microsecond=0)
            fim = hoje_tz.replace(hour=23, minute=59, second=59, microsecond=999999)
        elif periodo == 'semanal':
            inicio = (hoje_tz - timedelta(days=hoje_tz.weekday())).replace(hour=0, minute=0, second=0, microsecond=0)
            fim = (inicio + timedelta(days=6)).replace(hour=23, minute=59, second=59, microsecond=999999)
        elif periodo == 'mensal':
            inicio = hoje_tz.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
            # Para fim do mês, ir para o próximo mês e subtrair um dia
            next_month = inicio.replace(day=28) + timedelta(days=4) # Vai para o próximo mês
            fim = (next_month - timedelta(days=next_month.day)).replace(hour=23, minute=59, second=59, microsecond=999999)
        elif periodo == 'anual':
            inicio = hoje_tz.replace(month=1, day=1, hour=0, minute=0, second=0, microsecond=0)
            fim = hoje_tz.replace(month=12, day=31, hour=23, minute=59, second=59, microsecond=999999)
        else: # Caso 'todos' ou inválido, não aplica filtro de período específico
            inicio, fim = None, None

        if inicio and fim:
            query = query.filter(Finalizacao.registrado_em.between(inicio, fim))


    total_os = query.count()
    finalizadas_list = query.limit(100).all() # Renomeado para evitar conflito com model
    
    # Filtro de data para Login Events
    login_events_query = LoginEvent.query.order_by(LoginEvent.login_time.desc())
    if data_inicio_str and data_fim_str:
        try:
            inicio_login = saopaulo_tz.localize(parse(data_inicio_str).replace(hour=0, minute=0, second=0, microsecond=0))
            fim_login = saopaulo_tz.localize(parse(data_fim_str).replace(hour=23, minute=59, second=59, microsecond=999999))
            login_events_query = login_events_query.filter(LoginEvent.login_time.between(inicio_login, fim_login))
        except ValueError:
            flash('Datas inválidas para filtro de Eventos de Login. Usando todos os eventos.', 'warning')
    elif periodo != 'todos' and 'inicio' in locals() and 'fim' in locals() and inicio and fim: # reusa datas do filtro de OS se aplicável
         login_events_query = login_events_query.filter(LoginEvent.login_time.between(inicio, fim))


    login_events = login_events_query.limit(50).all()


    for event in login_events:
        event.login_time_formatted = format_datetime(event.login_time)
        event.logout_time_formatted = format_datetime(event.logout_time) if event.logout_time else None
        if event.logout_time and event.login_time:
            # Certificar que ambos são timezone-aware e no mesmo timezone para subtração correta
            login_t = event.login_time if event.login_time.tzinfo else saopaulo_tz.localize(event.login_time)
            logout_t = event.logout_time if event.logout_time.tzinfo else saopaulo_tz.localize(event.logout_time)
            login_t = login_t.astimezone(saopaulo_tz)
            logout_t = logout_t.astimezone(saopaulo_tz)
            duration = (logout_t - login_t).total_seconds()
            event.duration_secs = int(max(0, duration))
        elif event.duration_secs is None : # Se não há logout_time, duração não pode ser calculada
            event.duration_secs = 0


    users = User.query.order_by(User.username).all()
    gerentes_db = [u.username for u in users] # gerentes do banco de dados

    # Contagem de OS finalizadas por gerente (do BD)
    contagem_finalizadas_gerentes_db = {}
    if inicio and fim: # Se houver filtro de data, aplicar na contagem
        contagem_finalizadas_gerentes_db = {
            g: Finalizacao.query.filter(Finalizacao.gerente == g, Finalizacao.registrado_em.between(inicio, fim)).count()
            for g in gerentes_db
        }
    else: # Sem filtro de data
        contagem_finalizadas_gerentes_db = {
            g: Finalizacao.query.filter_by(gerente=g).count() for g in gerentes_db
        }
    
    # Contagem de OS abertas por gerente (dos arquivos JSON)
    abertas_gerentes_json = {g: len(carregar_os_gerente(g)) for g in gerentes_db}
    ranking_os_abertas_gerentes = sorted(abertas_gerentes_json.items(), key=lambda x: x[1], reverse=True)
    
    ranking_os_prestadores = carregar_os_prestadores() # Isso já carrega dos JSONs dos prestadores

    # Dados para gráficos
    chart_data = {
        'os_por_periodo': {}, # OS Finalizadas por período
        'os_por_gerente': Counter(), # OS Finalizadas por gerente (do BD)
        'os_abertas_por_gerente': Counter(abertas_gerentes_json) # OS Abertas por gerente (JSON)
    }
    
    # Processar OS finalizadas para gráfico de período e por gerente
    for f in finalizadas_list: # Usar a lista já filtrada e limitada
        # Para os_por_periodo, usar a data de finalização da OS
        try:
            data_finalizacao_obj = datetime.strptime(f.data_fin, "%d/%m/%Y")
            if periodo == 'anual':
                periodo_key = data_finalizacao_obj.strftime('%Y-%m')
            elif periodo == 'mensal':
                periodo_key = data_finalizacao_obj.strftime('%Y-%m-%d')
            elif periodo == 'semanal':
                periodo_key = data_finalizacao_obj.strftime('%Y-%U') # Ano-Semana
            elif periodo == 'diario':
                 periodo_key = data_finalizacao_obj.strftime('%Y-%m-%d')
            else: # 'todos' ou default
                periodo_key = data_finalizacao_obj.strftime('%Y-%m-%d') # Agrupar por dia se 'todos' for muito granular

            chart_data['os_por_periodo'][periodo_key] = chart_data['os_por_periodo'].get(periodo_key, 0) + 1
        except ValueError:
            logger.warning(f"Data de finalização em formato inválido para OS {f.os_numero}: {f.data_fin}")

        chart_data['os_por_gerente'][f.gerente] += 1


    return render_template('admin.html',
                         finalizadas=finalizadas_list,
                         total_os=total_os, # Total de OS finalizadas no período
                         gerentes_db=gerentes_db,
                         contagem_finalizadas_gerentes=contagem_finalizadas_gerentes_db, # Finalizadas por gerente (BD)
                         os_abertas_gerentes=abertas_gerentes_json, # Abertas por gerente (JSON)
                         ranking_os_abertas_gerentes=ranking_os_abertas_gerentes,
                         ranking_os_prestadores=ranking_os_prestadores,
                         login_events=login_events,
                         now=saopaulo_tz.localize(datetime.now()),
                         chart_data=chart_data,
                         periodo_selecionado=periodo, # Renomeado para clareza no template
                         data_inicio_filtro=data_inicio_str, # Renomeado
                         data_fim_filtro=data_fim_str, # Renomeado
                         format_datetime=format_datetime # Passando a função para o template
                         )


@app.route('/exportar_os_finalizadas')
def exportar_os_finalizadas():
    if not session.get('is_admin'):
        flash('Acesso negado', 'danger')
        return redirect(url_for('login'))

    periodo = request.args.get('periodo', 'todos')
    data_inicio_str = request.args.get('data_inicio')
    data_fim_str = request.args.get('data_fim')

    query = Finalizacao.query.order_by(Finalizacao.registrado_em.desc())

    # Reutilizar a lógica de filtro de data do admin_panel
    inicio, fim = None, None # Inicializar para evitar UnboundLocalError
    if data_inicio_str and data_fim_str:
        try:
            inicio = saopaulo_tz.localize(parse(data_inicio_str).replace(hour=0, minute=0, second=0, microsecond=0))
            fim = saopaulo_tz.localize(parse(data_fim_str).replace(hour=23, minute=59, second=59, microsecond=999999))
            query = query.filter(Finalizacao.registrado_em.between(inicio, fim))
        except ValueError:
            flash('Datas inválidas. Exportando todas as OS.', 'warning')
    elif periodo != 'todos':
        hoje_tz = saopaulo_tz.localize(datetime.now())
        if periodo == 'diario':
            inicio = hoje_tz.replace(hour=0, minute=0, second=0, microsecond=0)
            fim = hoje_tz.replace(hour=23, minute=59, second=59, microsecond=999999)
        elif periodo == 'semanal':
            inicio = (hoje_tz - timedelta(days=hoje_tz.weekday())).replace(hour=0, minute=0, second=0, microsecond=0)
            fim = (inicio + timedelta(days=6)).replace(hour=23, minute=59, second=59, microsecond=999999)
        elif periodo == 'mensal':
            inicio = hoje_tz.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
            next_month = inicio.replace(day=28) + timedelta(days=4)
            fim = (next_month - timedelta(days=next_month.day)).replace(hour=23, minute=59, second=59, microsecond=999999)
        elif periodo == 'anual':
            inicio = hoje_tz.replace(month=1, day=1, hour=0, minute=0, second=0, microsecond=0)
            fim = hoje_tz.replace(month=12, day=31, hour=23, minute=59, second=59, microsecond=999999)
        
        if inicio and fim: # Aplicar filtro somente se inicio e fim foram definidos
             query = query.filter(Finalizacao.registrado_em.between(inicio, fim))


    all_finalizadas = query.all()
    if not all_finalizadas:
        flash('Nenhuma OS finalizada para o período selecionado', 'warning')
        return redirect(url_for('admin_panel', periodo=periodo, data_inicio=data_inicio_str, data_fim=data_fim_str))

    pdf_path = os.path.join(BASE_DIR, 'relatorio_os_finalizadas.pdf')
    c = canvas.Canvas(pdf_path, pagesize=A4)
    width, height = A4

    c.setFont("Helvetica-Bold", 14)
    titulo_periodo = periodo.capitalize()
    if data_inicio_str and data_fim_str:
        titulo_periodo = f"{parse(data_inicio_str).strftime('%d/%m/%Y')} a {parse(data_fim_str).strftime('%d/%m/%Y')}"
    elif inicio and fim: # Se foi um período como 'semanal', 'mensal'
        titulo_periodo = f"{inicio.strftime('%d/%m/%Y')} a {fim.strftime('%d/%m/%Y')}"

    c.drawCentredString(width / 2, height - 50, f"Relatório de OS Finalizadas ({titulo_periodo})")
    
    y_pos = height - 80
    c.setFont("Helvetica-Bold", 9)
    
    col_widths = {
        'OS': 70, 'Gerente': 100, 'Data Fin.': 60, 'Hora Fin.': 50, 
        'Observações': 180, 'Registrado Em': 100
    }
    current_x = 30

    # Cabeçalho
    for col_name, col_width in col_widths.items():
        c.drawString(current_x, y_pos, col_name)
        current_x += col_width
    y_pos -= 15
    c.line(30, y_pos + 5, width - 30, y_pos + 5) # Linha abaixo do cabeçalho
    y_pos -= 5


    c.setFont("Helvetica", 8)
    for r in all_finalizadas:
        if y_pos < 40: # Nova página
            c.showPage()
            c.setFont("Helvetica-Bold", 14)
            c.drawCentredString(width / 2, height - 50, f"Relatório de OS Finalizadas ({titulo_periodo}) (continuação)")
            y_pos = height - 80
            c.setFont("Helvetica-Bold", 9)
            current_x_header = 30
            for col_name_h, col_width_h in col_widths.items():
                c.drawString(current_x_header, y_pos, col_name_h)
                current_x_header += col_width_h
            y_pos -= 15
            c.line(30, y_pos + 5, width - 30, y_pos + 5)
            y_pos -= 5
            c.setFont("Helvetica", 8)

        current_x = 30
        
        # Truncar observações longas
        obs_text = (r.observacoes or '')
        max_obs_chars = 45 # Ajustar conforme necessário para caber na coluna
        if len(obs_text) > max_obs_chars:
            obs_text = obs_text[:max_obs_chars-3] + "..."

        registrado_em_fmt = format_datetime(r.registrado_em) if r.registrado_em else "N/A"

        row_data = [
            str(r.os_numero), str(r.gerente), str(r.data_fin), str(r.hora_fin),
            obs_text, registrado_em_fmt
        ]
        
        idx = 0
        for col_name, col_width in col_widths.items():
            c.drawString(current_x, y_pos, row_data[idx])
            current_x += col_width
            idx +=1
            
        y_pos -= 12 # Espaçamento entre linhas

    c.save()
    return send_file(pdf_path,
                   as_attachment=True,
                   download_name=f'relatorio_os_{saopaulo_tz.localize(datetime.now()):%Y%m%d_%H%M}.pdf',
                   mimetype='application/pdf')

@app.route('/logout')
def logout():
    ev_id = session.pop('login_event_id', None)
    username_logged_out = session.get('gerente') or session.get('prestador') or session.get('manutencao') # Pega antes de limpar
    
    if ev_id:
        ev = LoginEvent.query.get(ev_id)
        if ev:
            logout_time = saopaulo_tz.localize(datetime.now()) # Logout no fuso de SP
            
            # Garantir que login_time seja timezone-aware e em SP para cálculo de duração
            login_time_aware = ev.login_time
            if login_time_aware.tzinfo is None:
                login_time_aware = saopaulo_tz.localize(login_time_aware)
            else:
                login_time_aware = login_time_aware.astimezone(saopaulo_tz)
            
            ev.logout_time = logout_time
            duration = (logout_time - login_time_aware).total_seconds()
            ev.duration_secs = int(max(0, duration))
            
            logger.info(f"Logout de {ev.username}: login às {format_datetime(login_time_aware)}, "
                        f"logout às {format_datetime(logout_time)}, duração: {ev.duration_secs} segundos")
            try:
                db.session.commit()
            except Exception as e:
                db.session.rollback()
                logger.error(f"Erro ao commitar logout event para {ev.username}: {e}")
        else:
            logger.warning(f"Evento de login ID {ev_id} não encontrado para {username_logged_out} no logout.")
    else:
        logger.info(f"Logout de {username_logged_out} sem login_event_id na sessão.")

    session.clear()
    flash(f'{username_logged_out if username_logged_out else "Usuário"} desconectado com sucesso.', 'info')
    return redirect(url_for('login'))

with app.app_context():
    init_db()

if __name__ == '__main__':
    app.run(host='0.0.0.0',
           port=int(os.environ.get('PORT', 10000)),
           debug=True)
