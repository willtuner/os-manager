import os
import time
import json
import pandas as pd
from datetime import datetime, timedelta
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.common.action_chains import ActionChains

# ========================= ETAPA 1 - DOWNLOAD AUTOMÁTICO =========================
print("\n🚀 Iniciando extração automática do relatório PIMNS...")

# --- Configurações ---
usuario = "WILSONS"
senha = "@prats456"
# Usar um caminho relativo para a pasta de downloads para portabilidade
download_dir = os.path.join(os.getcwd(), "downloads")
os.makedirs(download_dir, exist_ok=True)


# --- Configuração do WebDriver para download automático ---
options = webdriver.ChromeOptions()
options.add_argument("--start-maximized")
options.add_argument("--headless") # Executar em modo headless para automação
options.add_experimental_option("prefs", {
  "download.default_directory": download_dir,
  "download.prompt_for_download": False,
  "download.directory_upgrade": True,
  "safebrowsing.enabled": True
})

# A biblioteca selenium agora gerencia o chromedriver automaticamente
driver = webdriver.Chrome(options=options)

try:
    # --- Login ---
    driver.get("http://10.1.1.51:8080/pimsmc/login.jsp")
    WebDriverWait(driver, 20).until(EC.presence_of_element_located((By.ID, "USER"))).send_keys(usuario)
    WebDriverWait(driver, 10).until(EC.presence_of_element_located((By.ID, "SENHA"))).send_keys(senha)
    WebDriverWait(driver, 10).until(EC.element_to_be_clickable((By.XPATH, '//input[@type="submit"]'))).click()
    WebDriverWait(driver, 10).until(EC.url_contains("manterFavoritos"))
    print("✅ Login realizado com sucesso.")

    # --- Navegação e preenchimento do formulário ---
    driver.get("http://10.1.1.51:8080/pimsmc/manterIndicadores.do?method=showViewConsulta&objectName=VisoesIndicadores.VisoesConsultaIndicadores")
    campo_codigo = WebDriverWait(driver, 30).until(EC.presence_of_element_located((By.ID, "CODIGO_INDICADOR")))
    campo_codigo.clear()
    campo_codigo.send_keys("OFC.STSOS")
    ActionChains(driver).move_to_element_with_offset(driver.find_element(By.TAG_NAME, "body"), 0, 0).click().perform()
    time.sleep(3) # Pequena pausa para garantir que a ação de clique foi processada

    driver.find_element(By.ID, "VALOR_0").send_keys("01/01/2025")
    driver.find_element(By.ID, "VALOR_1").send_keys((datetime.today() + timedelta(days=1)).strftime("%d/%m/%Y"))
    driver.find_element(By.ID, "CODIGO_VALOR_2").clear()
    WebDriverWait(driver, 20).until(EC.element_to_be_clickable((By.XPATH, "//span[contains(text(), 'Aplicar')]"))).click()
    print("✅ Formulário preenchido e aplicado.")
    time.sleep(10) # Espera para a grade de dados carregar

    # --- Download ---
    # Contar arquivos no diretório antes do download
    files_before = os.listdir(download_dir)
    
    WebDriverWait(driver, 20).until(EC.element_to_be_clickable((By.XPATH, "//span[contains(text(), 'Exportar para Excel')]"))).click()
    print("⏳ Aguardando o download do relatório...")

    # Esperar pelo novo arquivo aparecer no diretório de forma robusta
    timeout = 30
    start_time = time.time()
    new_file_path = None
    while time.time() - start_time < timeout:
        current_files = os.listdir(download_dir)
        new_files = [f for f in current_files if f not in files_before]
        xlsx_files = [f for f in new_files if f.endswith('.xlsx') and not f.endswith('.crdownload')]
        
        if xlsx_files:
            new_file_path = os.path.join(download_dir, xlsx_files[0])
            print(f"✅ Relatório baixado com sucesso: {new_file_path}")
            break
        time.sleep(1)
    
    if not new_file_path:
        raise FileNotFoundError("O download do relatório demorou muito ou falhou.")

except Exception as e:
    print(f"❌ Erro na Etapa 1: {e}")
    driver.quit()
    exit()
finally:
    driver.quit()


# ========================= ETAPA 2 - LEITURA =========================
print("\n📊 Lendo relatório...")

try:
    arquivos = [os.path.join(download_dir, f) for f in os.listdir(download_dir) if f.startswith("Export_Consulta_Indicador_") and f.endswith(".xlsx")]
    if not arquivos:
        raise FileNotFoundError("Nenhum arquivo de relatório encontrado no diretório de downloads.")
    
    excel_path = max(arquivos, key=os.path.getctime)
    print(f"Lendo o arquivo: {excel_path}")
    
    df = pd.read_excel(excel_path, header=9)
    df = df[df["CD_UNI_ADM"].isin([4, 5])]
    df["STATUS"] = df["STATUS"].astype(str).str.strip().str.upper()
    df_abertas = df[(df["STATUS"] == "ABERTO") & df["FUNCIONAR_SOL"].notnull()]
    df_abertas["DT_ENTRADA"] = pd.to_datetime(df_abertas["DT_ENTRADA"], errors="coerce", dayfirst=True)
    df_abertas = df_abertas[df_abertas["DT_ENTRADA"].notnull()]
    
    # Salvar uma cópia filtrada para depuração
    df_abertas.to_csv(os.path.join(download_dir, "relatorio_filtrado.csv"), index=False)
    print("✅ Leitura e filtragem do relatório concluídas.")

except Exception as e:
    print(f"❌ Erro na Etapa 2: {e}")
    exit()

# Definir a pasta base para salvar os arquivos gerados
output_base_dir = os.getcwd()

# ========================= ETAPA 3 & 4 - JSON por gerente =========================
print("\n🧾 Gerando JSON por gerente...")
pasta_json_gerente = os.path.join(output_base_dir, "mensagens_por_gerente")
os.makedirs(pasta_json_gerente, exist_ok=True)

for solicitante, grupo in df_abertas.groupby("FUNCIONAR_SOL"):
    ordens = []
    for _, row in grupo.iterrows():
        ordem = {
            "frota": str(row.get("CD_EQT", "")),
            "os": str(row.get("NO_SERVICO", "")),
            "data": row["DT_ENTRADA"].strftime("%d/%m/%Y") if pd.notnull(row["DT_ENTRADA"]) else "",
            "prestador": str(row.get("PREST_SERVICO", "Não definido")),
            "servico": str(row.get("SERVICO", ""))
        }
        ordens.append(ordem)
    
    nome_json = solicitante.upper().replace(" ", "_") + ".json"
    with open(os.path.join(pasta_json_gerente, nome_json), "w", encoding="utf-8") as fjson:
        json.dump(ordens, fjson, ensure_ascii=False, indent=2)

print("✅ JSON por gerente gerado.")

# ========================= ETAPA 5 - JSON por prestador =========================
print("\n📦 Gerando JSON por prestador...")
pasta_prestador = os.path.join(output_base_dir, "mensagens_por_prestador")
os.makedirs(pasta_prestador, exist_ok=True)

df_com_prestador = df_abertas[df_abertas["PREST_SERVICO"].notnull()].copy()

for prestador, grupo in df_com_prestador.groupby("PREST_SERVICO"):
    registros = []
    for _, row in grupo.iterrows():
        registros.append({
            "frota": str(row.get("CD_EQT", "")),
            "cd_equipamento": str(row.get("CD_EQT", "")),
            "modelo": str(row.get("MODELO", "")),
            "os": str(row.get("NO_SERVICO", "")),
            "data_entrada": row["DT_ENTRADA"].strftime("%d/%m/%Y") if pd.notnull(row["DT_ENTRADA"]) else "",
            "servico": str(row.get("SERVICO", ""))
        })
    
    # Limpeza do nome do arquivo para garantir que seja válido
    nome_arquivo_prestador = "".join(c for c in prestador if c.isalnum() or c in (' ', '_')).rstrip()
    nome_arquivo = f"{nome_arquivo_prestador.upper().replace(' ', '_')}.json"
    
    with open(os.path.join(pasta_prestador, nome_arquivo), "w", encoding="utf-8") as f:
        json.dump(registros, f, indent=2, ensure_ascii=False)

print("✅ JSON por prestador gerado.")
        
# ========================= ETAPA 6 - Separação por responsável (Arthur / Mauricio) =========================
print("\n🔍 Gerando JSON para Arthur e Mauricio...")

# Preparar dados
df_abertas['SERVICO_UPPER'] = df_abertas['SERVICO'].astype(str).str.upper()
df_abertas['FUNCIONAR_SOL_UPPER'] = df_abertas['FUNCIONAR_SOL'].astype(str).str.upper()

# Filtrar para Arthur e Mauricio
df_arthur = df_abertas[df_abertas['SERVICO_UPPER'].str.contains("ARTHUR")]
df_mauricio = df_abertas[df_abertas['SERVICO_UPPER'].str.contains("MAURICIO")]

def gerar_json_responsavel(df_responsavel, nome_arquivo, liberador):
    registros = []
    for _, row in df_responsavel.iterrows():
        registros.append({
            "solicitante": str(row.get("FUNCIONAR_SOL", "")),
            "frota": str(row.get("CD_EQT", "")),
            "modelo": str(row.get("MODELO", "")),
            "os": str(row.get("NO_SERVICO", "")),
            "data_entrada": row["DT_ENTRADA"].strftime("%d/%m/%Y") if pd.notnull(row["DT_ENTRADA"]) else "",
            "previsao_saida": "---",
            "prestador": str(row.get("PREST_SERVICO", "Não definido")),
            "servico": str(row.get("SERVICO", "")),
            "liberado_por": liberador
        })
    
    path_json = os.path.join(output_base_dir, "static/json", nome_arquivo)
    os.makedirs(os.path.dirname(path_json), exist_ok=True)
    with open(path_json, "w", encoding="utf-8") as f:
        json.dump(registros, f, ensure_ascii=False, indent=4)
    print(f"📁 {nome_arquivo} salvo.")

gerar_json_responsavel(df_mauricio, "relatorio_mauricio.json", "Mauricio")
gerar_json_responsavel(df_arthur, "relatorio_arthur.json", "Arthur")

print("\n🎉 Tudo finalizado com sucesso!")
