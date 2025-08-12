
import os
import time
import json
import pyautogui
import pandas as pd
from datetime import datetime, timedelta
import re
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.common.action_chains import ActionChains

# ========================= ETAPA 1 - DOWNLOAD =========================
print("\n🚀 Iniciando extração automática do relatório PIMNS...")

CHROMEDRIVER_PATH = "chromedriver.exe"
usuario = "WILSONS"
senha = "@prats456"
pasta = r"C:\Users\wilsonsantana\Downloads"

options = webdriver.ChromeOptions()
options.add_argument("--start-maximized")
service = Service(CHROMEDRIVER_PATH)
driver = webdriver.Chrome(service=service, options=options)

try:
    driver.get("http://10.1.1.51:8080/pimsmc/login.jsp")
    WebDriverWait(driver, 20).until(EC.presence_of_element_located((By.ID, "USER"))).send_keys(usuario)
    WebDriverWait(driver, 10).until(EC.presence_of_element_located((By.ID, "SENHA"))).send_keys(senha)
    WebDriverWait(driver, 10).until(EC.element_to_be_clickable((By.XPATH, '//input[@type="submit"]'))).click()
    WebDriverWait(driver, 10).until(EC.url_contains("manterFavoritos"))

    driver.get("http://10.1.1.51:8080/pimsmc/manterIndicadores.do?method=showViewConsulta&objectName=VisoesIndicadores.VisoesConsultaIndicadores")
    campo_codigo = WebDriverWait(driver, 30).until(EC.presence_of_element_located((By.ID, "CODIGO_INDICADOR")))
    campo_codigo.clear()
    campo_codigo.send_keys("OFC.STSOS")
    ActionChains(driver).move_to_element_with_offset(driver.find_element(By.TAG_NAME, "body"), 0, 0).click().perform()
    time.sleep(3)

    driver.find_element(By.ID, "VALOR_0").send_keys("01/01/2025")
    driver.find_element(By.ID, "VALOR_1").send_keys((datetime.today() + timedelta(days=1)).strftime("%d/%m/%Y"))
    driver.find_element(By.ID, "CODIGO_VALOR_2").clear()
    WebDriverWait(driver, 20).until(EC.element_to_be_clickable((By.XPATH, "//span[contains(text(), 'Aplicar')]"))).click()
    time.sleep(10)

    WebDriverWait(driver, 20).until(EC.element_to_be_clickable((By.XPATH, "//span[contains(text(), 'Exportar para Excel')]"))).click()
    time.sleep(15)
    pyautogui.click(1186, 103)
    time.sleep(10)
    pyautogui.moveTo(1269, 62); pyautogui.click()
    time.sleep(1)
    pyautogui.moveTo(1189, 106); pyautogui.click()
    driver.quit()
    print("✅ Relatório baixado com sucesso!")
except Exception as e:
    print("❌ Erro:", e)
    driver.quit()
    exit()

# ========================= ETAPA 2 - LEITURA =========================
print("\n📊 Lendo relatório...")

arquivos = [os.path.join(pasta, f) for f in os.listdir(pasta) if f.startswith("Export_Consulta_Indicador_") and f.endswith(".xlsx")]
excel_path = max(arquivos, key=os.path.getctime)
df = pd.read_excel(excel_path, header=9)
df = df[df["CD_UNI_ADM"].isin([4, 5])]
df["STATUS"] = df["STATUS"].astype(str).str.strip().str.upper()
df_abertas = df[(df["STATUS"] == "ABERTO") & df["FUNCIONAR_SOL"].notnull()]
df_abertas["DT_ENTRADA"] = pd.to_datetime(df_abertas["DT_ENTRADA"], errors="coerce", dayfirst=True)
df_abertas = df_abertas[df_abertas["DT_ENTRADA"].notnull()]
df_abertas.to_csv(os.path.join(pasta, "relatorio_filtrado.csv"), index=False)

# ========================= ETAPA 3 - JSON por gerente =========================
print("📥 Gerando JSON por gerente diretamente...")
pasta_json_gerente = os.path.join(pasta, "mensagens_por_gerente", "convertidos_json")
os.makedirs(pasta_json_gerente, exist_ok=True)

def normalizar_nome(nome):
    nome = nome.upper().strip()
    nome = re.sub(r"[^A-Z0-9_]", "_", nome)
    nome = re.sub(r"_+", "_", nome)
    return nome

for solicitante, grupo in df_abertas.groupby("FUNCIONAR_SOL"):
    ordens = []
    for _, row in grupo.iterrows():
        data = row["DT_ENTRADA"].strftime("%d/%m/%Y") if pd.notnull(row["DT_ENTRADA"]) else ""
        ordens.append({
            "frota": str(row["CD_EQT"]),
            "os": str(row["NO_SERVICO"]),
            "data": data,
            "prestador": row.get("PREST_SERVICO", ""),
            "servico": row.get("SERVICO", "")
        })
    nome_arquivo = normalizar_nome(solicitante) + ".json"
    with open(os.path.join(pasta_json_gerente, nome_arquivo), "w", encoding="utf-8") as f:
        json.dump(ordens, f, ensure_ascii=False, indent=2)

# ========================= ETAPA 4 - JSON por prestador =========================
print("📦 Gerando JSON por prestador...")
pasta_prestador = os.path.join(pasta, "mensagens_por_prestador")
os.makedirs(pasta_prestador, exist_ok=True)
for prestador, grupo in df_abertas[df_abertas["PREST_SERVICO"].notnull()].groupby("PREST_SERVICO"):
    registros = []
    for _, row in grupo.iterrows():
        registros.append({
            "frota": str(row["CD_EQT"]),
            "cd_equipamento": str(row["CD_EQT"]),
            "modelo": row.get("MODELO", ""),
            "os": str(row["NO_SERVICO"]),
            "data_entrada": row["DT_ENTRADA"].strftime("%d/%m/%Y") if pd.notnull(row["DT_ENTRADA"]) else "",
            "servico": row["SERVICO"]
        })
    nome_arquivo = normalizar_nome(prestador) + ".json"
    with open(os.path.join(pasta_prestador, nome_arquivo), "w", encoding="utf-8") as f:
        json.dump(registros, f, indent=2, ensure_ascii=False)

# ========================= ETAPA 5 - Responsáveis Arthur/Mauricio =========================
print("🔍 Separando por responsável (Arthur / Mauricio)...")
mauricio, arthur, outros, sem_prev = [], [], [], []

for _, row in df_abertas.iterrows():
    if row["STATUS"] != "ABERTO":
        continue
    if pd.notnull(row["DT_SAI_PREV"]) or pd.notnull(row.get("DT_SAIDA", None)):
        continue
    data_entrada = row["DT_ENTRADA"].strftime("%d/%m/%Y") if pd.notnull(row["DT_ENTRADA"]) else "---"
    servico = str(row["SERVICO"]).upper()

    msg = {
        "solicitante": row["FUNCIONAR_SOL"],
        "frota": str(row["CD_EQT"]),
        "modelo": row.get("MODELO", ""),
        "os": str(row["NO_SERVICO"]),
        "data_entrada": data_entrada,
        "previsao_saida": "---",
        "prestador": row.get("PREST_SERVICO", ""),
        "servico": row.get("SERVICO", ""),
    }

    if "ARTHUR" in servico and "SR" in servico:
        arthur.append(msg)
    elif "MAURICIO" in servico and "SR" in servico:
        mauricio.append(msg)
    elif "PREVISÃO DE SAÍDA: ---" in servico:
        sem_prev.append(msg)
    else:
        outros.append(msg)

def salvar_json(lista, nome_arquivo, liberador):
    path = os.path.join(pasta, nome_arquivo)
    for item in lista:
        item["liberado_por"] = liberador
    with open(path, "w", encoding="utf-8") as f:
        json.dump(lista, f, ensure_ascii=False, indent=4)
    print(f"📁 {nome_arquivo} salvo.")

salvar_json(mauricio, "relatorio_mauricio.json", "Mauricio")
salvar_json(arthur, "relatorio_arthur.json", "Arthur")
salvar_json(outros, "relatorio_outros.json", "Outros")
salvar_json(sem_prev, "relatorio_sem_previsao.json", "Sem previsão")

print("\n🎉 Tudo finalizado com sucesso!")


