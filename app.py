
class FrotaLeve(db.Model):
    __tablename__ = 'frota_leve'
    id = db.Column(db.Integer, primary_key=True)
    placa = db.Column(db.String(20))
    veiculo = db.Column(db.String(50))
    motorista = db.Column(db.String(50))
    oficina = db.Column(db.String(50))
    servico = db.Column(db.Text)
    situacao = db.Column(db.String(20))
    entrada = db.Column(db.String(20))
    saida = db.Column(db.String(20))
    valor_mo = db.Column(db.String(20))
    valor_pecas = db.Column(db.String(20))
    aprovado_por = db.Column(db.String(50))
    cotacao1 = db.Column(db.Text)
    cotacao2 = db.Column(db.Text)
    cotacao3 = db.Column(db.Text)
    fechado_com = db.Column(db.Text)
    obs = db.Column(db.Text)
    hora_fim = db.Column(db.String(10))


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

# --- Helper para formatar datas no horário de São Paulo (AJUSTADO) ---
def format_datetime(dt_input):
    if not dt_input:
        return None
    
    dt_obj = None
    if isinstance(dt_input, datetime):
        dt_obj = dt_input
    else:
        try:
            dt_obj = parse(str(dt_input))
        except Exception as e:
            logger.warning(f"format_datetime: Não foi possível parsear '{dt_input}' para datetime. Erro: {e}")
            return str(dt_input) 

    if dt_obj.tzinfo is None:
        dt_obj = saopaulo_tz.localize(dt_obj)
    else:
        dt_obj = dt_obj.astimezone(saopaulo_tz)
    return dt_obj.strftime('%d/%m/%Y %H:%M:%S')

# --- Registra a função format_datetime para estar disponível em todos os templates ---
@app.context_processor
def utility_processor():
    return dict(format_datetime=format_datetime)

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

def init_db():
    with app.app_context(): # Garante contexto de aplicação para operações de BD
        db.create_all()
        try:
            from sqlalchemy import inspect
            inspector = inspect(db.engine)
            columns_login_events = [col['name'] for col in inspector.get_columns('login_events')]
            if 'user_type' not in columns_login_events:
                logger.info("Adicionando coluna user_type à tabela login_events")
                db.session.execute(text('ALTER TABLE login_events ADD COLUMN user_type VARCHAR(20) DEFAULT "gerente" NOT NULL'))
                db.session.commit()
                logger.info("Coluna user_type adicionada com sucesso")
            
            columns_users = [col['name'] for col in inspector.get_columns('users')]
            if 'profile_picture' not in columns_users:
                logger.info("Adicionando coluna profile_picture à tabela users")
                db.session.execute(text('ALTER TABLE users ADD COLUMN profile_picture VARCHAR(256)'))
                db.session.commit()
                logger.info("Coluna profile_picture adicionada com sucesso")
        except Exception as e:
            logger.error(f"Erro ao verificar/adicionar colunas: {e}")
            db.session.rollback()

        if User.query.count() == 0 and os.path.exists(USERS_FILE):
            with open(USERS_FILE, encoding='utf-8') as f:
                js_users = json.load(f)
            admins = {'wilson.santana'} 
            for u_name, u_data in js_users.items():
                senha_val = u_data.get("senha", "") if isinstance(u_data, dict) else u_data
                pic_val = u_data.get("profile_picture") if isinstance(u_data, dict) else None
                db.session.add(User(
                    username=u_name.lower(),
                    password=senha_val, 
                    is_admin=(u_name.lower() in admins),
                    profile_picture=pic_val
                ))
            db.session.commit()

# ... (Suas funções de carregamento de dados como carregar_os_gerente, carregar_prestadores, etc.)
def carregar_os_gerente(gerente_username):
    base_nome_gerente = gerente_username.upper().replace('.', '_')
    caminho_encontrado = None
    for sufixo_arquivo in ("", "_GONZAGA"):
        nome_arquivo_json = f"{base_nome_gerente}{sufixo_arquivo}.json"
        caminho_possivel = os.path.join(MENSAGENS_DIR, nome_arquivo_json)
        if os.path.exists(caminho_possivel):
            caminho_encontrado = caminho_possivel
            break
    if not caminho_encontrado: 
        for nome_arquivo_dir in os.listdir(MENSAGENS_DIR):
            if nome_arquivo_dir.upper().startswith(base_nome_gerente + "_") and nome_arquivo_dir.lower().endswith(".json"):
                caminho_encontrado = os.path.join(MENSAGENS_DIR, nome_arquivo_dir)
                break
    if not caminho_encontrado: return []
    
    try:
        with open(caminho_encontrado, encoding="utf-8") as f:
            dados_json = json.load(f)
    except Exception as e:
        logger.error(f"Erro ao carregar/decodificar JSON {caminho_encontrado} para {gerente_username}: {e}")
        return []

    lista_resultado_os = []
    data_hoje = saopaulo_tz.localize(datetime.now()).date()
    for os_item in dados_json:
        data_os_str = os_item.get("data") or os_item.get("Data") or ""
        data_abertura_os = None
        for fmt_data in ("%d/%m/%Y", "%Y-%m-%d", "%d-%m-%Y", "%d/%m/%y", "%Y/%m/%d"):
            try:
                data_abertura_os = datetime.strptime(data_os_str, fmt_data).date()
                break
            except (ValueError, TypeError): continue
        
        dias_em_aberto = (data_hoje - data_abertura_os).days if data_abertura_os else 0
        
        lista_resultado_os.append({
            "os": str(os_item.get("os") or os_item.get("OS", "")),
            "frota": str(os_item.get("frota") or os_item.get("Frota", "")),
            "data": data_os_str, 
            "dias": str(dias_em_aberto), 
            "prestador": str(os_item.get("prestador") or os_item.get("Prestador", "Prestador não definido")),
            "servico": str(os_item.get("servico") or os_item.get("Servico") or os_item.get("observacao") or os_item.get("Observacao", ""))
        })
    return lista_resultado_os

def carregar_prestadores():
    if not os.path.exists(PRESTADORES_FILE):
        logger.warning(f"Arquivo {PRESTADORES_FILE} não encontrado. Criando arquivo vazio.")
        os.makedirs(os.path.dirname(PRESTADORES_FILE), exist_ok=True)
        with open(PRESTADORES_FILE, 'w', encoding='utf-8') as f:
            json.dump([], f, ensure_ascii=False, indent=2)
        return []
    try:
        with open(PRESTADORES_FILE, "r", encoding="utf-8") as f:
            lista_prestadores = json.load(f)
        nomes_usuarios = [p.get('usuario', '').lower() for p in lista_prestadores if p.get('usuario')]
        if Counter(nomes_usuarios).most_common(1) and Counter(nomes_usuarios).most_common(1)[0][1] > 1:
            logger.warning(f"Usuários duplicados em {PRESTADORES_FILE}: {Counter(nomes_usuarios)}")
        return lista_prestadores
    except Exception as e:
        logger.error(f"Erro ao carregar {PRESTADORES_FILE}: {e}")
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
            lista_manutencao = json.load(f)
        nomes_usuarios_manut = [p.get('usuario', '').lower() for p in lista_manutencao if p.get('usuario')]
        if Counter(nomes_usuarios_manut).most_common(1) and Counter(nomes_usuarios_manut).most_common(1)[0][1] > 1:
            logger.warning(f"Usuários duplicados em {MANUTENCAO_FILE}: {Counter(nomes_usuarios_manut)}")
        return lista_manutencao
    except Exception as e:
        logger.error(f"Erro ao carregar {MANUTENCAO_FILE}: {e}")
        return []

def carregar_os_prestadores(): 
    lista_prestadores = carregar_prestadores()
    mapa_os_por_prestador = {}
    for dados_prestador in lista_prestadores:
        username_prestador = dados_prestador.get('usuario', '').lower()
        if not username_prestador or dados_prestador.get('tipo') == 'manutencao': continue
        
        nome_arquivo_os = dados_prestador.get('arquivo_os', '')
        if not nome_arquivo_os:
            mapa_os_por_prestador[username_prestador] = 0
            continue

        caminho_arquivo_os = os.path.join(MENSAGENS_PRESTADOR_DIR, nome_arquivo_os)
        if not os.path.exists(caminho_arquivo_os):
            mapa_os_por_prestador[username_prestador] = 0
            continue
        try:
            with open(caminho_arquivo_os, 'r', encoding='utf-8') as f_json:
                lista_os_prestador = json.load(f_json)
            mapa_os_por_prestador[username_prestador] = len(lista_os_prestador)
        except Exception as e:
            logger.error(f"Erro ao carregar OS para {username_prestador} de {caminho_arquivo_os}: {e}")
            mapa_os_por_prestador[username_prestador] = 0
            
    return sorted(mapa_os_por_prestador.items(), key=lambda item_mapa: item_mapa[1], reverse=True)

def carregar_os_manutencao(username_manut):
    usuarios_manutencao = carregar_manutencao()
    dados_usuario_manut = next((p for p in usuarios_manutencao if p.get('usuario', '').lower() == username_manut.lower()), None)
    if not dados_usuario_manut: return []
    
    nome_arquivo_os_manut = dados_usuario_manut.get('arquivo_os')
    if not nome_arquivo_os_manut: return []

    caminho_os_manut = os.path.join(JSON_DIR, nome_arquivo_os_manut)
    if not os.path.exists(caminho_os_manut): return []
    
    try:
        with open(caminho_os_manut, 'r', encoding='utf-8') as f_json_manut:
            lista_os_manut = json.load(f_json_manut)
    except Exception as e:
        logger.error(f"Erro ao carregar OS de manutenção de {caminho_os_manut}: {e}")
        return []

    data_hoje_manut = saopaulo_tz.localize(datetime.now()).date()
    for os_item_manut in lista_os_manut:
        os_item_manut['modelo'] = str(os_item_manut.get('modelo', 'Desconhecido') or 'Desconhecido')
        data_entrada_os_str = os_item_manut.get('data_entrada') or os_item_manut.get('data') or os_item_manut.get('Data','') 
        os_item_manut['data_entrada'] = data_entrada_os_str 
        
        data_abertura_os_manut = None
        if data_entrada_os_str:
            for fmt_dt_manut in ("%d/%m/%Y", "%Y-%m-%d", "%d-%m-%y", "%Y/%m/%d"):
                try:
                    data_abertura_os_manut = datetime.strptime(data_entrada_os_str, fmt_dt_manut).date()
                    break
                except (ValueError, TypeError): continue
        os_item_manut['dias_abertos'] = (data_hoje_manut - data_abertura_os_manut).days if data_abertura_os_manut else 0
    return lista_os_manut

def carregar_os_sem_prestador():
    lista_os_sem_p = []
    data_hoje_sem_p = saopaulo_tz.localize(datetime.now()).date()
    for nome_arquivo_json_gerente in os.listdir(MENSAGENS_DIR):
        if nome_arquivo_json_gerente.lower().endswith('.json'):
            caminho_arq_gerente = os.path.join(MENSAGENS_DIR, nome_arquivo_json_gerente)
            try:
                with open(caminho_arq_gerente, 'r', encoding='utf-8') as f_gerente:
                    dados_os_gerente = json.load(f_gerente)
                for os_item_g in dados_os_gerente:
                    nome_prestador = str(os_item_g.get('prestador') or os_item_g.get('Prestador', '')).lower().strip()
                    if nome_prestador in ('nan', '', 'none', 'não definido', 'prestador não definido'):
                        data_os_g_str = str(os_item_g.get('data') or os_item_g.get('Data', ''))
                        data_abertura_os_g = None
                        if data_os_g_str:
                            for fmt_g in ("%d/%m/%Y", "%Y-%m-%d", "%d-%m-%y", "%Y/%m/%d"):
                                try:
                                    data_abertura_os_g = datetime.strptime(data_os_g_str, fmt_g).date()
                                    break
                                except (ValueError,TypeError): continue
                        
                        dias_abertos_g = (data_hoje_sem_p - data_abertura_os_g).days if data_abertura_os_g else 0
                        lista_os_sem_p.append({
                            'os': str(os_item_g.get('os') or os_item_g.get('OS', '')),
                            'frota': str(os_item_g.get('frota') or os_item_g.get('Frota', '')),
                            'data_entrada': data_os_g_str, 
                            'modelo': str(os_item_g.get('modelo') or os_item_g.get('Modelo', 'Desconhecido') or 'Desconhecido'),
                            'servico': str(os_item_g.get('servico') or os_item_g.get('Servico') or os_item_g.get('observacao') or os_item_g.get('Observacao', '')),
                            'arquivo_origem': nome_arquivo_json_gerente,
                            'dias_abertos': dias_abertos_g
                        })
            except Exception as e:
                logger.error(f"Erro ao carregar OS sem prestador de {caminho_arq_gerente}: {e}")
    return lista_os_sem_p

# --- Rotas ---
@app.route('/')
def index():
    return redirect(url_for('login'))

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username_form = request.form.get('username', '').strip().lower()
        senha_form = request.form.get('senha', '').strip()
        
        user_db = User.query.filter_by(username=username_form).first()
        if user_db and user_db.password == senha_form: 
            login_time_now = saopaulo_tz.localize(datetime.now())
            login_event = LoginEvent(username=username_form, user_type='gerente', login_time=login_time_now)
            db.session.add(login_event)
            db.session.commit()
            session['login_event_id'] = login_event.id
            session['gerente'] = username_form
            session['is_admin'] = user_db.is_admin
            logger.info(f"Login (gerente): {username_form} às {format_datetime(login_time_now)}")
            return redirect(url_for('admin_panel' if user_db.is_admin else 'painel'))

        usuarios_manutencao = carregar_manutencao()
        user_manut = next((u for u in usuarios_manutencao if u.get('usuario','').lower() == username_form and u.get('senha','') == senha_form), None)
        if user_manut:
            login_time_now = saopaulo_tz.localize(datetime.now())
            login_event = LoginEvent(username=username_form, user_type='manutencao', login_time=login_time_now)
            db.session.add(login_event)
            db.session.commit()
            session['login_event_id'] = login_event.id
            session['manutencao'] = username_form
            session['manutencao_nome'] = user_manut.get('nome_exibicao', username_form.capitalize())
            logger.info(f"Login (manutenção): {username_form} às {format_datetime(login_time_now)}")
            return redirect(url_for('painel_manutencao'))

        lista_prestadores = carregar_prestadores()
        user_prestador = next((p for p in lista_prestadores if p.get('usuario','').lower() == username_form and p.get('senha','') == senha_form), None)
        if user_prestador:
            login_time_now = saopaulo_tz.localize(datetime.now())
            tipo_prestador = user_prestador.get('tipo', 'prestador')
            login_event = LoginEvent(username=username_form, user_type=tipo_prestador, login_time=login_time_now)
            db.session.add(login_event)
            db.session.commit()
            session['login_event_id'] = login_event.id
            session['prestador'] = username_form
            session['prestador_nome'] = user_prestador.get('nome_exibicao', username_form.capitalize())
            logger.info(f"Login (prestador tipo {tipo_prestador}): {username_form} às {format_datetime(login_time_now)}")
            return redirect(url_for('painel_prestador'))

        flash('Usuário ou senha incorreta.', 'danger')
        logger.warning(f"Falha no login para {username_form}: Credenciais inválidas.")
    return render_template('login.html', now=datetime.now(saopaulo_tz))

@app.route('/painel')
def painel():
    if 'gerente' not in session: return redirect(url_for('login'))
    
    os_pendentes_gerente = carregar_os_gerente(session['gerente'])
    finalizadas_gerente = Finalizacao.query.filter_by(gerente=session['gerente']).order_by(Finalizacao.registrado_em.desc()).limit(100).all()
    user_atual = User.query.filter_by(username=session['gerente']).first()
    caminho_foto_perfil = url_for('static', filename=user_atual.profile_picture) if user_atual and user_atual.profile_picture else None
    
    return render_template('painel.html',
                         os_pendentes=os_pendentes_gerente,
                         finalizadas=finalizadas_gerente,
                         gerente=session['gerente'],
                         profile_picture=caminho_foto_perfil,
                         now=datetime.now(saopaulo_tz), 
                         today_date=datetime.now(saopaulo_tz).strftime('%Y-%m-%d'))

@app.route('/upload_profile_picture', methods=['POST'])
def upload_profile_picture():
    username_responsavel = session.get('gerente') or session.get('manutencao')
    if not username_responsavel:
        flash('Acesso negado.', 'danger')
        return redirect(url_for('login'))

    user_db_entry = User.query.filter_by(username=username_responsavel.lower()).first()
    if not user_db_entry: 
        flash('Usuário não encontrado no banco para associar foto.', 'warning')
        # Determina para qual painel redirecionar com base na sessão
        redirect_target = 'login'
        if 'manutencao' in session: redirect_target = 'painel_manutencao'
        elif 'gerente' in session: redirect_target = 'painel'
        return redirect(url_for(redirect_target))


    if 'profile_picture' not in request.files or not request.files['profile_picture'].filename:
        flash('Nenhuma foto selecionada.', 'danger')
    else:
        foto = request.files['profile_picture']
        if allowed_file(foto.filename):
            nome_seguro_foto = secure_filename(f"{user_db_entry.username}_{datetime.now().strftime('%Y%m%d%H%M%S')}.{foto.filename.rsplit('.', 1)[1].lower()}")
            caminho_salvar_foto = os.path.join(app.config['UPLOAD_FOLDER'], nome_seguro_foto)
            try:
                img = Image.open(foto.stream)
                img.thumbnail((100, 100)) 
                img.save(caminho_salvar_foto)
                
                user_db_entry.profile_picture = f"uploads/{nome_seguro_foto}"
                db.session.commit()
                flash('Foto de perfil atualizada!', 'success')
            except Exception as e:
                logger.error(f"Erro ao processar/salvar foto: {e}")
                flash('Erro ao processar a foto.', 'danger')
        else:
            flash(f'Formato de arquivo não permitido. Use: {", ".join(ALLOWED_EXTENSIONS)}.', 'danger')

    # Determina para qual painel redirecionar com base na sessão
    redirect_target = 'login'
    if 'manutencao' in session: redirect_target = 'painel_manutencao'
    elif 'gerente' in session: redirect_target = 'painel'
    return redirect(url_for(redirect_target))


@app.route('/painel_prestador')
def painel_prestador():
    if 'prestador' not in session: return redirect(url_for('login'))
    
    dados_prestador_atual = next((p for p in carregar_prestadores() if p.get('usuario', '').lower() == session['prestador']), None)
    if not dados_prestador_atual:
        flash('Prestador não encontrado.', 'danger')
        return redirect(url_for('login'))
    
    nome_arquivo_os_prest = dados_prestador_atual.get('arquivo_os')
    lista_os_do_prestador = []
    if not nome_arquivo_os_prest:
        flash(f"Arquivo de OS não configurado para {session['prestador']}.", 'warning')
    else:
        caminho_arq_os_prest = os.path.join(MENSAGENS_PRESTADOR_DIR, nome_arquivo_os_prest)
        if not os.path.exists(caminho_arq_os_prest):
            logger.warning(f"Arquivo OS {caminho_arq_os_prest} não encontrado.")
        else:
            try:
                with open(caminho_arq_os_prest, 'r', encoding='utf-8') as f_os_prest:
                    os_list_raw_prest = json.load(f_os_prest)
                data_hoje_prest = saopaulo_tz.localize(datetime.now()).date()
                for os_item_raw_prest in os_list_raw_prest:
                    item_proc_prest = dict(os_item_raw_prest) # Cria cópia
                    data_os_str_prest = item_proc_prest.get('data_entrada') or item_proc_prest.get('data') or item_proc_prest.get('Data', '')
                    item_proc_prest['data_entrada'] = data_os_str_prest
                    item_proc_prest['modelo'] = str(item_proc_prest.get('modelo') or item_proc_prest.get('Modelo') or 'Desconhecido')
                    
                    dias_abertos_calc_prest = 0
                    if data_os_str_prest:
                        data_abertura_obj_prest = None
                        for fmt_prest in ("%d/%m/%Y", "%Y-%m-%d", "%d-%m-%y", "%Y/%m/%d"):
                            try:
                                data_abertura_obj_prest = datetime.strptime(data_os_str_prest, fmt_prest).date()
                                break
                            except (ValueError, TypeError): continue
                        if data_abertura_obj_prest: dias_abertos_calc_prest = (data_hoje_prest - data_abertura_obj_prest).days
                        else: logger.warning(f"Parse de data falhou para OS {item_proc_prest.get('os','?')} data: '{data_os_str_prest}'")
                    item_proc_prest['dias_abertos'] = dias_abertos_calc_prest
                    lista_os_do_prestador.append(item_proc_prest)
            except Exception as e:
                logger.error(f"Erro processando OS de {caminho_arq_os_prest}: {e}")
                flash("Erro ao carregar OS.", 'danger')

    return render_template('painel_prestador.html',
        nome=dados_prestador_atual.get('nome_exibicao', session['prestador'].capitalize()),
        os_list=lista_os_do_prestador,
        now=datetime.now(saopaulo_tz), 
        today_date=datetime.now(saopaulo_tz).strftime('%Y-%m-%d'))

@app.route('/painel_manutencao')
def painel_manutencao():
    if 'manutencao' not in session: return redirect(url_for('login'))

    dados_usuario_manut_atual = next((p for p in carregar_manutencao() if p.get('usuario','').lower() == session['manutencao']), None)
    if not dados_usuario_manut_atual:
        flash('Usuário de manutenção não encontrado.', 'danger')
        return redirect(url_for('login'))

    lista_os_manutencao = carregar_os_manutencao(session['manutencao'])
    lista_os_sem_p_manut = carregar_os_sem_prestador()
    
    ordenar_por = request.args.get('ordenar', 'data_desc')
    if lista_os_manutencao: 
        try:
            def sort_key_date(x):
                try:
                    return datetime.strptime(x['data_entrada'], '%d/%m/%Y') if x.get('data_entrada') else datetime.min.date()
                except ValueError: # Tenta outros formatos se o primeiro falhar
                    for fmt_sort in ("%Y-%m-%d", "%d-%m-%y", "%Y/%m/%d"):
                        try:
                            return datetime.strptime(x['data_entrada'], fmt_sort) if x.get('data_entrada') else datetime.min.date()
                        except ValueError:
                            continue
                    return datetime.min.date() # Fallback se nenhum formato funcionar

            if ordenar_por == 'data_asc':
                lista_os_manutencao.sort(key=sort_key_date)
            elif ordenar_por == 'data_desc':
                lista_os_manutencao.sort(key=sort_key_date, reverse=True)
            elif ordenar_por == 'frota':
                lista_os_manutencao.sort(key=lambda x: str(x.get('frota','')))
        except Exception as e_sort: # Captura exceção mais genérica durante a ordenação
             logger.warning(f"Erro ao ordenar OS de manutenção: {e_sort}")


    finalizadas_todas = Finalizacao.query.order_by(Finalizacao.registrado_em.desc()).limit(100).all()
    
    foto_perfil_manut = None
    user_manut_db_entry = User.query.filter_by(username=session['manutencao']).first()
    if user_manut_db_entry and user_manut_db_entry.profile_picture:
        foto_perfil_manut = url_for('static', filename=user_manut_db_entry.profile_picture)
    elif dados_usuario_manut_atual.get('profile_picture'): 
        foto_perfil_manut = url_for('static', filename=dados_usuario_manut_atual['profile_picture'])

    return render_template('painel_manutencao.html', 
                         nome=dados_usuario_manut_atual.get('nome_exibicao', session['manutencao'].capitalize()),
                         os_list=lista_os_manutencao, 
                         total_os=len(lista_os_manutencao), 
                         os_sem_prestador=lista_os_sem_p_manut, 
                         total_os_sem_prestador=len(lista_os_sem_p_manut),
                         finalizadas=finalizadas_todas,
                         ordenar_atual=ordenar_por, 
                         prestadores_disponiveis=carregar_prestadores(),
                         profile_picture=foto_perfil_manut,
                         now=datetime.now(saopaulo_tz), 
                         today_date=datetime.now(saopaulo_tz).strftime('%Y-%m-%d'))

@app.route('/finalizar_os/<os_numero_str>', methods=['POST'])
def finalizar_os(os_numero_str): 
    responsavel_login = session.get('gerente') or session.get('prestador') or session.get('manutencao')
    if not responsavel_login:
        flash('Acesso negado.', 'danger')
        return redirect(url_for('login'))

    dados_os_para_finalizar = None
    caminho_arquivo_json_os = None
    diretorio_json_os = None

    # Lógica para encontrar a OS e o diretório correspondente
    if 'gerente' in session:
        lista_os_gerente = carregar_os_gerente(session['gerente'])
        dados_os_para_finalizar = next((os_item for os_item in lista_os_gerente if str(os_item.get('os')) == os_numero_str), None)
        diretorio_json_os = MENSAGENS_DIR 
    elif 'prestador' in session:
        dados_prestador = next((p for p in carregar_prestadores() if p.get('usuario','').lower() == session['prestador']), None)
        if dados_prestador and dados_prestador.get('arquivo_os'):
            caminho_arquivo_json_os = os.path.join(MENSAGENS_PRESTADOR_DIR, dados_prestador['arquivo_os'])
            diretorio_json_os = MENSAGENS_PRESTADOR_DIR
    elif 'manutencao' in session:
        dados_manut = next((m for m in carregar_manutencao() if m.get('usuario','').lower() == session['manutencao']), None)
        if dados_manut and dados_manut.get('arquivo_os'):
            caminho_arquivo_json_os = os.path.join(JSON_DIR, dados_manut['arquivo_os'])
            diretorio_json_os = JSON_DIR
            
    # Se dados_os_para_finalizar não foi encontrado, tenta ler do arquivo específico
    if caminho_arquivo_json_os and os.path.exists(caminho_arquivo_json_os) and not dados_os_para_finalizar:
        try: 
            with open(caminho_arquivo_json_os, 'r', encoding='utf-8') as f_json_os_fin:
                lista_os_json = json.load(f_json_os_fin)
            dados_os_para_finalizar = next((item for item in lista_os_json if str(item.get('os') or item.get('OS', '')) == os_numero_str), None)
            if dados_os_para_finalizar:
                dados_os_para_finalizar['data_entrada'] = dados_os_para_finalizar.get('data_entrada') or dados_os_para_finalizar.get('data') or dados_os_para_finalizar.get('Data','')
        except Exception as e_read: 
            logger.error(f"Erro ao ler {caminho_arquivo_json_os} em finalizar_os: {e_read}")

    if not dados_os_para_finalizar and ('prestador' in session or 'manutencao' in session):
        flash(f'OS {os_numero_str} não encontrada nos arquivos do usuário para obter data de abertura. Finalização prossegue com cautela.', 'warning')
    elif not dados_os_para_finalizar and 'gerente' in session:
        flash(f'OS {os_numero_str} não encontrada nos arquivos principais do gerente para obter data de abertura. Finalização prossegue.', 'info')

    data_finalizacao_form = request.form.get('data_finalizacao')
    hora_finalizacao_form = request.form.get('hora_finalizacao')
    observacoes_form = request.form.get('observacoes', '')
    arquivo_evidencia = request.files.get('evidencia')

    if not data_finalizacao_form or not hora_finalizacao_form:
        flash('Data e hora de finalização são obrigatórias.', 'danger')
    else:
        data_abertura_os_obj = None
        if dados_os_para_finalizar:
            data_abertura_os_str = dados_os_para_finalizar.get('data_entrada') or dados_os_para_finalizar.get('data')
            if data_abertura_os_str:
                for fmt_abertura in ("%d/%m/%Y", "%Y-%m-%d", "%d-%m-%y", "%Y/%m/%d"):
                    try:
                        data_abertura_os_obj = datetime.strptime(data_abertura_os_str, fmt_abertura).date()
                        break
                    except (ValueError, TypeError): 
                        continue
        
        try:
            # Tentar parsear a data de finalização em múltiplos formatos
            data_finalizacao_obj = None
            for fmt_finalizacao in ("%Y-%m-%d", "%d/%m/%Y"):  # Prioriza YYYY-MM-DD (input HTML) e depois DD/MM/YYYY
                try:
                    data_finalizacao_obj = datetime.strptime(data_finalizacao_form, fmt_finalizacao).date()
                    break
                except (ValueError, TypeError):
                    continue
            
            if not data_finalizacao_obj:
                raise ValueError(f"Formato de data inválido: {data_finalizacao_form}")

            # Formatar a data para o banco (DD/MM/YYYY)
            data_finalizacao_formatada_db = data_finalizacao_obj.strftime('%d/%m/%Y')

            if data_abertura_os_obj and data_finalizacao_obj < data_abertura_os_obj:
                flash(f'Data de finalização ({data_finalizacao_obj.strftime("%d/%m/%Y")}) não pode ser anterior à data de abertura ({data_abertura_os_obj.strftime("%d/%m/%Y")}).', 'danger')
            else:
                nome_arquivo_evidencia = None
                if arquivo_evidencia and allowed_file(arquivo_evidencia.filename):
                    subpasta_evidencias = os.path.join(app.config['UPLOAD_FOLDER'], 'evidencias')
                    os.makedirs(subpasta_evidencias, exist_ok=True)
                    nome_arquivo_evidencia = secure_filename(f"ev_{os_numero_str}_{responsavel_login}_{datetime.now().strftime('%Y%m%d%H%M%S')}.{arquivo_evidencia.filename.rsplit('.',1)[1].lower()}")
                    try:
                        arquivo_evidencia.save(os.path.join(subpasta_evidencias, nome_arquivo_evidencia))
                    except Exception as e_save:
                        logger.error(f"Erro ao salvar evidência: {e_save}")
                        nome_arquivo_evidencia = None 

                nova_finalizacao = Finalizacao(
                    os_numero=os_numero_str, 
                    gerente=responsavel_login, 
                    data_fin=data_finalizacao_formatada_db,
                    hora_fin=hora_finalizacao_form, 
                    observacoes=observacoes_form,
                    registrado_em=saopaulo_tz.localize(datetime.now())
                )
                db.session.add(nova_finalizacao)
                db.session.commit()
                
                if diretorio_json_os: 
                    removidos = remover_os_de_todos_json(diretorio_json_os, os_numero_str)
                    if removidos: 
                        flash(f'OS {os_numero_str} removida de: {", ".join(removidos)}', 'info')
                elif 'gerente' in session:
                    removidos = remover_os_de_todos_json(MENSAGENS_DIR, os_numero_str)
                    if removidos: 
                        flash(f'OS {os_numero_str} removida de arquivos de gerente: {", ".join(removidos)}', 'info')

                flash(f'OS {os_numero_str} finalizada e registrada!', 'success')
        except ValueError as ve:
            logger.error(f"Erro de formato de data ao finalizar OS {os_numero_str}: {ve}. Data recebida: {data_finalizacao_form}")
            flash(f'Formato de data de finalização inválido. Recebido: "{data_finalizacao_form}". Esperado: DD/MM/YYYY ou YYYY-MM-DD.', 'danger')
        except Exception as e_commit:
            db.session.rollback()
            logger.error(f"Erro DB ao finalizar OS {os_numero_str}: {e_commit}")
            flash('Erro ao registrar finalização. Verifique os logs.', 'danger')

    # Redirecionamento
    if 'prestador' in session: 
        return redirect(url_for('painel_prestador'))
    if 'manutencao' in session: 
        return redirect(url_for('painel_manutencao'))
    if 'gerente' in session: 
        return redirect(url_for('painel'))
    return redirect(url_for('login'))


@app.route('/atribuir_prestador/<os_numero_str>', methods=['POST'])
def atribuir_prestador(os_numero_str):
    if 'manutencao' not in session:
        flash('Acesso negado.', 'danger')
        return redirect(url_for('login'))
    
    responsavel_atribuicao = session['manutencao']
    username_prestador_destino = request.form.get('prestador_usuario', '').strip()

    if not username_prestador_destino:
        flash('Nome de usuário do prestador não pode ser vazio.', 'danger')
    else:
        os_alvo_para_atribuicao = next((os_item for os_item in carregar_os_sem_prestador() if str(os_item.get('os')) == os_numero_str), None)
        if not os_alvo_para_atribuicao:
            flash(f'OS {os_numero_str} não encontrada ou já possui prestador.', 'warning')
        else:
            dados_prestador_destino = next((p for p in carregar_prestadores() if p.get('usuario','').lower() == username_prestador_destino.lower()), None)
            if not dados_prestador_destino or not dados_prestador_destino.get('arquivo_os'):
                flash(f'Prestador "{username_prestador_destino}" não encontrado ou sem arquivo OS configurado.', 'danger')
            else:
                caminho_arq_prest_destino = os.path.join(MENSAGENS_PRESTADOR_DIR, dados_prestador_destino['arquivo_os'])
                os_formatada_para_prestador = {
                    "os": os_alvo_para_atribuicao.get('os'), "frota": os_alvo_para_atribuicao.get('frota'),
                    "data": os_alvo_para_atribuicao.get('data_entrada'), "Data": os_alvo_para_atribuicao.get('data_entrada'),
                    "modelo": os_alvo_para_atribuicao.get('modelo'), "servico": os_alvo_para_atribuicao.get('servico'),
                    "observacao": f"Atribuída por {responsavel_atribuicao} em {datetime.now(saopaulo_tz).strftime('%d/%m/%Y %H:%M')}."
                }
                try:
                    lista_os_atuais_prest = []
                    if os.path.exists(caminho_arq_prest_destino):
                        with open(caminho_arq_prest_destino, 'r', encoding='utf-8') as f_leitura_prest:
                            lista_os_atuais_prest = json.load(f_leitura_prest)
                    
                    if not any(str(item.get('os') or item.get('OS','')) == os_numero_str for item in lista_os_atuais_prest):
                        lista_os_atuais_prest.append(os_formatada_para_prestador)
                        with open(caminho_arq_prest_destino, 'w', encoding='utf-8') as f_escrita_prest:
                            json.dump(lista_os_atuais_prest, f_escrita_prest, ensure_ascii=False, indent=2)
                        
                        remover_os_de_todos_json(MENSAGENS_DIR, os_numero_str) 
                        flash(f'OS {os_numero_str} atribuída a {dados_prestador_destino.get("nome_exibicao", username_prestador_destino)}!', 'success')
                    else:
                        flash(f'OS {os_numero_str} já consta para o prestador {username_prestador_destino}.', 'info')
                except Exception as e_atrib:
                    logger.error(f"Erro ao atribuir OS {os_numero_str} a {username_prestador_destino}: {e_atrib}")
                    flash(f'Erro ao atribuir OS: {e_atrib}', 'danger')
    return redirect(url_for('painel_manutencao'))

# ##########################################################################
# FUNÇÃO admin_panel ATUALIZADA
# ##########################################################################
@app.route('/admin')
def admin_panel():
    if not session.get('is_admin'):
        flash('Acesso negado', 'danger')
        return redirect(url_for('login'))

    periodo = request.args.get('periodo', 'todos')
    data_inicio = request.args.get('data_inicio') 
    data_fim = request.args.get('data_fim')       

    query_finalizadas = Finalizacao.query.order_by(Finalizacao.registrado_em.desc())
    
    inicio_periodo_filtro, fim_periodo_filtro = None, None 
    if data_inicio and data_fim: 
        try:
            inicio_periodo_filtro = saopaulo_tz.localize(parse(data_inicio).replace(hour=0, minute=0, second=0, microsecond=0))
            fim_periodo_filtro = saopaulo_tz.localize(parse(data_fim).replace(hour=23, minute=59, second=59, microsecond=999999))
            query_finalizadas = query_finalizadas.filter(Finalizacao.registrado_em.between(inicio_periodo_filtro, fim_periodo_filtro))
        except ValueError:
            flash('Datas inválidas para filtro de OS Finalizadas. Usando todas as OS.', 'warning')
            inicio_periodo_filtro, fim_periodo_filtro = None, None 
    elif periodo != 'todos':
        hoje_tz = saopaulo_tz.localize(datetime.now())
        if periodo == 'diario':
            inicio_periodo_filtro = hoje_tz.replace(hour=0, minute=0, second=0, microsecond=0)
            fim_periodo_filtro = hoje_tz.replace(hour=23, minute=59, second=59, microsecond=999999)
        elif periodo == 'semanal':
            inicio_periodo_filtro = (hoje_tz - timedelta(days=hoje_tz.weekday())).replace(hour=0, minute=0, second=0, microsecond=0)
            fim_periodo_filtro = (inicio_periodo_filtro + timedelta(days=6)).replace(hour=23, minute=59, second=59, microsecond=999999)
        elif periodo == 'mensal':
            inicio_periodo_filtro = hoje_tz.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
            if inicio_periodo_filtro.month == 12:
                fim_periodo_filtro = inicio_periodo_filtro.replace(year=inicio_periodo_filtro.year + 1, month=1, day=1) - timedelta(microseconds=1)
            else:
                fim_periodo_filtro = inicio_periodo_filtro.replace(month=inicio_periodo_filtro.month + 1, day=1) - timedelta(microseconds=1)
            fim_periodo_filtro = fim_periodo_filtro.replace(hour=23, minute=59, second=59, microsecond=999999)
        elif periodo == 'anual':
            inicio_periodo_filtro = hoje_tz.replace(month=1, day=1, hour=0, minute=0, second=0, microsecond=0)
            fim_periodo_filtro = hoje_tz.replace(month=12, day=31, hour=23, minute=59, second=59, microsecond=999999)
        
        if not (inicio_periodo_filtro and fim_periodo_filtro): 
            inicio_periodo_filtro, fim_periodo_filtro = None, None 
        else:
            query_finalizadas = query_finalizadas.filter(Finalizacao.registrado_em.between(inicio_periodo_filtro, fim_periodo_filtro))
    
    total_os = query_finalizadas.count() 
    finalizadas = query_finalizadas.limit(100).all() 
    
    login_events_query = LoginEvent.query.order_by(LoginEvent.login_time.desc())
    if inicio_periodo_filtro and fim_periodo_filtro: 
         login_events_query = login_events_query.filter(LoginEvent.login_time.between(inicio_periodo_filtro, fim_periodo_filtro))
    
    login_events = login_events_query.limit(50).all()

    for ev_item in login_events:
        ev_item.login_time_formatted = format_datetime(ev_item.login_time)
        ev_item.logout_time_formatted = format_datetime(ev_item.logout_time) if ev_item.logout_time else None
        if ev_item.logout_time and ev_item.login_time:
            login_t_calc = ev_item.login_time.astimezone(saopaulo_tz) if ev_item.login_time.tzinfo else saopaulo_tz.localize(ev_item.login_time)
            logout_t_calc = ev_item.logout_time.astimezone(saopaulo_tz) if ev_item.logout_time.tzinfo else saopaulo_tz.localize(ev_item.logout_time)
            ev_item.duration_secs = int(max(0, (logout_t_calc - login_t_calc).total_seconds()))
        elif ev_item.duration_secs is None : 
            ev_item.duration_secs = 0 

    usuarios_db = User.query.order_by(User.username).all()
    gerentes = [u.username for u in usuarios_db] 

    contagem_gerentes = {} 
    query_contagem_base = Finalizacao.query
    if inicio_periodo_filtro and fim_periodo_filtro: 
        query_contagem_base = query_contagem_base.filter(Finalizacao.registrado_em.between(inicio_periodo_filtro, fim_periodo_filtro))
    
    for g_user_template in gerentes:
        contagem_gerentes[g_user_template] = query_contagem_base.filter(Finalizacao.gerente == g_user_template).count()

    os_abertas = {g_user_t: len(carregar_os_gerente(g_user_t)) for g_user_t in gerentes} 
    ranking_os_abertas = sorted(os_abertas.items(), key=lambda x: x[1], reverse=True) 
    
    ranking_os_prestadores = carregar_os_prestadores() 

    chart_data = { 
        'os_por_periodo': Counter(),
        'os_por_gerente': Counter()
    }
    todas_finalizadas_no_periodo_grafico = query_finalizadas.all() 
    for f_grafico in todas_finalizadas_no_periodo_grafico:
        data_finalizacao_obj_g = None
        if f_grafico.data_fin:
            for fmt_g_parse in ("%d/%m/%Y", "%Y-%m-%d"): 
                try:
                    data_finalizacao_obj_g = datetime.strptime(f_grafico.data_fin, fmt_g_parse)
                    break 
                except (ValueError, TypeError): continue
        
        if not data_finalizacao_obj_g:
            logger.warning(f"ADMIN CHART: Parse data_fin '{f_grafico.data_fin}' OS {f_grafico.os_numero} falhou. Pulando.")
            continue

        chave_periodo_g = ""
        if periodo == 'anual': chave_periodo_g = data_finalizacao_obj_g.strftime('%Y-%m')
        elif periodo == 'mensal': chave_periodo_g = data_finalizacao_obj_g.strftime('%d/%m') 
        elif periodo == 'semanal': chave_periodo_g = data_finalizacao_obj_g.strftime('%d/%m') 
        elif periodo == 'diario': 
            chave_periodo_g = f_grafico.registrado_em.astimezone(saopaulo_tz).strftime('%H:00') if f_grafico.registrado_em else data_finalizacao_obj_g.strftime('%H:00')
        else: 
            chave_periodo_g = data_finalizacao_obj_g.strftime('%d/%m/%Y') 
        chart_data['os_por_periodo'][chave_periodo_g] += 1
        chart_data['os_por_gerente'][f_grafico.gerente] += 1
    
    chart_data['os_por_periodo'] = dict(sorted(chart_data['os_por_periodo'].items()))
    chart_data['os_por_gerente'] = dict(chart_data['os_por_gerente'])
    
    return render_template('admin.html',
                         total_os=total_os,
                         gerentes=gerentes,
                         now=datetime.now(saopaulo_tz), 
                         os_abertas=os_abertas,
                         finalizadas=finalizadas,
                         contagem_gerentes=contagem_gerentes,
                         ranking_os_abertas=ranking_os_abertas,
                         ranking_os_prestadores=ranking_os_prestadores,
                         login_events=login_events,
                         chart_data=chart_data,
                         periodo=periodo, 
                         data_inicio=data_inicio, 
                         data_fim=data_fim
                         # format_datetime=format_datetime # Removido pois está no context_processor
                         )
# ##########################################################################
# FIM DA FUNÇÃO admin_panel ATUALIZADA
# ##########################################################################

@app.route('/exportar_os_finalizadas')
def exportar_os_finalizadas():
    if not session.get('is_admin'):
        flash('Acesso negado', 'danger')
        return redirect(url_for('login'))

    periodo_export = request.args.get('periodo', 'todos')
    data_inicio_export_str = request.args.get('data_inicio')
    data_fim_export_str = request.args.get('data_fim')

    query_export = Finalizacao.query.order_by(Finalizacao.registrado_em.desc())

    inicio_export, fim_export = None, None 
    if data_inicio_export_str and data_fim_export_str:
        try:
            inicio_export = saopaulo_tz.localize(parse(data_inicio_export_str).replace(hour=0, minute=0, second=0, microsecond=0))
            fim_export = saopaulo_tz.localize(parse(data_fim_export_str).replace(hour=23, minute=59, second=59, microsecond=999999))
            query_export = query_export.filter(Finalizacao.registrado_em.between(inicio_export, fim_export))
        except ValueError:
            flash('Datas inválidas para exportação. Exportando todas as OS.', 'warning')
            inicio_export, fim_export = None, None
    elif periodo_export != 'todos':
        hoje_tz_export = saopaulo_tz.localize(datetime.now())
        if periodo_export == 'diario':
            inicio_export = hoje_tz_export.replace(hour=0, minute=0, second=0, microsecond=0)
            fim_export = hoje_tz_export.replace(hour=23, minute=59, second=59, microsecond=999999)
        elif periodo_export == 'semanal':
            inicio_export = (hoje_tz_export - timedelta(days=hoje_tz_export.weekday())).replace(hour=0, minute=0, second=0, microsecond=0)
            fim_export = (inicio_export + timedelta(days=6)).replace(hour=23, minute=59, second=59, microsecond=999999)
        elif periodo_export == 'mensal':
            inicio_export = hoje_tz_export.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
            if inicio_export.month == 12: fim_export = inicio_export.replace(year=inicio_export.year + 1, month=1, day=1) - timedelta(microseconds=1)
            else: fim_export = inicio_export.replace(month=inicio_export.month + 1, day=1) - timedelta(microseconds=1)
            fim_export = fim_export.replace(hour=23, minute=59, second=59, microsecond=999999)
        elif periodo_export == 'anual':
            inicio_export = hoje_tz_export.replace(month=1, day=1, hour=0, minute=0, second=0, microsecond=0)
            fim_export = hoje_tz_export.replace(month=12, day=31, hour=23, minute=59, second=59, microsecond=999999)
        
        if not (inicio_export and fim_export): inicio_export, fim_export = None, None
        else: query_export = query_export.filter(Finalizacao.registrado_em.between(inicio_export, fim_export))

    lista_finalizadas_para_export = query_export.all()
    if not lista_finalizadas_para_export:
        flash('Nenhuma OS finalizada para o período selecionado para exportação.', 'warning')
        return redirect(url_for('admin_panel', periodo=periodo_export, data_inicio=data_inicio_export_str, data_fim=data_fim_export_str))

    nome_arquivo_pdf = f'relatorio_os_finalizadas_{datetime.now(saopaulo_tz).strftime("%Y%m%d_%H%M%S")}.pdf'
    caminho_pdf_salvo = os.path.join(BASE_DIR, nome_arquivo_pdf)
    
    canvas_pdf = canvas.Canvas(caminho_pdf_salvo, pagesize=A4)
    largura_a4, altura_a4 = A4

    titulo_relatorio_periodo = periodo_export.capitalize()
    if data_inicio_export_str and data_fim_export_str: 
        try: titulo_relatorio_periodo = f"{parse(data_inicio_export_str).strftime('%d/%m/%Y')} a {parse(data_fim_export_str).strftime('%d/%m/%Y')}"
        except ValueError: titulo_relatorio_periodo = "Período Personalizado"
    elif inicio_export and fim_export: 
        titulo_relatorio_periodo = f"{inicio_export.strftime('%d/%m/%Y')} a {fim_export.strftime('%d/%m/%Y')}"
    
    num_pagina_atual = 1
    def desenhar_cabecalho_rodape_pdf(canv, num_pag):
        canv.setFont("Helvetica-Bold", 14)
        canv.drawCentredString(largura_a4 / 2, altura_a4 - 50, f"Relatório de OS Finalizadas ({titulo_relatorio_periodo})")
        canv.setFont("Helvetica", 8)
        canv.drawRightString(largura_a4 - 40, 30, f"Página {num_pag}")
        canv.drawString(40, 30, f"Exportado em: {datetime.now(saopaulo_tz).strftime('%d/%m/%Y %H:%M:%S')}")

    desenhar_cabecalho_rodape_pdf(canvas_pdf, str(num_pagina_atual))
    pos_y_linha = altura_a4 - 85
    
    canvas_pdf.setFont("Helvetica-Bold", 9)
    detalhes_colunas_pdf = [('OS', 50), ('Responsável', 100), ('Data Fin.', 60), ('Hora Fin.', 50), ('Observações', 180), ('Registrado Em', 110)]
    pos_x_col = 40
    for nome_col, largura_col in detalhes_colunas_pdf:
        canvas_pdf.drawString(pos_x_col, pos_y_linha, nome_col)
        pos_x_col += largura_col
    pos_y_linha -= 6
    canvas_pdf.line(35, pos_y_linha, largura_a4 - 35, pos_y_linha)
    pos_y_linha -= 10
    canvas_pdf.setFont("Helvetica", 8)

    for os_finalizada_item in lista_finalizadas_para_export:
        if pos_y_linha < 60: 
            canvas_pdf.showPage()
            num_pagina_atual += 1
            desenhar_cabecalho_rodape_pdf(canvas_pdf, str(num_pagina_atual))
            pos_y_linha = altura_a4 - 85 
            canvas_pdf.setFont("Helvetica-Bold", 9)
            pos_x_cabecalho_nova_pag = 40
            for nome_col_h, largura_col_h in detalhes_colunas_pdf:
                canvas_pdf.drawString(pos_x_cabecalho_nova_pag, pos_y_linha, nome_col_h)
                pos_x_cabecalho_nova_pag += largura_col_h
            pos_y_linha -= 6
            canvas_pdf.line(35, pos_y_linha, largura_a4 - 35, pos_y_linha)
            pos_y_linha -= 10
            canvas_pdf.setFont("Helvetica", 8)

        pos_x_atual_dado = 40
        texto_obs_pdf = (os_finalizada_item.observacoes or '')
        linhas_obs_pdf = [texto_obs_pdf[i:i+45] for i in range(0, len(texto_obs_pdf), 45)] 
        
        dados_linha_pdf = [
            str(os_finalizada_item.os_numero), str(os_finalizada_item.gerente), str(os_finalizada_item.data_fin), str(os_finalizada_item.hora_fin),
            linhas_obs_pdf[0] if linhas_obs_pdf else '', 
            format_datetime(os_finalizada_item.registrado_em) if os_finalizada_item.registrado_em else "N/A"
        ]
        
        altura_linha_pdf = 12 + ((len(linhas_obs_pdf) - 1) * 9 if len(linhas_obs_pdf) > 1 else 0)
        pos_y_temp_pdf = pos_y_linha
        for idx_dado, (_, largura_col_dado) in enumerate(detalhes_colunas_pdf):
            if detalhes_colunas_pdf[idx_dado][0] == 'Observações':
                offset_y_obs = 0
                for linha_obs_item in linhas_obs_pdf:
                    canvas_pdf.drawString(pos_x_atual_dado, pos_y_temp_pdf - offset_y_obs, linha_obs_item)
                    offset_y_obs += 9
            else:
                 canvas_pdf.drawString(pos_x_atual_dado, pos_y_temp_pdf, dados_linha_pdf[idx_dado])
            pos_x_atual_dado += largura_col_dado
        pos_y_linha -= altura_linha_pdf
            
    canvas_pdf.save()
    try:
        return send_file(caminho_pdf_salvo, as_attachment=True, download_name=nome_arquivo_pdf, mimetype='application/pdf')
    finally:
        if os.path.exists(caminho_pdf_salvo): 
            logger.info(f"PDF {caminho_pdf_salvo} gerado.")


@app.route('/logout')
def logout():
    id_evento_login = session.pop('login_event_id', None)
    username_sessao = session.get('gerente') or session.get('prestador') or session.get('manutencao')
    
    if id_evento_login:
        evento_login_db = LoginEvent.query.get(id_evento_login)
        if evento_login_db:
            tipo_usuario_logout = evento_login_db.user_type
            hora_logout_atual = saopaulo_tz.localize(datetime.now())
            hora_login_calc = evento_login_db.login_time
            if hora_login_calc.tzinfo is None: hora_login_calc = saopaulo_tz.localize(hora_login_calc)
            else: hora_login_calc = hora_login_calc.astimezone(saopaulo_tz)
            
            evento_login_db.logout_time = hora_logout_atual
            evento_login_db.duration_secs = int(max(0, (hora_logout_atual - hora_login_calc).total_seconds()))
            
            logger.info(f"Logout de {evento_login_db.username} (tipo: {tipo_usuario_logout}): "
                        f"Login {format_datetime(hora_login_calc)}, Logout {format_datetime(hora_logout_atual)}, "
                        f"Duração: {evento_login_db.duration_secs}s.")
            try:
                db.session.commit()
            except Exception as e_commit_logout:
                db.session.rollback()
                logger.error(f"Erro ao commitar logout event para {evento_login_db.username}: {e_commit_logout}")
        else: 
            logger.warning(f"Evento login ID {id_evento_login} (usuário: {username_sessao or 'Desconhecido'}) não encontrado no BD.")
    else: 
        logger.info(f"Logout de {username_sessao or 'Usuário desconhecido'} sem login_event_id.")

    nome_exibicao_logout = capitalize_name(username_sessao) if username_sessao else "Usuário"
    session.clear()
    flash(f'{nome_exibicao_logout} desconectado(a) com sucesso.', 'info')
    return redirect(url_for('login'))

with app.app_context():
    init_db()



# === ROTAS FROTA LEVE ===
FROTA_LEVE_FILE = os.path.join(BASE_DIR, 'frota_leve.json')


@app.route('/frota-leve')
def frota_leve():
    if not session.get('is_admin'):
        return redirect('/login')

    filtro = request.args.get('filtro')
    query = FrotaLeve.query

    if filtro and filtro.lower() != "todos":
        query = query.filter(FrotaLeve.situacao.ilike(f'%{filtro}%'))

dados = query.all()
return render_template(
    'frota_leve.html',
    dados=dados,
    usuario=session.get('gerente') or session.get('manutencao') or session.get('prestador')
)

@app.route('/frota-leve/novo', methods=['GET', 'POST'])
def nova_manutencao_frota_leve():
    if not session.get('is_admin'):
        return redirect('/login')

    if request.method == 'POST':
        nova_os = FrotaLeve(
            placa=request.form['placa'],
            veiculo=request.form['veiculo'],
            motorista=request.form['motorista'],
            oficina=request.form['oficina'],
            servico=request.form['servico'],
            situacao=request.form['situacao'],
            entrada=request.form['entrada'],
            saida=request.form['saida'],
            valor_mo=request.form['valor_mo'],
            valor_pecas=request.form['valor_pecas'],
            aprovado_por=request.form['aprovado_por'],
            cotacao1=request.form.get('cotacao1', ''),
            cotacao2=request.form.get('cotacao2', ''),
            cotacao3=request.form.get('cotacao3', ''),
            fechado_com=request.form.get('fechado_com', ''),
            obs=request.form['obs']
        )
        db.session.add(nova_os)
        db.session.commit()
        return redirect('/frota-leve')

    return render_template('nova_manutencao_frota.html', usuario=session.get('gerente') or session.get('manutencao') or session.get('prestador'))
 or session.get('manutencao') or session.get('prestador'))




@app.route('/frota-leve/finalizar/<int:index>', methods=['POST'])
def finalizar_manutencao_frota_leve(index):
    if not session.get('is_admin'):
        return redirect('/login')

    with open(FROTA_LEVE_FILE, 'r', encoding='utf-8') as f:
        dados = json.load(f)

    if 0 <= index < len(dados):
        dados[index]['situacao'] = 'Finalizado'
        dados[index]['saida'] = request.form['data_fim']
        dados[index]['hora_fim'] = request.form['hora_fim']
        dados[index]['obs'] += '\nFinalização: ' + request.form.get('obs_fim', '')

        with open(FROTA_LEVE_FILE, 'w', encoding='utf-8') as f:
            json.dump(dados, f, ensure_ascii=False, indent=4)

    return redirect('/frota-leve')


if __name__ == '__main__':
    app.run(host='0.0.0.0',
           port=int(os.environ.get('PORT', 10000)),
           debug=True)
