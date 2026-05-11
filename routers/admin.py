from fastapi import APIRouter, Depends, Request, Form, Query, HTTPException, UploadFile, File
from utils.arquivos import salvar_imagem_produto
from fastapi.responses import HTMLResponse, RedirectResponse
from starlette import status
from sqlalchemy.orm import Session, joinedload
from collections import defaultdict
from pathlib import Path
from fastapi.templating import Jinja2Templates
from datetime import datetime, date, time, timedelta
from decimal import Decimal
from typing import List, Optional
from sqlalchemy import func, or_
import models
from security import gerar_hash_senha
from dependencies import get_db, get_current_admin_user


router = APIRouter(
    prefix="/painel/admin", # Todas as rotas aqui começarão com /painel/admin
    tags=["Administração"],
    dependencies=[Depends(get_current_admin_user)] # Protege todas as rotas deste router
)


# Configuração dos Templates
BASE_DIR = Path(__file__).resolve().parent.parent
templates = Jinja2Templates(directory=str(Path(BASE_DIR, 'templates')))


######################################## PÁGINA DE ADMINISTRAÇÃO ########################################


@router.get("/", response_class=HTMLResponse)
async def get_admin_page(request: Request, user: dict = Depends(get_current_admin_user)):
    """
    Exibe a página principal da área de Administração.

    Esta rota serve como o "hub" de navegação para todas as funcionalidades
    restritas ao administrador, como a gestão de funcionários, serviços,
    categorias, configurações e a visualização de relatórios financeiros.
    A sua única responsabilidade é renderizar o menu principal de administração.

    Args:
        request (Request): O objeto de requisição do FastAPI.
        user (dict): Os dados do usuário administrador logado, garantidos pela dependência a nível do router.

    Returns:
        TemplateResponse: Uma resposta HTML que renderiza a página 'admin.html'.
    """
    return templates.TemplateResponse("admin.html", {"request": request, "user": user})


######################################## PÁGINA DE DESEMPENHO DA EQUIPE ########################################


@router.get("/desempenho", response_class=HTMLResponse)
async def get_pagina_desempenho_equipa(
        request: Request, db: Session = Depends(get_db), user: dict = Depends(get_current_admin_user),
        data_inicio_filtro: date | None = Query(default=None), data_fim_filtro: date | None = Query(default=None)
):
    """
    Exibe o dashboard de desempenho consolidado para toda a equipe.
    """
    if data_inicio_filtro and data_fim_filtro:
        data_inicio = data_inicio_filtro
        data_fim = data_fim_filtro
        titulo_periodo = f"Período Personalizado ({data_inicio.strftime('%d/%m/%Y')} a {data_fim.strftime('%d/%m/%Y')})"
    else:
        hoje = date.today()
        weekday_hoje = hoje.weekday()
        offset_para_terca = (weekday_hoje - 1 + 7) % 7
        terca_desta_semana = hoje - timedelta(days=offset_para_terca)
        if weekday_hoje in [3, 4, 5]:
            data_inicio = terca_desta_semana
        else:
            data_inicio = terca_desta_semana - timedelta(days=7)
        data_fim = data_inicio + timedelta(days=4)
        titulo_periodo = f"Semana de Pagamento ({data_inicio.strftime('%d/%m/%Y')} a {data_fim.strftime('%d/%m/%Y')})"

    inicio_periodo = datetime.combine(data_inicio, time.min)
    fim_periodo = datetime.combine(data_fim, time.max)

    # ======================== INÍCIO DA DEPURAÇÃO ========================
    print("\n--- DEPURAÇÃO: DESEMPENHO DA EQUIPA ---")
    print(f"A analisar o período de: {inicio_periodo} até {fim_periodo}")
    # ===================================================================

    # 1. Busca o total de vendas de SERVIÇOS por funcionário
    resultados_vendas_servicos = db.query(
        models.Agendamento.funcionario_id,
        func.sum(models.Agendamento.preco_final).label("total_vendas")
    ).filter(
        models.Agendamento.status == models.StatusAgendamento.CONCLUIDO,
        models.Agendamento.data_hora.between(inicio_periodo, fim_periodo)
    ).group_by(models.Agendamento.funcionario_id).all()
    vendas_servicos_por_func = {func_id: total for func_id, total in resultados_vendas_servicos}

    # 2. Busca o total de vendas de PRODUTOS com comissão por funcionário
    resultados_vendas_produtos = db.query(
        models.FluxoCaixa.funcionario_id,
        func.sum(models.FluxoCaixa.valor).label("total_vendas_produtos")
    ).filter(
        models.FluxoCaixa.tipo == models.TipoFluxoCaixa.ENTRADA,
        models.FluxoCaixa.produto_id != None,
        models.FluxoCaixa.comissao_percentual > 0,
        models.FluxoCaixa.data_hora_registro.between(inicio_periodo, fim_periodo)
    ).group_by(models.FluxoCaixa.funcionario_id).all()

    # ======================== INÍCIO DA DEPURAÇÃO ========================
    print(f"Resultados da consulta de produtos: {resultados_vendas_produtos}")
    print("--- FIM DA DEPURAÇÃO ---\n")
    # ===================================================================

    vendas_produtos_por_func = {func_id: total for func_id, total in resultados_vendas_produtos}

    # 3. Combina os resultados para cada funcionário ativo
    funcionarios_ativos = db.query(models.Funcionario).filter(models.Funcionario.is_ativo == True).order_by(
        models.Funcionario.nome).all()
    desempenho_funcionarios = []
    for f in funcionarios_ativos:
        total_servicos = vendas_servicos_por_func.get(f.id, Decimal("0.00"))
        total_produtos = vendas_produtos_por_func.get(f.id, Decimal("0.00"))
        total_vendas = total_servicos + total_produtos

        desempenho_funcionarios.append({
            "funcionario": f,
            "total_vendas": total_vendas
        })

    context = {
        "request": request, "user": user, "desempenho_funcionarios": desempenho_funcionarios,
        "titulo_periodo": titulo_periodo, "data_inicio_filtro": data_inicio_filtro,
        "data_fim_filtro": data_fim_filtro
    }
    return templates.TemplateResponse("admin_desempenho.html", context)


######################################## MÓDULO DE GESTÃO DO FLUXO DE CAIXA ########################################


@router.get("/fluxo-caixa", response_class=HTMLResponse)
async def get_pagina_fluxo_caixa(
    request: Request,
    db: Session = Depends(get_db),
    user: dict = Depends(get_current_admin_user),
    data_filtro_str: str | None = Query(default=None, alias="data_filtro"),
    funcionario_id_str: str | None = Query(default=None, alias="funcionario_id")
):
    """
    Exibe a página de Fluxo de Caixa, detalhando as transações do dia.

    Esta rota serve como o principal relatório financeiro diário para o administrador.
    A sua lógica é flexível, permitindo a filtragem dos registros de caixa por:

    1.  Uma data específica (assumindo o dia de hoje como padrão).
    2.  Um funcionário específico.

    A função busca os registros relevantes, calcula os totais de entradas, saídas,
    e o saldo final do dia com base nos filtros aplicados, enviando todos os
    dados para a renderização do template.

    Args:
        request (Request): O objeto de requisição do FastAPI.
        db (Session): A sessão do banco de dados, injetada como dependência.
        user (dict): Os dados do usuário administrador logado.
        data_filtro (date | None): Data opcional para filtrar os registros de caixa.
        funcionario_id (int | None): ID opcional do funcionário para filtrar os registros.

    Returns:
        TemplateResponse: Uma resposta HTML que renderiza a página 'admin_fluxo_caixa.html',
                          populada com as transações filtradas e os resumos financeiros.
    """
    data_filtro = date.fromisoformat(data_filtro_str) if data_filtro_str else None
    funcionario_id = int(funcionario_id_str) if funcionario_id_str else None

    # Se nenhuma data for fornecida, assume o dia de hoje como padrão.
    if data_filtro is None:
        data_filtro = date.today()

    inicio_do_dia = datetime.combine(data_filtro, time.min)
    fim_do_dia = datetime.combine(data_filtro, time.max)
    funcionarios = db.query(models.Funcionario).order_by(models.Funcionario.nome).all()
    query_caixa = db.query(models.FluxoCaixa).options(
        joinedload(models.FluxoCaixa.funcionario)
    ).filter(models.FluxoCaixa.data_hora_registro.between(inicio_do_dia, fim_do_dia))

    if funcionario_id:
        query_caixa = query_caixa.filter(models.FluxoCaixa.funcionario_id == funcionario_id)

    registros_caixa = query_caixa.order_by(models.FluxoCaixa.data_hora_registro.asc()).all()
    funcionario_selecionado = next((f for f in funcionarios if f.id == funcionario_id), None)

    total_entradas = sum(r.valor for r in registros_caixa if r.tipo == 'Entrada')
    total_saidas = sum(r.valor for r in registros_caixa if r.tipo == 'Saída')
    saldo_do_dia = total_entradas - total_saidas

    context = {
        "request": request, "user": user, "registros": registros_caixa,
        "data_filtro_str": data_filtro.isoformat(),
        "data_exibida_str": data_filtro.strftime("%d/%m/%Y"),
        "total_entradas": total_entradas, "total_saidas": total_saidas,
        "saldo_do_dia": saldo_do_dia, "funcionarios": funcionarios,
        "funcionario_id_filtro": funcionario_id, "funcionario_selecionado": funcionario_selecionado
    }
    return templates.TemplateResponse("admin_fluxo_caixa.html", context)



@router.post("/fluxo-caixa/registrar-saida")
async def handle_form_registrar_saida(
    db: Session = Depends(get_db), user: dict = Depends(get_current_admin_user),
    descricao: str = Form(...), valor: Decimal = Form(...)
):
    """
    Processa o registro de uma saída de caixa manual.

    Esta rota POST é utilizada para registrar despesas operacionais do salão
    (ex: compra de produtos, pagamento de contas) que não estão associadas a um
    agendamento específico. A transação é registrada como do tipo 'Saída' e
    é atribuída ao administrador que está registrando.

    Args:
        db (Session): A sessão do banco de dados, injetada como dependência.
        user (dict): Os dados do usuário administrador logado que está registrando a saída.
        descricao (str): A descrição da despesa, vinda do formulário.
        valor (Decimal): O valor da despesa, vindo do formulário.

    Returns:
        RedirectResponse: Redireciona o administrador de volta para a página do
                          fluxo de caixa, atualizada para o dia de hoje.
    """
    # ... (código da função handle_form_registrar_saida)
    nova_saida = models.FluxoCaixa(
        descricao=descricao, valor=valor, tipo=models.TipoFluxoCaixa.SAIDA,
        funcionario_id=user.id, agendamento_id=None
    )
    db.add(nova_saida)
    db.commit()
    return RedirectResponse(
        url=f"/painel/admin/fluxo-caixa?data_filtro={date.today().isoformat()}",
        status_code=status.HTTP_303_SEE_OTHER
    )


######################################## MÓDULO DE GESTÃO DOS FUNCIONÁRIOS ########################################


@router.get("/funcionarios", response_class=HTMLResponse)
async def get_pagina_gerir_funcionarios(
    request: Request, db: Session = Depends(get_db), user: dict = Depends(get_current_admin_user)
):
    """
    Exibe a página principal para a gestão de funcionários.

    Esta rota serve como o "hub" para todas as operações administrativas
    relacionadas aos funcionários, como criar, editar e ativar/desativar contas.

    A função busca e exibe uma lista de TODOS os funcionários cadastrados,
    incluindo os inativos, para que o administrador tenha uma visão completa
    e possa reativar contas se necessário.

    Args:
        request (Request): O objeto de requisição do FastAPI.
        db (Session): A sessão do banco de dados, injetada como dependência.
        user (dict): Os dados do usuário administrador logado.

    Returns:
        TemplateResponse: Uma resposta HTML que renderiza a página 'admin_funcionarios.html',
                          populada com a lista de todos os funcionários.
    """
    # ... (código da função get_pagina_gerir_funcionarios)
    funcionarios = db.query(models.Funcionario).order_by(models.Funcionario.nome).all()
    context = {"request": request, "user": user, "funcionarios": funcionarios}
    return templates.TemplateResponse("admin_funcionarios.html", context)



@router.get("/funcionarios/novo", response_class=HTMLResponse)
async def get_pagina_novo_funcionario(
    request: Request, user: dict = Depends(get_current_admin_user)
):
    """
    Exibe o formulário para o cadastro de um novo funcionário.

    Esta rota GET renderiza o template 'admin_funcionario_form.html', que é
    reutilizado tanto para a criação quanto para a edição de funcionários.
    Ao passar 'funcionario=None' para o contexto, o template entende que está
    no modo de "criação", exibindo um formulário vazio.

    Args:
        request (Request): O objeto de requisição do FastAPI.
        user (dict): Os dados do usuário administrador logado.

    Returns:
        TemplateResponse: Uma resposta HTML que renderiza a página 'admin_funcionario_form.html'.
    """
    # ... (código da função get_pagina_novo_funcionario)
    context = {
        "request": request, "user": user, "funcionario": None,
        "action_url": "/painel/admin/funcionarios/novo"
    }
    return templates.TemplateResponse("admin_funcionario_form.html", context)



@router.post("/funcionarios/novo")
async def handle_form_novo_funcionario(
    request: Request, db: Session = Depends(get_db), user: dict = Depends(get_current_admin_user),
    nome: str = Form(...), cargo: str = Form(...), funcao: str = Form(...), senha: str = Form(...)
):
    """
    Processa os dados do formulário para o cadastro de um novo funcionário.

    Esta rota POST é responsável por validar os dados e criar um novo funcionário
    no sistema. Ela executa duas operações cruciais antes de salvar:

    1.  **Validação de Duplicidade:** Verifica se já existe um funcionário com o
        mesmo nome para garantir a unicidade dos utilizadores.
    2.  **Segurança da Senha:** Utiliza a função 'gerar_hash_senha' para converter
        a senha em texto puro num hash seguro antes de a armazenar no banco de dados.

    Args:
        request (Request): O objeto de requisição do FastAPI.
        db (Session): A sessão do banco de dados, injetada como dependência.
        user (dict): Os dados do usuário administrador logado.
        nome (str): O nome do novo funcionário, vindo do formulário.
        cargo (str): O cargo do novo funcionário.
        funcao (str): A função do novo funcionário no sistema ('Admin' ou 'Funcionario').
        senha (str): A senha em texto puro para o novo funcionário.

    Returns:
        RedirectResponse: Em caso de sucesso, redireciona para a página de gestão de funcionários.
        TemplateResponse: Se o nome do funcionário já existir, re-renderiza o formulário
                          com uma mensagem de erro.
    """
    # ... (código da função handle_form_novo_funcionario)
    funcionario_existente = db.query(models.Funcionario).filter(models.Funcionario.nome == nome).first()
    if funcionario_existente:
        context = {
            "request": request, "user": user, "funcionario": None,
            "action_url": "/painel/admin/funcionarios/novo",
            "error": "Já existe um funcionário com este nome."
        }
        return templates.TemplateResponse("admin_funcionario_form.html", context, status_code=400)
    senha_hashed = gerar_hash_senha(senha)
    novo_funcionario = models.Funcionario(nome=nome, cargo=cargo, funcao=funcao, senha_hash=senha_hashed)
    db.add(novo_funcionario)
    db.commit()
    return RedirectResponse(url="/painel/admin/funcionarios", status_code=status.HTTP_303_SEE_OTHER)



@router.get("/funcionarios/{funcionario_id}/editar", response_class=HTMLResponse)
async def get_pagina_editar_funcionario(
    request: Request, funcionario_id: int, db: Session = Depends(get_db), user: dict = Depends(get_current_admin_user)
):
    """
    Exibe o formulário pré-preenchido para editar um funcionário existente.

    Esta rota GET busca um funcionário específico pelo seu ID e reutiliza o
    template 'admin_funcionario_form.html' para exibir os seus dados.
    Ao passar o objeto 'funcionario' para o contexto, o template entende que
    está no modo de "edição", preenchendo os campos do formulário com os
    dados atuais do funcionário.

    Args:
        request (Request): O objeto de requisição do FastAPI.
        funcionario_id (int): O ID do funcionário a ser editado, vindo da URL.
        db (Session): A sessão do banco de dados, injetada como dependência.
        user (dict): Os dados do usuário administrador logado.

    Returns:
        TemplateResponse: Uma resposta HTML que renderiza a página 'admin_funcionario_form.html',
                          com os campos preenchidos com os dados do funcionário.
    """
    # ... (código da função get_pagina_editar_funcionario)
    funcionario = db.query(models.Funcionario).filter(models.Funcionario.id == funcionario_id).first()
    if not funcionario:
        raise HTTPException(status_code=404, detail="Funcionário não encontrado")
    context = {
        "request": request, "user": user, "funcionario": funcionario,
        "action_url": f"/painel/admin/funcionarios/{funcionario_id}/editar"
    }
    return templates.TemplateResponse("admin_funcionario_form.html", context)



@router.post("/funcionarios/{funcionario_id}/editar")
async def handle_form_editar_funcionario(
    request: Request, funcionario_id: int, db: Session = Depends(get_db), user: dict = Depends(get_current_admin_user),
    nome: str = Form(...), cargo: str = Form(...), funcao: str = Form(...), senha: str = Form(None)
):
    """
    Processa os dados do formulário para atualizar um funcionário existente.

    Esta rota POST é responsável por salvar as alterações feitas nos dados
    de um funcionário. A sua lógica principal inclui uma verificação condicional
    para a senha:

    - Os dados principais (nome, cargo, função) são sempre atualizados.
    - A senha só é alterada se um novo valor for fornecido no campo de senha.
      Se o campo for deixado em branco, a senha atual é mantida intacta.
      Isto permite que o administrador altere outros dados sem precisar de
      redefinir a senha a cada edição.

    Args:
        request (Request): O objeto de requisição do FastAPI.
        funcionario_id (int): O ID do funcionário a ser atualizado.
        db (Session): A sessão do banco de dados, injetada como dependência.
        user (dict): Os dados do usuário administrador logado.
        nome (str): O novo nome do funcionário.
        cargo (str): O novo cargo do funcionário.
        funcao (str): A nova função do funcionário no sistema.
        senha (str, optional): A nova senha em texto puro, se fornecida.

    Returns:
        RedirectResponse: Redireciona o administrador de volta para a página de
                          gestão de funcionários após a atualização.
    """
    # ... (código da função handle_form_editar_funcionario)
    db_funcionario = db.query(models.Funcionario).filter(models.Funcionario.id == funcionario_id).first()
    if not db_funcionario:
        raise HTTPException(status_code=404, detail="Funcionário não encontrado")
    db_funcionario.nome = nome
    db_funcionario.cargo = cargo
    db_funcionario.funcao = funcao
    if senha:
        senha_hashed = gerar_hash_senha(senha)
        db_funcionario.senha_hash = senha_hashed
    db.commit()
    return RedirectResponse(url="/painel/admin/funcionarios", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/funcionarios/{funcionario_id}/toggle-status")
async def toggle_status_funcionario(
    funcionario_id: int, db: Session = Depends(get_db), user: dict = Depends(get_current_admin_user)
):
    """
    Ativa ou desativa a conta de um funcionário no sistema.

    Esta rota POST implementa a funcionalidade de "soft delete", onde um funcionário
    não é permanentemente excluído, mas sim marcado como inativo. A função inverte
    o valor booleano do campo 'is_ativo' do funcionário alvo.

    Uma regra de segurança crítica está implementada para impedir que o administrador
    logado desative a sua própria conta, garantindo que o sistema nunca fique
    sem um administrador acessível.

    Args:
        funcionario_id (int): O ID do funcionário cujo status será alterado.
        db (Session): A sessão do banco de dados, injetada como dependência.
        user (dict): Os dados do usuário administrador logado.

    Returns:
        RedirectResponse: Redireciona o administrador de volta para a página de
                          gestão de funcionários após a alteração.
    """
    # ... (código da função toggle_status_funcionario)
    if user.id == funcionario_id:
        raise HTTPException(status_code=403, detail="Você não pode desativar sua própria conta.")
    db_funcionario = db.query(models.Funcionario).filter(models.Funcionario.id == funcionario_id).first()
    if not db_funcionario:
        raise HTTPException(status_code=404, detail="Funcionário não encontrado")
    db_funcionario.is_ativo = not db_funcionario.is_ativo
    db.commit()
    return RedirectResponse(url="/painel/admin/funcionarios", status_code=status.HTTP_303_SEE_OTHER)


######################################## MÓDULO DE GESTÃO DAS CATEGORIAS DE SERVIÇO ########################################


@router.get("/categorias", response_class=HTMLResponse)
async def get_pagina_gerir_categorias(
    request: Request, db: Session = Depends(get_db), user: dict = Depends(get_current_admin_user),
    error: str = None
):
    """
    Exibe a página principal para a gestão de categorias de serviços.

    Esta rota serve como o "hub" para todas as operações relacionadas a categorias,
    listando as existentes e contendo o formulário para a criação de novas.

    A função também é projetada para receber uma mensagem de erro opcional,
    permitindo que seja usada para re-renderizar a página com um feedback para o
    usuário em caso de falha numa operação (ex: tentativa de criar uma
    categoria com um nome duplicado).

    Args:
        request (Request): O objeto de requisição do FastAPI.
        db (Session): A sessão do banco de dados, injetada como dependência.
        user (dict): Os dados do usuário administrador logado.
        error (str, optional): Uma mensagem de erro opcional a ser exibida no template.

    Returns:
        TemplateResponse: Uma resposta HTML que renderiza a página 'admin_categorias.html'.
    """
    # ... (código da função get_pagina_gerir_categorias)
    categorias = db.query(models.Categoria).order_by(models.Categoria.nome).all()
    context = {"request": request, "user": user, "categorias": categorias, "error": error}
    return templates.TemplateResponse("admin_categorias.html", context)



@router.post("/categorias/nova")
async def handle_form_nova_categoria(
    request: Request, db: Session = Depends(get_db), user: dict = Depends(get_current_admin_user),
    nome: str = Form(...)
):
    """
    Processa os dados do formulário para a criação de uma nova categoria.

    Esta rota POST é responsável por validar o nome da nova categoria e, se for
    único, criar ela no banco de dados. A principal lógica de negócio
    implementada é a verificação de duplicidade para garantir que não existam
    duas categorias com o mesmo nome.

    Args:
        request (Request): O objeto de requisição do FastAPI.
        db (Session): A sessão do banco de dados, injetada como dependência.
        user (dict): Os dados do usuário administrador logado.
        nome (str): O nome da nova categoria, vindo do formulário.

    Returns:
        RedirectResponse: Em caso de sucesso, redireciona para a página de gestão de categorias.
        Coroutine[TemplateResponse]: Se a categoria já existir, re-renderiza a página
                                     de gestão com uma mensagem de erro.
    """
    # ... (código da função handle_form_nova_categoria)
    categoria_existente = db.query(models.Categoria).filter(models.Categoria.nome == nome).first()
    if categoria_existente:
        error_message = f"A categoria '{nome}' já existe."
        return await get_pagina_gerir_categorias(request, db, user, error=error_message)
    nova_categoria = models.Categoria(nome=nome)
    db.add(nova_categoria)
    db.commit()
    return RedirectResponse(url="/painel/admin/categorias", status_code=status.HTTP_303_SEE_OTHER)



@router.get("/categorias/{categoria_id}/detalhes", response_class=HTMLResponse)
async def get_pagina_detalhes_categoria(
    request: Request, categoria_id: int, db: Session = Depends(get_db), user: dict = Depends(get_current_admin_user)
):
    """
    Exibe a página de gestão detalhada para uma categoria específica.

    Esta rota GET serve a interface onde o administrador pode realizar duas
    operações principais para uma categoria: editar o seu nome e gerenciar
    quais serviços pertencem a ela.

    Para permitir a associação de serviços, a função busca não apenas a
    categoria alvo, mas também uma lista de todos os serviços cadastrados no
    sistema. Esta lista completa é usada para popular o formulário com
    checkboxes, permitindo que o administrador marque/desmarque as
    associações de forma intuitiva.

    Args:
        request (Request): O objeto de requisição do FastAPI.
        categoria_id (int): O ID da categoria a ser gerenciada, vindo da URL.
        db (Session): A sessão do banco de dados, injetada como dependência.
        user (dict): Os dados do usuário administrador logado.

    Returns:
        TemplateResponse: Uma resposta HTML que renderiza a página 'admin_categoria_detalhes.html'.
    """
    # ... (código da função get_pagina_detalhes_categoria)
    categoria = db.query(models.Categoria).filter(models.Categoria.id == categoria_id).first()
    if not categoria:
        raise HTTPException(status_code=404, detail="Categoria não encontrada")
    todos_os_servicos = db.query(models.Servico).order_by(models.Servico.nome).all()
    context = {"request": request, "user": user, "categoria": categoria, "todos_os_servicos": todos_os_servicos}
    return templates.TemplateResponse("admin_categoria_detalhes.html", context)



@router.post("/categorias/{categoria_id}/detalhes")
async def handle_form_detalhes_categoria(
    request: Request, categoria_id: int, db: Session = Depends(get_db), user: dict = Depends(get_current_admin_user),
    nome_categoria: str = Form(...), servicos_selecionados: List[int] = Form(default=[])
):
    """
    Processa as alterações da página de gestão detalhada de uma categoria.

    Esta rota POST é responsável por sincronizar o estado da categoria no
    banco de dados com base nos dados enviados pelo formulário. Ela executa
    duas operações principais:

    1.  Atualiza o nome da categoria.
    2.  Realiza uma sincronização completa dos serviços associados. A lógica de
        "reset-and-reapply" é utilizada: primeiro, todos os serviços que
        atualmente pertencem a esta categoria são desassociados; depois, a
        nova lista de serviços selecionados é associada. Isto garante que
        tanto as adições quanto as remoções de serviços sejam tratadas de
        forma correta.

    Args:
        request (Request): O objeto de requisição do FastAPI.
        categoria_id (int): O ID da categoria a ser atualizada.
        db (Session): A sessão do banco de dados, injetada como dependência.
        user (dict): Os dados do usuário administrador logado.
        nome_categoria (str): O novo nome para a categoria.
        servicos_selecionados (List[int]): Uma lista dos IDs dos serviços que devem pertencer a esta categoria.

    Returns:
        RedirectResponse: Redireciona o administrador de volta para a página de gestão de categorias após a atualização.
    """
    # ... (código da função handle_form_detalhes_categoria)
    db_categoria = db.query(models.Categoria).filter(models.Categoria.id == categoria_id).first()
    if not db_categoria:
        raise HTTPException(status_code=404, detail="Categoria não encontrada")
    db_categoria.nome = nome_categoria
    servicos_antigos = db.query(models.Servico).filter(models.Servico.categoria_id == categoria_id).all()
    for servico in servicos_antigos:
        servico.categoria_id = None
    if servicos_selecionados:
        servicos_novos = db.query(models.Servico).filter(models.Servico.id.in_(servicos_selecionados)).all()
        for servico in servicos_novos:
            servico.categoria_id = categoria_id
    db.commit()
    return RedirectResponse(url="/painel/admin/categorias", status_code=status.HTTP_303_SEE_OTHER)



@router.post("/categorias/{categoria_id}/excluir")
async def handle_form_excluir_categoria(
    categoria_id: int, db: Session = Depends(get_db), user: dict = Depends(get_current_admin_user)
):
    """
    Processa a exclusão permanente de uma categoria de serviço.

    Esta rota POST implementa um processo de exclusão segura para garantir a
    integridade referencial dos dados. Antes de apagar a categoria, a função
    executa um passo crucial:
    1.  Encontra todos os serviços que estão atualmente associados a esta categoria.
    2.  Desassocia-os, definindo o seu campo 'categoria_id' como nulo.

    Apenas após garantir que nenhum serviço está relacionado a esta categoria,
    ela é permanentemente removida do banco de dados.

    Args:
        categoria_id (int): O ID da categoria a ser excluída.
        db (Session): A sessão do banco de dados, injetada como dependência.
        user (dict): Os dados do usuário administrador logado.

    Returns:
        RedirectResponse: Redireciona o administrador de volta para a página de gestão de categorias após a exclusão.
    """
    # ... (código da função handle_form_excluir_categoria)
    db_categoria = db.query(models.Categoria).filter(models.Categoria.id == categoria_id).first()
    if not db_categoria:
        raise HTTPException(status_code=404, detail="Categoria não encontrada")
    servicos_associados = db.query(models.Servico).filter(models.Servico.categoria_id == categoria_id).all()
    for servico in servicos_associados:
        servico.categoria_id = None
    db.delete(db_categoria)
    db.commit()
    return RedirectResponse(url="/painel/admin/categorias", status_code=status.HTTP_303_SEE_OTHER)


######################################## MÓDULO DE GESTÃO DOS SERVIÇOS ########################################


@router.get("/servicos", response_class=HTMLResponse)
async def get_pagina_gerir_servicos(
    request: Request, db: Session = Depends(get_db), user: dict = Depends(get_current_admin_user),
    error: str = None
):
    """
    Exibe a página principal para a gestão de serviços do salão.

    Esta rota serve como o "hub" para todas as operações administrativas
    relacionadas aos serviços, listando os existentes e permitindo o acesso
    às funcionalidades de criação e edição.

    A função também é projetada para receber uma mensagem de erro opcional,
    permitindo que seja usada para re-renderizar a página com um feedback para o
    usuário em caso de falha numa operação (ex: tentativa de criar um
    serviço com um nome duplicado).

    Args:
        request (Request): O objeto de requisição do FastAPI.
        db (Session): A sessão do banco de dados, injetada como dependência.
        user (dict): Os dados do usuário administrador logado.
        error (str, optional): Uma mensagem de erro opcional a ser exibida no template.

    Returns:
        TemplateResponse: Uma resposta HTML que renderiza a página 'admin_servicos.html'.
    """
    # ... (código da função get_pagina_gerir_servicos)
    servicos = db.query(models.Servico).order_by(models.Servico.nome).all()
    context = {"request": request, "servicos": servicos, "user": user, "error": error}
    return templates.TemplateResponse("admin_servicos.html", context)



@router.get("/servicos/novo", response_class=HTMLResponse)
async def get_pagina_novo_servico(
    request: Request, db: Session = Depends(get_db), user: dict = Depends(get_current_admin_user)
):
    """
    Exibe o formulário para o cadastro de um novo serviço.

    Esta rota GET prepara e serve a página de formulário para a criação de um
    novo serviço. A sua principal responsabilidade é buscar a lista completa de
    categorias de serviço cadastradas, para que o administrador possa associar
    o novo serviço a uma delas, preservando o fluxo de trabalho.

    A função reutiliza o template 'admin_servico_form.html', passando 'servico=None'
    para indicar que o formulário deve ser renderizado no modo de "criação".

    Args:
        request (Request): O objeto de requisição do FastAPI.
        db (Session): A sessão do banco de dados, injetada como dependência.
        user (dict): Os dados do usuário administrador logado.

    Returns:
        TemplateResponse: Uma resposta HTML que renderiza a página 'admin_servico_form.html',
                          populada com a lista de categorias disponíveis.
    """
    # ... (código da função get_pagina_novo_servico)
    categorias = db.query(models.Categoria).order_by(models.Categoria.nome).all()
    context = {"request": request, "user": user, "servico": None, "categorias": categorias}
    return templates.TemplateResponse("admin_servico_form.html", context)



@router.post("/servicos/novo")
async def handle_form_novo_servico(
    request: Request, db: Session = Depends(get_db), user: dict = Depends(get_current_admin_user),
    nome: str = Form(...), duracao_padrao_minutos: int = Form(...),
    preco_minimo: Decimal = Form(...), categoria_id: int = Form(...)
):
    """
    Processa os dados do formulário para a criação de um novo serviço.

    Esta rota POST é responsável por validar os dados e criar um novo serviço
    no sistema, associando-o a uma categoria. A sua principal lógica de negócio
    é a verificação de duplicidade para garantir que não existam dois serviços
    com o mesmo nome, mantendo a integridade do catálogo.

    Args:
        request (Request): O objeto de requisição do FastAPI.
        db (Session): A sessão do banco de dados, injetada como dependência.
        user (dict): Os dados do usuário administrador logado.
        nome (str): O nome do novo serviço.
        duracao_padrao_minutos (int): A duração padrão do serviço em minutos.
        preco_minimo (Decimal): O preço mínimo do serviço.
        categoria_id (int): O ID da categoria à qual o serviço será associado.

    Returns:
        RedirectResponse: Em caso de sucesso, redireciona para a página de gestão de serviços.
        TemplateResponse: Se o serviço já existir, re-renderiza o formulário com uma mensagem de erro.
    """
    # ... (código da função handle_form_novo_servico)
    servico_existente = db.query(models.Servico).filter(models.Servico.nome == nome).first()
    if servico_existente:
        error_message = f"O serviço '{nome}' já existe."
        categorias = db.query(models.Categoria).order_by(models.Categoria.nome).all()
        context = {
            "request": request, "user": user, "servico": None,
            "categorias": categorias, "error": error_message
        }
        return templates.TemplateResponse("admin_servico_form.html", context)
    novo_servico = models.Servico(
        nome=nome, duracao_padrao_minutos=duracao_padrao_minutos,
        preco_minimo=preco_minimo, is_ativo=True, categoria_id=categoria_id
    )
    db.add(novo_servico)
    db.commit()
    return RedirectResponse(url="/painel/admin/servicos", status_code=status.HTTP_303_SEE_OTHER)



@router.get("/servicos/{servico_id}/editar", response_class=HTMLResponse)
async def get_pagina_editar_servico(
    request: Request, servico_id: int, db: Session = Depends(get_db), user: dict = Depends(get_current_admin_user)
):
    """
    Exibe o formulário pré-preenchido para editar um serviço existente.

    Esta rota GET busca um serviço específico pelo seu ID, bem como a lista
    completa de todas as categorias de serviço disponíveis. Ela reutiliza o
    template 'admin_servico_form.html', passando o objeto 'servico' para o
    contexto, o que sinaliza ao template para renderizar no modo de "edição",
    preenchendo os campos do formulário com os dados atuais do serviço.

    Args:
        request (Request): O objeto de requisição do FastAPI.
        servico_id (int): O ID do serviço a ser editado, vindo da URL.
        db (Session): A sessão do banco de dados, injetada como dependência.
        user (dict): Os dados do usuário administrador logado.

    Returns:
        TemplateResponse: Uma resposta HTML que renderiza a página 'admin_servico_form.html',
                          com os campos preenchidos e a lista de categorias.
    """
    # ... (código da função get_pagina_editar_servico)
    servico = db.query(models.Servico).filter(models.Servico.id == servico_id).first()
    if not servico:
        raise HTTPException(status_code=404, detail="Serviço não encontrado")
    categorias = db.query(models.Categoria).order_by(models.Categoria.nome).all()
    context = {"request": request, "user": user, "servico": servico, "categorias": categorias}
    return templates.TemplateResponse("admin_servico_form.html", context)


@router.post("/servicos/{servico_id}/editar")
async def handle_form_editar_servico(
        servico_id: int, db: Session = Depends(get_db), user: dict = Depends(get_current_admin_user),
        nome: str = Form(...), duracao_padrao_minutos: int = Form(...),
        preco_minimo: Decimal = Form(...),
        categoria_id_str: Optional[str] = Form(None, alias="categoria_id")
):
    """
    Processa os dados do formulário para atualizar um serviço existente.

    Esta rota POST é responsável por manter as alterações feitas a um serviço
    no banco de dados. Ela localiza o serviço pelo seu ID, e atualiza todos os
    seus atributos principais, incluindo a sua associação com uma categoria.

    Args:
        servico_id (int): O ID do serviço a ser atualizado.
        db (Session): A sessão do banco de dados, injetada como dependência.
        user (dict): Os dados do usuário administrador logado.
        nome (str): O novo nome do serviço.
        duracao_padrao_minutos (int): A nova duração padrão do serviço.
        preco_minimo (Decimal): O novo preço mínimo do serviço.
        categoria_id (Optional[int]): O novo ID da categoria associada ao serviço.

    Returns:
        RedirectResponse: Redireciona o administrador de volta para a página de
                          gestão de serviços após a atualização.
    """
    categoria_id = int(categoria_id_str) if categoria_id_str else None

    db_servico = db.query(models.Servico).filter(models.Servico.id == servico_id).first()
    if not db_servico:
        raise HTTPException(status_code=404, detail="Serviço não encontrado")

    db_servico.nome = nome
    db_servico.duracao_padrao_minutos = duracao_padrao_minutos
    db_servico.preco_minimo = preco_minimo
    db_servico.categoria_id = categoria_id

    db.commit()

    return RedirectResponse(url="/painel/admin/servicos", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/servicos/{servico_id}/excluir")
async def handle_form_excluir_servico(
    request: Request, servico_id: int, db: Session = Depends(get_db), user: dict = Depends(get_current_admin_user)
):
    """
    Processa a desativação ("soft delete") de um serviço.

    Esta rota POST não exclui permanentemente o serviço do banco de dados.
    Em vez disso, ela implementa a prática de "soft delete", alterando o
    status do serviço para inativo (`is_ativo = False`).

    Esta abordagem garante a integridade referencial dos dados históricos,
    garantindo que agendamentos e registros financeiros anteriores, que estão
    associados a este serviço, não percam a sua referência. O serviço
    simplesmente deixa de ser oferecido para novos agendamentos.

    Args:
        request (Request): O objeto de requisição do FastAPI.
        servico_id (int): O ID do serviço a ser desativado.
        db (Session): A sessão do banco de dados, injetada como dependência.
        user (dict): Os dados do usuário administrador logado.

    Returns:
        RedirectResponse: Redireciona o administrador de volta para a página de gestão de serviços.
    """
    # ... (código da função handle_form_excluir_servico)
    db_servico = db.query(models.Servico).filter(models.Servico.id == servico_id).first()
    if not db_servico:
        raise HTTPException(status_code=404, detail="Serviço não encontrado")
    db_servico.is_ativo = False
    db.commit()
    return RedirectResponse(url="/painel/admin/servicos", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/servicos/{servico_id}/reativar")
async def handle_form_reativar_servico(
    servico_id: int, db: Session = Depends(get_db), user: dict = Depends(get_current_admin_user)
):
    """
    Processa a reativação de um serviço previamente desativado.

    Esta rota POST altera o status do serviço de inativo para ativo
    (`is_ativo = True`), tornando-o novamente disponível para novos agendamentos
    no sistema.

    Args:
        servico_id (int): O ID do serviço a ser reativado.
        db (Session): A sessão do banco de dados, injetada como dependência.
        user (dict): Os dados do usuário administrador logado.

    Returns:
        RedirectResponse: Redireciona o administrador de volta para a página de gestão de serviços.
    """
    db_servico = db.query(models.Servico).filter(models.Servico.id == servico_id).first()
    if not db_servico:
        raise HTTPException(status_code=404, detail="Serviço não encontrado")

    db_servico.is_ativo = True
    db.commit()

    return RedirectResponse(url="/painel/admin/servicos", status_code=status.HTTP_303_SEE_OTHER)


######################################## MÓDULO DE GESTÃO DAS CONTAS CORRENTES ########################################


@router.get("/contas-correntes", response_class=HTMLResponse)
async def get_pagina_contas_correntes(
    request: Request, db: Session = Depends(get_db), user: dict = Depends(get_current_admin_user)
):
    """
    Exibe a página de resumo com os saldos das contas correntes de todos os funcionários.

    Esta rota serve como o ponto de entrada para a gestão das contas correntes.
    Ela fornece ao administrador uma visão geral do saldo atual
    de cada funcionário ativo, permitindo identificar rapidamente quem possui
    débitos (dívidas) ou créditos com o salão. A partir desta página, o
    administrador pode navegar para o extrato detalhado de cada funcionário.

    Args:
        request (Request): O objeto de requisição do FastAPI.
        db (Session): A sessão do banco de dados, injetada como dependência.
        user (dict): Os dados do usuário administrador logado.

    Returns:
        TemplateResponse: Uma resposta HTML que renderiza a página 'admin_contas_correntes.html',
                          populada com a lista de funcionários ativos e os seus saldos.
    """
    # ... (código da função get_pagina_contas_correntes)
    funcionarios = db.query(models.Funcionario).filter(models.Funcionario.is_ativo == True).order_by(models.Funcionario.nome).all()
    context = {"request": request, "user": user, "funcionarios": funcionarios}
    return templates.TemplateResponse("admin_contas_correntes.html", context)



@router.get("/contas-correntes/{funcionario_id}", response_class=HTMLResponse)
async def get_pagina_detalhes_conta_corrente(
    request: Request, funcionario_id: int, db: Session = Depends(get_db),
    user: dict = Depends(get_current_admin_user), success: bool = False
):
    """
    Exibe o extrato detalhado da conta corrente de um funcionário específico.

    Esta rota GET serve a página onde o administrador pode ver todas as transações
    (débitos e créditos) da conta corrente de um funcionário, bem como registrar
    um novo pagamento (crédito) para abater o saldo devedor.

    A consulta utiliza 'eager loading' (joinedload) para carregar de forma
    eficiente todas as transações associadas ao funcionário, evitando múltiplas
    buscas no banco de dados.

    Args:
        request (Request): O objeto de requisição do FastAPI.
        funcionario_id (int): O ID do funcionário cujo extrato será exibido.
        db (Session): A sessão do banco de dados, injetada como dependência.
        user (dict): Os dados do usuário administrador logado.
        success (bool, optional): Um sinalizador para exibir uma mensagem de sucesso após o registro de um pagamento.

    Returns:
        TemplateResponse: Uma resposta HTML que renderiza a página 'admin_conta_corrente_detalhes.html',
        populada com os dados do funcionário e o seu extrato de transações.
    """
    # ... (código da função get_pagina_detalhes_conta_corrente)
    funcionario = db.query(models.Funcionario).options(
        joinedload(models.Funcionario.transacoes_conta_corrente)
    ).filter(models.Funcionario.id == funcionario_id).first()
    if not funcionario:
        raise HTTPException(status_code=404, detail="Funcionário não encontrado")
    context = {"request": request, "user": user, "funcionario": funcionario, "success": success}
    return templates.TemplateResponse("admin_conta_corrente_detalhes.html", context)



@router.post("/contas-correntes/{funcionario_id}/pagamento")
async def handle_form_pagamento_conta_corrente(
    funcionario_id: int, db: Session = Depends(get_db), user: dict = Depends(get_current_admin_user),
    valor: Decimal = Form(...), descricao: str = Form(...)
):
    """
    Registra um pagamento (crédito) feito por um funcionário para a sua conta corrente.

    Esta rota POST é usada pelo administrador para registrar um acerto de contas de um
    funcionário. Ela executa duas operações financeiras cruciais de forma completa:

    1.  Cria um registo de 'Crédito' no extrato da conta corrente do funcionário.
    2.  Atualiza o saldo geral do funcionário, abatendo a sua dívida.

    A transação também registra qual administrador processou o pagamento, garantindo
    a rastreabilidade das operações feitas.

    Args:
        funcionario_id (int): O ID do funcionário que está efetuando o pagamento.
        db (Session): A sessão do banco de dados, injetada como dependência.
        user (dict): Os dados do administrador logado que está registrando o pagamento.
        valor (Decimal): O valor do pagamento, vindo do formulário.
        descricao (str): Uma descrição para a transação, vinda do formulário.

    Returns:
        RedirectResponse: Redireciona o administrador de volta para a página do extrato
                          do funcionário, com uma mensagem de sucesso.
    """
    # ... (código da função handle_form_pagamento_conta_corrente)
    funcionario = db.query(models.Funcionario).filter(models.Funcionario.id == funcionario_id).first()
    if not funcionario:
        raise HTTPException(status_code=404, detail="Funcionário não encontrado")
    nova_transacao = models.TransacaoContaCorrente(
        funcionario_id=funcionario_id, admin_id=user.id, tipo=models.TipoTransacao.CREDITO,
        valor=valor, descricao=descricao
    )
    db.add(nova_transacao)
    funcionario.saldo_conta_corrente += valor
    db.commit()
    return RedirectResponse(
        url=f"/painel/admin/contas-correntes/{funcionario_id}?success=true",
        status_code=status.HTTP_303_SEE_OTHER
    )


@router.post("/contas-correntes/{funcionario_id}/debito")
async def handle_form_debito_conta_corrente(
        funcionario_id: int, db: Session = Depends(get_db), user: dict = Depends(get_current_admin_user),
        valor: Decimal = Form(...), descricao: str = Form(...)
):
    """
    Registra um débito manual na conta corrente de um funcionário.

    Esta rota POST é usada para registrar valores que o salão adiantou ou
    precisa cobrar do funcionário (ex: adiantamentos, permutas especiais).
    Ela executa duas operações financeiras:

    1.  Cria um registro de 'Débito' no extrato da conta corrente do funcionário.
    2.  Atualiza o saldo geral do funcionário, subtraindo o valor do débito.

    Args:
        funcionario_id (int): O ID do funcionário que está recebendo o débito.
        db (Session): A sessão do banco de dados.
        user (dict): Os dados do administrador logado que está registrando o débito.
        valor (Decimal): O valor do débito, vindo do formulário.
        descricao (str): Uma descrição para a transação, vindo do formulário.

    Returns:
        RedirectResponse: Redireciona o administrador de volta para a página do extrato
                          do funcionário, com uma mensagem de sucesso.
    """
    funcionario = db.query(models.Funcionario).filter(models.Funcionario.id == funcionario_id).first()
    if not funcionario:
        raise HTTPException(status_code=404, detail="Funcionário não encontrado")

    nova_transacao = models.TransacaoContaCorrente(
        funcionario_id=funcionario_id,
        admin_id=user.id,
        tipo=models.TipoTransacao.DEBITO,
        valor=valor,
        descricao=descricao
    )
    db.add(nova_transacao)

    funcionario.saldo_conta_corrente -= valor

    db.commit()

    return RedirectResponse(
        url=f"/painel/admin/contas-correntes/{funcionario_id}?success=true",
        status_code=status.HTTP_303_SEE_OTHER
    )


######################################## MÓDULO DE CONFIGURAÇÃO ########################################


@router.get("/configuracoes", response_class=HTMLResponse)
async def get_pagina_configuracoes(
        request: Request, db: Session = Depends(get_db), user: dict = Depends(get_current_admin_user),
        success: bool = False
):
    """
    Exibe a página de configurações gerais para o administrador.

    Esta rota GET é responsável por buscar e exibir as regras de negócio
    configuráveis do sistema, como o limite de desconto em pacotes e a
    comissão do salão em serviços de permuta.

    A função foi projetada para ser resiliente: se uma configuração específica
    ainda não existir no banco de dados, ela utiliza um valor padrão seguro
    ("fallback") para garantir que a aplicação continue a funcionar corretamente.

    Args:
        request (Request): O objeto de requisição do FastAPI.
        db (Session): A sessão do banco de dados, injetada como dependência.
        user (dict): Os dados do usuário administrador logado.
        success (bool, optional): Um sinalizador para exibir uma mensagem de sucesso após salvar as configurações.

    Returns:
        TemplateResponse: Uma resposta HTML que renderiza a página 'admin_configuracoes.html'.
    """
    # Busca o limite de desconto
    limite_desconto_obj = db.query(models.Configuracao).filter(
        models.Configuracao.chave == "LIMITE_DESCONTO_PACOTE").first()
    limite_desconto = limite_desconto_obj.valor if limite_desconto_obj else "20"

    # Busca a comissão de permuta
    comissao_permuta_obj = db.query(models.Configuracao).filter(
        models.Configuracao.chave == "COMISSAO_SALAO_PERMUTA_PERC").first()
    comissao_permuta = comissao_permuta_obj.valor if comissao_permuta_obj else "50"

    # Busca a comissão máxima de produto, com um valor padrão de 10%
    comissao_maxima_obj = db.query(models.Configuracao).filter(
        models.Configuracao.chave == "COMISSAO_MAXIMA_PRODUTO").first()
    comissao_maxima_produto = comissao_maxima_obj.valor if comissao_maxima_obj else "10"

    context = {
        "request": request, "user": user, "limite_desconto": limite_desconto,
        "comissao_permuta": comissao_permuta,
        "comissao_maxima_produto": comissao_maxima_produto,  # Adicionado ao contexto
        "success": success
    }
    return templates.TemplateResponse("admin_configuracoes.html", context)


@router.post("/configuracoes")
async def handle_form_configuracoes(
        db: Session = Depends(get_db), user: dict = Depends(get_current_admin_user),
        limite_desconto: int = Form(..., ge=0, le=100),
        comissao_permuta: int = Form(..., ge=0, le=100),
        comissao_maxima_produto: int = Form(..., ge=0, le=100)
):
    """
    Processa e persiste as configurações globais do sistema.

    Esta rota POST é responsável por salvar as regras de negócio definidas pelo
    administrador. Para garantir um código limpo e atualizável, ela utiliza
    uma função auxiliar interna ('salvar_config') que implementa uma lógica de
    "upsert" (update or insert):

    - Se uma configuração já existe no banco, o seu valor é atualizado.
    - Se não existir, um novo registro é criado.

    Isto torna o sistema resiliente, funcionando corretamente tanto na primeira
    vez que as configurações são salvas quanto nas subsequentes.

    Args:
        db (Session): A sessão do banco de dados, injetada como dependência.
        user (dict): Os dados do usuário administrador logado.
        limite_desconto (int): O novo valor para o limite de desconto em pacotes.
        comissao_permuta (int): O novo valor para a comissão do salão em permutas.
        comissao_maxima_produto (int): O novo valor para a comissão máxima em produtos.

    Returns:
        RedirectResponse: Redireciona o administrador de volta para a página de configurações,
        com uma mensagem de sucesso.
    """

    def salvar_config(chave: str, valor: str):
        config_obj = db.query(models.Configuracao).filter(models.Configuracao.chave == chave).first()
        if not config_obj:
            config_obj = models.Configuracao(chave=chave, valor=valor)
            db.add(config_obj)
        else:
            config_obj.valor = valor

    salvar_config("LIMITE_DESCONTO_PACOTE", str(limite_desconto))
    salvar_config("COMISSAO_SALAO_PERMUTA_PERC", str(comissao_permuta))
    salvar_config("COMISSAO_MAXIMA_PRODUTO", str(comissao_maxima_produto))

    db.commit()

    return RedirectResponse(url="/painel/admin/configuracoes?success=true", status_code=status.HTTP_303_SEE_OTHER)


######################################## MÓDULO DE GESTÃO DE PRODUTOS ########################################


@router.get("/produtos", response_class=HTMLResponse)
async def get_pagina_gerir_produtos(
    request: Request, db: Session = Depends(get_db), user: dict = Depends(get_current_admin_user)
):
    """
    Exibe a página principal para a gestão de produtos.

    Esta rota serve como o "hub" para todas as operações administrativas
    relacionadas aos produtos, como criar, editar e ativar/desativar.

    A função busca e exibe uma lista de TODOS os produtos cadastrados,
    incluindo os inativos, para que o administrador tenha uma visão completa.

    Args:
        request (Request): O objeto de requisição do FastAPI.
        db (Session): A sessão do banco de dados.
        user (dict): Os dados do usuário administrador logado.

    Returns:
        TemplateResponse: Uma resposta HTML que renderiza a página 'admin_produtos.html',
                          populada com a lista de todos os produtos.
    """
    produtos = db.query(models.Produto).order_by(models.Produto.nome).all()
    context = {"request": request, "user": user, "produtos": produtos}
    return templates.TemplateResponse("admin_produtos.html", context)


@router.get("/produtos/novo", response_class=HTMLResponse)
async def get_pagina_novo_produto(
    request: Request, user: dict = Depends(get_current_admin_user)
):
    """
    Exibe o formulário para o cadastro de um novo produto.

    Esta rota GET renderiza o template 'admin_produto_form.html' que será
    reutilizado tanto para a criação quanto para a edição de produtos.
    Ao passar 'produto=None' para o contexto, o template entende que está
    no modo de "criação".

    Args:
        request (Request): O objeto de requisição do FastAPI.
        user (dict): Os dados do usuário administrador logado.

    Returns:
        TemplateResponse: Uma resposta HTML que renderiza a página 'admin_produto_form.html'.
    """
    context = {"request": request, "user": user, "produto": None}
    return templates.TemplateResponse("admin_produto_form.html", context)


@router.post("/produtos/novo")
async def handle_form_novo_produto(
    request: Request,
    db: Session = Depends(get_db),
    user: dict = Depends(get_current_admin_user),
    nome: str = Form(...),
    valor: Decimal = Form(...),
    foto: Optional[UploadFile] = File(None)
):
    """
    Processa os dados do formulário para criar um novo produto, incluindo o upload da foto.

    Realiza validações de duplicidade de nome, formato de ficheiro e tamanho do
    ficheiro antes de salvar o produto e a sua imagem no sistema.

    Args:
        request (Request): O objeto de requisição do FastAPI.
        db (Session): A sessão do banco de dados.
        user (dict): Os dados do administrador logado.
        nome (str): O nome do produto.
        valor (Decimal): O preço do produto.
        foto (Optional[UploadFile]): O ficheiro da foto do produto (opcional).

    Returns:
        RedirectResponse: Redireciona para a página de gestão de produtos.
        TemplateResponse: Re-renderiza o formulário com uma mensagem de erro em caso de falha na validação.
    """
    # Validação para evitar produtos com nomes duplicados
    produto_existente = db.query(models.Produto).filter(func.lower(models.Produto.nome) == func.lower(nome)).first()
    if produto_existente:
        context = {
            "request": request,
            "user": user,
            "produto": None,
            "error": "Já existe um produto com este nome."
        }
        return templates.TemplateResponse("admin_produto_form.html", context, status_code=400)

    caminho_foto_final = None
    if foto and foto.filename:
        try:
            caminho_foto_final = await salvar_imagem_produto(foto)
        except ValueError as e:
            context = {"request": request, "user": user, "produto": None, "error": str(e)}
            return templates.TemplateResponse("admin_produto_form.html", context, status_code=400)

    # Cria a nova instância do produto no banco de dados
    novo_produto = models.Produto(
        nome=nome,
        valor=valor,
        caminho_foto=caminho_foto_final
    )
    db.add(novo_produto)
    db.commit()

    return RedirectResponse(url="/painel/admin/produtos", status_code=status.HTTP_303_SEE_OTHER)


@router.get("/produtos/{produto_id}/editar", response_class=HTMLResponse)
async def get_pagina_editar_produto(
    produto_id: int,
    request: Request,
    db: Session = Depends(get_db),
    user: dict = Depends(get_current_admin_user)
):
    """
    Exibe o formulário pré-preenchido para editar um produto existente.

    Esta rota GET busca um produto específico pelo seu ID e reutiliza o
    template 'admin_produto_form.html' para exibir os seus dados.
    Ao passar o objeto 'produto' para o contexto, o template entende que
    está no modo de "edição".

    Args:
        produto_id (int): O ID do produto a ser editado.
        request (Request): O objeto de requisição do FastAPI.
        db (Session): A sessão do banco de dados.
        user (dict): Os dados do administrador logado.

    Returns:
        TemplateResponse: Renderiza a página 'admin_produto_form.html' com os
                          campos preenchidos com os dados do produto.
    """
    produto = db.query(models.Produto).filter(models.Produto.id == produto_id).first()
    if not produto:
        raise HTTPException(status_code=404, detail="Produto não encontrado")

    context = {"request": request, "user": user, "produto": produto}
    return templates.TemplateResponse("admin_produto_form.html", context)

@router.post("/produtos/{produto_id}/editar")
async def handle_form_editar_produto(
    produto_id: int,
    request: Request,
    db: Session = Depends(get_db),
    user: dict = Depends(get_current_admin_user),
    nome: str = Form(...),
    valor: Decimal = Form(...),
    foto: Optional[UploadFile] = File(None)
):
    """
    Processa os dados do formulário para atualizar um produto existente.

    Args:
        produto_id (int): O ID do produto a ser atualizado.
        request (Request): O objeto de requisição do FastAPI.
        db (Session): A sessão do banco de dados.
        user (dict): Os dados do administrador logado.
        nome (str): O novo nome do produto.
        valor (Decimal): O novo preço do produto.
        foto (Optional[UploadFile]): O novo ficheiro da foto do produto (opcional).

    Returns:
        RedirectResponse: Redireciona para a página de gestão de produtos.
        TemplateResponse: Re-renderiza o formulário com uma mensagem de erro em caso de falha na validação.
    """
    db_produto = db.query(models.Produto).filter(models.Produto.id == produto_id).first()
    if not db_produto:
        raise HTTPException(status_code=404, detail="Produto não encontrado")

    produto_existente = db.query(models.Produto).filter(
        func.lower(models.Produto.nome) == func.lower(nome),
        models.Produto.id != produto_id
    ).first()
    if produto_existente:
        context = {"request": request, "user": user, "produto": db_produto, "error": "Já existe outro produto com este nome."}
        return templates.TemplateResponse("admin_produto_form.html", context, status_code=400)

    if foto and foto.filename:
        try:
            nome_ficheiro_unico = await salvar_imagem_produto(foto)
        except ValueError as e:
            context = {"request": request, "user": user, "produto": db_produto, "error": str(e)}
            return templates.TemplateResponse("admin_produto_form.html", context, status_code=400)

        if db_produto.caminho_foto:
            caminho_foto_antiga = Path(BASE_DIR, "static", "uploads", "products", db_produto.caminho_foto)
            if caminho_foto_antiga.is_file():
                caminho_foto_antiga.unlink()

        db_produto.caminho_foto = nome_ficheiro_unico

    db_produto.nome = nome
    db_produto.valor = valor
    db.commit()

    return RedirectResponse(url="/painel/admin/produtos", status_code=status.HTTP_303_SEE_OTHER)

@router.post("/produtos/{produto_id}/toggle-status")
async def toggle_status_produto(
    produto_id: int,
    db: Session = Depends(get_db),
    user: dict = Depends(get_current_admin_user)
):
    """
    Ativa ou desativa um produto no sistema.

    Esta rota POST implementa a funcionalidade de "soft delete", onde um produto
    não é permanentemente excluído, mas sim marcado como inativo. A função inverte
    o valor booleano do campo 'is_ativo' do produto alvo.

    Args:
        produto_id (int): O ID do produto cujo status será alterado.
        db (Session): A sessão do banco de dados.
        user (dict): Os dados do administrador logado.

    Returns:
        RedirectResponse: Redireciona o administrador de volta para a página de
                          gestão de produtos após a alteração.
    """
    db_produto = db.query(models.Produto).filter(models.Produto.id == produto_id).first()
    if not db_produto:
        raise HTTPException(status_code=404, detail="Produto não encontrado")

    db_produto.is_ativo = not db_produto.is_ativo
    db.commit()

    return RedirectResponse(url="/painel/admin/produtos", status_code=status.HTTP_303_SEE_OTHER)