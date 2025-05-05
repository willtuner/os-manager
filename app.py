import os
import json
from datetime import datetime
from flask import Flask, render_template, request, redirect, session, url_for, flash
from flask_sqlalchemy import SQLAlchemy
from fpdf import FPDF

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
    __tablename__ = 'user'
    id        = db.Column(db.Integer,   primary_key=True)
    username  = db.Column(db.String(80), unique=True, nullable=False)
    password  = db.Column(db.String(128), nullable=False)
    is_admin  = db.Column(db.Boolean,    default=False)

class Finalizacao(db.Model):
    __tablename__ = 'finalizacao'
    id            = db.Column(db.Integer,   primary_key=True)
    os_numero     = db.Column(db.String(50), nullable=False)
    prestador     = db.Column(db.String(80))
    gerente       = db.Column(db.String(80))
    data_fin      = db.Column(db.String(10), nullable=False)
    hora_fin      = db.Column(db.String(5),  nullable=False)
    observacoes   = db.Column(db.Text)
    registrado_em = db.Column(db.DateTime, default=datetime.utcnow)

# --- Diretórios e arquivos ---
BASE_DIR        = os.path.dirname(__file__)
GERENTES_DIR    = os.path.join(BASE_DIR, 'mensagens_por_gerente')
PRESTADORES_DIR = os.path.join(BASE_DIR, 'mensagens_por_prestador')
USERS_FILE      = os.path.join(BASE_DIR, 'users.json')

os.makedirs(GERENTES_DIR, exist_ok=True)
os.makedirs(PRESTADORES_DIR, exist_ok=True)

def init_db():
    db.create_all()
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

def carregar_json(dirpath, key):
    print(f"\n[DEBUG] Buscando arquivos para: {key} em {dirpath}")
    data = []
    
    # Padrão de nomes para gerentes (ADRIANO_CLAUDIO_FIRMINO.json)
    if dirpath == GERENTES_DIR:
        filename = f"{key.replace('.', '_').upper()}.json"
        filepath = os.path.join(dirpath, filename)
        
        if os.path.exists(filepath):
            print(f"[DEBUG] Arquivo de gerente encontrado: {filename}")
            with open(filepath, encoding='utf-8') as f:
                content = json.load(f)
                if isinstance(content, list):
                    data.extend(content)
                else:
                    data.append(content)  # Converte objeto único em lista

    # Padrão para prestadores (OS_NOME PRESTADOR.json)
    else:
        search_parts = key.replace('.', ' ').lower().split()
        
        for filename in os.listdir(dirpath):
            if not filename.startswith('OS_') or not filename.endswith('.json'):
                continue
                
            # Verifica matching parcial (ex: "anderson.bicudo" → "OS_ANDERSON DIEGO BICUDO...")
            if all(part in filename.lower() for part in search_parts):
                print(f"[DEBUG] Arquivo de prestador encontrado: {filename}")
                with open(os.path.join(dirpath, filename), encoding='utf-8') as f:
                    content = json.load(f)
                    if isinstance(content, dict) and 'ORDENS_DE_SERVICO' in content:
                        data.extend(content['ORDENS_DE_SERVICO'])

    print(f"[DEBUG] Total de OS carregadas: {len(data)}")
    return data

def montar_lista(items):
    out = []
    hoje = datetime.utcnow().date()
    
    for item in items:
        try:
            # Trata ambos formatos
            os_num = str(item.get('os') or item.get('NO-SERVIÇO') or '')
            frota = str(item.get('frota') or item.get('CD_EQT') or '')
            servico = str(item.get('servico') or item.get('SERVIÇO') or '')
            prestador = str(item.get('prestador') or item.get('PREST_SERVIÇO', 'Prestador não definido'))
            
            # Processamento de data
            data_str = item.get('data') or item.get('DT_ENTRADA') or ''
            data_dt = None
            for fmt in ('%d/%m/%Y', '%Y-%m-%d', '%d-%m-%Y'):
                try:
                    data_dt = datetime.strptime(data_str, fmt).date()
                    break
                except:
                    continue
            
            dias = (hoje - data_dt).days if data_dt else 0
            
            out.append({
                'os': os_num,
                'frota': frota,
                'data': data_str,
                'dias': dias,
                'servico': servico,
                'prestador': prestador
            })
            
        except Exception as e:
            print(f"[ERRO] Erro ao processar item: {item}\nErro: {str(e)}")
    
    return out


@app.route('/teste_carregar/<tipo>/<nome>')
def teste_carregar(tipo, nome):
    dirpath = GERENTES_DIR if tipo == 'gerente' else PRESTADORES_DIR
    dados = carregar_json(dirpath, nome)
    return jsonify({
        'tipo': tipo,
        'nome': nome,
        'dados_brutos': dados,
        'dados_processados': montar_lista(dados)
    })

# --- Rotas Gerente ---
@app.route('/')
def home():
    return redirect(url_for('login'))

@app.route('/login', methods=['GET','POST'])
def login():
    erro = None
    if request.method == 'POST':
        u = request.form['gerente'].strip().lower()
        p = request.form['senha'].strip()
        user = User.query.filter_by(username=u).first()
        if user and user.password == p:
            session['type'] = 'gerente'
            session['user'] = u
            return redirect(url_for('painel_gerente'))
        flash('Credenciais inválidas','danger')
    return render_template('login.html', erro=erro)

@app.route('/painel_gerente')
def painel_gerente():
    if session.get('type') != 'gerente':
        return redirect(url_for('login'))
    
    user_key = session['user'].replace('.', '_').upper()  # Converte "adriano.claudio" → "ADRIANO_CLAUDIO"
    pendentes = montar_lista(carregar_json(GERENTES_DIR, user_key))
    
    return render_template('painel.html', os_pendentes=pendentes, gerente=session['user'])

@app.route('/painel_prestador')
def painel_prestador():
    if session.get('type') != 'prestador':
        return redirect(url_for('login_prestador'))
    
    pendentes = montar_lista(carregar_json(PRESTADORES_DIR, session['user']))
    return render_template('painel_prestador.html', os_pendentes=pendentes, prestador=session['user'])

# --- Rotas Prestador ---
@app.route('/login_prestador', methods=['GET','POST'])
def login_prestador():
    erro = None
    if request.method == 'POST':
        key = request.form['prestador_key'].strip().lower()
        p   = request.form['senha'].strip()
        users = json.load(open(USERS_FILE, encoding='utf-8'))
        if users.get(key) == p:
            session['type'] = 'prestador'
            session['user'] = key
            return redirect(url_for('painel_prestador'))
        flash('Chave ou senha inválidos','danger')
    return render_template('login_prestador.html', erro=erro)

@app.route('/painel_prestador')
def painel_prestador():
    if session.get('type') != 'prestador':
        return redirect(url_for('login_prestador'))
    pend = montar_lista(carregar_json(PRESTADORES_DIR, session['user']))
    return render_template('painel_prestador.html',
                           os_pendentes=pend,
                           prestador=session['user'])

# --- Finalizar OS ---
@app.route('/finalizar/<os_numero>', methods=['POST'])
def finalizar(os_numero):
    tipo = session.get('type')
    if tipo not in ('gerente','prestador'):
        return redirect(url_for('login'))
    dados = {
        'os_numero':   os_numero,
        'gerente':     session['user'] if tipo=='gerente'   else None,
        'prestador':   session['user'] if tipo=='prestador' else None,
        'data_fin':    request.form['data_finalizacao'],
        'hora_fin':    request.form['hora_finalizacao'],
        'observacoes': request.form.get('observacoes','')
    }
    db.session.add(Finalizacao(**dados))
    db.session.commit()
    flash(f'OS {os_numero} finalizada','success')
    return (redirect(url_for('painel_gerente'))
            if tipo=='gerente'
            else redirect(url_for('painel_prestador')))

@app.route('/logout')
def logout():
    session.clear()
    flash('Desconectado com sucesso','info')
    return redirect(url_for('login'))

# --- Inicializa o banco ---
with app.app_context():
    init_db()

if __name__ == '__main__':
    app.run(debug=True)
