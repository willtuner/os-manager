# OS Manager – Sistema de Gestão de Ordens de Serviço

Um sistema web desenvolvido em Python/Flask para gerenciamento de Ordens de Serviço (OS) voltado à manutenção de frotas agrícolas e industriais. Permite que gerentes, prestadores e equipe de manutenção visualizem, atualizem e finalizem OS de forma fácil, segura e centralizada.

## Funcionalidades

- **Autenticação de usuários:** acesso individualizado para gerente, prestador e manutenção.
- **Visualização de OS abertas:** painel por usuário (gerente/prestador/manutenção) mostrando as OS em aberto.
- **Finalização de OS:** permite marcar OS como finalizada, adicionando data, hora e observações.
- **Painel de histórico:** exibe as OS já finalizadas, filtrando por usuário.
- **Atribuição de OS à equipe de manutenção.**
- **Exportação:** OS podem ser exportadas para Excel ou PDF.
- **Filtros avançados:** por data, frota ou palavras-chave.
- **Gestão por arquivos JSON:** OS e usuários são gerenciados por arquivos `.json` separados.

## Tecnologias utilizadas

- **Python 3**
- **Flask** (framework web)
- **Jinja2** (templates HTML)
- **Bootstrap/HTML/CSS** (front-end)
- **Pandas** (tratamento de dados)
- **JSON** (armazenamento das OS)
- **Gunicorn** (deploy)
- **Render** (hospedagem, pode ser usado localmente)

## Estrutura de Pastas
os-manager/
│
├── app.py # Arquivo principal da aplicação Flask
├── static/
│ └── json/ # OS abertas por usuário (ex: ARTHUR_SOUSA_OLIVEIRA.json)
├── templates/
│ ├── base.html
│ ├── painel_gerente.html
│ ├── painel_prestador.html
│ ├── painel_manutencao.html
│ └── login.html
├── users.json # Dados dos usuários (login e permissões)
├── Prestadores.json # Dados dos prestadores
├── fechamentos.csv # Histórico de OS finalizadas
├── pendentes.csv # Histórico de OS pendentes
├── requirements.txt # Dependências do projeto
└── README.md # Este arquivo
