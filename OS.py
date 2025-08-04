import os
import subprocess
import time
import json
import re
import pandas as pd
import pyautogui
from datetime import datetime, timedelta
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.common.action_chains import ActionChains

# ========================= ETAPA 1 =========================
print("\n🚀 Iniciando extração automática do relatório PIMNS...")
CHROMEDRIVER_PATH = "chromedriver.exe"
usuario = "WILSONS"
senha = "@prats456"

options = webdriver.ChromeOptions()
options.add_argument("--start-maximized")
service = Service(CHROMEDRIVER_PATH)
driver = webdriver.Chrome(service=service, options=options)

try:
    driver.get("http://10.1.1.51:8080/pimsmc/login.jsp")
    campo_usuario = WebDriverWait(driver, 20).until(EC.presence_of_element_located((By.ID, "USER")))
    campo_usuario.send_keys(usuario)
    campo_senha = WebDriverWait(driver, 10).until(EC.presence_of_element_located((By.ID, "SENHA")))
    campo_senha.send_keys(senha)
    botao_login = WebDriverWait(driver, 10).until(EC.element_to_be_clickable((By.XPATH, '//input[@type="submit" or @value="Fazer Login"]')))
    botao_login.click()
    WebDriverWait(driver, 10).until(EC.url_contains("manterFavoritos"))

    driver.get("http://10.1.1.51:8080/pimsmc/manterIndicadores.do?method=showViewConsulta&objectName=VisoesIndicadores.VisoesConsultaIndicadores")
    campo_codigo = WebDriverWait(driver, 30).until(EC.presence_of_element_located((By.ID, "CODIGO_INDICADOR")))
    campo_codigo.clear()
    campo_codigo.send_keys("OFC.STSOS")
    ActionChains(driver).move_to_element_with_offset(driver.find_element(By.TAG_NAME, "body"), 0, 0).click().perform()
    time.sleep(3)

    driver.find_element(By.ID, "VALOR_0").send_keys("01/01/2025")
    data_amanha = (datetime.today() + timedelta(days=1)).strftime("%d/%m/%Y")
    driver.find_element(By.ID, "VALOR_1").send_keys(data_amanha)
    driver.find_element(By.ID, "CODIGO_VALOR_2").clear()
    WebDriverWait(driver, 20).until(EC.element_to_be_clickable((By.XPATH, "//span[contains(text(), 'Aplicar')]"))).click()
    time.sleep(10)

    WebDriverWait(driver, 20).until(EC.element_to_be_clickable((By.XPATH, "//span[contains(text(), 'Exportar para Excel')]"))).click()
    time.sleep(15)
    pyautogui.click(1186, 103)
    time.sleep(15)
    pyautogui.moveTo(1269, 62)
    pyautogui.click()
    time.sleep(1)
    pyautogui.moveTo(1189, 106)
    pyautogui.click()
    driver.quit()
    print("✅ Relatório baixado com sucesso!")
except Exception as e:
    print("❌ Erro durante automação:", e)
    driver.save_screenshot("erro_automacao.png")
    driver.quit()
    exit()

# ========================= ETAPA 2 =========================
print("\n📊 Lendo relatório e gerando arquivos por gerente...")
pasta = r"C:\Users\wilsonsantana\Downloads"
remover_unidade_7 = True

arquivos = [os.path.join(pasta, f) for f in os.listdir(pasta) if f.startswith("Export_Consulta_Indicador_") and f.endswith(".xlsx")]
if not arquivos:
    print("❌ Nenhum arquivo encontrado!")
    exit()
excel_path = max(arquivos, key=os.path.getctime)
df = pd.read_excel(excel_path, header=9)
if remover_unidade_7:
    df = df[df["CD_UNI_ADM"] != 7]
df = df[df["DT_SAI_PREV"].isna()]
df["STATUS"] = df["STATUS"].astype(str).str.strip().str.upper()
df_abertas = df[df["STATUS"] == "ABERTO"]
df_abertas = df_abertas[df_abertas["FUNCIONAR_SOL"].notnull()]
df_abertas["DT_ENTRADA"] = pd.to_datetime(df_abertas["DT_ENTRADA"], errors="coerce", dayfirst=True)
df_abertas.to_csv(os.path.join(pasta, "relatorio_filtrado.csv"), index=False)

pasta_saida_txt = os.path.join(pasta, "mensagens_por_gerente")
os.makedirs(pasta_saida_txt, exist_ok=True)
for solicitante, grupo in df_abertas.groupby("FUNCIONAR_SOL"):
    mensagens = []
    for _, row in grupo.iterrows():
        data = row["DT_ENTRADA"].strftime("%d/%m/%Y") if pd.notnull(row["DT_ENTRADA"]) else ""
        msg = f"Frota: {row['CD_EQT']}\nO.S: {row['NO_SERVICO']}\nData de entrada: {data}\nPrestador: {row['PREST_SERVICO']}\nServiço: {row['SERVICO']}\n"
        mensagens.append(msg)
    with open(os.path.join(pasta_saida_txt, f"{solicitante}.txt"), "w", encoding="utf-8") as f:
        f.write(f"Solicitante: {solicitante}\n\n" + "\n---\n".join(mensagens))
print("✅ Arquivos .txt por gerente gerados!")

# ========================= ETAPA 3 =========================
print("\n🔁 Convertendo arquivos .txt para .json...")
pasta_json = os.path.join(pasta_saida_txt, "convertidos_json")
os.makedirs(pasta_json, exist_ok=True)

def processar_arquivo_txt(nome_arquivo):
    caminho_txt = os.path.join(pasta_saida_txt, nome_arquivo)
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
                elif chave.startswith("tempo") or chave.startswith("dias"): ordem["dias"] = valor
                elif chave == "prestador": ordem["prestador"] = valor if valor.lower() != "nan" else "Prestador não definido"
                elif chave in ("serviço", "servico"): ordem["servico"] = valor
                elif chave == "fazenda": ordem["fazenda"] = valor
                elif chave.startswith("liberado"): ordem["liberado"] = valor
                elif chave.startswith("solicitante"): ordem["solicitado"] = valor
        ordens.append(ordem)
    return ordens

for arquivo in os.listdir(pasta_saida_txt):
    if arquivo.lower().endswith(".txt"):
        nome_json = os.path.splitext(arquivo)[0].upper().replace(" ", "_").replace(".", "") + ".json"
        dados = processar_arquivo_txt(arquivo)
        with open(os.path.join(pasta_json, nome_json), "w", encoding="utf-8") as fjson:
            json.dump(dados, fjson, ensure_ascii=False, indent=2)
print("✅ Conversão dos .txt para .json concluída!")

# ========================= ETAPA 4 =========================
print("\n🧑‍🔧 Gerando arquivos JSON por prestador...")
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
print("✅ JSONs por prestador gerados com sucesso!")

print("\n🎉 Processo finalizado com sucesso!")