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
    
    try:
        with open(caminho_encontrado, encoding="utf-8") as f:
            dados = json.load(f)
    except Exception as e:
        logger.error(f"Erro ao carregar ou decodificar o arquivo JSON {caminho_encontrado}: {e}")
        return []

    resultado = []
    hoje = saopaulo_tz.localize(datetime.now()).date()
    for item in dados:
        data_str = item.get("data") or item.get("Data") or ""
        data_abertura = None
        for fmt in ("%d/%m/%Y", "%Y-%m-%d", "%d-%m-%Y"):
            try:
                data_abertura = datetime.strptime(data_str, fmt).date()
                break
            except (ValueError, TypeError):
                continue
        
        dias_abertos = (hoje - data_abertura).days if data_abertura else 0
        
        resultado.append({
            "os": str(item.get("os") or item.get("OS", "")),
            "frota": str(item.get("frota") or item.get("Frota", "")),
            "data": data_str, # Mantém a data original como string
            "dias": str(dias_abertos), # Dias como string para consistência, pode ser int se preferir
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
        usuarios = [p.get('usuario', '').lower() for p in prestadores if p.get('usuario')] # Evita erro se 'usuario' não existir
        duplicatas = [item for item, count in Counter(usuarios).items() if count > 1]
        if duplicatas:
            logger.warning(f"Usuários duplicados encontrados em prestadores.json: {duplicatas}")
        logger.debug(f"Prestadores carregados: {[p.get('usuario') for p in prestadores if p.get('usuario')]}")
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
        usuarios = [p.get('usuario', '').lower() for p in manutencao if p.get('usuario')]
        duplicatas = [item for item, count in Counter(usuarios).items() if count > 1]
        if duplicatas:
            logger.warning(f"Usuários duplicados encontrados em manutencao.json: {duplicatas}")
        logger.debug(f"Usuários de manutenção carregados: {[p.get('usuario') for p in manutencao if p.get('usuario')]}")
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
        if not usuario or prestador.get('tipo') == 'manutencao': # Pula se não houver usuário ou for de manutenção
            continue
        arquivo_os_nome = prestador.get('arquivo_os', '')
        if not arquivo_os_nome:
            logger.warning(f"Prestador {usuario} não tem 'arquivo_os' definido em prestadores.json.")
            os_por_prestador[usuario] = 0
            continue

        caminho = os.path.join(MENSAGENS_PRESTADOR_DIR, arquivo_os_nome)
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
            logger.error(f"Erro ao carregar OS para {usuario} do arquivo {caminho}: {e}")
            os_por_prestador[usuario] = 0
    ranking = sorted(os_por_prestador.items(), key=lambda x: x[1], reverse=True)
    return ranking

def carregar_os_manutencao(usuario):
    manutencao_users = carregar_manutencao()
    manutencao_user_data = next((p for p in manutencao_users if p.get('usuario', '').lower() == usuario.lower()), None)

    if not manutencao_user_data:
        logger.warning(f"Usuário {usuario} não encontrado na lista de manutenção.")
        return []
    
    arquivo_os_nome = manutencao_user_data.get('arquivo_os')
    if not arquivo_os_nome:
        logger.warning(f"Usuário de manutenção {usuario} não tem 'arquivo_os' definido.")
        return []

    caminho = os.path.join(JSON_DIR, arquivo_os_nome) # Assume que para manutenção, o arquivo está em JSON_DIR
    if not os.path.exists(caminho):
        logger.warning(f"Arquivo de OS de manutenção não encontrado: {caminho}")
        return []
    
    try:
        with open(caminho, 'r', encoding='utf-8') as f:
            os_list = json.load(f)
    except Exception as e:
        logger.error(f"Erro ao carregar ou decodificar o arquivo JSON de manutenção {caminho}: {e}")
        return []

    hoje = saopaulo_tz.localize(datetime.now()).date()
    for item in os_list:
        item['modelo'] = str(item.get('modelo', 'Desconhecido') or 'Desconhecido')
        data_entrada_str = item.get('data_entrada', '') # Prioriza 'data_entrada'
        
        data_abertura_obj = None
        if data_entrada_str:
            for fmt in ("%d/%m/%Y", "%Y-%m-%d", "%d-%m-%y", "%Y/%m/%d"):
                try:
                    data_abertura_obj = datetime.strptime(data_entrada_str, fmt).date()
                    break
                except (ValueError, TypeError):
                    continue
        
        item['dias_abertos'] = (hoje - data_abertura_obj).days if data_abertura_obj else 0
        # Garantir que 'data_entrada' seja uma string para o template, mesmo que vazia.
        item['data_entrada'] = data_entrada_str if data_entrada_str else ''


    return os_list


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
                    prestador = str(item.get('prestador') or item.get('Prestador', '')).lower().strip()
                    if prestador in ('nan', '', 'none', 'não definido', 'prestador não definido'):
                        data_str = str(item.get('data') or item.get('Data', '')) # Usado para 'data_entrada' no dict final
                        data_entrada_obj = None
                        if data_str:
                            for fmt in ("%d/%m/%Y", "%Y-%m-%d", "%d-%m-%y"):
                                try:
                                    data_entrada_obj = datetime.strptime(data_str, fmt).date()
                                    break
                                except ValueError:
                                    continue
                        
                        dias_abertos = (hoje - data_entrada_obj).days if data_entrada_obj else 0
                        
                        os_sem_prestador.append({
                            'os': str(item.get('os') or item.get('OS', '')),
                            'frota': str(item.get('frota') or item.get('Frota', '')),
                            'data_entrada': data_str, # Esta é a data original do arquivo do gerente
                            'modelo': str(item.get('modelo') or item.get('Modelo', 'Desconhecido') or 'Desconhecido'),
                            'servico': str(item.get('servico') or item.get('Servico') or item.get('observacao') or item.get('Observacao', '')),
                            'arquivo_origem': arquivo,
                            'dias_abertos': dias_abertos
                        })
            except Exception as e:
                logger.error(f"Erro ao carregar OS sem prestador de {caminho}: {e}")
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
        if not manutencao_users and os.path.exists(MANUTENCAO_FILE) and MANUTENCAO_FILE: # Adicionado MANUTENCAO_FILE para garantir que não está vazio
            flash('Erro interno: Não foi possível carregar a lista de usuários de manutenção.', 'danger')
            logger.warning(f"Falha no login para {username}: Problema ao carregar {MANUTENCAO_FILE} ou arquivo vazio.")
            return render_template('login.html')
        
        manutencao_user_data = next((p for p in manutencao_users if p.get('usuario', '').lower() == username and p.get('senha', '') == senha), None)
        if manutencao_user_data:
            login_time = saopaulo_tz.localize(datetime.now())
            ev = LoginEvent(username=username, user_type='manutencao', login_time=login_time)
            db.session.add(ev)
            db.session.commit()
            session['login_event_id'] = ev.id
            session['manutencao'] = manutencao_user_data['usuario']
            session['manutencao_nome'] = manutencao_user_data.get('nome_exibicao', username.capitalize())
            logger.info(f"Login bem-sucedido para usuário de manutenção: {username} às {format_datetime(login_time)}")
            return redirect(url_for('painel_manutencao'))

        prestadores_list = carregar_prestadores() # Renomeado para evitar conflito
        if not prestadores_list and os.path.exists(PRESTADORES_FILE) and PRESTADORES_FILE:
            flash('Erro interno: Não foi possível carregar a lista de prestadores.', 'danger')
            logger.warning(f"Falha no login para {username}: Problema ao carregar {PRESTADORES_FILE} ou arquivo vazio.")
            return render_template('login.html')

        prestador_data = next((p for p in prestadores_list if p.get('usuario', '').lower() == username and p.get('senha', '') == senha), None)
        if prestador_data:
            login_time = saopaulo_tz.localize(datetime.now())
            ev = LoginEvent(username=username, user_type=prestador_data.get('tipo', 'prestador'), login_time=login_time)
            db.session.add(ev)
            db.session.commit()
            session['login_event_id'] = ev.id
            session['prestador'] = prestador_data['usuario']
            session['prestador_nome'] = prestador_data.get('nome_exibicao', username.capitalize())
            logger.info(f"Login bem-sucedido para prestador: {username} às {format_datetime(login_time)}")
            return redirect(url_for('painel_prestador'))

        flash('Usuário ou senha incorreta.', 'danger') # Mensagem genérica
        logger.warning(f"Falha no login para {username}: Credenciais inválidas.")
    return render_template('login.html')

@app.route('/painel')
def painel():
    if 'gerente' not in session:
        return redirect(url_for('login'))
    pend = carregar_os_gerente(session['gerente'])
    finalizadas = Finalizacao.query.filter_by(gerente=session['gerente']).order_by(Finalizacao.registrado_em.desc()).limit(100).all()
    
    user = User.query.filter_by(username=session['gerente']).first()
    profile_picture = url_for('static', filename=user.profile_picture) if user and user.profile_picture else None
    
    return render_template('painel.html',
                         os_pendentes=pend,
                         finalizadas=finalizadas,
                         gerente=session['gerente'],
                         profile_picture=profile_picture,
                         now=saopaulo_tz.localize(datetime.now()),
                         today_date=datetime.now(saopaulo_tz).strftime('%Y-%m-%d'))


@app.route('/upload_profile_picture', methods=['POST'])
def upload_profile_picture():
    responsavel_username = session.get('gerente') or session.get('manutencao') # Username do responsável
    if not responsavel_username:
        flash('Acesso negado. Faça login para alterar a foto.', 'danger')
        return redirect(url_for('login'))

    # Verifica se o usuário logado (gerente ou manutenção) existe na tabela User
    user_in_db = User.query.filter_by(username=responsavel_username.lower()).first()

    if not user_in_db:
        # Se for um usuário de manutenção que não está na tabela User,
        # ou um gerente não encontrado (improvável se logado), impede o upload por ora.
        # Poderia-se adicionar lógica para salvar a foto em manutencao.json se desejado.
        flash('Usuário não configurado para upload de foto de perfil no banco de dados.', 'warning')
        return redirect(url_for('painel_manutencao' if 'manutencao' in session else 'painel'))


    if 'profile_picture' not in request.files:
        flash('Nenhuma foto selecionada.', 'danger')
        return redirect(url_for('painel_manutencao' if 'manutencao' in session else ('painel' if 'gerente' in session else 'login')))

    file = request.files['profile_picture']
    if file.filename == '':
        flash('Nenhuma foto selecionada.', 'danger')
        return redirect(url_for('painel_manutencao' if 'manutencao' in session else ('painel' if 'gerente' in session else 'login')))

    if file and allowed_file(file.filename):
        filename = secure_filename(f"{user_in_db.username}_{datetime.now().strftime('%Y%m%d%H%M%S')}.{file.filename.rsplit('.', 1)[1].lower()}")
        file_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
        
        try:
            img = Image.open(file.stream) # Usar file.stream para evitar salvar antes de redimensionar
            img = img.resize((100, 100), Image.Resampling.LANCZOS)
            img.save(file_path) # Salva a imagem redimensionada
        except Exception as e:
            logger.error(f"Erro ao redimensionar e salvar imagem: {e}")
            flash('Erro ao processar a imagem.', 'danger')
            return redirect(url_for('painel_manutencao' if 'manutencao' in session else ('painel' if 'gerente' in session else 'login')))

        user_in_db.profile_picture = f"uploads/{filename}" # Salva o caminho relativo
        try:
            db.session.commit()
            flash('Foto de perfil atualizada com sucesso!', 'success')
        except Exception as e:
            db.session.rollback()
            logger.error(f"Erro ao salvar foto de perfil no banco para {user_in_db.username}: {e}")
            flash('Erro ao salvar a foto de perfil. Tente novamente.', 'danger')
    else:
        flash(f'Formato de arquivo não permitido. Use um dos seguintes: {", ".join(ALLOWED_EXTENSIONS)}.', 'danger')

    return redirect(url_for('painel_manutencao' if 'manutencao' in session else ('painel' if 'gerente' in session else 'login')))


@app.route('/painel_prestador')
def painel_prestador():
    if 'prestador' not in session:
        return redirect(url_for('login'))
    
    prestadores_list = carregar_prestadores() #
    if not prestadores_list and os.path.exists(PRESTADORES_FILE): #
        flash('Erro interno: Não foi possível carregar a lista de prestadores', 'danger') #
        logger.error(f"Erro ao carregar prestadores para painel_prestador: {session['prestador']}") #
        return redirect(url_for('login')) #

    prestador_data = next((p for p in prestadores_list if p.get('usuario', '').lower() == session['prestador']), None) #
    if not prestador_data: #
        flash('Prestador não encontrado', 'danger') #
        logger.error(f"Prestador não encontrado na sessão: {session['prestador']}") #
        return redirect(url_for('login')) #
    
    arquivo_os_nome = prestador_data.get('arquivo_os')
    if not arquivo_os_nome:
        logger.warning(f"Prestador {session['prestador']} não tem 'arquivo_os' definido.")
        os_list = []
        flash(f"Arquivo de OS não configurado para o prestador {session['prestador']}.", 'warning')
    else:
        caminho = os.path.join(MENSAGENS_PRESTADOR_DIR, arquivo_os_nome) #
        if not os.path.exists(caminho): #
            logger.warning(f"Arquivo de OS não encontrado: {caminho}") #
            os_list = [] #
        else:
            try:
                with open(caminho, 'r', encoding='utf-8') as f: #
                    os_list_raw = json.load(f) #
                
                os_list = [] # Nova lista para armazenar itens processados
                hoje = saopaulo_tz.localize(datetime.now()).date() #
                for item_raw in os_list_raw: #
                    item = dict(item_raw) # Cria uma cópia para modificar
                    # Garante campo 'data_entrada'
                    data_str = item.get('data_entrada') or item.get('data') or item.get('Data', '') #
                    item['data_entrada'] = data_str  # Agora sempre terá #
                    
                    # Garante campo 'modelo'
                    item['modelo'] = str(item.get('modelo') or item.get('Modelo') or 'Desconhecido') #
                    
                    # Calcula dias_abertos corretamente
                    dias_calculados = 0 #
                    if data_str: #
                        data_abertura_obj = None #
                        for fmt in ("%d/%m/%Y", "%Y-%m-%d", "%d-%m-%y", "%Y/%m/%d"): # Adicionado mais formatos #
                            try:
                                data_abertura_obj = datetime.strptime(data_str, fmt).date() #
                                break #
                            except (ValueError, TypeError): # Adicionado TypeError para o caso de data_str ser None ou não string
                                continue #
                        
                        if data_abertura_obj: #
                            dias_calculados = (hoje - data_abertura_obj).days #
                        else:
                            logger.warning(f"Não foi possível parsear a data '{data_str}' para a OS {item.get('os') or item.get('OS', '')} com os formatos conhecidos.") #
                    item['dias_abertos'] = dias_calculados #
                    os_list.append(item) # Adiciona item processado à nova lista

            except json.JSONDecodeError as e: #
                logger.error(f"Erro ao decodificar {caminho}: {e}") #
                os_list = [] #
                flash(f"Erro ao ler o arquivo de OS: {arquivo_os_nome}. Verifique o formato JSON.", 'danger') #
            except Exception as e: #
                logger.error(f"Erro inesperado ao processar arquivo de OS {caminho} para {session['prestador']}: {e}") #
                os_list = [] #
                flash(f"Ocorreu um erro ao processar as OS. Tente novamente mais tarde.", 'warning') #

    return render_template(
        'painel_prestador.html',
        nome=prestador_data.get('nome_exibicao', session['prestador'].capitalize()), #
        os_list=os_list, #
        today_date=datetime.now(saopaulo_tz).strftime('%Y-%m-%d') #
    )

@app.route('/painel_manutencao')
def painel_manutencao():
    if 'manutencao' not in session:
        flash('Acesso negado. Faça login.', 'danger')
        return redirect(url_for('login'))
    
    manutencao_users_list = carregar_manutencao()
    if not manutencao_users_list and os.path.exists(MANUTENCAO_FILE):
        flash('Erro interno: Não foi possível carregar a lista de usuários de manutenção', 'danger')
        logger.error(f"Erro ao carregar manutencao para painel_manutencao: {session['manutencao']}")
        return redirect(url_for('login'))

    manutencao_user_data = next((p for p in manutencao_users_list if p.get('usuario', '').lower() == session['manutencao']), None)
    if not manutencao_user_data:
        flash('Usuário de manutenção não encontrado', 'danger')
        logger.error(f"Usuário de manutenção não encontrado na sessão: {session['manutencao']}")
        return redirect(url_for('login'))
    
    os_list_manutencao = carregar_os_manutencao(session['manutencao'])
    os_sem_prestador_list = carregar_os_sem_prestador()
    total_os_manutencao = len(os_list_manutencao)
    total_os_sem_prestador = len(os_sem_prestador_list)

    ordenar = request.args.get('ordenar', 'data_desc')
    # Validação para ordenar apenas se a lista não estiver vazia e 'data_entrada' existir
    if os_list_manutencao and all('data_entrada' in item for item in os_list_manutencao):
        try:
            if ordenar == 'data_asc':
                os_list_manutencao.sort(key=lambda x: datetime.strptime(x['data_entrada'], '%d/%m/%Y') if x['data_entrada'] else datetime.min.date())
            elif ordenar == 'data_desc':
                os_list_manutencao.sort(key=lambda x: datetime.strptime(x['data_entrada'], '%d/%m/%Y') if x['data_entrada'] else datetime.min.date(), reverse=True)
            elif ordenar == 'frota':
                os_list_manutencao.sort(key=lambda x: str(x.get('frota',''))) # Ordenar por frota como string
        except ValueError as e:
            logger.warning(f"Erro ao ordenar OS de manutenção por data: {e}. Alguma data pode estar em formato inválido ou vazia.")
            flash("Algumas OS não puderam ser ordenadas por data devido a formato inválido.", "warning")


    finalizadas_list = Finalizacao.query.order_by(Finalizacao.registrado_em.desc()).limit(100).all()

    profile_picture_path = None
    user_manutencao_db = User.query.filter_by(username=session['manutencao']).first()
    if user_manutencao_db and user_manutencao_db.profile_picture:
        profile_picture_path = url_for('static', filename=user_manutencao_db.profile_picture)
    elif manutencao_user_data.get('profile_picture'): # Supondo que manutencao.json possa ter a chave
        profile_picture_path = url_for('static', filename=manutencao_user_data['profile_picture'])


    return render_template('painel_manutencao.html', 
                         nome=manutencao_user_data.get('nome_exibicao', session['manutencao'].capitalize()), 
                         manutencao_username=session['manutencao'], # Passando username para uso interno se necessário
                         os_list=os_list_manutencao, 
                         total_os=total_os_manutencao, 
                         os_sem_prestador=os_sem_prestador_list, 
                         total_os_sem_prestador=total_os_sem_prestador,
                         finalizadas=finalizadas_list,
                         ordenar_atual=ordenar, # Passando o critério de ordenação atual
                         prestadores_disponiveis=carregar_prestadores(), # Para dropdown de atribuição
                         now_formatted=saopaulo_tz.localize(datetime.now()).strftime('%d/%m/%Y %H:%M'),
                         profile_picture=profile_picture_path,
                         today_date=datetime.now(saopaulo_tz).strftime('%Y-%m-%d'))


@app.route('/finalizar_os/<os_numero>', methods=['GET', 'POST'])
def finalizar_os(os_numero):
    responsavel = session.get('gerente') or session.get('prestador') or session.get('manutencao')
    if not responsavel:
        flash('Acesso negado. Faça login.', 'danger')
        return redirect(url_for('login'))

    os_data_to_finalize = None
    source_file_path = None # Para saber qual arquivo JSON atualizar

    # Carregar a OS específica para obter 'data_entrada' ou 'data'
    if 'gerente' in session:
        all_gerente_os = carregar_os_gerente(session['gerente'])
        os_data_to_finalize = next((os_item for os_item in all_gerente_os if str(os_item.get('os')) == str(os_numero)), None)
        # Definir source_file_path para gerente (complexo, pois pode ser um de vários arquivos)
        # A função remover_os_de_todos_json já varre MENSAGENS_DIR
    elif 'prestador' in session:
        prestadores_list = carregar_prestadores()
        prestador_data = next((p for p in prestadores_list if p.get('usuario', '').lower() == session['prestador']), None)
        if prestador_data and prestador_data.get('arquivo_os'):
            source_file_path = os.path.join(MENSAGENS_PRESTADOR_DIR, prestador_data['arquivo_os'])
            if os.path.exists(source_file_path):
                try:
                    with open(source_file_path, 'r', encoding='utf-8') as f:
                        all_prestador_os_raw = json.load(f)
                    os_data_to_finalize = next((item for item in all_prestador_os_raw if str(item.get('os') or item.get('OS', '')) == str(os_numero)), None)
                    if os_data_to_finalize: # Adicionar data_entrada e dias_abertos se não existirem (para validação)
                        os_data_to_finalize['data_entrada'] = os_data_to_finalize.get('data_entrada') or os_data_to_finalize.get('data') or os_data_to_finalize.get('Data','')
                except Exception as e:
                    logger.error(f"Erro ao ler arquivo OS do prestador {source_file_path} para finalizar OS: {e}")
    elif 'manutencao' in session:
        manutencao_users = carregar_manutencao()
        manutencao_user = next((p for p in manutencao_users if p.get('usuario', '').lower() == session['manutencao']), None)
        if manutencao_user and manutencao_user.get('arquivo_os'):
            source_file_path = os.path.join(JSON_DIR, manutencao_user['arquivo_os'])
            if os.path.exists(source_file_path):
                try:
                    with open(source_file_path, 'r', encoding='utf-8') as f:
                        all_manutencao_os_raw = json.load(f)
                    os_data_to_finalize = next((item for item in all_manutencao_os_raw if str(item.get('os') or item.get('OS', '')) == str(os_numero)), None)
                    # data_entrada já deve estar presente devido ao carregar_os_manutencao
                except Exception as e:
                    logger.error(f"Erro ao ler arquivo OS de manutenção {source_file_path} para finalizar OS: {e}")
    
    if not os_data_to_finalize and request.method == 'POST': # Se não achou a OS para pegar data de abertura, mas é POST
        flash(f'OS {os_numero} não encontrada nos arquivos para obter data de abertura. Finalização prossegue sem essa validação.', 'warning')
        # Permite continuar, mas a validação de data de abertura será pulada

    if request.method == 'GET': # GET request ainda renderiza o modal/formulário no painel apropriado
        # A lógica de GET foi removida daqui pois o modal é parte do painel principal.
        # Se houver um template GET dedicado para finalizar_os, ele precisaria ser ajustado.
        # Por ora, o POST vem direto do modal no painel.
        flash('Ação GET para finalizar_os não é suportada diretamente. Use o formulário no painel.', 'info')
        if 'prestador' in session: return redirect(url_for('painel_prestador'))
        if 'manutencao' in session: return redirect(url_for('painel_manutencao'))
        if 'gerente' in session: return redirect(url_for('painel'))
        return redirect(url_for('login'))


    if request.method == 'POST':
        data_fin_str = request.form.get('data_finalizacao')
        hora_fin = request.form.get('hora_finalizacao')
        observacoes = request.form.get('observacoes', '')
        evidencia_file = request.files.get('evidencia') # Opcional

        if not data_fin_str or not hora_fin:
            flash('Data e hora de finalização são obrigatórias.', 'danger')
            # Redirecionar de volta para o painel onde o modal está
            if 'prestador' in session: return redirect(url_for('painel_prestador'))
            if 'manutencao' in session: return redirect(url_for('painel_manutencao'))
            if 'gerente' in session: return redirect(url_for('painel'))
            return redirect(url_for('login'))

        data_abertura_str = None
        if os_data_to_finalize: # Se a OS foi encontrada
            data_abertura_str = os_data_to_finalize.get('data_entrada') or os_data_to_finalize.get('data') # 'data' para gerente

        data_abertura_obj = None
        if data_abertura_str:
            for fmt in ("%d/%m/%Y", "%Y-%m-%d", "%d-%m-%y"):
                try:
                    data_abertura_obj = datetime.strptime(data_abertura_str, fmt).date()
                    break
                except (ValueError, TypeError):
                    continue
        
        data_fin_obj = None
        data_fin_formatted = ""
        # O input date HTML envia YYYY-MM-DD
        try:
            data_fin_obj = datetime.strptime(data_fin_str, '%Y-%m-%d').date()
            data_fin_formatted = data_fin_obj.strftime('%d/%m/%Y') # Salvar sempre como DD/MM/YYYY
        except ValueError:
            flash('Formato de data de finalização inválido. Use o calendário.', 'danger')
            if 'prestador' in session: return redirect(url_for('painel_prestador'))
            if 'manutencao' in session: return redirect(url_for('painel_manutencao'))
            if 'gerente' in session: return redirect(url_for('painel'))
            return redirect(url_for('login'))

        if data_abertura_obj and data_fin_obj < data_abertura_obj:
            flash(f'A data de finalização ({data_fin_formatted}) não pode ser anterior à data de abertura da OS ({data_abertura_obj.strftime("%d/%m/%Y")}).', 'danger')
            if 'prestador' in session: return redirect(url_for('painel_prestador'))
            if 'manutencao' in session: return redirect(url_for('painel_manutencao'))
            if 'gerente' in session: return redirect(url_for('painel'))
            return redirect(url_for('login'))
        
        # Lógica para salvar evidência (exemplo simples)
        evidencia_filename = None
        if evidencia_file and allowed_file(evidencia_file.filename):
            evidencia_filename = secure_filename(f"ev_{os_numero}_{responsavel}_{datetime.now().strftime('%Y%m%d%H%M%S')}.{evidencia_file.filename.rsplit('.',1)[1].lower()}")
            try:
                evidencia_path = os.path.join(app.config['UPLOAD_FOLDER'], 'evidencias') # Subpasta para evidencias
                os.makedirs(evidencia_path, exist_ok=True)
                evidencia_file.save(os.path.join(evidencia_path, evidencia_filename))
                logger.info(f"Evidência {evidencia_filename} salva para OS {os_numero}.")
            except Exception as e:
                logger.error(f"Erro ao salvar evidência {evidencia_filename}: {e}")
                flash("Erro ao salvar arquivo de evidência.", "warning")
                evidencia_filename = None # Não salvar referência se falhou

        fz = Finalizacao(
            os_numero=str(os_numero),
            gerente=responsavel, # Aqui 'gerente' é quem finalizou, pode ser prestador, gerente ou manutenção
            data_fin=data_fin_formatted,
            hora_fin=hora_fin,
            observacoes=observacoes,
            registrado_em=saopaulo_tz.localize(datetime.now())
            # evidencia_path=f"uploads/evidencias/{evidencia_filename}" if evidencia_filename else None # Adicionar ao modelo se necessário
        )
        db.session.add(fz)
        try:
            db.session.commit()
            logger.info(f"OS {os_numero} finalizada por {responsavel} e registrada no banco.")
        except Exception as e:
            db.session.rollback()
            logger.error(f"Erro ao salvar finalização da OS {os_numero} no banco: {e}")
            flash('Erro ao registrar finalização da OS. Verifique os logs.', 'danger')
            if 'prestador' in session: return redirect(url_for('painel_prestador'))
            if 'manutencao' in session: return redirect(url_for('painel_manutencao'))
            if 'gerente' in session: return redirect(url_for('painel'))
            return redirect(url_for('login'))

        # Remover OS dos arquivos JSON relevantes
        removido_de_arquivos = []
        if 'gerente' in session:
            # Para gerente, a OS pode estar em qualquer arquivo no MENSAGENS_DIR
            removidos_gerente = remover_os_de_todos_json(MENSAGENS_DIR, str(os_numero))
            if removidos_gerente: removido_de_arquivos.extend(removidos_gerente)
        
        if source_file_path and os.path.exists(source_file_path): # Se o arquivo de origem é conhecido (prestador/manutenção)
            removidos_source = remover_os_de_todos_json(os.path.dirname(source_file_path), str(os_numero)) # Passa o diretório do arquivo
            # A função remover_os_de_todos_json varre o diretório, então pode remover de outros arquivos se o OS for igual.
            # Idealmente, seria mais preciso e removeria apenas do source_file_path.
            # Para uma remoção precisa de um único arquivo:
            # try:
            #     with open(source_file_path, 'r', encoding='utf-8') as f: data = json.load(f)
            #     original_len = len(data)
            #     data = [item for item in data if str(item.get('os') or item.get('OS', '')) != str(os_numero)]
            #     if len(data) < original_len:
            #         with open(source_file_path, 'w', encoding='utf-8') as f: json.dump(data, f, ensure_ascii=False, indent=2)
            #         removido_de_arquivos.append(os.path.basename(source_file_path))
            #         logger.info(f"OS {os_numero} removida do arquivo específico: {source_file_path}")
            # except Exception as e: logger.error(f"Erro ao tentar remover OS {os_numero} do arquivo {source_file_path}: {e}")
            if removidos_source: removido_de_arquivos.extend(removidos_source)


        if removido_de_arquivos:
            flash(f'OS {os_numero} removida dos arquivos: {", ".join(list(set(removido_de_arquivos)))}', 'info')
        else:
            # Se source_file_path era esperado mas não houve remoção, pode ser que já tinha sido removida ou OS não encontrada no JSON
            if source_file_path:
                 logger.warning(f"OS {os_numero} não encontrada para remoção no arquivo {source_file_path} ou já removida.")
            # Não emitir warning se for gerente e não encontrar, pois varre muitos arquivos.

        flash(f'OS {os_numero} finalizada e registrada com sucesso!', 'success')
        
        if 'prestador' in session: return redirect(url_for('painel_prestador'))
        if 'manutencao' in session: return redirect(url_for('painel_manutencao'))
        if 'gerente' in session: return redirect(url_for('painel'))
        return redirect(url_for('login'))


@app.route('/atribuir_prestador/<os_numero>', methods=['POST'])
def atribuir_prestador(os_numero):
    if 'manutencao' not in session: # Apenas manutenção pode atribuir por esta rota
        flash('Acesso negado. Apenas usuários de manutenção podem atribuir prestadores.', 'danger')
        return redirect(url_for('login'))
    
    responsavel_manutencao = session['manutencao'] # Quem está fazendo a atribuição

    prestador_usuario_atribuido = request.form.get('prestador_usuario', '').strip() # Username do prestador a quem a OS será atribuída
    if not prestador_usuario_atribuido:
        flash('O nome de usuário do prestador não pode estar vazio.', 'danger')
        return redirect(url_for('painel_manutencao'))

    # 1. Encontrar a OS na lista de OS sem prestador (que vem de MENSAGENS_DIR)
    os_sem_prestador_list = carregar_os_sem_prestador()
    os_target_data = next((os_item for os_item in os_sem_prestador_list if str(os_item.get('os')) == str(os_numero)), None)

    if not os_target_data:
        flash(f'OS {os_numero} não encontrada na lista de "OS sem prestador" ou já pode ter um prestador.', 'warning')
        return redirect(url_for('painel_manutencao'))

    # 2. Encontrar os dados do prestador a quem a OS será atribuída (de PRESTADORES_FILE)
    prestadores_list = carregar_prestadores()
    prestador_info = next((p for p in prestadores_list if p.get('usuario', '').lower() == prestador_usuario_atribuido.lower()), None)

    if not prestador_info or not prestador_info.get('arquivo_os'):
        flash(f'Prestador "{prestador_usuario_atribuido}" não encontrado ou não possui arquivo de OS configurado.', 'danger')
        return redirect(url_for('painel_manutencao'))
    
    arquivo_os_prestador_destino = prestador_info['arquivo_os']
    caminho_destino_prestador = os.path.join(MENSAGENS_PRESTADOR_DIR, arquivo_os_prestador_destino)

    # 3. Construir o objeto OS para adicionar ao arquivo do prestador
    # Usar os dados de os_target_data
    os_para_adicionar = {
        "os": os_target_data.get('os'),
        "frota": os_target_data.get('frota'),
        "data": os_target_data.get('data_entrada'), # Usar 'data_entrada' que já foi processada
        "Data": os_target_data.get('data_entrada'), # Adicionar ambos por segurança se o prestador usar 'Data'
        "modelo": os_target_data.get('modelo'),
        "servico": os_target_data.get('servico'),
        "observacao": f"Atribuída por {responsavel_manutencao} em {datetime.now(saopaulo_tz).strftime('%d/%m/%Y %H:%M')}. Detalhes originais: {os_target_data.get('servico','')}",
        # Outros campos que o arquivo do prestador possa esperar
    }

    # 4. Adicionar a OS ao arquivo JSON do prestador de destino
    try:
        os_list_prestador_destino = []
        if os.path.exists(caminho_destino_prestador):
            with open(caminho_destino_prestador, 'r', encoding='utf-8') as f:
                os_list_prestador_destino = json.load(f)
        
        # Verificar se a OS já existe no arquivo do prestador para não duplicar
        if any(str(item.get('os') or item.get('OS','')) == str(os_numero) for item in os_list_prestador_destino):
            flash(f'OS {os_numero} já consta no arquivo do prestador {prestador_usuario_atribuido}.', 'info')
        else:
            os_list_prestador_destino.append(os_para_adicionar)
            with open(caminho_destino_prestador, 'w', encoding='utf-8') as f:
                json.dump(os_list_prestador_destino, f, ensure_ascii=False, indent=2)
            logger.info(f"OS {os_numero} atribuída a {prestador_usuario_atribuido} e adicionada a {arquivo_os_prestador_destino} por {responsavel_manutencao}.")
            flash(f'OS {os_numero} atribuída a {prestador_info.get("nome_exibicao", prestador_usuario_atribuido)} com sucesso!', 'success')
            
            # 5. Remover a OS do arquivo original do gerente (MENSAGENS_DIR)
            caminho_origem_gerente = os.path.join(MENSAGENS_DIR, os_target_data['arquivo_origem'])
            removido_origem = remover_os_de_todos_json(MENSAGENS_DIR, str(os_numero)) # A função varre o diretório
            if removido_origem:
                 logger.info(f"OS {os_numero} removida de {', '.join(removido_origem)} após atribuição a prestador.")
            else:
                 logger.warning(f"OS {os_numero} não encontrada para remoção no diretório {MENSAGENS_DIR} após atribuição.")


    except Exception as e:
        logger.error(f"Erro ao atribuir OS {os_numero} para {prestador_usuario_atribuido}: {e}")
        flash(f'Erro ao tentar atribuir a OS {os_numero}. Detalhes: {e}', 'danger')
    
    return redirect(url_for('painel_manutencao'))


@app.route('/admin')
def admin_panel():
    if not session.get('is_admin'):
        flash('Acesso negado', 'danger')
        return redirect(url_for('login'))

    periodo = request.args.get('periodo', 'todos')
    data_inicio_str = request.args.get('data_inicio')
    data_fim_str = request.args.get('data_fim')

    query_finalizadas = Finalizacao.query.order_by(Finalizacao.registrado_em.desc())
    
    inicio, fim = None, None # Para usar no filtro de login_events também
    if data_inicio_str and data_fim_str:
        try:
            inicio = saopaulo_tz.localize(parse(data_inicio_str).replace(hour=0, minute=0, second=0, microsecond=0))
            fim = saopaulo_tz.localize(parse(data_fim_str).replace(hour=23, minute=59, second=59, microsecond=999999))
            query_finalizadas = query_finalizadas.filter(Finalizacao.registrado_em.between(inicio, fim))
        except ValueError:
            flash('Datas inválidas para filtro de OS Finalizadas. Usando todas as OS.', 'warning')
            inicio, fim = None, None # Resetar se inválido
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
            next_month_start = (inicio.replace(day=28) + timedelta(days=4)).replace(day=1) # Início do próximo mês
            fim = (next_month_start - timedelta(microseconds=1)) # Fim do mês atual
        elif periodo == 'anual':
            inicio = hoje_tz.replace(month=1, day=1, hour=0, minute=0, second=0, microsecond=0)
            fim = hoje_tz.replace(month=12, day=31, hour=23, minute=59, second=59, microsecond=999999)
        
        if inicio and fim: # Somente aplicar filtro se 'inicio' e 'fim' foram definidos
            query_finalizadas = query_finalizadas.filter(Finalizacao.registrado_em.between(inicio, fim))
        else: # Se periodo for inválido ou não resultar em 'inicio'/'fim', não filtra por data
            inicio, fim = None, None 


    total_os_finalizadas = query_finalizadas.count()
    finalizadas_list_display = query_finalizadas.limit(100).all() 
    
    login_events_query = LoginEvent.query.order_by(LoginEvent.login_time.desc())
    if inicio and fim: # Reusa o mesmo período do filtro de OS Finalizadas, se definido
         login_events_query = login_events_query.filter(LoginEvent.login_time.between(inicio, fim))
    
    login_events_list = login_events_query.limit(50).all()

    for event in login_events_list:
        event.login_time_formatted = format_datetime(event.login_time)
        event.logout_time_formatted = format_datetime(event.logout_time) if event.logout_time else "Em atividade"
        if event.logout_time and event.login_time:
            login_t = event.login_time.astimezone(saopaulo_tz) if event.login_time.tzinfo else saopaulo_tz.localize(event.login_time)
            logout_t = event.logout_time.astimezone(saopaulo_tz) if event.logout_time.tzinfo else saopaulo_tz.localize(event.logout_time)
            duration = (logout_t - login_t).total_seconds()
            event.duration_secs = int(max(0, duration))
        elif event.duration_secs is None : 
            event.duration_secs = 0 # Para eventos ainda ativos ou sem logout


    all_users_db = User.query.order_by(User.username).all()
    gerentes_usernames_db = [u.username for u in all_users_db] 

    contagem_finalizadas_gerentes_db = {}
    base_query_contagem = Finalizacao.query
    if inicio and fim: # Aplicar filtro de data à contagem se as datas estiverem definidas
        base_query_contagem = base_query_contagem.filter(Finalizacao.registrado_em.between(inicio, fim))
    
    for g_user in gerentes_usernames_db:
        contagem_finalizadas_gerentes_db[g_user] = base_query_contagem.filter(Finalizacao.gerente == g_user).count()

    abertas_gerentes_json = {g_user: len(carregar_os_gerente(g_user)) for g_user in gerentes_usernames_db}
    ranking_os_abertas_gerentes = sorted(abertas_gerentes_json.items(), key=lambda x: x[1], reverse=True)
    
    ranking_os_prestadores_abertas = carregar_os_prestadores() 

    chart_data_finalizadas_por_periodo = Counter()
    chart_data_finalizadas_por_responsavel = Counter()

    # Para o gráfico, usamos todas as OS finalizadas no período, não apenas o limite de 100
    all_finalizadas_no_periodo = query_finalizadas.all() 

    for f_item in all_finalizadas_no_periodo:
        try:
            data_finalizacao_obj = datetime.strptime(f_item.data_fin, "%d/%m/%Y")
            if periodo == 'anual': periodo_key = data_finalizacao_obj.strftime('%Y-%m')
            elif periodo == 'mensal': periodo_key = data_finalizacao_obj.strftime('%d') # Dia do mês
            elif periodo == 'semanal': periodo_key = data_finalizacao_obj.strftime('%a') # Dia da semana
            elif periodo == 'diario': periodo_key = f_item.registrado_em.astimezone(saopaulo_tz).strftime('%H:00') if f_item.registrado_em else "N/A" # Hora do dia
            else: periodo_key = data_finalizacao_obj.strftime('%d/%m/%Y') 

            chart_data_finalizadas_por_periodo[periodo_key] += 1
        except (ValueError, TypeError) as e:
            logger.warning(f"Data de finalização em formato inválido ou ausente para OS {f_item.os_numero}: {f_item.data_fin}, erro: {e}")

        chart_data_finalizadas_por_responsavel[f_item.gerente] += 1


    return render_template('admin.html',
                         finalizadas_para_tabela=finalizadas_list_display, # Lista limitada para exibição na tabela
                         total_os_finalizadas_periodo=total_os_finalizadas, 
                         gerentes_db_list=gerentes_usernames_db,
                         contagem_finalizadas_por_gerente=contagem_finalizadas_gerentes_db, 
                         os_abertas_por_gerente_map=abertas_gerentes_json, 
                         ranking_os_abertas_gerentes_list=ranking_os_abertas_gerentes,
                         ranking_os_prestadores_list=ranking_os_prestadores_abertas,
                         login_events_list=login_events_list,
                         current_time_sp=datetime.now(saopaulo_tz).strftime('%d/%m/%Y %H:%M:%S'),
                         chart_data_periodo=dict(sorted(chart_data_finalizadas_por_periodo.items())), # Ordenado para gráfico
                         chart_data_responsavel=dict(chart_data_finalizadas_por_responsavel),
                         periodo_selecionado_filtro=periodo, 
                         data_inicio_filtro_val=data_inicio_str, 
                         data_fim_filtro_val=data_fim_str, 
                         format_datetime_func=format_datetime 
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

    inicio, fim = None, None 
    if data_inicio_str and data_fim_str:
        try:
            inicio = saopaulo_tz.localize(parse(data_inicio_str).replace(hour=0, minute=0, second=0, microsecond=0))
            fim = saopaulo_tz.localize(parse(data_fim_str).replace(hour=23, minute=59, second=59, microsecond=999999))
            query = query.filter(Finalizacao.registrado_em.between(inicio, fim))
        except ValueError:
            flash('Datas inválidas. Exportando todas as OS.', 'warning')
            inicio, fim = None, None
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
            next_month_start = (inicio.replace(day=28) + timedelta(days=4)).replace(day=1)
            fim = (next_month_start - timedelta(microseconds=1))
        elif periodo == 'anual':
            inicio = hoje_tz.replace(month=1, day=1, hour=0, minute=0, second=0, microsecond=0)
            fim = hoje_tz.replace(month=12, day=31, hour=23, minute=59, second=59, microsecond=999999)
        
        if inicio and fim: 
             query = query.filter(Finalizacao.registrado_em.between(inicio, fim))
        else:
             inicio, fim = None, None


    all_finalizadas_export = query.all()
    if not all_finalizadas_export:
        flash('Nenhuma OS finalizada para o período selecionado para exportação.', 'warning')
        return redirect(url_for('admin_panel', periodo=periodo, data_inicio=data_inicio_str, data_fim=data_fim_str))

    pdf_filename = f'relatorio_os_finalizadas_{datetime.now(saopaulo_tz).strftime("%Y%m%d_%H%M%S")}.pdf'
    pdf_path = os.path.join(BASE_DIR, pdf_filename) # Salvar no diretório base temporariamente
    
    c = canvas.Canvas(pdf_path, pagesize=A4)
    width, height = A4

    titulo_periodo_pdf = periodo.capitalize()
    if data_inicio_str and data_fim_str: # Se usou range específico
        try:
            titulo_periodo_pdf = f"{parse(data_inicio_str).strftime('%d/%m/%Y')} a {parse(data_fim_str).strftime('%d/%m/%Y')}"
        except ValueError:
            titulo_periodo_pdf = "Período Personalizado (Datas Inválidas no Título)"
    elif inicio and fim: # Se usou período como 'semanal', 'mensal' que resultou em datas válidas
        titulo_periodo_pdf = f"{inicio.strftime('%d/%m/%Y')} a {fim.strftime('%d/%m/%Y')}"
    
    
    page_num = 1
    def draw_header_footer(can, page_num_text):
        can.setFont("Helvetica-Bold", 14)
        can.drawCentredString(width / 2, height - 50, f"Relatório de OS Finalizadas ({titulo_periodo_pdf})")
        can.setFont("Helvetica", 8)
        can.drawRightString(width - 40, 30, f"Página {page_num_text}")
        can.drawString(40, 30, f"Exportado em: {datetime.now(saopaulo_tz).strftime('%d/%m/%Y %H:%M:%S')}")

    draw_header_footer(c, str(page_num))
    y_pos = height - 85
    
    c.setFont("Helvetica-Bold", 9)
    col_details = [
        ('OS', 50), ('Responsável', 100), ('Data Fin.', 60), ('Hora Fin.', 50), 
        ('Observações', 180), ('Registrado Em', 110)
    ]
    current_x = 40
    for col_name, col_width_val in col_details:
        c.drawString(current_x, y_pos, col_name)
        current_x += col_width_val
    
    y_pos -= 6
    c.line(35, y_pos, width - 35, y_pos) # Linha abaixo do cabeçalho
    y_pos -= 10
    c.setFont("Helvetica", 8)

    for r_item in all_finalizadas_export:
        if y_pos < 60: # Espaço para footer e nova página
            c.showPage()
            page_num += 1
            draw_header_footer(c, str(page_num))
            y_pos = height - 85 # Reset Y para cabeçalho da tabela
            c.setFont("Helvetica-Bold", 9)
            current_x_header = 40
            for col_name_h, col_width_h in col_details:
                c.drawString(current_x_header, y_pos, col_name_h)
                current_x_header += col_width_h
            y_pos -= 6
            c.line(35, y_pos, width - 35, y_pos)
            y_pos -= 10
            c.setFont("Helvetica", 8)

        current_x = 40
        obs_text = (r_item.observacoes or '')
        # Quebra de linha manual simples para observações longas (rudimentar)
        # Uma solução melhor usaria Paragraph da ReportLab para auto-wrap.
        lines = []
        max_chars_line = 40 # Aproximado para a largura da coluna
        for i in range(0, len(obs_text), max_chars_line):
            lines.append(obs_text[i:i+max_chars_line])
        
        registrado_em_fmt = format_datetime(r_item.registrado_em) if r_item.registrado_em else "N/A"

        row_display_data = [
            str(r_item.os_numero), str(r_item.gerente), str(r_item.data_fin), str(r_item.hora_fin),
            lines[0] if lines else '', # Primeira linha da observação
            registrado_em_fmt
        ]
        
        line_height_based_on_obs = 12 + ( (len(lines) -1) * 9 if len(lines)>1 else 0)


        temp_y = y_pos
        for idx, (col_name, col_w) in enumerate(col_details):
            if col_name == 'Observações':
                obs_y_offset = 0
                for line_obs in lines:
                    c.drawString(current_x, temp_y - obs_y_offset, line_obs)
                    obs_y_offset += 9 # Espaço entre linhas da observação
            else:
                 c.drawString(current_x, temp_y, row_display_data[idx])
            current_x += col_w
        
        y_pos -= line_height_based_on_obs # Ajustar Y com base na altura da linha
            
    c.save()
    try:
        return send_file(pdf_path,
                       as_attachment=True,
                       download_name=pdf_filename, # Nome do arquivo já com timestamp
                       mimetype='application/pdf')
    finally:
        if os.path.exists(pdf_path):
            # os.remove(pdf_path) # Remover o arquivo do servidor após o envio se não for mais necessário
            logger.info(f"Arquivo PDF {pdf_path} gerado e enviado. Considere remover se não for mais necessário no servidor.")


@app.route('/logout')
def logout():
    ev_id = session.pop('login_event_id', None)
    username_logged_out = session.get('gerente') or session.get('prestador') or session.get('manutencao') 
    user_type_logged_out = None # Para log mais preciso

    if ev_id:
        ev = LoginEvent.query.get(ev_id)
        if ev:
            user_type_logged_out = ev.user_type # Pega o tipo antes de commitar
            logout_time_now = saopaulo_tz.localize(datetime.now())
            
            login_time_for_calc = ev.login_time
            if login_time_for_calc.tzinfo is None: # Se for naive, localizar
                login_time_for_calc = saopaulo_tz.localize(login_time_for_calc)
            else: # Se tiver timezone, converter para SP
                login_time_for_calc = login_time_for_calc.astimezone(saopaulo_tz)
            
            ev.logout_time = logout_time_now
            duration_seconds = (logout_time_now - login_time_for_calc).total_seconds()
            ev.duration_secs = int(max(0, duration_seconds))
            
            logger.info(f"Logout de {ev.username} (tipo: {user_type_logged_out}): "
                        f"Login às {format_datetime(login_time_for_calc)}, "
                        f"Logout às {format_datetime(logout_time_now)}, "
                        f"Duração: {ev.duration_secs} segundos.")
            try:
                db.session.commit()
            except Exception as e:
                db.session.rollback()
                logger.error(f"Erro ao commitar logout event para {ev.username}: {e}")
        else: # Evento de login não encontrado no BD
            logger.warning(f"Evento de login ID {ev_id} (usuário: {username_logged_out or 'Desconhecido'}) não encontrado no BD durante logout.")
    else: # Sem login_event_id na sessão
        logger.info(f"Logout de {username_logged_out or 'Usuário desconhecido'} sem login_event_id na sessão.")

    display_name = capitalize_name(username_logged_out) if username_logged_out else "Usuário"
    session.clear()
    flash(f'{display_name} desconectado(a) com sucesso.', 'info')
    return redirect(url_for('login'))

with app.app_context():
    init_db()

if __name__ == '__main__':
    app.run(host='0.0.0.0',
           port=int(os.environ.get('PORT', 10000)),
           debug=True)
