import os
import json
import logging
from datetime import datetime
from flask import Flask, render_template, request, redirect, session, url_for, flash, send_file
from flask_sqlalchemy import SQLAlchemy
from fpdf import FPDF
from collections import Counter

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
    registrado_em = db.Column(db.DateTime, default=datetime.utcnow)

class LoginEvent(db.Model):
    __tablename__ = 'login_events'
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), nullable=False)
    user_type = db.Column(db.String(20), nullable=False)  # 'gerente' ou 'prestador'
    login_time = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    logout_time = db.Column(db.DateTime)
    duration_secs = db.Column(db.Integer)

# --- Constantes de caminho e inicialização do JSON ---
BASE_DIR = os.path.dirname(__file__)
MENSAGENS_DIR = os.path.join(BASE_DIR, 'mensagens_por_gerente')
USERS_FILE = os.path.join(BASE_DIR, 'users.json')
PRESTADORES_FILE = os.path.join(BASE_DIR, 'prestadores.json')
MENSAGENS_PRESTADORES_DIR = os.path.join(BASE_DIR, 'mensagens_por_prestador')
os.makedirs(MENSAGENS_DIR, exist_ok=True)
os.makedirs(MENSAGENS_PRESTADORES_DIR, exist_ok=True)

def init_db():
    """Cria tabelas e importa users.json na tabela users, se vazia."""
    db.create_all()
    if User.query.count() == 0 and os.path.exists(USERS_FILE):
        with open(USERS_FILE, encoding='utf-8') as f:
            js = json.load(f)
        admins = {'wilson.santana'}  # quem deve virar admin
        for u, pwd in js.items():
            db.session.add(User(
                username=u.lower(),
                password=pwd,
                is_admin=(u.lower() in admins)
            ))
        db.session.commit()

def carregar_os_gerente(gerente):
    """
    Carrega apenas o JSON do gerente exato.
    Tenta, nessa ordem:
     1) GERENTE.json
     2) GERENTE_GONZAGA.json
     3) Qualquer arquivo que comece com GERENTE_ (ex: GERENTE_QUALQUERCOISA.json)
    Se nada for encontrado, retorna lista vazia.
    """
    base = gerente.upper().replace('.', '_')
    caminho_encontrado = None

    # 1) arquivo exato
    for sufixo in ("", "_GONZAGA"):
        nome = f"{base}{sufixo}.json"
        p = os.path.join(MENSAGENS_DIR, nome)
        if os.path.exists(p):
            caminho_encontrado = p
            break

    # 2) fallback: qualquer arquivo que inicie com base + "_"
    if not caminho_encontrado:
        for nome_arquivo in os.listdir(MENSAGENS_DIR):
            if nome_arquivo.upper().startswith(base + "_") and nome_arquivo.lower().endswith(".json"):
                caminho_encontrado = os.path.join(MENSAGENS_DIR, nome_arquivo)
                break

    # 3) se ainda nada, retorna vazio
    if not caminho_encontrado:
        return []

    # finalmente lê o JSON
    with open(caminho_encontrado, encoding="utf-8") as f:
        dados = json.load(f)

    resultado = []
    hoje = datetime.utcnow().date()
    for item in dados:
        # extrai a string de data de abertura
        data_str = item.get("data") or item.get("Data") or ""
        # tenta vários formatos
        for fmt in ("%d/%m/%Y", "%Y-%m-%d", "%d-%m-%Y"):
            try:
                data_abertura = datetime.strptime(data_str, fmt).date()
                break
            except Exception:
                data_abertura = None
        # calcula dias em aberto
        if data_abertura:
            dias_abertos = (hoje - data_abertura).days
        else:
            dias_abertos = 0

        resultado.append({
            "os":        str(item.get("os") or item.get("OS", "")),
            "frota":     str(item.get("frota") or item.get("Frota", "")),
            "data":      data_str,
            "dias":      str(dias_abertos),
            "prestador": str(item.get("prestador") or item.get("Prestador", "Prestador não definido")),
            "servico":   str(
                item.get("servico")
                or item.get("Servico")
                or item.get("observacao")
                or item.get("Observacao", "")
            )
        })
    return resultado

def carregar_prestadores():
    """Carrega a lista de prestadores a partir do arquivo prestadores.json."""
    if not os.path.exists(PRESTADORES_FILE):
        logger.error(f"Arquivo {PRESTADORES_FILE} não encontrado.")
        return []
    try:
        with open(PRESTADORES_FILE, "r", encoding="utf-8") as f:
            prestadores = json.load(f)
        # Verifica duplicatas em 'usuario'
        usuarios = [p.get('usuario', '').lower() for p in prestadores]
        duplicatas = [item for item, count in Counter(usuarios).items() if count > 1]
        if duplicatas:
            logger.warning(f"Usuários duplicados encontrados em prestadores.json: {duplicatas}")
        logger.debug(f"Prestadores carregados: {[p['usuario'] for p in prestadores]}")
        return prestadores
    except json.JSONDecodeError as e:
        logger.error(f"Erro ao decodificar {PRESTADORES_FILE}: {e}")
        return []
    except Exception as e:
        logger.error(f"Erro ao carregar prestadores: {e}")
        return []

def carregar_os_prestadores():
    """Conta OSs pendentes por prestador a partir dos arquivos em mensagens_por_prestador."""
    prestadores = carregar_prestadores()
    os_por_prestador = {}
    
    for prestador in prestadores:
        usuario = prestador.get('usuario', '').lower()
        arquivo_os = prestador.get('arquivo_os', '')
        caminho = os.path.join(MENSAGENS_PRESTADORES_DIR, arquivo_os)
        
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
    
    # Ordena por número de OSs (decrescente)
    ranking = sorted(os_por_prestador.items(), key=lambda x: x[1], reverse=True)
    return ranking

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

        # Tenta autenticar como gerente
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

        # Tenta autenticar como prestador
        prestadores = carregar_prestadores()
        if not prestadores:
            flash('Erro ao carregar lista de prestadores. Contate o administrador.', 'danger')
            logger.error("Lista de prestadores vazia ou não carregada.")
            return render_template('login.html')

        prestador = next((p for p in prestadores if p.get('usuario', '').lower() == username and p.get('senha', '') == senha), None)
        if prestador:
            ev = LoginEvent(username=username, user_type='prestador')
            db.session.add(ev)
            db.session.commit()
            session['login_event_id'] = ev.id
            session['prestador'] = prestador['usuario']
            session['prestador_nome'] = prestador.get('nome_exibicao', username)
            logger.info(f"Login bem-sucedido para prestador: {username}")
            return redirect(url_for('painel_prestador'))

        # Falha na autenticação
        flash('Usuário ou senha inválidos.', 'danger')
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
                         now=datetime.utcnow())

@app.route('/painel_prestador')
def painel_prestador():
    if 'prestador' not in session:
        return redirect(url_for('login'))

    prestadores = carregar_prestadores()
    prestador = next((p for p in prestadores if p.get('usuario', '').lower() == session['prestador']), None)
    if not prestador:
        flash('Prestador não encontrado', 'danger')
        logger.error(f"Prestador não encontrado na sessão: {session['prestador']}")
        return redirect(url_for('login'))

    caminho = os.path.join(MENSAGENS_PRESTADORES_DIR, prestador['arquivo_os'])
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

@app.route('/finalizar_os/<os_numero>', methods=['POST'])
def finalizar_os(os_numero):
    responsavel = session.get('gerente') or session.get('prestador')
    if not responsavel:
        return redirect(url_for('login'))

    # Adiciona ao banco de dados
    d = request.form['data_finalizacao']
    h = request.form['hora_finalizacao']
    o = request.form.get('observacoes','')
    fz = Finalizacao(
        os_numero=os_numero,
        gerente=responsavel,  # pode ser gerente ou prestador
        data_fin=d,
        hora_fin=h,
        observacoes=o
    )
    db.session.add(fz)

    # Remove do JSON do gerente, se for gerente
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

            # Filtra removendo a OS finalizada
            data = [item for item in data if str(item.get('os') or item.get('OS','')) != os_numero]

            with open(caminho, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)

    # Remove do JSON do prestador, se for prestador
    if 'prestador' in session:
        prestadores = carregar_prestadores()
        prestador = next((p for p in prestadores if p.get('usuario', '').lower() == session['prestador']), None)
        if prestador:
            caminho = os.path.join(MENSAGENS_PRESTADORES_DIR, prestador['arquivo_os'])
            if os.path.exists(caminho):
                with open(caminho, 'r', encoding='utf-8') as f:
                    data = json.load(f)

                # Filtra removendo a OS finalizada
                data = [item for item in data if str(item.get('os') or item.get('OS','')) != os_numero]

                with open(caminho, 'w', encoding='utf-8') as f:
                    json.dump(data, f, ensure_ascii=False, indent=2)

    db.session.commit()
    flash(f'OS {os_numero} finalizada','success')
    return redirect(url_for('painel' if 'gerente' in session else 'painel_prestador'))

@app.route('/admin')
def admin_panel():
    if not session.get('is_admin'):
        flash('Acesso negado','danger')
        return redirect(url_for('login'))
    finalizadas = Finalizacao.query.order_by(Finalizacao.registrado_em.desc()).limit(100).all()
    login_events = LoginEvent.query.order_by(LoginEvent.login_time.desc()).limit(50).all()
    users = User.query.order_by(User.username).all()
    gerentes = [u.username for u in users]
    contagem = {g: Finalizacao.query.filter_by(gerente=g).count() for g in gerentes}
    abertas = {g: len(carregar_os_gerente(g)) for g in gerentes}
    ranking_os_abertas = sorted(abertas.items(), key=lambda x: x[1], reverse=True)
    ranking_os_prestadores = carregar_os_prestadores()

    return render_template('admin.html',
                         finalizadas=finalizadas,
                         total_os=len(finalizadas),
                         gerentes=gerentes,
                         contagem_gerentes=contagem,
                         os_abertas=abertas,
                         ranking_os_abertas=ranking_os_abertas,
                         ranking_os_prestadores=ranking_os_prestadores,
                         login_events=login_events,
                         now=datetime.utcnow())

@app.route('/exportar_os_finalizadas')
def exportar_os_finalizadas():
    if not session.get('is_admin'):
        flash('Acesso negado','danger')
        return redirect(url_for('login'))
    allf = Finalizacao.query.order_by(Finalizacao.registrado_em.desc()).all()
    if not allf:
        flash('Nenhuma OS finalizada','warning')
        return redirect(url_for('admin_panel'))
    pdf_path = os.path.join(BASE_DIR,'relatorio.pdf')
    pdf = FPDF()
    pdf.add_page()
    pdf.set_font('Arial','B',12)
    pdf.cell(0,10,'Relatório de OS Finalizadas',ln=True,align='C')
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
                   download_name=f'relatorio_{datetime.utcnow():%Y%m%d}.pdf',
                   mimetype='application/pdf')

@app.route('/logout')
def logout():
    ev_id = session.pop('login_event_id', None)
    if ev_id:
        ev = LoginEvent.query.get(ev_id)
        if ev:
            ev.logout_time = datetime.utcnow()
            ev.duration_secs = int((ev.logout_time - ev.login_time).total_seconds())
            db.session.commit()
    session.clear()
    flash('Desconectado','info')
    return redirect(url_for('login'))

# garante que as tabelas serão criadas tanto no gunicorn quanto no 'python app.py'
with app.app_context():
    init_db()

# só para quem rodar 'python app.py' em dev:
if __name__ == '__main__':
    app.run(host='0.0.0.0',
           port=int(os.environ.get('PORT', 10000)),
           debug=True)
