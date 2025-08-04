import os
import time
import json
import pyautogui
import pandas as pd
from datetime import datetime, timedelta
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

# ========================= ETAPA 3 - TXT por gerente =========================
print("🧾 Gerando .txt por gerente...")
pasta_txt = os.path.join(pasta, "mensagens_por_gerente")
os.makedirs(pasta_txt, exist_ok=True)
for solicitante, grupo in df_abertas.groupby("FUNCIONAR_SOL"):
    mensagens = []
    for _, row in grupo.iterrows():
        data = row["DT_ENTRADA"].strftime("%d/%m/%Y") if pd.notnull(row["DT_ENTRADA"]) else ""
        msg = f"Frota: {row['CD_EQT']}\nO.S: {row['NO_SERVICO']}\nData de entrada: {data}\nPrestador: {row['PREST_SERVICO']}\nServiço: {row['SERVICO']}\n"
        mensagens.append(msg)
    with open(os.path.join(pasta_txt, f"{solicitante}.txt"), "w", encoding="utf-8") as f:
        f.write(f"Solicitante: {solicitante}\n\n" + "\n---\n".join(mensagens))

# ========================= ETAPA 4 - JSON por gerente =========================
print("📥 Convertendo .txt para .json...")

pasta_json = os.path.join(pasta_txt, "convertidos_json")
os.makedirs(pasta_json, exist_ok=True)

def processar_arquivo_txt(nome_arquivo):
    caminho_txt = os.path.join(pasta_txt, nome_arquivo)
    with open(caminho_txt, "r", encoding="utf-8") as f:
        conteudo = f.read()
    blocos = [b.strip() for b in conteudo.split("---") if b.strip() and "Frota" in b]
    ordens = []
    for bloco in blocos:
        ordem = {}
        for linha in bloco.split("\n"):
            if ":" in linha:
                chave, valor = linha.split(":", 1)
                chave = chave.strip().lower()
                valor = valor.strip()
                if chave == "frota": ordem["frota"] = valor
                elif chave in ("o.s", "os"): ordem["os"] = valor
                elif chave.startswith("data"): ordem["data"] = valor
                elif chave == "prestador": ordem["prestador"] = valor
                elif chave in ("serviço", "servico"): ordem["servico"] = valor
        ordens.append(ordem)
    return ordens

for arquivo in os.listdir(pasta_txt):
    if arquivo.lower().endswith(".txt"):
        nome_json = os.path.splitext(arquivo)[0].upper().replace(" ", "_") + ".json"
        dados = processar_arquivo_txt(arquivo)
        with open(os.path.join(pasta_json, nome_json), "w", encoding="utf-8") as fjson:
            json.dump(dados, fjson, ensure_ascii=False, indent=2)

# ========================= ETAPA 5 - JSON por prestador =========================
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
    nome_arquivo = f"{prestador.upper().replace(' ', '_')}.json"
    with open(os.path.join(pasta_prestador, nome_arquivo), "w", encoding="utf-8") as f:
        json.dump(registros, f, indent=2, ensure_ascii=False)
        
# ========================= ETAPA 6 - Separação por prestador responsável na descrição do serviço =========================
print("🔍 Separando por responsável (Arthur / Mauricio) com base na descrição do serviço...")

mauricio, arthur, outros, sem_prev = [], [], [], []

for _, row in df_abertas.iterrows():
    # Filtros obrigatórios
    if row["STATUS"] != "ABERTO":
        continue
    if pd.notnull(row["DT_SAI_PREV"]) or pd.notnull(row.get("DT_SAIDA", None)):
        continue

    # Dados formatados
    data_entrada = row["DT_ENTRADA"].strftime("%d/%m/%Y") if pd.notnull(row["DT_ENTRADA"]) else "---"
    previsao_saida = "---"
    servico = str(row["SERVICO"]).upper()

    msg = (
        f"Solicitante: {row['FUNCIONAR_SOL']}\n"
        f"Frota: {row['CD_EQT']}\n"
        f"Modelo: {row['MODELO']}\n"
        f"O.S: {row['NO_SERVICO']}\n"
        f"Data de entrada: {data_entrada}\n"
        f"Previsão de saída: {previsao_saida}\n"
        f"Prestador: {row['PREST_SERVICO']}\n"
        f"Serviço: {row['SERVICO']}\n"
    )

    if "ARTHUR" in servico and "SR" in servico:
        arthur.append(msg)
    elif "MAURICIO" in servico and "SR" in servico:
        mauricio.append(msg)
    elif "PREVISÃO DE SAÍDA: ---" in msg.upper():
        sem_prev.append(msg)
    else:
        outros.append(msg)

def salvar_bloco_txt_json(lista, nome_arquivo_txt, nome_arquivo_json, liberador=None):
    path_txt = os.path.join(pasta, nome_arquivo_txt)
    path_json = os.path.join(pasta, nome_arquivo_json)

    with open(path_txt, "w", encoding="utf-8") as f:
        f.write("\n\n" + ("\n" + "-"*50 + "\n\n").join(lista))
    print(f"📄 {nome_arquivo_txt} salvo.")

    dados = []
    for bloco in lista:
        linhas = bloco.strip().split("\n")
        if len(linhas) < 8:
            continue
        item = {
            "solicitante": linhas[0].split(":", 1)[1].strip(),
            "frota": linhas[1].split(":", 1)[1].strip(),
            "modelo": linhas[2].split(":", 1)[1].strip(),
            "os": linhas[3].split(":", 1)[1].strip(),
            "data_entrada": linhas[4].split(":", 1)[1].strip(),
            "previsao_saida": linhas[5].split(":", 1)[1].strip(),
            "prestador": linhas[6].split(":", 1)[1].strip(),
            "servico": linhas[7].split(":", 1)[1].strip(),
            "liberado_por": liberador if liberador else "Desconhecido"
        }
        dados.append(item)

    with open(path_json, "w", encoding="utf-8") as f:
        json.dump(dados, f, ensure_ascii=False, indent=4)
    print(f"📁 {nome_arquivo_json} salvo.")

salvar_bloco_txt_json(mauricio, "relatorio_mauricio.txt", "relatorio_mauricio.json", "Mauricio")
salvar_bloco_txt_json(arthur, "relatorio_arthur.txt", "relatorio_arthur.json", "Arthur")
salvar_bloco_txt_json(outros, "relatorio_outros.txt", "relatorio_outros.json", "Outros")
salvar_bloco_txt_json(sem_prev, "relatorio_sem_previsao.txt", "relatorio_sem_previsao.json", "Sem previsão")

print("\n🎉 Tudo finalizado com sucesso!")
