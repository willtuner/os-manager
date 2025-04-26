from flask import Flask, render_template, request, redirect, session, url_for, flash, send_file
from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate
import json
import os
from datetime import datetime
from fpdf import FPDF

# --- App & DB setup ---
app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', os.urandom(24).hex())
app.config.update(
    SESSION_COOKIE_SECURE=True,
    SESSION_COOKIE_SAMESITE='Lax',
    SQLALCHEMY_DATABASE_URI=f"sqlite:///{os.path.join(os.path.dirname(__file__),'app.db')}",
    SQLALCHEMY_TRACK_MODIFICATIONS=False
)
db = SQLAlchemy(app)
migrate = Migrate(app, db)

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

# --- File paths & constants ---
BASE_DIR        = os.path.dirname(__file__)
MENSAGENS_DIR   = os.path.join(BASE_DIR, 'mensagens_por_gerente')
USERS_FILE      = os.path.join(BASE_DIR, 'users.json')
os.makedirs(MENSAGENS_DIR, exist_ok=True)

ADMIN_USERNAMES = {'wilson.santana'}

# --- DB initialization ---
with app.app_context():
    db.create_all()
    # importa users.json se ainda não houver usuários
    if User.query.count() == 0 and os.path.exists(USERS_FILE):
        with open(USERS_FILE, encoding='utf-8') as f:
            js = json.load(f)
        for username, pwd in js.items():
            db.session.add(User(
                username=username.lower(),
                password=pwd,
                is_admin=(username.lower() in ADMIN_USERNAMES)
            ))
        db.session.commit()

# --- Helpers ---
def carregar_os_gerente(gerente):
    base = gerente.upper().replace('.', '_') + "_GONZAGA.json"
    path = os.path.join(MENSAGENS_DIR, base)
    if not os.path.exists(path):
        prefixo = gerente.split('.')[0].upper()
        for fn in os.listdir(MENSAGENS_DIR):
            if fn.upper().startswith(prefixo) and fn.lower().endswith('.json'):
                path = os.path.join(MENSAGENS_DIR, fn)
                break
    if not os.path.exists(path):
        return []
    with open(path, encoding='utf-8') as f:
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

# --- Routes ---
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
            session['gerente']  = u
            session['is_admin'] = user.is_admin
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
                           now=datetime.now())

@app.route('/finalizar_os/<os_numero>', methods=['POST'])
def finalizar_os(os_numero):
    if 'gerente' not in session:
        return redirect(url_for('login'))
    d = request.form['data_finalizacao']
    h = request.form['hora_finalizacao']
    o = request.form.get('observacoes','')
    f = Finalizacao(os_numero=os_numero,
                    gerente=session['gerente'],
                    data_fin=d, hora_fin=h,
                    observacoes=o)
    db.session.add(f)
    db.session.commit()
    # remove do JSON
    base = session['gerente'].upper().replace('.','_') + '_GONZAGA.json'
    path = os.path.join(MENSAGENS_DIR, base)
    if not os.path.exists(path):
        pre = session['gerente'].split('.')[0].upper()
        for fn in os.listdir(MENSAGENS_DIR):
            if fn.upper().startswith(pre):
                path = os.path.join(MENSAGENS_DIR, fn)
                break
    try:
        with open(path, encoding='utf-8') as jf:
            lst = json.load(jf)
        lst = [x for x in lst if str(x.get('os') or x.get('OS','')) != os_numero]
        with open(path, 'w', encoding='utf-8') as jf:
            json.dump(lst, jf, indent=2, ensure_ascii=False)
    except:
        pass
    flash(f'OS {os_numero} finalizada','success')
    return redirect(url_for('painel'))

@app.route('/admin')
def admin_panel():
    if not session.get('is_admin'):
        flash('Acesso negado','danger')
        return redirect(url_for('login'))
    finalizadas = (Finalizacao.query
                   .order_by(Finalizacao.registrado_em.desc())
                   .limit(100).all())
    users      = User.query.order_by(User.username).all()
    gerentes   = [u.username for u in users]
    contagem   = {g: Finalizacao.query.filter_by(gerente=g).count() for g in gerentes}
    abertas    = {g: len(carregar_os_gerente(g)) for g in gerentes}
    return render_template('admin.html',
                           finalizadas=finalizadas,
                           total_os=len(finalizadas),
                           gerentes=gerentes,
                           contagem_gerentes=contagem,
                           os_abertas=abertas,
                           now=datetime.now())

@app.route('/exportar_os_finalizadas')
def exportar_os_finalizadas():
    if not session.get('is_admin'):
        flash('Acesso negado','danger')
        return redirect(url_for('login'))
    allf = Finalizacao.query.order_by(Finalizacao.registrado_em.desc()).all()
    if not allf:
        flash('Nenhuma OS finalizada','warning')
        return redirect(url_for('admin_panel'))
    pdf_path = os.path.join(BASE_DIR, 'relatorio.pdf')
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
                     download_name=f'relatorio_{datetime.now():%Y%m%d}.pdf',
                     mimetype='application/pdf')

@app.route('/logout')
def logout():
    session.clear()
    flash('Desconectado','info')
    return redirect(url_for('login'))

if __name__ == '__main__':
    app.run(host='0.0.0.0',
            port=int(os.environ.get('PORT',10000)),
            debug=True)
