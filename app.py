import os
import json
from datetime import datetime
from flask import Flask, render_template, request, redirect, session, url_for, flash, jsonify
from flask_sqlalchemy import SQLAlchemy

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', os.urandom(24).hex())
app.config['SQLALCHEMY_DATABASE_URI'] = os.environ.get(
    'DATABASE_URL', f"sqlite:///{os.path.join(os.path.dirname(__file__), 'app.db')}"
)
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
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
    prestador = db.Column(db.String(80))
    gerente = db.Column(db.String(80))
    data_fin = db.Column(db.String(10), nullable=False)
    hora_fin = db.Column(db.String(5), nullable=False)
    observacoes = db.Column(db.Text)
    registrado_em = db.Column(db.DateTime, default=datetime.utcnow)

# --- Configurações de diretórios ---
BASE_DIR = os.path.dirname(__file__)
GERENTES_DIR = os.path.join(BASE_DIR, 'mensagens_por_gerente')
PRESTADORES_DIR = os.path.join(BASE_DIR, 'mensagens_por_prestador')
USERS_FILE = os.path.join(BASE_DIR, 'users.json')

# Garante que os diretórios existam
os.makedirs(GERENTES_DIR, exist_ok=True)
os.makedirs(PRESTADORES_DIR, exist_ok=True)

def init_db():
    with app.app_context():
        db.create_all()
        if User.query.count() == 0 and os.path.exists(USERS_FILE):
            with open(USERS_FILE, encoding='utf-8') as f:
                users_data = json.load(f)
            for username, password in users_data.items():
                db.session.add(User(
                    username=username.lower(),
                    password=password,
                    is_admin=(username.lower() == 'wilson.santana')
                ))
            db.session.commit()

def carregar_os(dirpath, identifier):
    """Carrega OS com tratamento robusto para diferentes formatos"""
    print(f"\n[DEBUG] Buscando OS para '{identifier}' em {dirpath}")
    data = []
    
    # Para gerentes (formato NOME_SOBRENOME.json)
    if dirpath == GERENTES_DIR:
        filename = f"{identifier.replace('.', '_').upper()}.json"
        filepath = os.path.join(dirpath, filename)
        
        if os.path.exists(filepath):
            print(f"[DEBUG] Tentando ler: {filepath}")
            try:
                with open(filepath, 'r', encoding='utf-8') as f:
                    content = json.load(f)
                    data.extend(content if isinstance(content, list) else [content])
            except Exception as e:
                print(f"[ERRO] Falha ao ler {filename}: {str(e)}")
    
    # Para prestadores (formato OS_NOME*.json)
    else:
        search_parts = identifier.replace('.', ' ').lower().split()
        
        for filename in os.listdir(dirpath):
            if filename.lower().startswith('os_') and filename.lower().endswith('.json'):
                if all(part in filename.lower() for part in search_parts):
                    filepath = os.path.join(dirpath, filename)
                    try:
                        with open(filepath, 'r', encoding='utf-8') as f:
                            content = json.load(f)
                            if isinstance(content, dict) and 'ORDENS_DE_SERVICO' in content:
                                data.extend(content['ORDENS_DE_SERVICO'])
                            elif isinstance(content, list):
                                data.extend(content)
                    except Exception as e:
                        print(f"[ERRO] Falha ao ler {filename}: {str(e)}")

    print(f"[DEBUG] Total de OS carregadas: {len(data)}")
    return data

def processar_os_items(items):
    """Processa itens de OS com tratamento robusto"""
    resultado = []
    hoje = datetime.utcnow().date()
    
    for item in items:
        try:
            # Extração de campos com múltiplos nomes possíveis
            os_num = str(item.get('os') or item.get('NO-SERVIÇO') or item.get('numero') or '')
            frota = str(item.get('frota') or item.get('CD_EQT') or item.get('equipamento') or '')
            servico = str(item.get('servico') or item.get('SERVIÇO') or item.get('descricao') or '')
            prestador = str(item.get('prestador') or item.get('PREST_SERVIÇO') or 'Prestador não definido')
            
            # Processamento de data com múltiplos formatos
            data_str = item.get('data') or item.get('DT_ENTRADA') or item.get('data_entrada') or ''
            data_dt = None
            for fmt in ('%d/%m/%Y', '%Y-%m-%d', '%d-%m-%Y', '%m/%d/%Y'):
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
            print(f"[ERRO] Item inválido ignorado: {item}\nErro: {str(e)}")
    
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
            session['user'] = username
            session['type'] = 'gerente' if '.' in username else 'prestador'
            return redirect(url_for('painel_gerente' if session['type'] == 'gerente' else 'painel_prestador'))
        
        flash('Credenciais inválidas', 'danger')
    return render_template('login.html')

@app.route('/painel_gerente')
def painel_gerente():
    if session.get('type') != 'gerente':
        return redirect(url_for('login'))
    
    user_id = session['user']
    os_items = carregar_os(GERENTES_DIR, user_id)
    
    # Fallback: se não encontrou como gerente, tenta como prestador
    if not os_items:
        os_items = carregar_os(PRESTADORES_DIR, user_id)
    
    pendentes = processar_os_items(os_items)
    return render_template('painel.html', 
                         os_pendentes=pendentes,
                         gerente=user_id)

@app.route('/painel_prestador')
def painel_prestador():
    if session.get('type') != 'prestador':
        return redirect(url_for('login'))
    
    prestador_id = session['user']
    os_items = carregar_os(PRESTADORES_DIR, prestador_id)
    pendentes = processar_os_items(os_items)
    
    if not pendentes:
        print(f"[DEBUG] Nenhuma OS encontrada para {prestador_id}. Verifique:")
        print(f"1. Arquivo existe em {PRESTADORES_DIR}?")
        print(f"2. Nome do arquivo contém partes de '{prestador_id}'?")
        print("3. Estrutura do JSON está correta?")
    
    return render_template('painel_prestador.html',
                         os_pendentes=pendentes,
                         prestador=prestador_id)

@app.route('/finalizar/<os_numero>', methods=['POST'])
def finalizar_os(os_numero):
    if 'user' not in session:
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

@app.route('/logout')
def logout():
    session.clear()
    flash('Você foi desconectado', 'info')
    return redirect(url_for('login'))

# --- Rotas de diagnóstico ---
@app.route('/debug/dir/<tipo>')
def debug_dir(tipo):
    dirpath = GERENTES_DIR if tipo == 'gerente' else PRESTADORES_DIR
    return jsonify({
        'diretorio': dirpath,
        'arquivos': os.listdir(dirpath),
        'caminho_absoluto': os.path.abspath(dirpath)
    })

@app.route('/debug/user/<username>')
def debug_user(username):
    tipo = 'gerente' if '.' in username else 'prestador'
    dirpath = GERENTES_DIR if tipo == 'gerente' else PRESTADORES_DIR
    os_items = carregar_os(dirpath, username)
    
    return jsonify({
        'username': username,
        'type': tipo,
        'dir': dirpath,
        'arquivos_encontrados': [f for f in os.listdir(dirpath) 
                                if all(p in f.lower() 
                                     for p in username.replace('.', ' ').lower().split())],
        'os_carregadas': len(os_items),
        'os_processadas': len(processar_os_items(os_items))
    })

# --- Inicialização ---
init_db()

if __name__ == '__main__':
    app.run(debug=True)
