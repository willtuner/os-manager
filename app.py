import os
import json
from datetime import datetime
from flask import Flask, render_template, request, redirect, session, url_for, flash
from flask_sqlalchemy import SQLAlchemy

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
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password = db.Column(db.String(128), nullable=False)
    is_admin = db.Column(db.Boolean, default=False)
    is_gerente = db.Column(db.Boolean, default=False)

class Finalizacao(db.Model):
    __tablename__ = 'finalizacao'
    id = db.Column(db.Integer, primary_key=True)
    os_numero = db.Column(db.String(50), nullable=False)
    prestador = db.Column(db.String(80))
    gerente = db.Column(db.String(80))
    data_fin = db.Column(db.String(10), nullable=False)
    hora_fin = db.Column(db.String(5), nullable=False)
    observacoes = db.Column(db.Text)
    registrado_em = db.Column(db.DateTime, default=datetime.utcnow)

# --- Diretórios e arquivos ---
BASE_DIR = os.path.dirname(__file__)
GERENTES_DIR = os.path.join(BASE_DIR, 'mensagens_por_gerente')
PRESTADORES_DIR = os.path.join(BASE_DIR, 'mensagens_por_prestador')
USERS_FILE = os.path.join(BASE_DIR, 'users.json')

os.makedirs(GERENTES_DIR, exist_ok=True)
os.makedirs(PRESTADORES_DIR, exist_ok=True)

def init_db():
    with app.app_context():
        db.create_all()
        if User.query.count() == 0 and os.path.exists(USERS_FILE):
            try:
                with open(USERS_FILE, encoding='utf-8') as f:
                    users_data = json.load(f)
                
                # Processa admin
                for username, info in users_data['admin'].items():
                    db.session.add(User(
                        username=username.lower(),
                        password=info['password'],
                        is_admin=info['is_admin'],
                        is_gerente=info['is_gerente']
                    ))
                
                # Processa gerentes
                for username, info in users_data['gerentes'].items():
                    db.session.add(User(
                        username=username.lower(),
                        password=info['password'],
                        is_admin=info['is_admin'],
                        is_gerente=info['is_gerente']
                    ))
                
                # Processa prestadores
                for username, info in users_data['prestadores'].items():
                    db.session.add(User(
                        username=username.lower(),
                        password=info['password'],
                        is_admin=info['is_admin'],
                        is_gerente=info['is_gerente']
                    ))
                
                db.session.commit()
            except Exception as e:
                print(f"Erro ao inicializar banco: {str(e)}")
                db.session.rollback()

def carregar_os_gerente(username):
    """Carrega OS específicas para gerentes"""
    try:
        # Remove números e pontos do username
        clean_id = ''.join([c for c in username if not c.isdigit()]).rstrip('.')
        filename = f"{clean_id.replace('.', '_').upper()}.json"
        filepath = os.path.join(GERENTES_DIR, filename)
        
        if os.path.exists(filepath):
            with open(filepath, encoding='utf-8') as f:
                data = json.load(f)
                return data if isinstance(data, list) else [data]
    except Exception as e:
        print(f"Erro ao carregar OS para gerente {username}: {str(e)}")
    return []

def carregar_os_prestador(username):
    """Carrega OS específicas para prestadores"""
    try:
        # Remove números e pontos, mantendo apenas nome
        clean_id = ' '.join([part for part in username.replace('.', ' ').split() if not part.isdigit()])
        
        # Busca todos arquivos que contenham partes do nome
        for filename in os.listdir(PRESTADORES_DIR):
            if filename.startswith("OS_") and all(part.upper() in filename.upper() for part in clean_id.split()):
                with open(os.path.join(PRESTADORES_DIR, filename), encoding='utf-8') as f:
                    data = json.load(f)
                    if isinstance(data, dict) and 'ORDENS_DE_SERVICO' in data:
                        return data['ORDENS_DE_SERVICO']
                    return data if isinstance(data, list) else [data]
    except Exception as e:
        print(f"Erro ao carregar OS para prestador {username}: {str(e)}")
    return []

def processar_os_items(items):
    """Processa itens de OS para exibição"""
    resultado = []
    hoje = datetime.utcnow().date()
    
    for item in items:
        try:
            # Extração robusta de campos
            os_num = str(item.get('os') or item.get('NO-SERVIÇO') or item.get('numero') or '')
            frota = str(item.get('frota') or item.get('CD_EQT') or item.get('equipamento') or '')
            servico = str(item.get('servico') or item.get('SERVIÇO') or item.get('descricao') or '')
            prestador = str(item.get('prestador') or item.get('PREST_SERVIÇO') or 'Prestador não definido')
            
            # Processamento de data
            data_str = item.get('data') or item.get('DT_ENTRADA') or item.get('data_entrada') or ''
            data_dt = None
            for fmt in ('%d/%m/%Y', '%Y-%m-%d', '%d-%m-%Y'):
                try:
                    data_dt = datetime.strptime(data_str, fmt).date()
                    break
                except:
                    continue
            
            dias = (hoje - data_dt).days if data_dt else 0
            
            resultado.append({
                'os': os_num,
                'frota': frota,
                'data': data_str,
                'dias': dias,
                'servico': servico,
                'prestador': prestador
            })
        except Exception as e:
            print(f"Erro ao processar item: {item}\n{str(e)}")
    
    return resultado

# --- Rotas ---
@app.route('/')
def home():
    return redirect(url_for('login'))

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form.get('username', '').strip().lower()
        password = request.form.get('password', '').strip()
        
        user = User.query.filter_by(username=username).first()
        
        if user and user.password == password:
            session['user'] = user.username
            if user.is_admin:
                session['type'] = 'admin'
                return redirect(url_for('admin_panel'))
            elif user.is_gerente:
                session['type'] = 'gerente'
                return redirect(url_for('painel_gerente'))
            else:
                session['type'] = 'prestador'
                return redirect(url_for('painel_prestador'))
        
        flash('Credenciais inválidas', 'danger')
    return render_template('login.html')

@app.route('/logout')
def logout():
    session.clear()
    flash('Desconectado com sucesso', 'info')
    return redirect(url_for('login'))

@app.route('/painel_gerente')
def painel_gerente():
    if 'user' not in session or session.get('type') != 'gerente':
        flash('Acesso não autorizado', 'danger')
        return redirect(url_for('login'))
    
    user_id = session['user']
    os_items = carregar_os_gerente(user_id)
    pendentes = processar_os_items(os_items)
    
    return render_template('painel.html', 
                         os_pendentes=pendentes,
                         gerente=user_id)

@app.route('/painel_prestador')
def painel_prestador():
    if 'user' not in session or session.get('type') != 'prestador':
        flash('Acesso não autorizado', 'danger')
        return redirect(url_for('login'))
    
    prestador_id = session['user']
    os_items = carregar_os_prestador(prestador_id)
    pendentes = processar_os_items(os_items)
    
    return render_template('painel_prestador.html',
                         os_pendentes=pendentes,
                         prestador=prestador_id)

@app.route('/finalizar/<os_numero>', methods=['POST'])
def finalizar_os(os_numero):
    if 'user' not in session:
        flash('Sessão expirada', 'danger')
        return redirect(url_for('login'))
    
    dados = {
        'os_numero': os_numero,
        session['type']: session['user'],
        'data_fin': request.form.get('data_finalizacao', ''),
        'hora_fin': request.form.get('hora_finalizacao', ''),
        'observacoes': request.form.get('observacoes', '')
    }
    
    try:
        db.session.add(Finalizacao(**dados))
        db.session.commit()
        flash(f'OS {os_numero} finalizada com sucesso!', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'Erro ao finalizar OS: {str(e)}', 'danger')
    
    return redirect(url_for(f"painel_{session['type']}"))

@app.route('/admin')
def admin_panel():
    if 'user' not in session or session.get('type') != 'admin':
        flash('Acesso não autorizado', 'danger')
        return redirect(url_for('login'))
    
    finalizadas = Finalizacao.query.order_by(Finalizacao.registrado_em.desc()).all()
    contagem = {}
    
    for fz in finalizadas:
        key = fz.gerente or fz.prestador
        contagem[key] = contagem.get(key, 0) + 1
    
    return render_template('admin.html',
                         finalizadas=finalizadas,
                         contagem_gerentes=contagem,
                         total_os=len(finalizadas))

# --- Inicialização ---
if __name__ == '__main__':
    init_db()
    app.run(debug=True)
