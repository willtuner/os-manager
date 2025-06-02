from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.common.action_chains import ActionChains
from datetime import datetime, timedelta
import time
import os
import pyautogui
import pandas as pd
import json
import shutil # Para manipulação de arquivos/pastas

# ========================= CONFIGURAÇÕES GLOBAIS =========================
CHROMEDRIVER_PATH = "chromedriver.exe" # Certifique-se que o chromedriver.exe está no PATH ou especifique o caminho completo
USUARIO_SISTEMA = "WILSONS"
SENHA_SISTEMA = "@prats456"
PASTA_DOWNLOADS = r"C:\Users\wilsonsantana\Downloads" # Use raw string para caminhos

URL_LOGIN = "http://10.1.1.51:8080/pimsmc/login.jsp"
URL_CONSULTA_INDICADORES = "http://10.1.1.51:8080/pimsmc/manterIndicadores.do?method=showViewConsulta&objectName=VisoesIndicadores.VisoesConsultaIndicadores"
CODIGO_INDICADOR_CONSULTA = "OFC.STSOS"

# Configuração das datas para a consulta web
DATA_INICIO_CONSULTA = "01/01/2025" # Fixa, conforme ambos os scripts
DATA_FIM_CONSULTA = (datetime.today() + timedelta(days=1)).strftime("%d/%m/%Y")

# Datas para a filtragem específica do 'extrair_aberta.py'
DATA_INICIO_FILTRO_EXTRAIR_ABERTA = datetime(2025, 1, 1)
DATA_FIM_FILTRO_EXTRAIR_ABERTA = datetime.today() + timedelta(days=1) # datetime object for comparison

# Configuração para 'OS.py'
REMOVER_UNIDADE_7_OS_PY = True

# Pastas de saída
PASTA_SAIDA_BASE = os.path.join(PASTA_DOWNLOADS, "Relatorios_Unificados_OS")
PASTA_SAIDA_EXTRAIR_ABERTA = os.path.join(PASTA_SAIDA_BASE, "Saidas_Extrair_Aberta")
PASTA_SAIDA_OS_PY = os.path.join(PASTA_SAIDA_BASE, "Saidas_OS_Py")
PASTA_SAIDA_OS_PY_TXT_POR_GERENTE = r"C:\\Users\\wilsonsantana\\Documents\\os-manager\\mensagens_por_gerente"
PASTA_SAIDA_OS_PY_JSON_CONVERTIDOS = r"C:\\Users\\wilsonsantana\\Documents\\os-manager\\static\\json"
PASTA_SAIDA_OS_PY_JSON_POR_PRESTADOR = r"C:\\Users\\wilsonsantana\\Documents\\os-manager\\mensagens_por_prestador"

# Coordenadas PyAutoGUI (ATENÇÃO: ESTA É A PARTE MAIS FRÁGIL DO SCRIPT)
# Usando as coordenadas e tempos do OS.py, que parecem ser os mais completos/recentes.
# Se a tela de "Imprimir" ou "Salvar" do Excel mudar, estas coordenadas precisarão de ajuste.
PYAUTOGUI_CLICK_1_X, PYAUTOGUI_CLICK_1_Y = 1186, 103
PYAUTOGUI_MOVETO_2_X, PYAUTOGUI_MOVETO_2_Y = 1269, 62
PYAUTOGUI_CLICK_3_X, PYAUTOGUI_CLICK_3_Y = 1189, 106 # Do OS.py

# ========================= FUNÇÕES AUXILIARES DE AUTOMAÇÃO WEB =========================
def inicializar_driver(chromedriver_path):
    print("🔧 Inicializando o WebDriver...")
    options = webdriver.ChromeOptions()
    options.add_argument("--start-maximized")
    # Descomente a linha abaixo para executar em modo headless (sem interface gráfica)
    # options.add_argument("--headless")
    options.add_experimental_option("prefs", {
        "download.default_directory": PASTA_DOWNLOADS,
        "download.prompt_for_download": False,
        "download.directory_upgrade": True,
        "plugins.always_open_pdf_externally": True # Pode ajudar se for PDF, mas aqui é Excel
    })
    service = Service(chromedriver_path)
    driver = webdriver.Chrome(service=service, options=options)
    return driver

def fazer_login(driver, usuario, senha):
    print(f"🔑 Efetuando login com o usuário: {usuario}...")
    driver.get(URL_LOGIN)
    try:
        campo_usuario = WebDriverWait(driver, 20).until(EC.presence_of_element_located((By.ID, "USER")))
        campo_usuario.send_keys(usuario)
        campo_senha = WebDriverWait(driver, 10).until(EC.presence_of_element_located((By.ID, "SENHA")))
        campo_senha.send_keys(senha)
        botao_login = WebDriverWait(driver, 10).until(EC.element_to_be_clickable((By.XPATH, '//input[@type="submit" or @value="Fazer Login"]')))
        botao_login.click()
        WebDriverWait(driver, 10).until(EC.url_contains("manterFavoritos"))
        print("✅ Login realizado com sucesso!")
    except Exception as e:
        print(f"❌ Erro ao fazer login: {e}")
        driver.save_screenshot(os.path.join(PASTA_DOWNLOADS, "erro_login.png"))
        raise

def baixar_relatorio_excel(driver):
    print("📊 Navegando para a consulta e aplicando filtros...")
    driver.get(URL_CONSULTA_INDICADORES)
    try:
        campo_codigo = WebDriverWait(driver, 30).until(EC.presence_of_element_located((By.ID, "CODIGO_INDICADOR")))
        campo_codigo.clear()
        campo_codigo.send_keys(CODIGO_INDICADOR_CONSULTA)
        
        # Clicar fora para validar o código do indicador (se necessário)
        body = driver.find_element(By.TAG_NAME, "body")
        ActionChains(driver).move_to_element_with_offset(body, 0, 0).click().perform()
        time.sleep(3) # Aguardar possível atualização da página

        driver.find_element(By.ID, "VALOR_0").send_keys(DATA_INICIO_CONSULTA)
        driver.find_element(By.ID, "VALOR_1").send_keys(DATA_FIM_CONSULTA)
        driver.find_element(By.ID, "CODIGO_VALOR_2").clear() # Limpa campo conforme os scripts

        WebDriverWait(driver, 20).until(EC.element_to_be_clickable((By.XPATH, "//span[contains(text(), 'Aplicar')]"))).click()
        print("⏳ Aguardando aplicação dos filtros...")
        time.sleep(10) # Espera para os dados carregarem

        print("📤 Exportando para Excel...")
        WebDriverWait(driver, 20).until(EC.element_to_be_clickable((By.XPATH, "//span[contains(text(), 'Exportar para Excel')]"))).click()
        
        print("⏳ Aguardando início do download e interação com PyAutoGUI...")
        time.sleep(15) # Tempo para a caixa de diálogo/processamento do Excel aparecer
        
        # ATENÇÃO: A sequência PyAutoGUI é altamente dependente da interface do usuário
        # e pode precisar de ajustes.
        print(f"🖱️ PyAutoGUI: Clicando em {PYAUTOGUI_CLICK_1_X}, {PYAUTOGUI_CLICK_1_Y}")
        pyautogui.click(PYAUTOGUI_CLICK_1_X, PYAUTOGUI_CLICK_1_Y)
        time.sleep(15) # OS.py tem um sleep longo aqui.
        
        print(f"🖱️ PyAutoGUI: Movendo para {PYAUTOGUI_MOVETO_2_X}, {PYAUTOGUI_MOVETO_2_Y} e clicando.")
        pyautogui.moveTo(PYAUTOGUI_MOVETO_2_X, PYAUTOGUI_MOVETO_2_Y)
        pyautogui.click()
        time.sleep(1)
        
        print(f"🖱️ PyAutoGUI: Movendo para {PYAUTOGUI_CLICK_3_X}, {PYAUTOGUI_CLICK_3_Y} e clicando.")
        pyautogui.moveTo(PYAUTOGUI_CLICK_3_X, PYAUTOGUI_CLICK_3_Y)
        pyautogui.click()
        
        print("⏳ Aguardando conclusão do download...")
        time.sleep(10) # Tempo para o arquivo ser completamente salvo

        # Encontrar o arquivo Excel mais recente
        arquivos_excel = [
            os.path.join(PASTA_DOWNLOADS, f)
            for f in os.listdir(PASTA_DOWNLOADS)
            if f.startswith("Export_Consulta_Indicador_") and f.endswith(".xlsx")
        ]
        if not arquivos_excel:
            raise FileNotFoundError("Nenhum relatório Excel ('Export_Consulta_Indicador_*.xlsx') encontrado na pasta de Downloads.")
        
        caminho_excel_baixado = max(arquivos_excel, key=os.path.getctime)
        print(f"✅ Relatório baixado: {caminho_excel_baixado}")
        return caminho_excel_baixado

    except Exception as e:
        print(f"❌ Erro durante a extração do relatório: {e}")
        driver.save_screenshot(os.path.join(PASTA_DOWNLOADS, "erro_extracao_relatorio.png"))
        raise

# ========================= LÓGICA DE PROCESSAMENTO (BASEADA EM extrair_aberta.py) =========================
def processar_para_extrair_aberta(df_original, pasta_saida):
    print("\n--- Iniciando Processamento: Lógica 'extrair_aberta.py' ---")
    os.makedirs(pasta_saida, exist_ok=True)
    
    df = df_original.copy() # Trabalhar com uma cópia para não afetar outros processamentos

    # Filtros específicos de extrair_aberta.py
    df = df[df["CD_UNI_ADM"].isin([4, 5])]
    df["STATUS"] = df["STATUS"].astype(str).str.strip().str.upper()
    df_abertas = df[df["STATUS"] == "ABERTO"]
    df_abertas = df_abertas[df_abertas["FUNCIONAR_SOL"].notnull()]
    df_abertas = df_abertas.copy() # Para evitar SettingWithCopyWarning
    
    df_abertas.loc[:, "DT_ENTRADA"] = pd.to_datetime(df_abertas["DT_ENTRADA"], errors="coerce", dayfirst=True)
    # Filtrar pelo intervalo de datas definido globalmente
    df_abertas = df_abertas[
        (df_abertas["DT_ENTRADA"] >= DATA_INICIO_FILTRO_EXTRAIR_ABERTA) &
        (df_abertas["DT_ENTRADA"] <= DATA_FIM_FILTRO_EXTRAIR_ABERTA)
    ]

    mensagens = []
    for _, row in df_abertas.iterrows():
        data_entrada = row["DT_ENTRADA"].strftime("%d/%m/%Y") if pd.notnull(row["DT_ENTRADA"]) else "---"
        # Corrigido para usar DT_SAI_PREV como em extrair_aberta.py
        dt_saida_prev = row["DT_SAI_PREV"] if pd.notnull(row["DT_SAI_PREV"]) else "---"
        msg = (
            f"Solicitante: {row['FUNCIONAR_SOL']}\n"
            f"Frota: {row['CD_EQT']}\n"
            f"Modelo: {row.get('MODELO', 'N/A')}\n" # Usar .get para colunas que podem não existir
            f"O.S: {row['NO_SERVICO']}\n"
            f"Data de entrada: {data_entrada}\n"
            f"Previsão de saída: {dt_saida_prev}\n"
            f"Prestador: {row['PREST_SERVICO']}\n"
            f"Serviço: {row['SERVICO']}\n"
            f"{'-'*50}\n"
        )
        mensagens.append(msg)

    saida_txt_geral = os.path.join(pasta_saida, "relatorio_OS_abertas_extrair_aberta.txt")
    with open(saida_txt_geral, "w", encoding="utf-8") as f:
        f.writelines(mensagens)
    print(f"✅ Relatório TXT Geral (extrair_aberta) salvo: {saida_txt_geral}")

    # Separação por liberador e sem previsão
    with open(saida_txt_geral, "r", encoding="utf-8") as f:
        conteudo = f.read()
    os_blocos = [bloco.strip() for bloco in conteudo.split("-" * 50) if bloco.strip()]


    arthur_os = []
    mauricio_os = []
    outros_os = [] # Blocos que não se encaixam em Arthur ou Mauricio, mas não necessariamente "sem previsão"
    sem_previsao_saida = [] # Blocos explicitamente sem previsão

    # Lógica de separação conforme extrair_aberta.py
    # Um bloco pode ser de um liberador E estar sem previsão.
    # A lógica original adicionava a "outros_os" se não fosse Mauricio nem Arthur.
    # E separadamente, adicionava a "sem_previsao_saida" se a previsão fosse "---".

    for bloco in os_blocos:
        is_mauricio = "LIBERADO SR. MAURICIO" in bloco.upper()
        is_arthur = "LIBERADO SR. ARTHUR" in bloco.upper()
        
        if "PREVISÃO DE SAÍDA: ---" in bloco.upper():
            sem_previsao_saida.append(bloco)

        if is_mauricio:
            mauricio_os.append(bloco)
        elif is_arthur:
            arthur_os.append(bloco)
        else: # Se não for de Mauricio nem de Arthur, vai para outros.
            outros_os.append(bloco)


    def salvar_txt_lista(lista, nome_arquivo, pasta_destino):
        path = os.path.join(pasta_destino, nome_arquivo)
        # Adiciona uma quebra de linha dupla entre os blocos e a linha separadora
        conteudo_final = ("\n\n" + "-"*50 + "\n\n").join(lista)
        # Adiciona um separador no início se a lista não estiver vazia, para manter consistência
        if lista:
             conteudo_final = "\n" + conteudo_final # Adiciona o primeiro separador e \n
        
        with open(path, "w", encoding="utf-8") as f:
            f.write(conteudo_final)
        print(f"📁 Arquivo TXT (extrair_aberta) salvo: {path}")

    def salvar_json_lista(lista_txt, nome_arquivo, liberador_tag, pasta_destino):
        dados = []
        for bloco in lista_txt:
            linhas = bloco.strip().split("\n")
            item = {}
            try:
                item["solicitante"] = linhas[0].split(":", 1)[1].strip() if len(linhas) > 0 and ":" in linhas[0] else "N/A"
                item["frota"] = linhas[1].split(":", 1)[1].strip() if len(linhas) > 1 and ":" in linhas[1] else "N/A"
                item["modelo"] = linhas[2].split(":", 1)[1].strip() if len(linhas) > 2 and ":" in linhas[2] else "N/A"
                item["os"] = linhas[3].split(":", 1)[1].strip() if len(linhas) > 3 and ":" in linhas[3] else "N/A"
                item["data_entrada"] = linhas[4].split(":", 1)[1].strip() if len(linhas) > 4 and ":" in linhas[4] else "N/A"
                item["previsao_saida"] = linhas[5].split(":", 1)[1].strip() if len(linhas) > 5 and ":" in linhas[5] else "N/A"
                item["prestador"] = linhas[6].split(":", 1)[1].strip() if len(linhas) > 6 and ":" in linhas[6] else "N/A"
                item["servico"] = linhas[7].split(":", 1)[1].strip() if len(linhas) > 7 and ":" in linhas[7] else "N/A"
                item["liberado_por"] = liberador_tag
                dados.append(item)
            except IndexError:
                print(f"⚠️ Aviso: Bloco mal formatado ignorado durante a criação do JSON para {nome_arquivo}:\n{bloco}")
            except Exception as e:
                print(f"⚠️ Erro ao processar bloco para JSON {nome_arquivo}: {e}\nBloco:\n{bloco}")


        path = os.path.join(pasta_destino, nome_arquivo)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(dados, f, ensure_ascii=False, indent=4)
        print(f"📁 JSON (extrair_aberta) salvo: {path}")

    salvar_txt_lista(mauricio_os, "relatorio_mauricio_extrair_aberta.txt", pasta_saida)
    salvar_txt_lista(arthur_os, "relatorio_arthur_extrair_aberta.txt", pasta_saida)
    salvar_txt_lista(outros_os, "relatorio_outros_extrair_aberta.txt", pasta_saida)
    salvar_txt_lista(sem_previsao_saida, "relatorio_sem_previsao_saida_extrair_aberta.txt", pasta_saida)
    
    salvar_json_lista(mauricio_os, "relatorio_mauricio_extrair_aberta.json", "Mauricio", pasta_saida)
    salvar_json_lista(arthur_os, "relatorio_arthur_extrair_aberta.json", "Arthur", pasta_saida)
    # Não há JSON para 'outros' ou 'sem_previsao' no script original extrair_aberta.py
    
    print("✅ Processamento (extrair_aberta) concluído.")


# ========================= LÓGICA DE PROCESSAMENTO (BASEADA EM OS.py) =========================
def processar_para_os_py(df_original, pasta_base_saida_os_py):
    print("\n--- Iniciando Processamento: Lógica 'OS.py' ---")
    os.makedirs(PASTA_SAIDA_OS_PY_TXT_POR_GERENTE, exist_ok=True)
    os.makedirs(PASTA_SAIDA_OS_PY_JSON_CONVERTIDOS, exist_ok=True)
    os.makedirs(PASTA_SAIDA_OS_PY_JSON_POR_PRESTADOR, exist_ok=True)

    df = df_original.copy()

    # Filtros específicos de OS.py
    if REMOVER_UNIDADE_7_OS_PY:
        df = df[df["CD_UNI_ADM"] != 7]
    
    # Em OS.py, o foco é em OS sem previsão de saída
    df = df[df["DT_SAI_PREV"].isna()] 
    df["STATUS"] = df["STATUS"].astype(str).str.strip().str.upper()
    df_abertas = df[df["STATUS"] == "ABERTO"]
    df_abertas = df_abertas[df_abertas["FUNCIONAR_SOL"].notnull()]
    df_abertas = df_abertas.copy() # Para evitar SettingWithCopyWarning
    df_abertas.loc[:, "DT_ENTRADA"] = pd.to_datetime(df_abertas["DT_ENTRADA"], errors="coerce", dayfirst=True)
    
    # Salvar CSV filtrado
    caminho_csv_filtrado = os.path.join(pasta_base_saida_os_py, "relatorio_filtrado_OS_py.csv")
    df_abertas.to_csv(caminho_csv_filtrado, index=False, encoding='utf-8-sig')
    print(f"✅ Relatório CSV Filtrado (OS_py) salvo: {caminho_csv_filtrado}")

    # Gerar TXT por gerente (FUNCIONAR_SOL)
    print("📊 Gerando arquivos .txt por gerente (OS_py)...")
    for solicitante, grupo in df_abertas.groupby("FUNCIONAR_SOL"):
        mensagens = []
        for _, row in grupo.iterrows():
            data_entrada = row["DT_ENTRADA"].strftime("%d/%m/%Y") if pd.notnull(row["DT_ENTRADA"]) else ""
            # Formato da mensagem conforme OS.py
            msg = (
                f"Frota: {row['CD_EQT']}\n"
                f"O.S: {row['NO_SERVICO']}\n"
                f"Data de entrada: {data_entrada}\n"
                f"Prestador: {row.get('PREST_SERVICO', 'N/A')}\n" # .get para segurança
                f"Serviço: {row.get('SERVICO', 'N/A')}\n"
            )
            mensagens.append(msg)
        
        nome_arquivo_solicitante = str(solicitante).replace("/", "_").replace("\\", "_") # Sanitizar nome do arquivo
        caminho_txt_solicitante = os.path.join(PASTA_SAIDA_OS_PY_TXT_POR_GERENTE, f"{nome_arquivo_solicitante}.txt")
        with open(caminho_txt_solicitante, "w", encoding="utf-8") as f:
            f.write(f"Solicitante: {solicitante}\n\n" + "\n---\n".join(mensagens))
    print("✅ Arquivos .json por gerente (OS_py) gerados!")

    # Converter TXT para JSON (por gerente)
    print("\n🔁 Convertendo arquivos .txt para .json (OS_py)...")
    def processar_arquivo_txt_os_py(caminho_txt_completo): # Renomeado para evitar conflito
        with open(caminho_txt_completo, "r", encoding="utf-8") as f:
            conteudo = f.read()
        
        # Extrai o solicitante do cabeçalho do arquivo
        match_solicitante = re.search(r"Solicitante:\s*(.*)", conteudo)
        solicitante_arquivo = match_solicitante.group(1).strip() if match_solicitante else "N/A"

        # Remove o cabeçalho do solicitante para processar apenas os blocos de OS
        conteudo_blocos = re.sub(r"Solicitante:\s*.*\n\n", "", conteudo)
        blocos = [b.strip() for b in conteudo_blocos.split("---") if b.strip() and "Frota" in b]
        
        ordens = []
        for bloco in blocos:
            ordem = {"solicitado_por_arquivo": solicitante_arquivo} # Adiciona o solicitante do arquivo
            for linha in bloco.split("\n"):
                if ":" in linha:
                    chave, valor = linha.split(":", 1)
                    chave_limpa = chave.strip().lower().replace(".", "") # Limpa a chave
                    valor_limpo = valor.strip()
                    
                    if chave_limpa == "frota": ordem["frota"] = valor_limpo
                    elif chave_limpa == "os": ordem["os"] = valor_limpo # "o.s" ou "os"
                    elif chave_limpa.startswith("data"): ordem["data_entrada"] = valor_limpo
                    # 'dias' e 'tempo' não estão no formato de OS.py, mantendo para robustez se o formato mudar
                    elif chave_limpa.startswith("tempo") or chave_limpa.startswith("dias"): ordem["dias"] = valor_limpo 
                    elif chave_limpa == "prestador": ordem["prestador"] = valor_limpo if valor_limpo.lower() != "nan" else "Prestador não definido"
                    elif chave_limpa == "serviço" or chave_limpa == "servico": ordem["servico"] = valor_limpo
                    # 'fazenda' e 'liberado' não estão no formato de OS.py, mantendo para robustez
                    elif chave_limpa == "fazenda": ordem["fazenda"] = valor_limpo
                    elif chave_limpa.startswith("liberado"): ordem["liberado"] = valor_limpo
            ordens.append(ordem)
        return ordens

    for arquivo_txt in os.listdir(PASTA_SAIDA_OS_PY_TXT_POR_GERENTE):
        if arquivo_txt.lower().endswith(".txt"):
            caminho_txt_completo = os.path.join(PASTA_SAIDA_OS_PY_TXT_POR_GERENTE, arquivo_txt)
            nome_base_json = os.path.splitext(arquivo_txt)[0]
            nome_json_convertido = nome_base_json.upper().replace(" ", "_").replace(".", "") + ".json"
            
            dados_json = processar_arquivo_txt_os_py(caminho_txt_completo)
            caminho_json_final = os.path.join(PASTA_SAIDA_OS_PY_JSON_CONVERTIDOS, nome_json_convertido)
            with open(caminho_json_final, "w", encoding="utf-8") as fjson:
                json.dump(dados_json, fjson, ensure_ascii=False, indent=2)
    print("✅ Conversão dos .txt para .json (OS_py) concluída!")

    # Gerar JSON por prestador
    print("\n🧑‍🔧 Gerando arquivos JSON por prestador (OS_py)...")
    # Usar df_abertas que já tem os filtros corretos de OS.py
    prestadores_df = df_abertas[df_abertas["PREST_SERVICO"].notnull()]
    for prestador, grupo in prestadores_df.groupby("PREST_SERVICO"):
        registros = []
        for _, row in grupo.iterrows():
            registros.append({
                "frota": str(row.get("CD_EQT", "")),
                "cd_equipamento": str(row.get("CD_EQT", "")), # Campo duplicado em OS.py original
                "modelo": row.get("MODELO", ""),
                "os": str(row.get("NO_SERVICO", "")),
                "data_entrada": row["DT_ENTRADA"].strftime("%d/%m/%Y") if pd.notnull(row["DT_ENTRADA"]) else "",
                "servico": row.get("SERVICO", "")
            })
        nome_prestador_sanitizado = str(prestador).upper().replace(" ", "_").replace("/", "_").replace("\\", "_")
        nome_arquivo_prestador = f"{nome_prestador_sanitizado}.json"
        caminho_json_prestador = os.path.join(PASTA_SAIDA_OS_PY_JSON_POR_PRESTADOR, nome_arquivo_prestador)
        with open(caminho_json_prestador, "w", encoding="utf-8") as f:
            json.dump(registros, f, indent=2, ensure_ascii=False)
    print("✅ JSONs por prestador (OS_py) gerados com sucesso!")
    print("✅ Processamento (OS_py) concluído.")

# ========================= FUNÇÃO PRINCIPAL =========================
def main():
    print("🚀 Iniciando Processo Unificado de Extração e Relatórios 🚀")
    
    # Criar pastas de saída se não existirem
    os.makedirs(PASTA_SAIDA_BASE, exist_ok=True)
    os.makedirs(PASTA_SAIDA_EXTRAIR_ABERTA, exist_ok=True)
    os.makedirs(PASTA_SAIDA_OS_PY, exist_ok=True)

    driver = None
    excel_baixado_path = None

    try:
        driver = inicializar_driver(CHROMEDRIVER_PATH)
        fazer_login(driver, USUARIO_SISTEMA, SENHA_SISTEMA)
        excel_baixado_path = baixar_relatorio_excel(driver)

        if excel_baixado_path and os.path.exists(excel_baixado_path):
            print(f"\n📖 Lendo o arquivo Excel baixado: {excel_baixado_path}")
            # Ler o Excel uma vez para ambos os processamentos
            # É importante que o header=9 seja o correto para a estrutura do seu Excel.
            df_principal = pd.read_excel(excel_baixado_path, header=9) 
            print("🔎 DataFrame Principal Carregado com Sucesso.")
            
            # --- Executar lógica baseada em extrair_aberta.py ---
            processar_para_extrair_aberta(df_principal, PASTA_SAIDA_EXTRAIR_ABERTA)
            
            # --- Executar lógica baseada em OS.py ---
            processar_para_os_py(df_principal, PASTA_SAIDA_OS_PY) # Passa a pasta base de OS_py

            print("\n🎉🎉 Processo Unificado Finalizado com Sucesso! 🎉🎉")
        else:
            print("❌ Falha ao baixar ou encontrar o relatório Excel. Processamento subsequente cancelado.")

    except FileNotFoundError as fnf_error:
        print(f"❌ ERRO DE ARQUIVO: {fnf_error}")
    except Exception as e:
        print(f"❌ ERRO CRÍTICO NO PROCESSO UNIFICADO: {e}")
        if driver:
            driver.save_screenshot(os.path.join(PASTA_DOWNLOADS, "erro_geral_processo_unificado.png"))
    finally:
        if driver:
            print("🚪 Fechando o WebDriver...")
            driver.quit()
        print("🏁 Script finalizado.")
        subir_para_git("Relatórios atualizados automaticamente via script")



import subprocess

def subir_para_git(mensagem_commit="Atualização automática dos relatórios"):
    pasta_repo = r"C:\Users\wilsonsantana\Documents\os-manager"
    print("⬆️ Subindo arquivos pro GitHub...")
    try:
        comandos = [
            f'cd /d "{pasta_repo}"',
            'git add .',
            f'git commit -m "{mensagem_commit}"',
            'git push origin main'
        ]
        comando_total = " && ".join(comandos)
        resultado = subprocess.run(comando_total, shell=True, capture_output=True, text=True)
        print("📄 STDOUT:", resultado.stdout)
        print("⚠️ STDERR:", resultado.stderr)
    except Exception as e:
        print(f"❌ Erro ao fazer upload para o Git: {e}")


if __name__ == "__main__":
    main()
