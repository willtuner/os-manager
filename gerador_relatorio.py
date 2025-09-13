import json
import argparse
import sys
from datetime import datetime
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import cm

def load_data(json_path):
    """
    Carrega os dados de um arquivo JSON.

    Args:
        json_path (str): O caminho para o arquivo JSON.

    Returns:
        list: Uma lista de dicionários com os dados, ou None se ocorrer um erro.
    """
    try:
        with open(json_path, "r", encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        print(f"Erro: O arquivo '{json_path}' não foi encontrado.")
        return None
    except json.JSONDecodeError:
        print(f"Erro: O arquivo '{json_path}' não é um JSON válido.")
        return None
    except Exception as e:
        print(f"Ocorreu um erro inesperado ao ler o arquivo: {e}")
        return None

def create_styles():
    """Cria e retorna os estilos de parágrafo para o PDF."""
    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        'TitleCustom',
        parent=styles['Title'],
        fontSize=20,
        leading=24,
        alignment=1,  # centralizado
        spaceAfter=12
    )
    subtitle_style = ParagraphStyle(
        'SubtitleCustom',
        parent=styles['Normal'],
        fontSize=10,
        leading=12,
        textColor=colors.gray,
        alignment=1,
        spaceAfter=12
    )
    header_style = ParagraphStyle(
        'HeaderCell',
        parent=styles['Normal'],
        fontSize=9,
        leading=11,
        textColor=colors.white,
        alignment=1
    )
    cell_style = ParagraphStyle(
        'Cell',
        parent=styles['Normal'],
        fontSize=8.2,
        leading=10.2,
    )
    return title_style, subtitle_style, header_style, cell_style

def generate_pdf(data, output_path):
    """
    Gera o relatório em PDF a partir dos dados fornecidos.

    Args:
        data (list): A lista de dados (ordens de serviço).
        output_path (str): O caminho para salvar o arquivo PDF de saída.
    """
    doc = SimpleDocTemplate(
        output_path,
        pagesize=landscape(A4),
        rightMargin=1*cm, leftMargin=1*cm, topMargin=1*cm, bottomMargin=1*cm
    )

    elements = []
    title_style, subtitle_style, header_style, cell_style = create_styles()

    today = datetime.now().strftime("%d/%m/%Y %H:%M")

    # --- Cabeçalho do Documento ---
    elements.append(Paragraph("RELATÓRIO DE ORDENS DE SERVIÇO", title_style))
    elements.append(Paragraph(f"Gerado em {today} • Total de OS: {len(data)}", subtitle_style))
    elements.append(Spacer(1, 6))

    # --- Tabela ---
    headers = ["OS", "Frota", "Modelo", "Data Entrada", "Solicitante", "Prestador", "Serviço", "Liberado por"]
    header_paragraphs = [Paragraph(h, header_style) for h in headers]
    rows = [header_paragraphs]

    for item in data:
        row = [
            Paragraph(str(item.get("os", "")), cell_style),
            Paragraph(str(item.get("frota", "")), cell_style),
            Paragraph(str(item.get("modelo", "")), cell_style),
            Paragraph(str(item.get("data_entrada", "")), cell_style),
            Paragraph(str(item.get("solicitante", "")), cell_style),
            Paragraph(str(item.get("prestador", "")).replace("nan", "—"), cell_style),
            Paragraph(str(item.get("servico", "")), cell_style),
            Paragraph(str(item.get("liberado_por", "")), cell_style),
        ]
        rows.append(row)

    # Ajuste de largura das colunas
    col_widths = [1.5*cm, 1.5*cm, 4.5*cm, 2.5*cm, 4*cm, 4*cm, 8.7*cm, 2*cm]

    table = Table(rows, colWidths=col_widths, repeatRows=1)

    table_style = TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#0F172A")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("ALIGN", (0, 0), (1, -1), "CENTER"),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LINEABOVE", (0, 0), (-1, 0), 1, colors.HexColor("#0F172A")),
        ("LINEBELOW", (0, 0), (-1, 0), 1, colors.HexColor("#0F172A")),
        ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#E5E7EB")),
    ])

    # Zebra striping (listras na tabela)
    for i in range(1, len(rows)):
        bg = colors.HexColor("#F8FAFC") if i % 2 != 0 else colors.white
        table_style.add("BACKGROUND", (0, i), (-1, i), bg)

    # Destaque de status por cor na lateral
    for r_idx, item in enumerate(data, 1):
        serv_text = item.get("servico", "").lower()
        if "parado" in serv_text or "parada" in serv_text:
            table_style.add("LINEBEFORE", (0, r_idx), (0, r_idx), 2, colors.HexColor("#DC2626"))
        elif "liberado" in serv_text or "finalizado" in serv_text:
            table_style.add("LINEBEFORE", (0, r_idx), (0, r_idx), 2, colors.HexColor("#16A34A"))

    table.setStyle(table_style)
    elements.append(table)

    # --- Rodapé ---
    def on_page(canvas, doc):
        canvas.saveState()
        footer_text = f"Relatório Gerado • {today}  |  Página {doc.page}"
        canvas.setFont("Helvetica", 8)
        canvas.setFillColor(colors.gray)
        canvas.drawRightString(landscape(A4)[0] - doc.rightMargin, 0.75*cm, footer_text)
        canvas.restoreState()

    try:
        doc.build(elements, onFirstPage=on_page, onLaterPages=on_page)
        print(f"PDF gerado com sucesso em: {output_path}")
    except Exception as e:
        print(f"Ocorreu um erro ao gerar o PDF: {e}")

def main():
    """Função principal para executar o script a partir da linha de comando."""
    parser = argparse.ArgumentParser(description="Gera um relatório em PDF a partir de um arquivo JSON.")
    parser.add_argument(
        "-i", "--input",
        dest="json_path",
        default="relatorio_mauricio.json",
        help="Caminho para o arquivo JSON de entrada (padrão: relatorio_mauricio.json)"
    )
    parser.add_argument(
        "-o", "--output",
        dest="output_path",
        default="Relatorio_OS_Mauricio.pdf",
        help="Caminho para salvar o arquivo PDF de saída (padrão: Relatorio_OS_Mauricio.pdf)"
    )
    args = parser.parse_args()

    data = load_data(args.json_path)
    if data:
        generate_pdf(data, args.output_path)
    else:
        sys.exit(1) # Termina o script com um código de erro

if __name__ == "__main__":
    main()
