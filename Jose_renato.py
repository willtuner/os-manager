import json
from fpdf import FPDF
from datetime import datetime
import os
import re

# Arquivo de entrada e saída
ARQUIVO_JSON = r"C:\Users\wilsonsantana\Desktop\Extrator OS\JOSE_RENATO_LEMES_MARINHO_06173795990.json"
ARQUIVO_SAIDA = "Relatorio_OS_Jose_Renato.pdf"

# Função para extrair nome da fazenda
def extrair_fazenda(texto):
    match = re.search(r'\(?Faz(?:enda)?[\s\-:]*([A-Za-zÀ-ÿ0-9\s]+)', texto, re.IGNORECASE)
    return match.group(1).strip() if match else "Desconhecida"

# Função para limpar caracteres não suportados pela codificação 'latin-1'
def limpar_caracteres(texto):
    return (
        texto.replace("–", "-")
             .replace("“", '"')
             .replace("”", '"')
             .replace("‘", "'")
             .replace("’", "'")
             .replace("•", "-")
             .replace("→", "->")
             .replace("→", "->")
    )

# Ler JSON
with open(ARQUIVO_JSON, 'r', encoding='utf-8') as f:
    ordens = json.load(f)

# Agrupar por fazenda
fazendas = {}
for ordem in ordens:
    fazenda = extrair_fazenda(ordem.get("servico", ""))
    fazendas.setdefault(fazenda, []).append(ordem)

# Criar PDF
pdf = FPDF()
pdf.set_auto_page_break(auto=True, margin=15)
pdf.add_page()

# Cabeçalho
pdf.set_font("Arial", 'B', 16)
pdf.cell(0, 10, limpar_caracteres("Relatório de OS Abertas – Jose Renato"), ln=True, align="C")

pdf.set_font("Arial", size=12)
data_geracao = datetime.now().strftime("Gerado em: %d/%m/%Y %H:%M")
pdf.cell(0, 10, limpar_caracteres(data_geracao), ln=True, align="R")

pdf.set_font("Arial", 'B', 12)
pdf.cell(0, 10, f"Total de OS encontradas: {len(ordens)}", ln=True)

pdf.ln(5)

# Conteúdo por fazenda
for fazenda, lista_os in fazendas.items():
    pdf.set_font("Arial", 'B', 13)
    pdf.cell(0, 10, limpar_caracteres(f"Fazenda: {fazenda}"), ln=True)
    
    for ordem in lista_os:
        pdf.set_font("Arial", size=11)
        texto = (
            f"OS: {ordem['os']}\n"
            f"Frota: {ordem['frota']}\n"
            f"Modelo: {ordem['modelo']}\n"
            f"Data de entrada: {ordem['data_entrada']}\n"
            f"Serviço:\n{ordem['servico']}\n"
            "-----------------------------------------\n"
        )
        for linha in texto.split('\n'):
            pdf.multi_cell(0, 8, limpar_caracteres(linha))
    pdf.ln(5)

# Salvar PDF
pdf.output(ARQUIVO_SAIDA)
print(f"✅ PDF gerado com sucesso: {ARQUIVO_SAIDA}")
