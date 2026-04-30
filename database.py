"""
Configuração central da conexão com o banco de dados.

Este módulo é responsável por inicializar a conexão com o banco de dados PostgreSQL
utilizando SQLAlchemy. Ele lê a URL de conexão de forma segura a partir de
variáveis de ambiente (ficheiro .env) e exporta os componentes essenciais
(engine, SessionLocal, Base) que são utilizados em toda a aplicação para
interagir com o banco de dados.
"""
from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base
from sqlalchemy.orm import sessionmaker
import os
from dotenv import load_dotenv

# Carrega as variáveis de ambiente do ficheiro .env para o ambiente de execução.
# Esta linha deve ser executada antes de qualquer tentativa de proceder às variáveis.
load_dotenv()

# Lê a URL de conexão do banco de dados a partir das variáveis de ambiente.
# Esta é uma prática de segurança fundamental para evitar expor credenciais no código.
SQLALCHEMY_DATABASE_URL = os.getenv("SQLALCHEMY_DATABASE_URL", "sqlite:///./database.db")

# O 'engine' é o ponto de entrada principal do SQLAlchemy para o banco de dados.
# Ele gerencia as conexões e a comunicação com o PostgreSQL.
engine = create_engine(SQLALCHEMY_DATABASE_URL)

# Cria uma fábrica de sessões ('SessionLocal'). Cada instância desta classe
# representará uma nova sessão de banco de dados (uma única conversa com o banco).
# É a base para a injeção de dependência 'get_db'.
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# Cria uma classe 'Base' declarativa. Todos os nossos modelos de dados (tabelas)
# no ficheiro models.py irão herdar desta classe.
Base = declarative_base()

