
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

CHROMEDRIVER_PATH = "chromedriver.exe"
usuario = "WILSONS"
senha = "@prats456"
pasta = r"C:\Users\wilsonsantana\Downloads"

options = webdriver.ChromeOptions()
options.add_argument("--start-maximized")
service = Service(CHROMEDRIVER_PATH)
driver = webdriver.Chrome(service=service, options=options)

driver.get("http://10.1.1.51:8080/pimsmc/login.jsp")
try:
    campo_usuario = WebDriverWait(driver, 20).until(EC.presence_of_element_located((By.ID, "USER")))
    campo_usuario.send_keys(usuario)
    campo_senha = WebDriverWait(driver, 10).until(EC.presence_of_element_located((By.ID, "SENHA")))
    campo_senha.send_keys(senha)
    botao_login = WebDriverWait(driver, 10).until(EC.element_to_be_clickable((By.XPATH, '//input[@type="submit" or @value="Fazer Login"]')))
    botao_login.click()
except Exception as e:
    print("Erro ao fazer login:", e)
    driver.quit()

WebDriverWait(driver, 10).until(EC.url_contains("manterFavoritos"))
driver.get("http://10.1.1.51:8080/pimsmc/manterIndicadores.do?method=showViewConsulta&objectName=VisoesIndicadores.VisoesConsultaIndicadores")

campo_codigo = WebDriverWait(driver, 30).until(EC.presence_of_element_located((By.ID, "CODIGO_INDICADOR")))
campo_codigo.clear()
campo_codigo.send_keys("OFC.STSOS")
body = driver.find_element(By.TAG_NAME, "body")
ActionChains(driver).move_to_element_with_offset(body, 0, 0).click().perform()
time.sleep(3)

data_inicio = datetime(2025, 1, 1)
data_fim = datetime.today() + timedelta(days=1)
driver.find_element(By.ID, "VALOR_0").send_keys(data_inicio.strftime("%d/%m/%Y"))
driver.find_element(By.ID, "VALOR_1").send_keys(data_fim.strftime("%d/%m/%Y"))

driver.find_element(By.ID, "CODIGO_VALOR_2").clear()
WebDriverWait(driver, 20).until(EC.element_to_be_clickable((By.XPATH, "//span[contains(text(), 'Aplicar')]"))).click()
time.sleep(10)

WebDriverWait(driver, 20).until(EC.element_to_be_clickable((By.XPATH, "//span[contains(text(), 'Exportar para Excel')]"))).click()
time.sleep(15)
pyautogui.click(1186, 103)
time.sleep(10)
pyautogui.moveTo(1269, 62); pyautogui.click()
time.sleep(1)
pyautogui.moveTo(1197, 160); pyautogui.click()

arquivos = [os.path.join(pasta, f) for f in os.listdir(pasta) if f.startswith("Export_Consulta_Indicador_") and f.endswith(".xlsx")]
if not arquivos:
    raise FileNotFoundError("Nenhum relatório encontrado em Downloads.")
excel_path = max(arquivos, key=os.path.getctime)

df = pd.read_excel(excel_path, header=9)
df = df[df["CD_UNI_ADM"].isin([4, 5])]
df["STATUS"] = df["STATUS"].astype(str).str.strip().str.upper()
df_abertas = df[df["STATUS"] == "ABERTO"]
df_abertas = df_abertas[df_abertas["FUNCIONAR_SOL"].notnull()]
df_abertas = df_abertas.copy()
df_abertas["DT_ENTRADA"] = pd.to_datetime(df_abertas["DT_ENTRADA"], errors="coerce", dayfirst=True)
df_abertas = df_abertas[(df_abertas["DT_ENTRADA"] >= data_inicio) & (df_abertas["DT_ENTRADA"] <= data_fim)]

mensagens = []
for _, row in df_abertas.iterrows():
    data_entrada = row["DT_ENTRADA"].strftime("%d/%m/%Y") if pd.notnull(row["DT_ENTRADA"]) else "---"
    dt_saida_prev = row["DT_SAI_PREV"] if pd.notnull(row["DT_SAI_PREV"]) else "---"
    msg = (
        f"Solicitante: {row['FUNCIONAR_SOL']}\n"
        f"Frota: {row['CD_EQT']}\n"
        f"Modelo: {row['MODELO']}\n"
        f"O.S: {row['NO_SERVICO']}\n"
        f"Data de entrada: {data_entrada}\n"
        f"Previsão de saída: {dt_saida_prev}\n"
        f"Prestador: {row['PREST_SERVICO']}\n"
        f"Serviço: {row['SERVICO']}\n"
        f"{'-'*50}\n"
    )
    mensagens.append(msg)

saida_txt = os.path.join(pasta, "relatorio_OS_abertas.txt")
with open(saida_txt, "w", encoding="utf-8") as f:
    f.writelines(mensagens)

print(f"✅ Relatório salvo: {saida_txt}")

# Separação por liberador e sem previsão
with open(saida_txt, "r", encoding="utf-8") as f:
    conteudo = f.read()
os_blocos = conteudo.split("-" * 50)

arthur_os = []
mauricio_os = []
outros_os = []
sem_previsao_saida = []

for bloco in os_blocos:
    bloco_limpo = bloco.strip()
    if "PREVISÃO DE SAÍDA: ---" in bloco_limpo.upper():
        sem_previsao_saida.append(bloco_limpo)
    if "LIBERADO SR. MAURICIO" in bloco_limpo.upper():
        mauricio_os.append(bloco_limpo)
    elif "LIBERADO SR. ARTHUR" in bloco_limpo.upper():
        arthur_os.append(bloco_limpo)
    else:
        outros_os.append(bloco_limpo)

def salvar_txt(lista, nome):
    path = os.path.join(pasta, nome)
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n\n" + ("-"*50 + "\n\n").join(lista))
    print(f"📁 Arquivo salvo: {path}")

def salvar_json(lista_txt, nome, liberador):
    dados = []
    for bloco in lista_txt:
        linhas = bloco.strip().split("\n")
        item = {
            "solicitante": linhas[0].split(":", 1)[1].strip(),
            "frota": linhas[1].split(":", 1)[1].strip(),
            "modelo": linhas[2].split(":", 1)[1].strip(),
            "os": linhas[3].split(":", 1)[1].strip(),
            "data_entrada": linhas[4].split(":", 1)[1].strip(),
            "previsao_saida": linhas[5].split(":", 1)[1].strip(),
            "prestador": linhas[6].split(":", 1)[1].strip(),
            "servico": linhas[7].split(":", 1)[1].strip(),
            "liberado_por": liberador
        }
        dados.append(item)
    path = os.path.join(pasta, nome)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(dados, f, ensure_ascii=False, indent=4)
    print(f"📁 JSON salvo: {path}")

salvar_txt(mauricio_os, "relatorio_mauricio.txt")
salvar_txt(arthur_os, "relatorio_arthur.txt")
salvar_txt(outros_os, "relatorio_outros.txt")
salvar_txt(sem_previsao_saida, "relatorio_sem_previsao_saida.txt")
salvar_json(mauricio_os, "relatorio_mauricio.json", "Mauricio")
salvar_json(arthur_os, "relatorio_arthur.json", "Arthur")

