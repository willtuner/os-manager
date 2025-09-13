import os
import sys
from gerador_relatorio import load_data, generate_pdf

# Diretório onde os JSONs de entrada estão localizados
INPUT_DIR = "mensagens_por_gerente/"

# Diretório onde os PDFs gerados serão salvos
OUTPUT_DIR = "relatorios_gerados/"

def main():
    """
    Função principal para encontrar todos os JSONs e gerar os PDFs correspondentes.
    """
    print("Iniciando a geração de relatórios em lote...")

    # Verifica se o diretório de entrada existe
    if not os.path.isdir(INPUT_DIR):
        print(f"Erro: O diretório de entrada '{INPUT_DIR}' não foi encontrado.")
        sys.exit(1)

    # Cria o diretório de saída se ele não existir
    if not os.path.exists(OUTPUT_DIR):
        print(f"Criando diretório de saída: '{OUTPUT_DIR}'")
        os.makedirs(OUTPUT_DIR)

    # Lista todos os arquivos no diretório de entrada
    try:
        json_files = [f for f in os.listdir(INPUT_DIR) if f.endswith('.json')]
    except OSError as e:
        print(f"Erro ao ler o diretório '{INPUT_DIR}': {e}")
        sys.exit(1)


    if not json_files:
        print(f"Nenhum arquivo .json encontrado em '{INPUT_DIR}'.")
        return

    print(f"Encontrados {len(json_files)} arquivos .json para processar.")

    success_count = 0
    error_count = 0

    # Itera sobre cada arquivo JSON e gera um PDF
    for json_file in json_files:
        json_path = os.path.join(INPUT_DIR, json_file)

        # Define o nome do arquivo de saída
        pdf_filename = os.path.splitext(json_file)[0] + '.pdf'
        output_path = os.path.join(OUTPUT_DIR, pdf_filename)

        print(f"Processando '{json_path}' -> '{output_path}'")

        # Carrega os dados do JSON
        data = load_data(json_path)

        # Gera o PDF se os dados foram carregados com sucesso
        if data:
            # Verifica se os dados não estão vazios
            if not data:
                print(f"Aviso: O arquivo '{json_path}' está vazio. Pulando.")
                error_count += 1
                continue
            generate_pdf(data, output_path)
            success_count += 1
        else:
            print(f"Erro ao carregar dados de '{json_path}'. Pulando.")
            error_count += 1

    print("\n--- Geração de Relatórios Concluída ---")
    print(f"Relatórios gerados com sucesso: {success_count}")
    print(f"Arquivos com erro ou vazios: {error_count}")
    print(f"Os relatórios estão salvos em: '{OUTPUT_DIR}'")


if __name__ == "__main__":
    main()
