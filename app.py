import os
import json
from datetime import datetime
from flask import Flask, render_template, request, redirect, session, url_for, flash, send_file
from flask_sqlalchemy import SQLAlchemy
from fpdf import FPDF

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
    gerente        = db.Column(db.String(80), nullable=False)
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

# --- Constantes de caminho e inicialização do JSON ---
BASE_DIR      = os.path.dirname(__file__)
MENSAGENS_DIR = os.path.join(BASE_DIR, 'mensagens_por_gerente')
USERS_FILE    = os.path.join(BASE_DIR, 'users.json')
os.makedirs(MENSAGENS_DIR, exist_ok=True)

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

# --- Helpers para carregar JSON de OS pendentes ---
def carregar_os_gerente(gerente):
    base = gerente.upper().replace('.', '_') + "_GONZAGA.json"
    caminho = os.path.join(MENSAGENS_DIR, base)
    if not os.path.exists(caminho):
        prefixo = gerente.split('.')[0].upper()
        for fn in os.listdir(MENSAGENS_DIR):
            if fn.upper().startswith(prefixo) and fn.lower().endswith('.json'):
                caminho = os.path.join(MENSAGENS_DIR, fn)
                break
    if not os.path.exists(caminho):
        return []
    with open(caminho, encoding='utf-8') as f:
        data = json.load(f)
    out = []
    for i in data:
        out.append({
            'os':        str(i.get('os') or i.get('OS','')),
            'frota':     str(i.get('frota') or i.get('Frota','')),
            'data':      str(i.get('data') or i.get('Data','')),
            'dias':      str(i.get('dias') or i.get('Dias','0')),
            'prestador': str(i.get('prestador') or i.get('Prestador','Prestador não definido')),
            'servico':   str(i.get('servico') or i.get('Servico') or i.get('observacao') or i.get('Observacao',''))
        })
    return out

# --- Rotas ---
@app.route('/')
def index():
    return redirect(url_for('login'))

@app.route('/login', methods=['GET','POST'])
def login():
    if request.method == 'POST':
        u = request.form['gerente'].strip().lower()
        p = request.form['senha'].strip()
        user = User.query.filter_by(username=u).first()
        if user and user.password == p:
            ev = LoginEvent(username=u)
            db.session.add(ev)
            db.session.commit()
            session['login_event_id'] = ev.id
            session['gerente']        = u
            session['is_admin']       = user.is_admin
            return redirect(url_for('admin_panel' if user.is_admin else 'painel'))
        flash('Usuário ou senha inválidos','danger')
    return render_template('login.html')

@app.route('/painel')
def painel():
    if 'gerente' not in session:
        return redirect(url_for('login'))
    pend = carregar_os_gerente(session['gerente'])
    return render_template('painel.html',
                           os_pendentes=pend,
                           gerente=session['gerente'],
                           now=datetime.utcnow())

@app.route('/finalizar_os/<os_numero>', methods=['POST'])
def finalizar_os(os_numero):
    if 'gerente' not in session:
        return redirect(url_for('login'))
    d = request.form['data_finalizacao']
    h = request.form['hora_finalizacao']
    o = request.form.get('observacoes','')
    fz = Finalizacao(os_numero=os_numero,
                     gerente=session['gerente'],
                     data_fin=d, hora_fin=h,
                     observacoes=o)
    db.session.add(fz)
    db.session.commit()
    # ... código de remoção do JSON permanece igual ...
    flash(f'OS {os_numero} finalizada','success')
    return redirect(url_for('painel'))

@app.route('/admin')
def admin_panel():
    if not session.get('is_admin'):
        flash('Acesso negado','danger')
        return redirect(url_for('login'))
    finalizadas  = Finalizacao.query.order_by(Finalizacao.registrado_em.desc()).limit(100).all()
    login_events = LoginEvent.query.order_by(LoginEvent.login_time.desc()).limit(50).all()
    users        = User.query.order_by(User.username).all()
    gerentes     = [u.username for u in users]
    contagem     = {g: Finalizacao.query.filter_by(gerente=g).count() for g in gerentes}
    abertas      = {g: len(carregar_os_gerente(g)) for g in gerentes}
    return render_template('admin.html',
                           finalizadas=finalizadas,
                           total_os=len(finalizadas),
                           gerentes=gerentes,
                           contagem_gerentes=contagem,
                           os_abertas=abertas,
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
    pdf = FPDF(); pdf.add_page(); pdf.set_font('Arial','B',12)
    pdf.cell(0,10,'Relatório de OS Finalizadas',ln=True,align='C'); pdf.ln(5)
    cols, w = ['OS','Gerente','Data','Hora','Obs'], [20,40,30,25,75]
    pdf.set_font('Arial','B',10)
    for c,width in zip(cols,w): pdf.cell(width,8,c,border=1)
    pdf.ln(); pdf.set_font('Arial','',9)
    for r in allf:
        pdf.cell(w[0],6,r.os_numero,border=1)
        pdf.cell(w[1],6,r.gerente,   border=1)
        pdf.cell(w[2],6,r.data_fin,  border=1)
        pdf.cell(w[3],6,r.hora_fin,  border=1)
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
            ev.logout_time   = datetime.utcnow()
            ev.duration_secs = int((ev.logout_time - ev.login_time).total_seconds())
            db.session.commit()
    session.clear()
    flash('Desconectado','info')
    return redirect(url_for('login'))

# --- Inicializa o banco e executa ---
if __name__ == '__main__':
    with app.app_context():
        init_db()
    app.run(host='0.0.0.0',
            port=int(os.environ.get('PORT', 10000)),
            debug=True)
