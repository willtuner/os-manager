import os
import json
from datetime import datetime
from flask import Flask, render_template, request, redirect, session, url_for, flash, send_file
from flask_sqlalchemy import SQLAlchemy
from fpdf import FPDF
from extract_prestadores import extract_prestadores  # seu script de extração de prestadores

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
    id        = db.Column(db.Integer, primary_key=True)
    username  = db.Column(db.String(80), unique=True, nullable=False)
    password  = db.Column(db.String(128), nullable=False)
    is_admin  = db.Column(db.Boolean, default=False)

class Finalizacao(db.Model):
    __tablename__ = 'finalizacoes'
    id             = db.Column(db.Integer, primary_key=True)
    os_numero      = db.Column(db.String(50), nullable=False)
    gerente        = db.Column(db.String(80))   # null se for prestador
    prestador      = db.Column(db.String(80))   # opcional: quem finalizou
    data_fin       = db.Column(db.String(10), nullable=False)
    hora_fin       = db.Column(db.String(5), nullable=False)
    observacoes    = db.Column(db.Text)
    registrado_em  = db.Column(db.DateTime, default=datetime.utcnow)

class LoginEvent(db.Model):
    __tablename__ = 'login_events'
    id            = db.Column(db.Integer, primary_key=True)
    username      = db.Column(db.String(80), nullable=False)
    login_time    = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    logout_time   = db.Column(db.DateTime)
    duration_secs = db.Column(db.Integer)

# --- Constantes de caminho ---
BASE_DIR        = os.path.dirname(__file__)
MENSAGENS_DIR   = os.path.join(BASE_DIR, 'mensagens_por_gerente')
PRESTADORES_DIR = os.path.join(BASE_DIR, 'mensagens_por_prestador')
USERS_FILE      = os.path.join(BASE_DIR, 'users.json')

# garante pastas
os.makedirs(MENSAGENS_DIR, exist_ok=True)
os.makedirs(PRESTADORES_DIR, exist_ok=True)

def init_db():
    """Cria tabelas e importa users.json na tabela users, se vazia."""
    db.create_all()
    if User.query.count() == 0 and os.path.exists(USERS_FILE):
        with open(USERS_FILE, encoding='utf-8') as f:
            js = json.load(f)
        admins = {'wilson.santana'}  # quem vira admin
        for u, pwd in js.items():
            db.session.add(User(
                username=u.lower(),
                password=pwd,
                is_admin=(u.lower() in admins)
            ))
        db.session.commit()

# --- Helpers para carregar OS ---
def carregar_os_gerente(gerente):
    base = gerente.upper().replace('.', '_')
    # tenta GERENTE.json e GERENTE_GONZAGA.json
    candidatos = [f"{base}.json", f"{base}_GONZAGA.json"]
    caminho = None
    for nome in candidatos:
        p = os.path.join(MENSAGENS_DIR, nome)
        if os.path.exists(p):
            caminho = p; break
    # fallback: qualquer que comece com base_
    if not caminho:
        for fn in os.listdir(MENSAGENS_DIR):
            if fn.upper().startswith(base + '_') and fn.lower().endswith('.json'):
                caminho = os.path.join(MENSAGENS_DIR, fn)
                break
    if not caminho:
        return []

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
            'os':        str(it.get('os') or it.get('OS','')),
            'frota':     str(it.get('frota') or it.get('Frota','')),
            'data':      data_str,
            'dias':      str(dias),
            'prestador': str(it.get('prestador') or it.get('Prestador','Prestador não definido')),
            'servico':   str(it.get('servico') or it.get('Servico') or it.get('observacao') or it.get('Observacao',''))
        })
    return resultado

def carregar_os_prestador(prest):
    caminho = os.path.join(PRESTADORES_DIR, f"{prest}.json")
    if not os.path.exists(caminho):
        return []
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
            'os':      str(it.get('os') or it.get('OS','')),
            'frota':   str(it.get('frota') or it.get('Frota','')),
            'data':    data_str,
            'dias':    str(dias),
            'servico': str(it.get('servico') or it.get('Servico') or it.get('observacao') or it.get('Observacao',''))
        })
    return resultado

# --- Rotas de Autenticação ---
@app.route('/')
def index():
    return redirect(url_for('login'))

@app.route('/login', methods=['GET','POST'])
def login():
    erro = None
    if request.method == 'POST':
        u = request.form['gerente'].strip().lower()
        p = request.form['senha'].strip()
        user = User.query.filter_by(username=u).first()
        if user and user.password == p:
            ev = LoginEvent(username=u)
            db.session.add(ev); db.session.commit()
            session['login_event_id'] = ev.id
            session['user_type'] = 'gerente'
            session['user']      = u
            return redirect(url_for('painel'))
        flash('Usuário ou senha inválidos','danger')
    return render_template('login.html', erro=erro)

@app.route('/login_prestador', methods=['GET','POST'])
def login_prestador():
    erro = None
    if request.method=='POST':
        key   = request.form['prestador_key'].strip().lower()
        senha = request.form['senha'].strip()
        users = json.load(open(USERS_FILE, encoding='utf-8'))
        if users.get(key) == senha:
            ev = LoginEvent(username=key)
            db.session.add(ev); db.session.commit()
            session['login_event_id'] = ev.id
            session['user_type'] = 'prestador'
            session['user']      = key
            return redirect(url_for('painel_prestador'))
        flash('Chave ou senha inválidos','danger')
    return render_template('login_prestador.html', erro=erro)

# --- Painéis ---
@app.route('/painel')
def painel():
    if session.get('user_type') != 'gerente':
        return redirect(url_for('login'))
    u    = session['user']
    pend = carregar_os_gerente(u)
    return render_template('painel.html',
                           os_pendentes=pend,
                           gerente=u,
                           now=datetime.utcnow())

@app.route('/painel_prestador')
def painel_prestador():
    if session.get('user_type') != 'prestador':
        return redirect(url_for('login_prestador'))
    p    = session['user']
    pend = carregar_os_prestador(p)
    return render_template('painel_prestador.html',
                           os_pendentes=pend,
                           prestador=p,
                           now=datetime.utcnow())

# --- Finalização de OS (ambos) ---
@app.route('/finalizar_os/<os_numero>', methods=['POST'])
def finalizar_os(os_numero):
    if 'user_type' not in session:
        return redirect(url_for('login'))
    tipo = session['user_type']
    user = session['user']
    d = request.form['data_finalizacao']
    h = request.form['hora_finalizacao']
    o = request.form.get('observacoes','')
    fz = Finalizacao(
        os_numero=os_numero,
        gerente=(user if tipo=='gerente' else None),
        prestador=(user if tipo=='prestador' else None),
        data_fin=d, hora_fin=h,
        observacoes=o
    )
    db.session.add(fz); db.session.commit()
    flash(f'OS {os_numero} finalizada','success')
    return redirect(url_for('painel' if tipo=='gerente' else 'painel_prestador'))

# --- Painel Administrativo ---
@app.route('/admin')
def admin_panel():
    if session.get('user_type') != 'gerente' or not session.get('user') in [u.username for u in User.query.filter_by(is_admin=True)]:
        flash('Acesso não autorizado','danger')
        return redirect(url_for('login'))
    finalizadas = Finalizacao.query.order_by(Finalizacao.registrado_em.desc()).limit(100).all()
    login_events = LoginEvent.query.order_by(LoginEvent.login_time.desc()).limit(50).all()
    # contagens
    gerentes = [u.username for u in User.query.order_by(User.username).all() if u.is_admin or True]
    contagem_f = {g: Finalizacao.query.filter_by(gerente=g).count() for g in gerentes}
    contagem_p = {g: Finalizacao.query.filter_by(prestador=g).count() for g in gerentes}
    os_abertas = {g: len(carregar_os_gerente(g)) for g in gerentes}
    return render_template('admin.html',
                           finalizadas=finalizadas,
                           login_events=login_events,
                           cont_gerentes=contagem_f,
                           cont_prest=contagem_p,
                           os_abertas=os_abertas,
                           now=datetime.utcnow(),
                           gerentes=gerentes)

# --- Exportar PDF ---
@app.route('/exportar_os_finalizadas')
def exportar_os_finalizadas():
    if session.get('user_type')!='gerente':
        return redirect(url_for('login'))
    allf = Finalizacao.query.order_by(Finalizacao.registrado_em.desc()).all()
    if not allf:
        flash('Nenhuma OS finalizada','warning'); return redirect(url_for('admin_panel'))
    pdf_path = os.path.join(BASE_DIR,'relatorio_finalizacoes.pdf')
    pdf = FPDF()
    pdf.add_page(); pdf.set_font('Arial','B',12)
    pdf.cell(0,10,'Relatório de OS Finalizadas',ln=True,align='C'); pdf.ln(5)
    cols, w = ['OS','Gerente','Prest.','Data','Hora','Obs'], [20,30,30,25,20,60]
    pdf.set_font('Arial','B',10)
    for c,width in zip(cols,w): pdf.cell(width,8,c,border=1)
    pdf.ln(); pdf.set_font('Arial','',9)
    for r in allf:
        pdf.cell(w[0],6,r.os_numero,border=1)
        pdf.cell(w[1],6,(r.gerente or ''),border=1)
        pdf.cell(w[2],6,(r.prestador or ''),border=1)
        pdf.cell(w[3],6,r.data_fin,border=1)
        pdf.cell(w[4],6,r.hora_fin,border=1)
        pdf.cell(w[5],6,(r.observacoes or '')[:40],border=1)
        pdf.ln()
    pdf.output(pdf_path)
    return send_file(pdf_path, as_attachment=True, download_name=f"relatorio_{datetime.utcnow():%Y%m%d}.pdf")

# --- Logout e registrar logout_time ---
@app.route('/logout')
def logout():
    ev_id = session.pop('login_event_id', None)
    if ev_id:
        ev = LoginEvent.query.get(ev_id)
        ev.logout_time   = datetime.utcnow()
        ev.duration_secs = int((ev.logout_time - ev.login_time).total_seconds())
        db.session.commit()
    session.clear()
    flash('Desconectado','info')
    return redirect(url_for('login'))

# --- Boot ---
with app.app_context():
    init_db()
    extract_prestadores()

if __name__ == '__main__':
    app.run(host='0.0.0.0',
            port=int(os.environ.get('PORT',10000)),
            debug=True)
