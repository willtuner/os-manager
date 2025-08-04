import os
import pandas as pd
from datetime import datetime
from fpdf import FPDF

# Caminho da pasta onde está a planilha
pasta = r"C:\Users\wilsonsantana\Downloads"

# Encontra a planilha mais recente
arquivos = [os.path.join(pasta, f) for f in os.listdir(pasta) if f.startswith("Export_Consulta_Indicador_") and f.endswith(".xlsx")]
if not arquivos:
    raise FileNotFoundError("Nenhum arquivo .xlsx encontrado com prefixo esperado.")
excel_path = max(arquivos, key=os.path.getctime)

# Lê a planilha
df = pd.read_excel(excel_path, header=9)

# Filtros
df["STATUS"] = df["STATUS"].astype(str).str.strip().str.upper()
df = df[df["CD_UNI_ADM"].isin([4, 5])]  # ✅ Só unidades 04 e 05
df_filtrado = df[
    (df["STATUS"] == "ABERTO") &
    (df["DT_SAI_PREV"].notnull()) &
    (df["DT_SAIDA"].isna())
]

# Converte datas
df_filtrado["DT_ENTRADA"] = pd.to_datetime(df_filtrado["DT_ENTRADA"], errors="coerce", dayfirst=True)
df_filtrado["DT_SAI_PREV"] = pd.to_datetime(df_filtrado["DT_SAI_PREV"], errors="coerce", dayfirst=True)

# Classe PDF
class RelatorioPDF(FPDF):
    def header(self):
        self.set_font("Arial", "B", 14)
        self.cell(0, 10, "Relatório de OS Abertas com Previsão de Saída", ln=True, align="C")
        self.ln(5)
        self.set_font("Arial", "", 10)
        self.cell(0, 10, f"Gerado em: {datetime.now().strftime('%d/%m/%Y %H:%M')}", ln=True, align="R")
        self.set_font("Arial", "B", 11)
        self.cell(0, 10, f"Total de OS encontradas: {len(df_filtrado)}", ln=True)
        self.ln(5)

    def add_ordem(self, row):
        self.set_font("Arial", "", 11)
        self.multi_cell(0, 6, f"""
O.S: {row['NO_SERVICO']}
Frota: {row['CD_EQT']} | Modelo: {row.get('MODELO', '')}
Solicitante: {row['FUNCIONAR_SOL']}
Data de Entrada: {row['DT_ENTRADA'].strftime('%d/%m/%Y') if pd.notnull(row['DT_ENTRADA']) else '--'}
Previsão de Saída: {row['DT_SAI_PREV'].strftime('%d/%m/%Y') if pd.notnull(row['DT_SAI_PREV']) else '--'}
Prestador: {row['PREST_SERVICO']}
Serviço: {row['SERVICO']}
{"-"*80}
""")

# Gera PDF
pdf = RelatorioPDF()
pdf.set_auto_page_break(auto=True, margin=15)
pdf.add_page()

for _, row in df_filtrado.iterrows():
    pdf.add_ordem(row)

# Salva
saida_pdf = os.path.join(pasta, "Relatorio_Veganeer.pdf")
pdf.output(saida_pdf)

print(f"✅ PDF gerado com sucesso seu GOSTOSOOOO <3: {saida_pdf}")
