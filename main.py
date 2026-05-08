"""
Ponto de entrada principal e configuração da aplicação FastAPI.

Este módulo é o coração da aplicação. As suas responsabilidades são:

1.  Carregar as variáveis de ambiente de forma segura a partir do ficheiro .env.
2.  Garantir que todas as tabelas do banco de dados sejam criadas no arranque.
3.  Inicializar a instância principal da aplicação FastAPI.
4.  Configurar middlewares globais, como o de gestão de sessões.
5.  Definir handlers de exceção globais, como o de redirecionamento para login.
6.  Incluir e agregar todos os routers modulares (autenticacao, painel, admin) para construir a API completa.
7.  Configurar o serviço de ficheiros estáticos para exibir imagens.
"""
from fastapi import FastAPI, Request
from fastapi.responses import RedirectResponse
from starlette import status
from starlette.middleware.sessions import SessionMiddleware
from fastapi.staticfiles import StaticFiles
import os
from dotenv import load_dotenv

from routers import autenticacao, painel, admin
from dependencies import NotAuthenticatedException

# Carrega as variáveis de ambiente definidas no ficheiro .env para o ambiente de execução.
load_dotenv()


SESSION_MAX_AGE_SECONDS = int(os.getenv("SESSION_MAX_AGE_SECONDS", "36000"))
SESSION_HTTPS_ONLY = os.getenv("SESSION_HTTPS_ONLY", "false").lower() == "true"


# Cria a instância principal da aplicação FastAPI, com metadados para documentação.
app = FastAPI(
    title="API do Salão de Beleza",
    description="API para gerenciar agendamentos, funcionários e serviços."
)

# Esta linha "monta" a pasta 'static' na URL '/static'.
# Qualquer ficheiro dentro da pasta 'static' do seu projeto estará acessível através de um URL que comece com /static.
app.mount("/static", StaticFiles(directory="static"), name="static")


# Adiciona o middleware de sessão à aplicação.
app.add_middleware(
    SessionMiddleware,
    secret_key=os.getenv("SECRET_KEY"),
    session_cookie="beauty_parlor_session",
    same_site="lax",
    https_only=SESSION_HTTPS_ONLY,
    max_age=SESSION_MAX_AGE_SECONDS
)

@app.exception_handler(NotAuthenticatedException)
async def auth_exception_handler(request: Request, exc: NotAuthenticatedException):
    """

    Handler de exceção global para utilizadores não autenticados.

    Este handler é acionado sempre que a exceção 'NotAuthenticatedException' é
    levantada em qualquer parte da aplicação (especificamente, na dependência
    'get_current_user'). A sua única responsabilidade é redirecionar o
    utilizador para a página de login, centralizando a lógica de proteção de
    rotas.
    """
    return RedirectResponse(url="/login", status_code=status.HTTP_302_FOUND)


# Inclui os routers modulares na aplicação principal.
app.include_router(autenticacao.router)
app.include_router(painel.router)
app.include_router(admin.router)
