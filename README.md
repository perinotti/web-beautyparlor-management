# Bella Estética — Sistema de Gestão para Salão de Beleza

## Descrição

Este projeto é um sistema de gestão web completo para salões de beleza, desenvolvido como projeto acadêmico do curso de Análise e Desenvolvimento de Sistemas. A aplicação foi inspirada pela necessidade real do salão de beleza da minha mãe, que anteriormente gerenciava toda a sua operação com papel e caneta.

O sistema visa modernizar e otimizar a gestão diária, oferecendo uma solução robusta para agendamentos, controle financeiro, gestão de clientes, funcionários e produtos, com uma arquitetura de software limpa e escalável.

---

## Funcionalidades Principais

- **Autenticação Segura:** Sistema de login com distinção entre perfis "Funcionário" e "Admin", protegendo as rotas de acordo com a permissão.
- **Agenda Dinâmica:** Interface de agenda centralizada que permite visualizar e alternar entre os horários de múltiplos funcionários, fazer agendamentos e bloquear horários.
- **Gestão Financeira Completa:**
  - Fluxo de Caixa com filtros por data e funcionário.
  - Contas Correntes de Funcionários para débitos e créditos internos.
- **Hub de Clientes (CRM):**
  - Cadastro automático e manual de clientes.
  - Histórico completo de serviços e extrato de transações de crédito.
  - Sistema de Venda de Pacotes com descontos percentuais.
- **Gestão e Venda de Produtos:**
  - CRUD completo de Produtos com upload de imagens.
  - Ponto de Venda (PDV) para registro de vendas com lógica de comissão.
- **Painel de Administração:**
  - Gestão de Funcionários, Serviços e Categorias.
  - Dashboards de desempenho com filtros personalizáveis.
  - Configurações Gerais para ajuste de regras de negócio sem alterar código.
- **Auditoria:** Logs detalhados de todas as alterações importantes no sistema.

---

## Tecnologias Utilizadas

| Camada | Tecnologia |
|---|---|
| Backend | Python 3.9+ com FastAPI |
| Banco de Dados | PostgreSQL |
| ORM e Migrações | SQLAlchemy e Alembic |
| Frontend | HTML5, CSS3, Bootstrap 5, JavaScript |
| Autenticação | SessionMiddleware do Starlette + Passlib (bcrypt) |
| Segurança | python-dotenv para variáveis de ambiente |
| Controle de Versões | Git e GitHub |

---

## Como Executar o Projeto Localmente

### Pré-requisitos

Antes de começar, você precisará ter instalado na sua máquina:

- **Python 3.9 ou superior**
  - [Download para Windows](https://www.python.org/downloads/)
  - Linux/macOS: geralmente já vem instalado. Verifique com `python3 --version`
- **PostgreSQL 13 ou superior**
  - [Download para Windows](https://www.postgresql.org/download/windows/)
  - Linux (Debian/Ubuntu): `sudo apt install postgresql postgresql-contrib`
  - macOS: `brew install postgresql`
- **Git**
  - [Download para Windows](https://git-scm.com/download/win)
  - Linux: `sudo apt install git`
  - macOS: `brew install git`

---

### Passo 1 — Clonar o repositório

```bash
git clone https://github.com/perinotti/web-beautyparlor-management.git
cd web-beautyparlor-management
```

---

### Passo 2 — Criar e ativar o ambiente virtual

**Linux / macOS:**
```bash
python3 -m venv venv
source venv/bin/activate
```

**Windows (Prompt de Comando):**
```cmd
python -m venv venv
venv\Scripts\activate
```

**Windows (PowerShell):**
```powershell
python -m venv venv
venv\Scripts\Activate.ps1
```

> Se o PowerShell bloquear a execução de scripts, rode primeiro:
> `Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser`

Quando o ambiente estiver ativo, você verá `(venv)` no início da linha do terminal.

---

### Passo 3 — Instalar as dependências

```bash
pip install -r requirements.txt
```

---

### Passo 4 — Configurar o banco de dados PostgreSQL

**Linux / macOS:**
```bash
sudo -u postgres psql
```

**Windows:** abra o **pgAdmin** ou o **SQL Shell (psql)** instalado com o PostgreSQL.

Dentro do console do PostgreSQL, execute:

```sql
CREATE DATABASE beauty_parlor;
CREATE USER fastapi_user WITH PASSWORD 'sua_senha_aqui';
GRANT ALL PRIVILEGES ON DATABASE beauty_parlor TO fastapi_user;
\q
```

---

### Passo 5 — Configurar as variáveis de ambiente

Crie uma cópia do arquivo `.env.example` e renomeie para `.env`:

**Linux / macOS:**
```bash
cp .env.example .env
```

**Windows:**
```cmd
copy .env.example .env
```

Abra o arquivo `.env` e preencha com suas credenciais:

```env
DATABASE_URL=postgresql://fastapi_user:sua_senha_aqui@localhost/beauty_parlor
SECRET_KEY=uma_chave_secreta_longa_e_aleatoria_aqui
```

> Para gerar uma SECRET_KEY segura, você pode usar:
> ```bash
> python -c "import secrets; print(secrets.token_hex(32))"
> ```

---

### Passo 6 — Aplicar as migrações do banco de dados

```bash
alembic upgrade head
```

Este comando cria todas as tabelas e aplica as migrações necessárias. Ao final, deve aparecer algo como:
```
INFO [alembic.runtime.migration] Running upgrade ... -> ..., nome_da_migration
```

---

### Passo 7 — Iniciar o servidor

```bash
uvicorn main:app --reload
```

A aplicação estará disponível em: **http://127.0.0.1:8000**

**Credenciais padrão de acesso:**
- Usuário: `admin`
- Senha: `admin123`

> ⚠️ Altere a senha do admin imediatamente após o primeiro acesso em **Painel → Alterar Senha**.

---

## Fluxo de Trabalho para Contribuidores

Este projeto segue um fluxo baseado em forks e Pull Requests. Consulte o arquivo `CONTRIBUTING.md` para o guia completo.

### Branches principais

| Branch | Propósito |
|---|---|
| `master` | Código estável, aprovado e testado |
| `develop` | Branch de integração — PRs devem ser abertos para cá |

### Resumo do fluxo

```
fork → branch pessoal → PR para develop → revisão → merge em develop → PR para master
```

---

## Estrutura do Projeto

```
web-beautyparlor-management/
├── alembic/               # Migrações do banco de dados
│   └── versions/          # Arquivos de migration
├── routers/               # Rotas da aplicação
│   ├── autenticacao.py    # Login e logout
│   ├── painel.py          # Rotas do painel de funcionários
│   └── admin.py           # Rotas do painel administrativo
├── templates/             # Templates HTML (Jinja2)
├── static/                # Arquivos estáticos (CSS, imagens)
├── database.py            # Configuração da conexão com o banco
├── dependencies.py        # Dependências reutilizáveis (autenticação)
├── models.py              # Modelos do banco de dados (SQLAlchemy)
├── security.py            # Funções de hashing de senha
├── main.py                # Ponto de entrada da aplicação
├── requirements.txt       # Dependências Python
├── .env.example           # Exemplo de variáveis de ambiente
└── README.md              # Este arquivo
```

---

## Solução de Problemas Comuns

**Erro: `uvicorn: command not found`**
O ambiente virtual não está ativo. Execute `source venv/bin/activate` (Linux/macOS) ou `venv\Scripts\activate` (Windows) antes de rodar o servidor.

**Erro: `FATAL: Peer authentication failed for user "postgres"`**
No Linux, use `sudo -u postgres psql` em vez de `psql -U postgres`.

**Erro: `connection refused` ao conectar ao banco**
Verifique se o PostgreSQL está rodando:
- Linux: `sudo systemctl status postgresql`
- Windows: verifique nos Serviços do Windows se o serviço PostgreSQL está iniciado.

**Migrações com erro**
Verifique se as credenciais no `.env` estão corretas e se o banco `beauty_parlor` foi criado antes de rodar `alembic upgrade head`.
