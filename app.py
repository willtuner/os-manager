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
        if User.query.count() == 0:
            try:
                if os.path.exists(USERS_FILE):
                    print(f"[INIT] Inicializando banco de dados a partir de {USERS_FILE}")
                    with open(USERS_FILE, encoding='utf-8') as f:
                        users_data = json.load(f)
                    
                    print(f"[INIT] {len(users_data)} usuários encontrados no arquivo")
                    
                    for username, password in users_data.items():
                        username_lower = username.lower()
                        if not User.query.filter_by(username=username_lower).first():
                            new_user = User(
                                username=username_lower,
                                password=password.strip(),
                                is_admin=(username_lower == 'wilson.santana')
                            )
                            db.session.add(new_user)
                            print(f"[INIT] Usuário cadastrado: {username_lower}")
                    
                    db.session.commit()
                    print("[INIT] Banco de dados inicializado com sucesso!")
                else:
                    print(f"[ERRO] Arquivo {USERS_FILE} não encontrado!")
                    # Cria um usuário padrão se o arquivo não existir
                    if not User.query.filter_by(username='admin').first():
                        db.session.add(User(
                            username='admin',
                            password='admin',
                            is_admin=True
                        ))
                        db.session.commit()
                        print("[INIT] Usuário admin padrão criado")
            except Exception as e:
                print(f"[ERRO CRÍTICO] Falha ao inicializar banco: {str(e)}")
                db.session.rollback()

def carregar_os(dirpath, identifier):
    """Carrega OS com tratamento robusto para diferentes formatos"""
    print(f"\n[OS] Buscando para '{identifier}' em {dirpath}")
    data = []
    
    # Para gerentes (formato NOME_SOBRENOME.json)
    if dirpath == GERENTES_DIR:
        filename = f"{identifier.replace('.', '_').upper()}.json"
        filepath = os.path.join(dirpath, filename)
        
        if os.path.exists(filepath):
            print(f"[OS] Lendo arquivo de gerente: {filename}")
            try:
                with open(filepath, 'r', encoding='utf-8') as f:
                    content = json.load(f)
                    data.extend(content if isinstance(content, list) else [content])
            except Exception as e:
                print(f"[ERRO] Falha ao ler {filename}: {str(e)}")
        else:
            print(f"[OS] Arquivo não encontrado: {filepath}")
    
    # Para prestadores (formato OS_NOME*.json)
    else:
        search_parts = identifier.replace('.', ' ').lower().split()
        print(f"[OS] Buscando arquivos que contenham: {search_parts}")
        
        for filename in os.listdir(dirpath):
            if filename.lower().startswith('os_') and filename.lower().endswith('.json'):
                if all(part in filename.lower() for part in search_parts):
                    filepath = os.path.join(dirpath, filename)
                    print(f"[OS] Arquivo candidato: {filename}")
                    try:
                        with open(filepath, 'r', encoding='utf-8') as f:
                            content = json.load(f)
                            if isinstance(content, dict) and 'ORDENS_DE_SERVICO' in content:
                                data.extend(content['ORDENS_DE_SERVICO'])
                            elif isinstance(content, list):
                                data.extend(content)
                    except Exception as e:
                        print(f"[ERRO] Falha ao ler {filename}: {str(e)}")

    print(f"[OS] Total de OS carregadas: {len(data)}")
    return data

def processar_os_items(items):
    """Processa itens de OS com tratamento robusto"""
    resultado = []
    hoje = datetime.utcnow().date()
    
    if not items:
        print("[OS] Nenhum item recebido para processar")
        return resultado
    
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
        
        print(f"\n[LOGIN] Tentativa de acesso: {username}")
        print(f"[LOGIN] Verificando usuário no banco...")
        
        user = User.query.filter_by(username=username).first()
        
        if user:
            print(f"[LOGIN] Usuário encontrado. Verificando senha...")
            print(f"[DEBUG] Senha fornecida: '{password}'")
            print(f"[DEBUG] Senha armazenada: '{user.password}'")
            
            if user.password == password:
                session['user'] = user.username
                session['type'] = 'gerente' if '.' in user.username else 'prestador'
                print(f"[LOGIN] Acesso concedido! Tipo: {session['type']}")
                return redirect(url_for('painel_gerente' if session['type'] == 'gerente' else 'painel_prestador'))
            else:
                print("[LOGIN] Senha incorreta!")
        else:
            print("[LOGIN] Usuário não encontrado!")
        
        flash('Credenciais inválidas', 'danger')
    return render_template('login.html')

@app.route('/painel_gerente')
def painel_gerente():
    if 'user' not in session or session.get('type') != 'gerente':
        flash('Acesso não autorizado', 'danger')
        return redirect(url_for('login'))
    
    user_id = session['user']
    print(f"\n[PAINEL] Carregando painel para gerente: {user_id}")
    
    os_items = carregar_os(GERENTES_DIR, user_id)
    
    # Fallback: se não encontrou como gerente, tenta como prestador
    if not os_items:
        print("[PAINEL] Nenhuma OS encontrada como gerente, tentando como prestador")
        os_items = carregar_os(PRESTADORES_DIR, user_id)
    
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
    print(f"\n[PAINEL] Carregando painel para prestador: {prestador_id}")
    
    os_items = carregar_os(PRESTADORES_DIR, prestador_id)
    pendentes = processar_os_items(os_items)
    
    if not pendentes:
        print(f"[PAINEL] Nenhuma OS encontrada para {prestador_id}")
        print(f"[DEBUG] Conteúdo de {PRESTADORES_DIR}: {os.listdir(PRESTADORES_DIR)}")
    
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

@app.route('/logout')
def logout():
    session.clear()
    flash('Você foi desconectado', 'info')
    return redirect(url_for('login'))

# --- Rotas de diagnóstico ---
@app.route('/debug/users')
def debug_users():
    users = User.query.all()
    users_data = [{
        'username': u.username, 
        'password': u.password, 
        'is_admin': u.is_admin
    } for u in users]
    return jsonify({
        'count': len(users_data),
        'users': users_data,
        'db_path': os.path.abspath(os.path.join(BASE_DIR, 'app.db'))
    })

@app.route('/debug/dir/<tipo>')
def debug_dir(tipo):
    dirpath = GERENTES_DIR if tipo == 'gerente' else PRESTADORES_DIR
    return jsonify({
        'diretorio': dirpath,
        'arquivos': os.listdir(dirpath),
        'caminho_absoluto': os.path.abspath(dirpath)
    })

# --- Inicialização ---
if __name__ == '__main__':
    init_db()
    print("\n[INIT] Aplicação iniciada com sucesso!")
    print(f"[INIT] Modo debug: {'ON' if app.debug else 'OFF'}")
    app.run(debug=True)
