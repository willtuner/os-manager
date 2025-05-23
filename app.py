from flask import Flask, render_template, request, redirect, url_for, flash, session, send_file
from flask_sqlalchemy import SQLAlchemy
from datetime import datetime
import pytz
import os
import json
import logging
from collections import Counter
from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph
from reportlab.lib.styles import getSampleStyleSheet
import io

app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'chave_secreta_padrao')
app.config['SQLALCHEMY_DATABASE_URI'] = os.environ.get('DATABASE_URL', 'sqlite:///site.db')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db = SQLAlchemy(app)

# Configuração de logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger('app')

# Diretórios
BASE_DIR = os.path.abspath(os.path.dirname(__file__))
JSON_DIR = os.path.join(BASE_DIR, 'static', 'json')
MENSAGENS_GERENTE_DIR = os.path.join(BASE_DIR, 'mensagens_por_gerente')
MENSAGENS_PRESTADOR_DIR = os.path.join(BASE_DIR, 'mensagens_por_prestador')
PRESTADORES_FILE = os.path.join(JSON_DIR, 'prestadores.json')
MANUTENCAO_FILE = os.path.join(JSON_DIR, 'manutencao.json')

# Fuso horário de São Paulo
saopaulo_tz = pytz.timezone('America/Sao_Paulo')

# Modelo do banco de dados
class Finalizacao(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    os_numero = db.Column(db.String(20), nullable=False)
    gerente = db.Column(db.String(100), nullable=False)
    data_fin = db.Column(db.String(10), nullable=False)
    hora_fin = db.Column(db.String(5), nullable=False)
    observacoes = db.Column(db.Text)
    registrado_em = db.Column(db.DateTime, default=lambda: saopaulo_tz.localize(datetime.now()))

class LoginEvent(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(100), nullable=False)
    user_type = db.Column(db.String(20), nullable=False)
    login_time = db.Column(db.DateTime, nullable=False)
    logout_time = db.Column(db.DateTime)
    duration_secs = db.Column(db.Integer)

    @property
    def login_time_formatted(self):
        return self.login_time.astimezone(saopaulo_tz).strftime('%d/%m/%Y %H:%M:%S')

    @property
    def logout_time_formatted(self):
        if self.logout_time:
            return self.logout_time.astimezone(saopaulo_tz).strftime('%d/%m/%Y %H:%M:%S')
        return None

# Funções auxiliares
def carregar_prestadores():
    if not os.path.exists(PRESTADORES_FILE):
        logger.warning(f"Arquivo de prestadores não encontrado: {PRESTADORES_FILE}")
        return []
    try:
        with open(PRESTADORES_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    except json.JSONDecodeError as e:
        logger.error(f"Erro ao decodificar {PRESTADORES_FILE}: {e}")
        return []
    except Exception as e:
        logger.error(f"Erro ao carregar prestadores: {e}")
        return []

def carregar_manutencao():
    if not os.path.exists(MANUTENCAO_FILE):
        logger.warning(f"Arquivo de manutenção não encontrado: {MANUTENCAO_FILE}")
        return []
    try:
        with open(MANUTENCAO_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    except json.JSONDecodeError as e:
        logger.error(f"Erro ao decodificar {MANUTENCAO_FILE}: {e}")
        return []
    except Exception as e:
        logger.error(f"Erro ao carregar manutenção: {e}")
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
            except Exception:
                item['dias_abertos'] = 0
        # Ordenar por data de entrada (mais nova para mais antiga)
        os_list.sort(key=lambda x: datetime.strptime(x['data_entrada'], '%d/%m/%Y'), reverse=True)
        return os_list
    except json.JSONDecodeError as e:
        logger.error(f"Erro ao decodificar {caminho}: {e}")
        return []
    except Exception as e:
        logger.error(f"Erro ao carregar OS para {usuario}: {e}")
        return []

def carregar_os_sem_prestador():
    caminho = os.path.join(JSON_DIR, 'os_sem_prestador.json')
    if not os.path.exists(caminho):
        logger.warning(f"Arquivo de OS sem prestador não encontrado: {caminho}")
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
        logger.error(f"Erro ao carregar OS sem prestador: {e}")
        return []

# Rotas
@app.route('/')
def index():
    return redirect(url_for('login'))

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form.get('username', '').lower()
        password = request.form.get('password', '')
        prestadores = carregar_prestadores()
        manutencao_users = carregar_manutencao()
        
        # Verificar administrador
        if username == 'wilson.santana' and password == '123':
            session['admin'] = username
            login_event = LoginEvent(
                username=username,
                user_type='admin',
                login_time=saopaulo_tz.localize(datetime.now())
            )
            db.session.add(login_event)
            db.session.commit()
            logger.info(f"Login bem-sucedido para admin: {username}")
            return redirect(url_for('admin'))
        
        # Verificar prestador
        prestador = next((p for p in prestadores if p.get('usuario', '').lower() == username and p.get('senha') == password), None)
        if prestador:
            session['prestador'] = username
            login_event = LoginEvent(
                username=username,
                user_type='prestador',
                login_time=saopaulo_tz.localize(datetime.now())
            )
            db.session.add(login_event)
            db.session.commit()
            logger.info(f"Login bem-sucedido para prestador: {username}")
            return redirect(url_for('painel_prestador'))
        
        # Verificar manutenção
        manutencao = next((p for p in manutencao_users if p.get('usuario', '').lower() == username and p.get('senha') == password), None)
        if manutencao:
            session['manutencao'] = username
            login_event = LoginEvent(
                username=username,
                user_type='manutencao',
                login_time=saopaulo_tz.localize(datetime.now())
            )
            db.session.add(login_event)
            db.session.commit()
            logger.info(f"Login bem-sucedido para manutenção: {username}")
            return redirect(url_for('painel_manutencao'))
        
        flash('Usuário ou senha inválidos', 'danger')
        logger.warning(f"Falha no login para {username}")
    
    return render_template('login.html')

@app.route('/logout')
def logout():
    username = session.get('admin') or session.get('prestador') or session.get('manutencao')
    user_type = 'admin' if session.get('admin') else 'prestador' if session.get('prestador') else 'manutencao'
    if username:
        login_event = LoginEvent.query.filter_by(
            username=username, 
            user_type=user_type, 
            logout_time=None
        ).order_by(LoginEvent.login_time.desc()).first()
        if login_event:
            login_event.logout_time = saopaulo_tz.localize(datetime.now())
            login_event.duration_secs = int((login_event.logout_time - login_event.login_time).total_seconds())
            db.session.commit()
    session.clear()
    flash('Desconectado com sucesso', 'success')
    return redirect(url_for('login'))

@app.route('/admin')
def admin():
    if 'admin' not in session:
        flash('Acesso negado. Faça login.', 'danger')
        return redirect(url_for('login'))
    
    periodo = request.args.get('periodo', 'mensal')
    data_inicio = request.args.get('data_inicio')
    data_fim = request.args.get('data_fim')
    
    finalizadas = Finalizacao.query
    if periodo == 'diario':
        finalizadas = finalizadas.filter(Finalizacao.data_fin == saopaulo_tz.localize(datetime.now()).strftime('%d/%m/%Y'))
    elif periodo == 'semanal':
        data_inicio = (saopaulo_tz.localize(datetime.now()) - timedelta(days=7)).strftime('%d/%m/%Y')
        finalizadas = finalizadas.filter(Finalizacao.data_fin >= data_inicio)
    elif periodo == 'mensal':
        data_inicio = saopaulo_tz.localize(datetime.now()).replace(day=1).strftime('%d/%m/%Y')
        finalizadas = finalizadas.filter(Finalizacao.data_fin >= data_inicio)
    elif periodo == 'anual':
        data_inicio = saopaulo_tz.localize(datetime.now()).replace(month=1, day=1).strftime('%d/%m/%Y')
        finalizadas = finalizadas.filter(Finalizacao.data_fin >= data_inicio)
    elif periodo == 'custom' and data_inicio and data_fim:
        try:
            data_inicio_dt = datetime.strptime(data_inicio, '%Y-%m-%d').strftime('%d/%m/%Y')
            data_fim_dt = datetime.strptime(data_fim, '%Y-%m-%d').strftime('%d/%m/%Y')
            finalizadas = finalizadas.filter(Finalizacao.data_fin.between(data_inicio_dt, data_fim_dt))
        except ValueError:
            flash('Datas inválidas', 'danger')
    
    finalizadas = finalizadas.order_by(Finalizacao.registrado_em.desc()).all()
    total_os = len(finalizadas)
    
    gerentes = sorted(set(f.gerente for f in finalizadas))
    contagem_gerentes = Counter(f.gerente for f in finalizadas)
    
    os_abertas = carregar_os_prestadores()
    ranking_os_abertas = sorted([(g, contagem_gerentes.get(g, 0)) for g in gerentes], key=lambda x: x[1], reverse=True)
    
    login_events = LoginEvent.query.order_by(LoginEvent.login_time.desc()).limit(50).all()
    
    chart_data = {
        'os_por_periodo': Counter(f.data_fin for f in finalizadas),
        'os_por_gerente': Counter(f.gerente for f in finalizadas)
    }
    
    return render_template('admin.html',
                         finalizadas=finalizadas,
                         total_os=total_os,
                         gerentes=gerentes,
                         contagem_gerentes=contagem_gerentes,
                         os_abertas=dict(os_abertas),
                         ranking_os_abertas=ranking_os_abertas,
                         ranking_os_prestadores=carregar_os_prestadores(),
                         login_events=login_events,
                         chart_data=chart_data,
                         periodo=periodo,
                         data_inicio=data_inicio,
                         data_fim=data_fim,
                         now=saopaulo_tz.localize(datetime.now()))

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
    
    # Carregar OS finalizadas pelo usuário de manutenção
    finalizadas = Finalizacao.query.filter_by(gerente=session['manutencao']).order_by(Finalizacao.registrado_em.desc()).limit(100).all()
    
    return render_template('painel_manutencao.html', 
                         nome=manutencao['nome_exibicao'], 
                         os_list=os_list, 
                         total_os=total_os, 
                         os_sem_prestador=os_sem_prestador, 
                         prestadores=carregar_prestadores(),
                         finalizadas=finalizadas,
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
            # Ordenar por data de entrada (mais nova para mais antiga)
            os_list.sort(key=lambda x: datetime.strptime(x['data_entrada'], '%d/%m/%Y'), reverse=True)
            # Calcular dias abertos
            hoje = saopaulo_tz.localize(datetime.now()).date()
            for item in os_list:
                try:
                    data_entrada = datetime.strptime(item['data_entrada'], '%d/%m/%Y').date()
                    item['dias_abertos'] = (hoje - data_entrada).days
                except Exception:
                    item['dias_abertos'] = 0
        except json.JSONDecodeError as e:
            logger.error(f"Erro ao decodificar {caminho}: {e}")
            os_list = []
    # Carregar OS finalizadas pelo prestador
    finalizadas = Finalizacao.query.filter_by(gerente=session['prestador']).order_by(Finalizacao.registrado_em.desc()).limit(100).all()
    return render_template('painel_prestador.html', nome=prestador['nome_exibicao'], os_list=os_list, finalizadas=finalizadas)

@app.route('/finalizar_os/<os_numero>', methods=['POST'])
def finalizar_os(os_numero):
    if 'prestador' not in session and 'manutencao' not in session:
        flash('Acesso negado. Faça login.', 'danger')
        return redirect(url_for('login'))
    
    responsavel = session.get('prestador') or session.get('manutencao')
    tipo = 'prestador' if session.get('prestador') else 'manutencao'
    
    data_finalizacao = request.form.get('data_finalizacao')
    hora_finalizacao = request.form.get('hora_finalizacao')
    observacoes = request.form.get('observacoes', '').strip() or None
    
    if not data_finalizacao or not hora_finalizacao:
        flash('Data e hora de finalização são obrigatórias', 'danger')
        return redirect(url_for('painel_prestador' if tipo == 'prestador' else 'painel_manutencao'))
    
    try:
        d = datetime.strptime(data_finalizacao, '%d/%m/%Y').strftime('%d/%m/%Y')
        h = datetime.strptime(hora_finalizacao, '%H:%M').strftime('%H:%M')
    except ValueError:
        flash('Formato de data ou hora inválido', 'danger')
        return redirect(url_for('painel_prestador' if tipo == 'prestador' else 'painel_manutencao'))
    
    if tipo == 'prestador':
        prestadores = carregar_prestadores()
        prestador = next((p for p in prestadores if p.get('usuario', '').lower() == responsavel), None)
        if not prestador:
            flash('Prestador não encontrado', 'danger')
            return redirect(url_for('painel_prestador'))
        caminho = os.path.join(MENSAGENS_PRESTADOR_DIR, prestador['arquivo_os'])
    else:
        manutencao_users = carregar_manutencao()
        manutencao = next((p for p in manutencao_users if p.get('usuario', '').lower() == responsavel), None)
        if not manutencao:
            flash('Usuário de manutenção não encontrado', 'danger')
            return redirect(url_for('painel_manutencao'))
        caminho = os.path.join(JSON_DIR, manutencao['arquivo_os'])
    
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
    
    os_list = [os for os in os_list if os['os'] != os_numero]
    
    try:
        with open(caminho, 'w', encoding='utf-8') as f:
            json.dump(os_list, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.error(f"Erro ao salvar {caminho}: {e}")
        flash('Erro ao salvar a finalização', 'danger')
        return redirect(url_for('painel_prestador' if tipo == 'prestador' else 'painel_manutencao'))
    
    fz = Finalizacao(
        os_numero=os_numero,
        gerente=responsavel,
        data_fin=d,
        hora_fin=h,
        observacoes=observacoes
    )
    db.session.add(fz)
    db.session.commit()
    
    flash(f'OS {os_numero} finalizada', 'success')
    return redirect(url_for('painel_prestador' if tipo == 'prestador' else 'painel_manutencao'))

@app.route('/atribuir_prestador/<os_numero>', methods=['POST'])
def atribuir_prestador(os_numero):
    if 'manutencao' not in session:
        flash('Acesso negado. Faça login.', 'danger')
        return redirect(url_for('login'))
    
    prestador_nome = request.form.get('prestador')
    if not prestador_nome:
        flash('Selecione um prestador', 'danger')
        return redirect(url_for('painel_manutencao'))
    
    prestadores = carregar_prestadores()
    prestador = next((p for p in prestadores if p.get('nome_exibicao') == prestador_nome), None)
    if not prestador:
        flash('Prestador inválido', 'danger')
        return redirect(url_for('painel_manutencao'))
    
    caminho_os_sem_prestador = os.path.join(JSON_DIR, 'os_sem_prestador.json')
    if not os.path.exists(caminho_os_sem_prestador):
        logger.warning(f"Arquivo de OS sem prestador não encontrado: {caminho_os_sem_prestador}")
        os_list = []
    else:
        try:
            with open(caminho_os_sem_prestador, 'r', encoding='utf-8') as f:
                os_list = json.load(f)
        except json.JSONDecodeError as e:
            logger.error(f"Erro ao decodificar {caminho_os_sem_prestador}: {e}")
            os_list = []
    
    os_target = next((os for os in os_list if os['os'] == os_numero), None)
    if not os_target:
        flash('OS não encontrada', 'danger')
        return redirect(url_for('painel_manutencao'))
    
    os_list = [os for os in os_list if os['os'] != os_numero]
    
    try:
        with open(caminho_os_sem_prestador, 'w', encoding='utf-8') as f:
            json.dump(os_list, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.error(f"Erro ao salvar {caminho_os_sem_prestador}: {e}")
        flash('Erro ao salvar a atribuição', 'danger')
        return redirect(url_for('painel_manutencao'))
    
    caminho_prestador = os.path.join(MENSAGENS_PRESTADOR_DIR, prestador['arquivo_os'])
    if not os.path.exists(caminho_prestador):
        logger.warning(f"Arquivo de OS do prestador não encontrado: {caminho_prestador}")
        prestador_os_list = []
    else:
        try:
            with open(caminho_prestador, 'r', encoding='utf-8') as f:
                prestador_os_list = json.load(f)
        except json.JSONDecodeError as e:
            logger.error(f"Erro ao decodificar {caminho_prestador}: {e}")
            prestador_os_list = []
    
    os_target['prestador'] = prestador['usuario']
    prestador_os_list.append(os_target)
    
    try:
        with open(caminho_prestador, 'w', encoding='utf-8') as f:
            json.dump(prestador_os_list, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.error(f"Erro ao salvar {caminho_prestador}: {e}")
        flash('Erro ao salvar a atribuição', 'danger')
        return redirect(url_for('painel_manutencao'))
    
    flash(f'OS {os_numero} atribuída a {prestador_nome}', 'success')
    return redirect(url_for('painel_manutencao'))

@app.route('/adicionar_comentario/<os_numero>', methods=['POST'])
def adicionar_comentario(os_numero):
    if 'manutencao' not in session:
        flash('Acesso negado. Faça login.', 'danger')
        return redirect(url_for('login'))
    
    comentario = request.form.get('comentario', '').strip()
    if not comentario:
        flash('O comentário não pode estar vazio', 'danger')
        return redirect(url_for('painel_manutencao'))
    
    manutencao_users = carregar_manutencao()
    manutencao = next((p for p in manutencao_users if p.get('usuario', '').lower() == session['manutencao']), None)
    if not manutencao:
        flash('Usuário de manutenção não encontrado', 'danger')
        return redirect(url_for('painel_manutencao'))
    
    caminho = os.path.join(JSON_DIR, manutencao['arquivo_os'])
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
    
    os_target = next((os for os in os_list if os['os'] == os_numero), None)
    if not os_target:
        flash('OS não encontrada', 'danger')
        return redirect(url_for('painel_manutencao'))
    
    if 'comentarios' not in os_target:
        os_target['comentarios'] = []
    
    os_target['comentarios'].append({
        'autor': session['manutencao'],
        'data': saopaulo_tz.localize(datetime.now()).strftime('%d/%m/%Y %H:%M'),
        'texto': comentario
    })
    
    try:
        with open(caminho, 'w', encoding='utf-8') as f:
            json.dump(os_list, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.error(f"Erro ao salvar {caminho}: {e}")
        flash('Erro ao salvar o comentário', 'danger')
        return redirect(url_for('painel_manutencao'))
    
    flash('Comentário adicionado com sucesso', 'success')
    return redirect(url_for('painel_manutencao'))

@app.route('/exportar_os_finalizadas')
def exportar_os_finalizadas():
    if 'admin' not in session:
        flash('Acesso negado. Faça login.', 'danger')
        return redirect(url_for('login'))
    
    periodo = request.args.get('periodo', 'mensal')
    data_inicio = request.args.get('data_inicio')
    data_fim = request.args.get('data_fim')
    
    finalizadas = Finalizacao.query
    if periodo == 'diario':
        finalizadas = finalizadas.filter(Finalizacao.data_fin == saopaulo_tz.localize(datetime.now()).strftime('%d/%m/%Y'))
    elif periodo == 'semanal':
        data_inicio = (saopaulo_tz.localize(datetime.now()) - timedelta(days=7)).strftime('%d/%m/%Y')
        finalizadas = finalizadas.filter(Finalizacao.data_fin >= data_inicio)
    elif periodo == 'mensal':
        data_inicio = saopaulo_tz.localize(datetime.now()).replace(day=1).strftime('%d/%m/%Y')
        finalizadas = finalizadas.filter(Finalizacao.data_fin >= data_inicio)
    elif periodo == 'anual':
        data_inicio = saopaulo_tz.localize(datetime.now()).replace(month=1, day=1).strftime('%d/%m/%Y')
        finalizadas = finalizadas.filter(Finalizacao.data_fin >= data_inicio)
    elif periodo == 'custom' and data_inicio and data_fim:
        try:
            data_inicio_dt = datetime.strptime(data_inicio, '%Y-%m-%d').strftime('%d/%m/%Y')
            data_fim_dt = datetime.strptime(data_fim, '%Y-%m-%d').strftime('%d/%m/%Y')
            finalizadas = finalizadas.filter(Finalizacao.data_fin.between(data_inicio_dt, data_fim_dt))
        except ValueError:
            flash('Datas inválidas', 'danger')
            return redirect(url_for('admin'))
    
    finalizadas = finalizadas.order_by(Finalizacao.registrado_em.desc()).all()
    
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=letter)
    elements = []
    
    styles = getSampleStyleSheet()
    elements.append(Paragraph("Relatório de Manutenções Concluídas", styles['Title']))
    
    data = [['OS', 'Supervisor', 'Data', 'Hora', 'Observações']]
    for f in finalizadas:
        data.append([
            f.os_numero,
            f.gerente,
            f.data_fin,
            f.hora_fin,
            f.observacoes or '-'
        ])
    
    table = Table(data)
    table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.grey),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
        ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, 0), 12),
        ('BOTTOMPADDING', (0, 0), (-1, 0), 12),
        ('BACKGROUND', (0, 1), (-1, -1), colors.beige),
        ('GRID', (0, 0), (-1, -1), 1, colors.black)
    ]))
    elements.append(table)
    
    doc.build(elements)
    buffer.seek(0)
    
    return send_file(
        buffer,
        as_attachment=True,
        download_name=f'relatorio_os_finalizadas_{periodo}.pdf',
        mimetype='application/pdf'
    )

# Filtros Jinja
@app.template_filter('capitalize_name')
def capitalize_name(name):
    if not name:
        return ''
    parts = name.split('.')
    return ' '.join(part.capitalize() for part in parts)

if __name__ == '__main__':
    with app.app_context():
        db.create_all()
    app.run(debug=os.environ.get('FLASK_DEBUG', '0') == '1')
