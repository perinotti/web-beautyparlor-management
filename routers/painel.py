from fastapi import APIRouter, Depends, Request, Form, Query, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse
from starlette import status
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import text, or_
from collections import defaultdict
from pathlib import Path
from fastapi.templating import Jinja2Templates
from datetime import datetime, date, time, timedelta, timezone
import pytz
from decimal import Decimal
from typing import Optional
import math
import models
from dependencies import get_db, get_current_user
from security import verificar_senha, gerar_hash_senha

router = APIRouter(
    prefix="/painel",  # Todas as rotas aqui começarão com /painel
    tags=["Painel Web"],
    dependencies=[Depends(get_current_user)] # Protege todas as rotas deste router
)

# Configuração dos Templates
BASE_DIR = Path(__file__).resolve().parent.parent
templates = Jinja2Templates(directory=str(Path(BASE_DIR, 'templates')))


def set_flash_message(request: Request, mensagem: str):
    request.session["flash_message"] = mensagem


def get_flash_message(request: Request) -> str | None:
    return request.session.pop("flash_message", None)


@router.get("/", response_class=HTMLResponse)
async def get_painel_gestao(request: Request, db: Session = Depends(get_db), user: dict = Depends(get_current_user)):
    """
    Exibe o painel principal da aplicação, a página inicial após o login.

    A principal responsabilidade desta rota é buscar e exibir a lista de todos
    os funcionários que estão atualmente ativos no sistema, permitindo que o
    usuário logado navegue para a agenda de cada um deles.

    Args:
        request (Request): O objeto de requisição do FastAPI, necessário para os templates.
        db (Session): A sessão do banco de dados, injetada como dependência.
        user (dict): Os dados do usuário logado, obtidos da sessão.

    Returns:
        TemplateResponse: Uma resposta HTML que renderiza a página 'painel.html',
        populada com a lista de funcionários ativos.
    """
    funcionarios = db.query(models.Funcionario).filter(models.Funcionario.is_ativo == True).order_by(models.Funcionario.nome).all()
    context = {"request": request, "funcionarios": funcionarios, "user": user}
    return templates.TemplateResponse("painel.html", context)


@router.get("/dashboard", response_class=HTMLResponse)
async def get_dashboard_page(
    request: Request,
    db: Session = Depends(get_db),
    user: dict = Depends(get_current_user),
    data: Optional[date] = Query(None)
):
    """
    Exibe o dashboard de desempenho semanal para o funcionário logado.

    Esta rota calcula o desempenho total de um funcionário num período de trabalho
    (Terça a Sábado), somando os valores dos serviços concluídos com as vendas
    de produtos que foram marcadas como comissionáveis.

    A função implementa a regra de negócio do dia de pagamento: com base numa
    data de referência (o dia atual ou uma data da URL), ela decide qual semana
    exibir. Até Quarta-feira, mostra a semana anterior completa (para a conferência
    do pagamento); a partir de Quinta-feira, mostra a semana corrente. A função
    também fornece datas para a navegação entre semanas.

    Args:
        request (Request): O objeto de requisição do FastAPI.
        db (Session): A sessão do banco de dados.
        user (dict): Os dados do usuário logado.
        data (Optional[date]): Uma data de referência opcional para calcular a semana.

    Returns:
        TemplateResponse: Renderiza a página 'dashboard.html' com os dados de
                          desempenho consolidados e as datas para navegação.
    """
    # 1. Determina a data de referência
    if data:
        data_base = data
    else:
        hoje = date.today()
        if hoje.weekday() in [6, 0, 1, 2]:
            data_base = hoje - timedelta(days=7)
        else:
            data_base = hoje

    # 2. Calcula a semana de trabalho
    weekday_base = data_base.weekday()
    offset_para_terca = (weekday_base - 1 + 7) % 7
    data_inicio = data_base - timedelta(days=offset_para_terca)
    data_fim = data_inicio + timedelta(days=4)

    data_semana_anterior = data_inicio - timedelta(days=7)
    data_proxima_semana = data_inicio + timedelta(days=7)

    inicio_periodo = datetime.combine(data_inicio, time.min)
    fim_periodo = datetime.combine(data_fim, time.max)

    # 3. Calcula o total de vendas de SERVIÇOS
    agendamentos_concluidos = db.query(models.Agendamento).filter(
        models.Agendamento.funcionario_id == user.id,
        models.Agendamento.status == models.StatusAgendamento.CONCLUIDO,
        models.Agendamento.data_hora.between(inicio_periodo, fim_periodo)
    ).all()
    total_vendas_servicos = sum(ag.preco_final for ag in agendamentos_concluidos if ag.preco_final is not None)

    # 4. Calcula o total de vendas de PRODUTOS com comissão
    vendas_produtos_comissionadas = db.query(models.FluxoCaixa).filter(
        models.FluxoCaixa.funcionario_id == user.id,
        models.FluxoCaixa.tipo == models.TipoFluxoCaixa.ENTRADA,
        models.FluxoCaixa.produto_id != None,
        models.FluxoCaixa.comissao_percentual > 0,
        models.FluxoCaixa.data_hora_registro.between(inicio_periodo, fim_periodo)
    ).all()
    total_vendas_produtos = sum(venda.valor for venda in vendas_produtos_comissionadas)

    # 5. Soma os totais para o desempenho final
    total_vendas = total_vendas_servicos + total_vendas_produtos

    # Prepara o contexto para enviar ao template
    context = {
        "request": request,
        "user": user,
        "agendamentos_concluidos": agendamentos_concluidos, # Mantemos para a lista de serviços
        "total_vendas": total_vendas,
        "data_inicio_str": data_inicio.strftime("%d/%m/%Y"),
        "data_fim_str": data_fim.strftime("%d/%m/%Y"),
        "data_semana_anterior": data_semana_anterior.isoformat(),
        "data_proxima_semana": data_proxima_semana.isoformat()
    }
    return templates.TemplateResponse("dashboard.html", context)


@router.get("/historico-desempenho", response_class=HTMLResponse)
async def get_pagina_historico_desempenho(
    request: Request,
    db: Session = Depends(get_db),
    user: dict = Depends(get_current_user),
    data_inicio_str: str | None = Query(default=None, alias="data_inicio"),
    data_fim_str: str | None = Query(default=None, alias="data_fim"),
    cliente_id_str: str | None = Query(default=None, alias="cliente_id"),
    servico_id_str: str | None = Query(default=None, alias="servico_id")
):
    """
    Exibe o relatório de histórico de desempenho para o funcionário logado.

    Esta rota serve como uma ferramenta de análise de vendas pessoal, permitindo
    que o funcionário filtre todos os seus serviços concluídos por um intervalo
    de datas, cliente específico ou serviço específico. A consulta ao banco de dados
    é construída dinamicamente, adicionando filtros apenas para os parâmetros
    que foram fornecidos pelo usuário na requisição.

    Args:
        request (Request): O objeto de requisição do FastAPI.
        db (Session): A sessão do banco de dados, injetada como dependência.
        user (dict): Os dados do usuário logado, obtidos da sessão.
        data_inicio (date | None): Data de início opcional para o filtro de período.
        data_fim (date | None): Data de fim opcional para o filtro de período.
        cliente_id (int | None): ID opcional do cliente para filtrar os resultados.
        servico_id (int | None): ID opcional do serviço para filtrar os resultados.

    Returns:
        TemplateResponse: Uma resposta HTML que renderiza a página 'historico_desempenho.html',
                          populada com os agendamentos filtrados e as opções para os
                          menus de filtro.
    """
    data_inicio = date.fromisoformat(data_inicio_str) if data_inicio_str else None
    data_fim = date.fromisoformat(data_fim_str) if data_fim_str else None
    cliente_id = int(cliente_id_str) if cliente_id_str else None
    servico_id = int(servico_id_str) if servico_id_str else None

    # Constrói a base da consulta
    query = db.query(models.Agendamento).options(
        joinedload(models.Agendamento.cliente),
        joinedload(models.Agendamento.servico)
    ).filter(
        models.Agendamento.funcionario_id == user.id,
        models.Agendamento.status == models.StatusAgendamento.CONCLUIDO
    )

    # Aplica os filtros dinamicamente
    if data_inicio:
        inicio_periodo = datetime.combine(data_inicio, time.min)
        query = query.filter(models.Agendamento.data_hora >= inicio_periodo)
    if data_fim:
        fim_periodo = datetime.combine(data_fim, time.max)
        query = query.filter(models.Agendamento.data_hora <= fim_periodo)
    if cliente_id:
        query = query.filter(models.Agendamento.cliente_id == cliente_id)
    if servico_id:
        query = query.filter(models.Agendamento.servico_id == servico_id)

    agendamentos_filtrados = query.order_by(models.Agendamento.data_hora.desc()).all()
    total_vendas_periodo = sum(ag.preco_final for ag in agendamentos_filtrados if ag.preco_final is not None)

    # Prepara dados para os menus dropdown do formulário de filtro
    todos_clientes = db.query(models.Cliente).order_by(models.Cliente.nome).all()
    servicos_para_filtro = db.query(models.Servico).options(
        joinedload(models.Servico.categoria)
    ).filter(models.Servico.is_ativo == True).join(
        models.Categoria, isouter=True
    ).order_by(models.Categoria.nome, models.Servico.nome).all()

    servicos_agrupados_filtro = defaultdict(list)
    for servico in servicos_para_filtro:
        categoria_nome = servico.categoria.nome if servico.categoria else "Outros"
        servicos_agrupados_filtro[categoria_nome].append(servico)

    context = {
        "request": request, "user": user, "agendamentos": agendamentos_filtrados,
        "total_vendas": total_vendas_periodo, "todos_clientes": todos_clientes,
        "servicos_agrupados_filtro": servicos_agrupados_filtro,
        "data_inicio_filtro": data_inicio, "data_fim_filtro": data_fim,
        "cliente_id_filtro": cliente_id, "servico_id_filtro": servico_id
    }
    return templates.TemplateResponse("historico_desempenho.html", context)


@router.get("/clientes", response_class=HTMLResponse)
async def get_pagina_listar_clientes(
    request: Request, db: Session = Depends(get_db), user: dict = Depends(get_current_user),
    q: str | None = Query(default=None), page: int = Query(default=1, ge=1)
):
    """
    Exibe o "Hub de Clientes", a página central para a gestão de clientes.

    Esta rota serve como o ponto de entrada principal para todas as operações
    relacionadas a clientes. Ela é responsável por:

    1. Filtrar clientes com base num termo de pesquisa opcional (nome ou WhatsApp).
    2. Paginar os resultados para garantir uma interface limpa e performática.
    3. Preparar e fornecer todos os dados necessários para a janela modal de
       "Vender Pacote", incluindo a lista completa de clientes e serviços.

    Args:
        request (Request): O objeto de requisição do FastAPI.
        db (Session): A sessão do banco de dados, injetada como dependência.
        user (dict): Os dados do usuário logado, obtidos da sessão.
        q (str | None): Termo de pesquisa opcional para filtrar a lista de clientes.
        page (int): O número da página atual para a paginação, com valor padrão 1.

    Returns:
        TemplateResponse: Uma resposta HTML que renderiza a página 'painel_clientes.html',
                          populada com a lista paginada de clientes e todos os dados
                          necessários para as funcionalidades da página.
    """
    # ... (código da função get_pagina_listar_clientes)
    page_size = 15
    query_clientes = db.query(models.Cliente)
    if q:
        search_term = f"%{q}%"
        query_clientes = query_clientes.filter(
            or_(models.Cliente.nome.ilike(search_term), models.Cliente.whatsapp.ilike(search_term))
        )
    total_items = query_clientes.count()
    total_pages = math.ceil(total_items / page_size)
    offset = (page - 1) * page_size
    clientes_paginados = query_clientes.order_by(models.Cliente.nome).offset(offset).limit(page_size).all()
    servicos_ativos = db.query(models.Servico).options(
        joinedload(models.Servico.categoria)
    ).filter(models.Servico.is_ativo == True).join(models.Categoria, isouter=True).order_by(
        models.Categoria.nome, models.Servico.nome
    ).all()
    servicos_agrupados = defaultdict(list)
    for servico in servicos_ativos:
        categoria_nome = servico.categoria.nome if servico.categoria else "Outros"
        servicos_agrupados[categoria_nome].append({"id": servico.id, "nome": servico.nome})
    servicos_json = {s.id: {"nome": s.nome, "preco": float(s.preco_minimo)} for s in servicos_ativos}
    todos_clientes_filtro = db.query(models.Cliente).order_by(models.Cliente.nome).all()
    context = {
        "request": request, "user": user, "clientes": clientes_paginados, "page": page,
        "total_pages": total_pages, "q": q, "servicos_agrupados": servicos_agrupados,
        "servicos_json": servicos_json, "todos_clientes_filtro": todos_clientes_filtro
    }
    return templates.TemplateResponse("painel_clientes.html", context)


@router.get("/vender-produto", response_class=HTMLResponse)
async def get_pagina_vender_produto(
        request: Request,
        db: Session = Depends(get_db),
        user: dict = Depends(get_current_user)
):
    """
    Exibe a página para a venda de produtos.

    Esta rota GET prepara e serve a interface de ponto de venda (PDV) para produtos.
    As suas principais responsabilidades são:

    1.  Buscar todos os produtos ativos no catálogo.
    2.  Buscar a configuração global de "comissão máxima" para informar os limites ao funcionário.
    3.  Formatar os dados dos produtos de duas maneiras para o frontend:
        - Uma lista de objetos para a renderização da tabela na página.
        - Um dicionário JSON para ser usado pelo JavaScript, permitindo que o
          resumo da venda seja calculado dinamicamente no lado do cliente.

    Args:
        request (Request): O objeto de requisição do FastAPI.
        db (Session): A sessão do banco de dados.
        user (dict): Os dados do funcionário logado.

    Returns:
        TemplateResponse: Renderiza a página 'vender_produto.html' com a lista
                          de produtos, o JSON para o script e a comissão máxima permitida.
    """
    produtos_ativos = db.query(models.Produto).filter(
        models.Produto.is_ativo == True
    ).order_by(models.Produto.nome).all()

    # Busca a configuração de comissão máxima definida pelo admin
    comissao_maxima_obj = db.query(models.Configuracao).filter(
        models.Configuracao.chave == "COMISSAO_MAXIMA_PRODUTO"
    ).first()
    # Usa um valor padrão de 10% se a configuração não existir
    comissao_maxima = comissao_maxima_obj.valor if comissao_maxima_obj else "10"

    # Prepara os dados para o JavaScript da página
    produtos_json = {p.id: {"nome": p.nome, "valor": float(p.valor)} for p in produtos_ativos}

    context = {
        "request": request,
        "user": user,
        "produtos": produtos_ativos,
        "produtos_json": produtos_json,
        "comissao_maxima": comissao_maxima
    }
    return templates.TemplateResponse("vender_produto.html", context)


@router.post("/vender-produto")
async def handle_form_vender_produto(
        request: Request,
        db: Session = Depends(get_db),
        user: dict = Depends(get_current_user),
        produto_ids: list[int] = Form(...),
        quantidades: list[int] = Form(...),
        metodo_pagamento: str = Form(...),
        comissao_percentual: Optional[Decimal] = Form(None)
):
    """
    Processa o formulário de venda de produtos, com lógica de comissão por percentagem.

    Esta rota POST valida a comissão inserida pelo funcionário contra o limite
    máximo definido pelo administrador. Se válida, cria registos no Fluxo de Caixa
    para cada produto vendido, armazenando a percentagem de comissão exata para
    futuros cálculos de desempenho.
    """
    # 1. Busca o limite máximo de comissão configurado pelo admin
    comissao_maxima_obj = db.query(models.Configuracao).filter(
        models.Configuracao.chave == "COMISSAO_MAXIMA_PRODUTO"
    ).first()
    limite_comissao = Decimal(comissao_maxima_obj.valor) if comissao_maxima_obj else Decimal("10")

    # 2. Valida a comissão recebida do formulário
    comissao_a_registrar = comissao_percentual if comissao_percentual is not None else Decimal("0.00")

    if not (0 <= comissao_a_registrar <= limite_comissao):
        # Se a comissão for inválida, recarrega a página com uma mensagem de erro
        produtos_ativos = db.query(models.Produto).filter(models.Produto.is_ativo == True).order_by(
            models.Produto.nome).all()
        produtos_json = {p.id: {"nome": p.nome, "valor": float(p.valor)} for p in produtos_ativos}
        context = {
            "request": request, "user": user, "produtos": produtos_ativos, "produtos_json": produtos_json,
            "comissao_maxima": limite_comissao,
            "error": f"A comissão deve estar entre 0% e {limite_comissao}%."
        }
        return templates.TemplateResponse("vender_produto.html", context, status_code=400)

    # 3. Se a validação passar, processa a venda
    for produto_id, quantidade in zip(produto_ids, quantidades):
        if quantidade > 0:
            produto = db.query(models.Produto).filter(models.Produto.id == produto_id).first()
            if not produto:
                continue

            valor_total_item = produto.valor * quantidade

            novo_registro_caixa = models.FluxoCaixa(
                descricao=f"Venda produto: {quantidade}x {produto.nome}",
                valor=valor_total_item,
                tipo=models.TipoFluxoCaixa.ENTRADA,
                metodo_pagamento=metodo_pagamento,
                funcionario_id=user.id,
                produto_id=produto.id,
                quantidade=quantidade,
                comissao_percentual=comissao_a_registrar
            )
            db.add(novo_registro_caixa)

    db.commit()

    return RedirectResponse(
        url="/painel/vender-produto?success=true",
        status_code=status.HTTP_303_SEE_OTHER
    )


@router.get("/clientes/novo", response_class=HTMLResponse)
async def get_pagina_novo_cliente(
    request: Request, user: dict = Depends(get_current_user), error: str | None = None
):
    """
    Exibe o formulário para o cadastro manual de um novo cliente.

    Esta rota GET serve a página que contém o formulário para adicionar um
    cliente diretamente ao sistema. Ela também é utilizada para re-renderizar
    o formulário com uma mensagem de erro, caso a submissão via POST falhe
    (por exemplo, ao tentar cadastrar um WhatsApp já existente).

    Args:
        request (Request): O objeto de requisição do FastAPI.
        user (dict): Os dados do usuário logado, obtidos da sessão.
        error (str | None): Uma mensagem de erro opcional a ser exibida no template.

    Returns:
        TemplateResponse: Uma resposta HTML que renderiza a página 'painel_cliente_form.html'.
    """
    context = {"request": request, "user": user, "error": error}
    return templates.TemplateResponse("painel_cliente_form.html", context)



@router.post("/clientes/novo")
async def handle_form_novo_cliente(
    request: Request, db: Session = Depends(get_db), user: dict = Depends(get_current_user),
    nome: str = Form(...), whatsapp: str = Form(...)
):
    """
    Processa os dados do formulário para o cadastro manual de um novo cliente.

    Esta rota POST recebe o nome e o WhatsApp de um novo cliente. Ela primeiro
    limpa a máscara do número de telefone e depois realiza uma validação
    crucial para verificar se o WhatsApp já existe no sistema, evitando
    duplicatas.

    Se o cliente for novo, ele é salvo e o sistema redireciona o usuário
    diretamente para a página de histórico do cliente recém-criado, otimizando
    o fluxo de trabalho para uma possível venda de pacote imediata.

    Args:
        request (Request): O objeto de requisição, passado para re-renderizar o formulário em caso de erro.
        db (Session): A sessão do banco de dados, injetada como dependência.
        user (dict): Os dados do usuário logado, obtidos da sessão.
        nome (str): O nome do cliente, recebido do formulário.
        whatsapp (str): O número de WhatsApp do cliente, recebido do formulário.

    Returns:
        RedirectResponse: Em caso de sucesso, redireciona para a página de histórico do cliente recém-criado.
        Coroutine[TemplateResponse]: Em caso de WhatsApp duplicado, re-renderiza o formulário de cadastro com uma mensagem de erro.
    """
    # ... (código da função handle_form_novo_cliente)
    whatsapp_limpo = "".join(filter(str.isdigit, whatsapp))
    cliente_existente = db.query(models.Cliente).filter(models.Cliente.whatsapp == whatsapp_limpo).first()
    if cliente_existente:
        return await get_pagina_novo_cliente(request, user, "Já existe um cliente cadastrado com este número de WhatsApp.")
    novo_cliente = models.Cliente(nome=nome, whatsapp=whatsapp_limpo)
    db.add(novo_cliente)
    db.commit()
    db.refresh(novo_cliente)
    return RedirectResponse(url=f"/painel/clientes/{novo_cliente.id}/historico", status_code=status.HTTP_303_SEE_OTHER)



@router.get("/clientes/{cliente_id}/historico", response_class=HTMLResponse)
async def get_pagina_historico_cliente(
    request: Request, cliente_id: int, db: Session = Depends(get_db), user: dict = Depends(get_current_user)
):
    """
    Exibe o painel de histórico completo de um cliente específico.

    Esta rota serve como o "Dashboard do Cliente", agregando todas as
    informações relevantes sobre ele. Ela realiza duas buscas principais:

    1. Busca os dados do cliente, utilizando 'eager loading' (joinedload) para
       carregar eficientemente o seu extrato de transações de crédito.
    2. Busca o histórico completo de agendamentos do cliente, carregando também
       os dados do serviço e do funcionário associados a cada um.

    Args:
        request (Request): O objeto de requisição do FastAPI.
        cliente_id (int): O ID do cliente a ser consultado, vindo da URL.
        db (Session): A sessão do banco de dados, injetada como dependência.
        user (dict): Os dados do usuário logado, obtidos da sessão.

    Returns:
        TemplateResponse: Uma resposta HTML que renderiza a página 'painel_cliente_historico.html',
        populada com os dados do cliente e seus históricos.
    """
    # ... (código da função get_pagina_historico_cliente)
    cliente = db.query(models.Cliente).options(
        joinedload(models.Cliente.transacoes_credito)
    ).filter(models.Cliente.id == cliente_id).first()
    if not cliente:
        raise HTTPException(status_code=404, detail="Cliente não encontrado")
    historico_agendamentos = db.query(models.Agendamento).options(
        joinedload(models.Agendamento.servico),
        joinedload(models.Agendamento.funcionario)
    ).filter(
        models.Agendamento.cliente_id == cliente_id
    ).order_by(models.Agendamento.data_hora.desc()).all()
    context = {"request": request, "user": user, "cliente": cliente, "historico": historico_agendamentos}
    return templates.TemplateResponse("painel_cliente_historico.html", context)


@router.get("/clientes/{cliente_id}/creditos", response_class=HTMLResponse)
async def get_pagina_adicionar_creditos(
    request: Request, cliente_id: int, db: Session = Depends(get_db), user: dict = Depends(get_current_user)
):
    """
    Exibe o formulário para a venda de pacotes de crédito para um cliente.

    Esta rota GET prepara todos os dados necessários para a complexa e interativa
    página de venda de pacotes. Suas responsabilidades incluem:

    1. Buscar os dados do cliente específico.
    2. Buscar todos os serviços ativos e agrupá-los por categoria para o menu de seleção.
    3. Buscar a configuração global de "limite de desconto" para aplicá-la como uma trava de segurança no formulário.
    4. Serializar os dados dos serviços para um formato JSON, para que o JavaScript
       possa realizar os cálculos de valor do pacote em tempo real na interface.

    Args:
        request (Request): O objeto de requisição do FastAPI.
        cliente_id (int): O ID do cliente para o qual o pacote será vendido.
        db (Session): A sessão do banco de dados, injetada como dependência.
        user (dict): Os dados do usuário logado, obtidos da sessão.

    Returns:
        TemplateResponse: Uma resposta HTML que renderiza a página 'painel_cliente_creditos.html',
        populada com todos os dados necessários para a sua interatividade.
    """
    # ... (código da função get_pagina_adicionar_creditos)
    cliente = db.query(models.Cliente).filter(models.Cliente.id == cliente_id).first()
    if not cliente:
        raise HTTPException(status_code=404, detail="Cliente não encontrado")
    servicos_ativos = db.query(models.Servico).options(
        joinedload(models.Servico.categoria)
    ).filter(
        models.Servico.is_ativo == True
    ).join(models.Categoria, isouter=True).order_by(
        models.Categoria.nome, models.Servico.nome
    ).all()
    servicos_agrupados = defaultdict(list)
    for servico in servicos_ativos:
        categoria_nome = servico.categoria.nome if servico.categoria else "Outros"
        servicos_agrupados[categoria_nome].append(servico)
    limite_obj = db.query(models.Configuracao).filter(models.Configuracao.chave == "LIMITE_DESCONTO_PACOTE").first()
    limite_desconto = limite_obj.valor if limite_obj else "20"
    context = {
        "request": request, "user": user, "cliente": cliente, "servicos_agrupados": servicos_agrupados,
        "servicos_json": {s.id: {"nome": s.nome, "preco": float(s.preco_minimo)} for s in servicos_ativos},
        "limite_desconto": limite_desconto
    }
    return templates.TemplateResponse("painel_cliente_creditos.html", context)



@router.post("/clientes/{cliente_id}/creditos")
async def handle_form_adicionar_creditos(
    request: Request, cliente_id: int, db: Session = Depends(get_db), user: dict = Depends(get_current_user),
    servicos_selecionados: list[int] = Form(...), quantidade_servicos: list[int] = Form(...),
    desconto_percentual: Decimal = Form(...), valor_total_pago: Decimal = Form(...),
    metodo_pagamento: str = Form(...)
):
    """
    Processa e registra a venda de um pacote de créditos para um cliente.

    Esta é uma rota crítica que executa uma transação financeira complexa,
    garantindo a consistência dos dados em várias tabelas.

    Suas responsabilidades são:

    1. Validar o desconto oferecido comparado ao limite máximo configurado pelo administrador.
    2. Atualizar o saldo de crédito na conta do cliente.
    3. Criar um registro de 'Adição' no extrato de transações de crédito do cliente.
    4. Criar um registro de 'Entrada' no fluxo de caixa geral do salão.

    Todas estas operações são consolidadas num único commit para garantir a totalidade da transação.

    Args:
        request (Request): O objeto de requisição do FastAPI.
        cliente_id (int): O ID do cliente que está a comprar o pacote.
        db (Session): A sessão do banco de dados, injetada como dependência.
        user (dict): Os dados do funcionário logado que está a realizar a venda.
        servicos_selecionados (list[int]): Lista de IDs dos serviços incluídos no pacote.
        quantidade_servicos (list[int]): Lista de quantidades para cada serviço correspondente.
        desconto_percentual (Decimal): A porcentagem de desconto aplicada.
        valor_total_pago (Decimal): O valor final pago pelo cliente após o desconto.
        metodo_pagamento (str): A forma de pagamento utilizada.

    Returns:
        RedirectResponse: Redireciona o usuário de volta para a página de histórico do cliente,
        onde o novo saldo e a transação serão visíveis.
    """
    # ... (código da função handle_form_adicionar_creditos)
    cliente = db.query(models.Cliente).filter(models.Cliente.id == cliente_id).first()
    if not cliente:
        raise HTTPException(status_code=404, detail="Cliente não encontrado")
    limite_obj = db.query(models.Configuracao).filter(models.Configuracao.chave == "LIMITE_DESCONTO_PACOTE").first()
    limite_maximo = Decimal(limite_obj.valor) if limite_obj else Decimal("20")
    if desconto_percentual > limite_maximo:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Operação não permitida. O desconto máximo para pacotes é de {limite_maximo}%."
        )
    descricao_pacote = "Pacote: "
    detalhes = []
    for servico_id, qtd in zip(servicos_selecionados, quantidade_servicos):
        servico = db.query(models.Servico).filter(models.Servico.id == servico_id).first()
        if servico:
            detalhes.append(f"{qtd}x {servico.nome}")
    descricao_pacote += ", ".join(detalhes)
    cliente.saldo_credito += valor_total_pago
    nova_transacao = models.TransacaoCredito(
        cliente_id=cliente.id, funcionario_id=user.id, tipo=models.TipoTransacao.ADICAO,
        valor=valor_total_pago, descricao=descricao_pacote
    )
    db.add(nova_transacao)
    nova_entrada_caixa = models.FluxoCaixa(
        funcionario_id=user.id, tipo=models.TipoFluxoCaixa.ENTRADA, valor=valor_total_pago,
        metodo_pagamento=metodo_pagamento, descricao=f"Venda de Crédito/Pacote para {cliente.nome}"
    )
    db.add(nova_entrada_caixa)
    db.commit()
    return RedirectResponse(url=f"/painel/clientes/{cliente_id}/historico", status_code=status.HTTP_303_SEE_OTHER)



@router.get("/funcionarios/{funcionario_id}", response_class=HTMLResponse)
async def get_detalhes_funcionario(
    request: Request, funcionario_id: int, db: Session = Depends(get_db),
    data: date = None, user: dict = Depends(get_current_user), error: str = None
):
    """
    Exibe a página da agenda diária para um funcionário específico.

    Esta é a rota central da aplicação, responsável por agregar e preparar
    uma grande quantidade de dados para a interface dinâmica da agenda.

    Suas principais responsabilidades são:

    1. Buscar o funcionário selecionado e uma lista de todos os outros funcionários ativos para permitir a navegação rápida entre agendas.
    2. Consultar todos os agendamentos e bloqueios para o dia e funcionário especificados.
    3. Separar os agendamentos em duas listas distintas: 'ativos' (para a agenda principal) e 'cancelados' (para a janela modal).
    4. Combinar e ordenar os agendamentos ativos e os bloqueios para criar a visualização cronológica do dia.
    5. Preparar a lista de serviços, agrupados por categoria, para o formulário de novo agendamento.
    6. Calcular e anexar um prazo de edição dinâmico para cada agendamento.

    Args:
        request (Request): O objeto de requisição do FastAPI.
        funcionario_id (int): O ID do funcionário cuja agenda deve ser exibida.
        db (Session): A sessão do banco de dados, injetada como dependência.
        data (date, optional): A data para a qual a agenda deve ser exibida. Assume o dia de hoje se não for fornecida.
        user (dict): Os dados do usuário logado, obtidos da sessão.
        error (str, optional): Uma mensagem de erro opcional a ser exibida (ex: conflito de horário).

    Returns:
        TemplateResponse: Uma resposta HTML que renderiza a página 'funcionario_agenda.html',
        populada com todos os dados processados para a interface.
    """
    # ... (código da função get_detalhes_funcionario)
    flash_message = get_flash_message(request)
    if not error and flash_message:
        error = flash_message
    funcionario_selecionado = db.query(models.Funcionario).filter(models.Funcionario.id == funcionario_id).first()
    if not funcionario_selecionado:
        return templates.TemplateResponse("404.html", {"request": request}, status_code=404)
    todos_funcionarios_ativos = db.query(models.Funcionario).filter(models.Funcionario.is_ativo == True).order_by(models.Funcionario.nome).all()
    if data is None: data = date.today()
    dia_anterior = data - timedelta(days=1)
    proximo_dia = data + timedelta(days=1)
    inicio_do_dia = datetime.combine(data, time.min)
    fim_do_dia = datetime.combine(data, time.max)
    todos_agendamentos_do_dia = db.query(models.Agendamento).options(
        joinedload(models.Agendamento.cliente),
        joinedload(models.Agendamento.servico)
    ).filter(
        models.Agendamento.funcionario_id == funcionario_id,
        models.Agendamento.data_hora.between(inicio_do_dia, fim_do_dia)
    ).order_by(models.Agendamento.data_hora).all()
    agendamentos_ativos = []
    agendamentos_cancelados = []
    for ag in todos_agendamentos_do_dia:
        if ag.status == models.StatusAgendamento.CANCELADO:
            agendamentos_cancelados.append(ag)
        else:
            ag.tipo = 'agendamento'
            agendamentos_ativos.append(ag)
    bloqueios_do_dia = db.query(models.Bloqueio).filter(
        models.Bloqueio.funcionario_id == funcionario_id,
        models.Bloqueio.inicio < fim_do_dia,
        models.Bloqueio.fim > inicio_do_dia
    ).order_by(models.Bloqueio.inicio).all()
    for item in bloqueios_do_dia: item.tipo = 'bloqueio'
    agenda_completa = sorted(agendamentos_ativos + bloqueios_do_dia,
                             key=lambda item: item.data_hora if item.tipo == 'agendamento' else item.inicio)
    for item in agenda_completa:
        if item.tipo == 'agendamento':
            horario_termino = item.data_hora + timedelta(minutes=item.duracao_efetiva_minutos)
            item.prazo_edicao = horario_termino + timedelta(hours=1)
    servicos_ativos = db.query(models.Servico).options(
        joinedload(models.Servico.categoria)
    ).filter(
        models.Servico.is_ativo == True
    ).join(models.Categoria, isouter=True).order_by(
        models.Categoria.nome, models.Servico.nome
    ).all()
    servicos_agrupados = defaultdict(list)
    for servico in servicos_ativos:
        categoria_nome = servico.categoria.nome if servico.categoria else "Outros"
        servicos_agrupados[categoria_nome].append(servico)
    horarios_selecao = [f"{h:02d}:{m:02d}" for h in range(8, 20) for m in range(0, 60, 30)]
    context = {
        "request": request, "funcionario": funcionario_selecionado,
        "todos_funcionarios_ativos": todos_funcionarios_ativos,
        "agenda_completa": agenda_completa, "agendamentos_cancelados": agendamentos_cancelados,
        "data_exibida_str": data.strftime("%d/%m/%Y"), "data_atual_iso": data.isoformat(),
        "dia_anterior_str": dia_anterior.isoformat(), "proximo_dia_str": proximo_dia.isoformat(),
        "servicos_agrupados": servicos_agrupados, "servicos": servicos_ativos,
        "horarios_selecao": horarios_selecao, "data_hoje_obj": date.today(),
        "agora_local": datetime.now(), "user": user, "error": error
    }
    return templates.TemplateResponse("funcionario_agenda.html", context)


@router.post("/funcionarios/{funcionario_id}/agendar")
async def handle_form_agendamento(
    request: Request, funcionario_id: int, db: Session = Depends(get_db), user: dict = Depends(get_current_user),
    nome_cliente: str = Form(...), whatsapp_cliente: str = Form(...),
    data_agendamento: date = Form(...), hora_agendamento: time = Form(...),
    servico_id: int = Form(...), duracao_efetiva: int = Form(...)
):
    """
    Processa os dados do formulário para criar um novo agendamento.

    Esta rota POST é o motor central do sistema. Suas responsabilidades são:

    1.  **Gestão de Clientes "Find-or-Create":** Procura um cliente pelo número
        de WhatsApp. Se o cliente não existir, cria um novo registro de
        cliente automaticamente, otimizando o fluxo de trabalho.
    2.  **Validação de Conflitos:** Realiza uma verificação rigorosa para garantir
        que o novo agendamento não se sobreponha a agendamentos ou bloqueios
        de tempo já existentes na agenda do funcionário.
    3.  **Criação do Agendamento:** Se não houver conflitos, cria o novo registro de agendamento no banco de dados.

    Args:
        request (Request): O objeto de requisição do FastAPI.
        funcionario_id (int): O ID do funcionário para o qual o agendamento está a ser criado.
        db (Session): A sessão do banco de dados, injetada como dependência.
        user (dict): Os dados do usuário logado.
        nome_cliente (str): O nome do cliente, vindo do formulário.
        whatsapp_cliente (str): O WhatsApp do cliente, vindo do formulário.
        data_agendamento (date): A data do agendamento, vinda do formulário.
        hora_agendamento (time): A hora do agendamento, vinda do formulário.
        servico_id (int): O ID do serviço selecionado.
        duracao_efetiva (int): A duração em minutos do serviço.

    Returns:
        RedirectResponse: Em caso de sucesso, redireciona para a página da agenda do funcionário, mostrando o dia do novo agendamento.
        Coroutine[TemplateResponse]: Em caso de conflito de horário, re-renderiza a página da agenda com uma mensagem de erro.
    """
    # ... (código da função handle_form_agendamento)
    whatsapp_numeros = "".join(filter(str.isdigit, whatsapp_cliente))
    cliente = db.query(models.Cliente).filter(models.Cliente.whatsapp == whatsapp_numeros).first()
    if not cliente:
        cliente = models.Cliente(nome=nome_cliente, whatsapp=whatsapp_numeros)
        db.add(cliente)
        db.flush()
    data_hora_completa = datetime.combine(data_agendamento, hora_agendamento)
    servico = db.query(models.Servico).filter(models.Servico.id == servico_id).first()
    if not servico:
        raise HTTPException(status_code=404, detail="Serviço não encontrado")
    fim_novo_agendamento = data_hora_completa + timedelta(minutes=duracao_efetiva)
    conflitos_agendamento = db.query(models.Agendamento).filter(
        models.Agendamento.funcionario_id == funcionario_id,
        models.Agendamento.data_hora < fim_novo_agendamento,
        (models.Agendamento.data_hora + (models.Agendamento.duracao_efetiva_minutos * text("interval '1 minute'"))) > data_hora_completa
    ).all()
    conflitos_bloqueio = db.query(models.Bloqueio).filter(
        models.Bloqueio.funcionario_id == funcionario_id,
        models.Bloqueio.inicio < fim_novo_agendamento,
        models.Bloqueio.fim > data_hora_completa
    ).all()
    if conflitos_agendamento or conflitos_bloqueio:
        set_flash_message(request, "Conflito de horário! O período selecionado já está ocupado.")
        return RedirectResponse(url=f"/painel/funcionarios/{funcionario_id}?data={data_agendamento.isoformat()}", status_code=status.HTTP_303_SEE_OTHER)
    novo_agendamento = models.Agendamento(
        cliente_id=cliente.id, data_hora=data_hora_completa, servico_id=servico_id,
        funcionario_id=funcionario_id, duracao_efetiva_minutos=duracao_efetiva,
        preco_final=servico.preco_minimo
    )
    db.add(novo_agendamento)
    db.commit()
    return RedirectResponse(url=f"/painel/funcionarios/{funcionario_id}?data={data_agendamento.isoformat()}",
                            status_code=status.HTTP_303_SEE_OTHER)



@router.post("/funcionarios/{funcionario_id}/bloquear")
async def handle_form_bloqueio(
    request: Request, funcionario_id: int, db: Session = Depends(get_db), user: dict = Depends(get_current_user),
    inicio_data: date = Form(...), inicio_hora: time = Form(...),
    fim_data: date = Form(...), fim_hora: time = Form(...), motivo: str = Form(None)
):
    """
    Processa os dados do formulário para criar um bloqueio de tempo na agenda.

    Esta rota POST é responsável por criar um período de indisponibilidade na
    agenda de um funcionário. Antes de criar o bloqueio, ela realiza duas
    validações críticas:

    1. Garante que o horário de término seja posterior ao de início.
    2. Realiza uma verificação de conflitos, garantindo que o novo bloqueio
       não se sobreponha a agendamentos ou outros bloqueios já existentes.

    Args:
        request (Request): O objeto de requisição do FastAPI.
        funcionario_id (int): O ID do funcionário cuja agenda será bloqueada.
        db (Session): A sessão do banco de dados, injetada como dependência.
        user (dict): Os dados do usuário logado.
        inicio_data (date): A data de início do bloqueio.
        inicio_hora (time): A hora de início do bloqueio.
        fim_data (date): A data de término do bloqueio.
        fim_hora (time): A hora de término do bloqueio.
        motivo (str, optional): Uma descrição opcional para o motivo do bloqueio.

    Returns:
        RedirectResponse: Em caso de sucesso, redireciona para a página da agenda do funcionário, mostrando o dia do novo bloqueio.
        Coroutine[TemplateResponse]: Em caso de conflito ou horário inválido, re-renderiza a página da agenda com uma mensagem de erro.
    """
    # ... (código da função handle_form_bloqueio)
    inicio_completo = datetime.combine(inicio_data, inicio_hora)
    fim_completo = datetime.combine(fim_data, fim_hora)
    if fim_completo <= inicio_completo:
        set_flash_message(request, "O horário de término do bloqueio deve ser posterior ao horário de início.")
        return RedirectResponse(url=f"/painel/funcionarios/{funcionario_id}?data={inicio_data.isoformat()}", status_code=status.HTTP_303_SEE_OTHER)
    conflitos_agendamento = db.query(models.Agendamento).filter(
        models.Agendamento.funcionario_id == funcionario_id,
        models.Agendamento.data_hora < fim_completo,
        (models.Agendamento.data_hora + (models.Agendamento.duracao_efetiva_minutos * text("interval '1 minute'"))) > inicio_completo
    ).all()
    conflitos_bloqueio = db.query(models.Bloqueio).filter(
        models.Bloqueio.funcionario_id == funcionario_id,
        models.Bloqueio.inicio < fim_completo,
        models.Bloqueio.fim > inicio_completo
    ).all()
    if conflitos_agendamento or conflitos_bloqueio:
        set_flash_message(request, "Conflito de horário! O período selecionado já está ocupado por um agendamento ou outro bloqueio.")
        return RedirectResponse(url=f"/painel/funcionarios/{funcionario_id}?data={inicio_data.isoformat()}", status_code=status.HTTP_303_SEE_OTHER)
    novo_bloqueio = models.Bloqueio(
        inicio=inicio_completo, fim=fim_completo, motivo=motivo, funcionario_id=funcionario_id
    )
    db.add(novo_bloqueio)
    db.commit()
    return RedirectResponse(url=f"/painel/funcionarios/{funcionario_id}?data={inicio_data.isoformat()}",
                            status_code=status.HTTP_303_SEE_OTHER)


@router.post("/agendamentos/{agendamento_id}/finalizar")
async def finalizar_agendamento(
    agendamento_id: int,
    db: Session = Depends(get_db),
    user: dict = Depends(get_current_user),
    metodo_pagamento: str = Form(...),
    valor_final_pago: Optional[Decimal] = Form(None)
):
    """
    Processa a finalização de um agendamento, registrando o pagamento.

    Esta é uma rota financeira crítica que lida com a conclusão de um serviço.
    A sua lógica principal é condicional, baseada no método de pagamento:

    1.  **Se o pagamento for "Permuta"**:
        -   O Fluxo de Caixa NÃO é afetado.
        -   Calcula a comissão do salão e debita da Conta Corrente do funcionário.
    2.  **Se o pagamento for "Credito em Conta"**:
        -   O Fluxo de Caixa NÃO é afetado.
        -   Verifica se o cliente tem saldo suficiente e debita o valor do seu saldo de créditos.
        -   Regista a transação no extrato de créditos do cliente.
    3.  **Para todos os outros métodos (PIX, Dinheiro, etc.)**:
        -   Registra uma 'Entrada' normal no Fluxo de Caixa com o valor exato informado no formulário.

    Em todos os casos, o status do agendamento é alterado para "Concluído" e um log de alteração é gerado.

    Args:
        agendamento_id (int): O ID do agendamento que está a ser finalizado.
        db (Session): A sessão do banco de dados, injetada como dependência.
        user (dict): Os dados do usuário logado que está realizando a ação.
        metodo_pagamento (str): A forma de pagamento selecionada na janela modal.
        valor_final_pago (Optional[Decimal]): O valor exato pago pelo cliente,
        enviado pelo formulário para pagamentos monetários.

    Returns:
        RedirectResponse: Redireciona o usuário de volta para a página da agenda do funcionário,
        mostrando o dia do agendamento finalizado.
    """
    db_agendamento = db.query(models.Agendamento).options(
        joinedload(models.Agendamento.servico),
        joinedload(models.Agendamento.cliente),
        joinedload(models.Agendamento.funcionario)
    ).filter(models.Agendamento.id == agendamento_id).first()

    if not db_agendamento:
        raise HTTPException(status_code=404, detail="Agendamento não encontrado")

    sao_paulo_tz = pytz.timezone('America/Sao_Paulo')
    agora_local_aware = datetime.now(sao_paulo_tz)
    data_agendamento_aware = sao_paulo_tz.localize(db_agendamento.data_hora)

    if data_agendamento_aware > agora_local_aware:
        raise HTTPException(status_code=403, detail="Não é possível finalizar um agendamento futuro.")

    # A lógica de negócio só é executada se o agendamento ainda não estiver concluído.
    if db_agendamento.status != models.StatusAgendamento.CONCLUIDO:
        log_status = models.LogAlteracao(
            agendamento_id=agendamento_id, funcionario_id=user.id,
            campo_alterado="status", valor_antigo=db_agendamento.status, valor_novo="Concluído"
        )
        db.add(log_status)

        if metodo_pagamento == "Permuta":
            comissao_obj = db.query(models.Configuracao).filter(
                models.Configuracao.chave == "COMISSAO_SALAO_PERMUTA_PERC").first()
            percentual_comissao_salao = Decimal(comissao_obj.valor) if comissao_obj else Decimal("50")
            valor_comissao_salao = db_agendamento.preco_final * (percentual_comissao_salao / 100)
            nova_transacao_cc = models.TransacaoContaCorrente(
                funcionario_id=db_agendamento.funcionario_id, agendamento_id=agendamento_id,
                tipo=models.TipoTransacao.DEBITO, valor=valor_comissao_salao,
                descricao=f"Comissão permuta: {db_agendamento.servico.nome} p/ {db_agendamento.cliente.nome}"
            )
            db.add(nova_transacao_cc)
            db_agendamento.funcionario.saldo_conta_corrente -= valor_comissao_salao

        elif metodo_pagamento == "Credito em Conta":
            if db_agendamento.cliente.saldo_credito < db_agendamento.preco_final:
                raise HTTPException(status_code=400, detail="Saldo de crédito insuficiente para realizar o pagamento.")
            db_agendamento.cliente.saldo_credito -= db_agendamento.preco_final
            nova_transacao_credito = models.TransacaoCredito(
                cliente_id=db_agendamento.cliente_id,
                funcionario_id=user.id,
                agendamento_id=agendamento_id,
                tipo=models.TipoTransacao.USO,
                valor=db_agendamento.preco_final,
                descricao=f"Pagamento serviço: {db_agendamento.servico.nome}"
                )
            db.add(nova_transacao_credito)

        else:  # Para PIX, Dinheiro, Cartão, etc.
            valor_a_registrar = valor_final_pago if valor_final_pago is not None else db_agendamento.preco_final
            novo_registro_caixa = models.FluxoCaixa(
                descricao=f"Serviço: {db_agendamento.servico.nome} - Cliente: {db_agendamento.cliente.nome}",
                valor=valor_a_registrar,
                tipo=models.TipoFluxoCaixa.ENTRADA,
                metodo_pagamento=metodo_pagamento,
                funcionario_id=db_agendamento.funcionario_id,
                agendamento_id=agendamento_id
            )
            db.add(novo_registro_caixa)

        db_agendamento.status = models.StatusAgendamento.CONCLUIDO
        db.commit()
    funcionario_id = db_agendamento.funcionario_id
    data_agendamento = db_agendamento.data_hora.date()
    return RedirectResponse(url=f"/painel/funcionarios/{funcionario_id}?data={data_agendamento.isoformat()}",
                            status_code=status.HTTP_303_SEE_OTHER)



@router.post("/agendamentos/{agendamento_id}/cancelar")
async def cancelar_agendamento(
    agendamento_id: int, db: Session = Depends(get_db), user: dict = Depends(get_current_user)
):
    """
    Processa o cancelamento de um agendamento existente.

    Esta rota altera o status de um agendamento para "Cancelado". Para garantir
    a integridade dos dados históricos, ela implementa uma regra de negócio que
    impede o cancelamento de agendamentos de dias anteriores.

    A função também garante a auditoria, criando um registro em 'LogAlteracao'
    para documentar a ação de cancelamento, além de ser idempotente, ou seja, não
    realiza nenhuma alteração se o agendamento já estiver cancelado.

    Args:
        agendamento_id (int): O ID do agendamento a ser cancelado.
        db (Session): A sessão do banco de dados, injetada como dependência.
        user (dict): Os dados do usuário logado que está realizando a ação.

    Returns:
        RedirectResponse: Redireciona o usuário de volta para a página da agenda do funcionário,
        mostrando o dia do agendamento cancelado.
    """
    # ... (código da função cancelar_agendamento)
    db_agendamento = db.query(models.Agendamento).filter(models.Agendamento.id == agendamento_id).first()
    if not db_agendamento:
        raise HTTPException(status_code=404, detail="Agendamento não encontrado")
    if db_agendamento.data_hora.date() < date.today():
        raise HTTPException(status_code=403, detail="Não é possível cancelar agendamentos de dias anteriores.")
    if db_agendamento.status != models.StatusAgendamento.CANCELADO:
        log_cancelamento = models.LogAlteracao(
            agendamento_id=agendamento_id, funcionario_id=user.id,
            campo_alterado="status", valor_antigo=db_agendamento.status, valor_novo="Cancelado"
        )
        db.add(log_cancelamento)
        db_agendamento.status = models.StatusAgendamento.CANCELADO
        db.commit()
    funcionario_id = db_agendamento.funcionario_id
    data_agendamento = db_agendamento.data_hora.date()
    return RedirectResponse(url=f"/painel/funcionarios/{funcionario_id}?data={data_agendamento.isoformat()}",
                            status_code=status.HTTP_303_SEE_OTHER)



@router.get("/agendamentos/{agendamento_id}/editar", response_class=HTMLResponse)
async def get_pagina_editar_agendamento(
    request: Request, agendamento_id: int, db: Session = Depends(get_db), user: dict = Depends(get_current_user)
):
    """
    Exibe a página para editar o preço final de um agendamento.

    Esta rota GET busca um agendamento específico pelo seu ID e renderiza o
    formulário de edição. Os dados do agendamento são pré-carregados no formulário,
    permitindo que o usuário altere o seu preço final. A consulta utiliza
    'eager loading' (joinedload) para carregar os dados do cliente e do serviço de forma eficiente.

    Args:
        request (Request): O objeto de requisição do FastAPI.
        agendamento_id (int): O ID do agendamento a ser editado, vindo da URL.
        db (Session): A sessão do banco de dados, injetada como dependência.
        user (dict): Os dados do usuário logado, obtidos da sessão.

    Returns:
        TemplateResponse: Uma resposta HTML que renderiza a página 'editar_agendamento.html',
        populada com os dados do agendamento a ser editado.
    """
    # ... (código da função get_pagina_editar_agendamento)
    agendamento = db.query(models.Agendamento).options(
        joinedload(models.Agendamento.cliente),
        joinedload(models.Agendamento.servico)
    ).filter(models.Agendamento.id == agendamento_id).first()
    if not agendamento:
        raise HTTPException(status_code=404, detail="Agendamento não encontrado")
    context = {"request": request, "agendamento": agendamento, "user": user}
    return templates.TemplateResponse("editar_agendamento.html", context)



@router.post("/agendamentos/{agendamento_id}/editar")
async def handle_form_editar_agendamento(
    request: Request, agendamento_id: int, db: Session = Depends(get_db), user: dict = Depends(get_current_user),
    preco_final: Decimal = Form(...)
):
    """
    Processa a alteração do preço final de um agendamento.

    Esta rota POST é responsável por salvar o novo preço final de um agendamento.
    Ela implementa várias regras de negócio críticas para garantir a integridade
    dos dados financeiros e operacionais:

    1.  Valida o prazo da edição, permitindo alterações apenas até 1 hora após o término do serviço.
    2.  Verifica se o agendamento ainda está no status 'Agendado'.
    3.  Garante que o novo preço não seja inferior ao preço mínimo do serviço.

    Se a alteração for válida e o preço for de fato diferente, um registro de
    auditoria ('LogAlteracao') é criado antes de a alteração ser salva.

    Args:
        request (Request): O objeto de requisição do FastAPI.
        agendamento_id (int): O ID do agendamento a ser editado.
        db (Session): A sessão do banco de dados, injetada como dependência.
        user (dict): Os dados do usuário logado que está realizando a ação.
        preco_final (Decimal): O novo preço final do serviço, vindo do formulário.

    Returns:
        RedirectResponse: Em caso de sucesso, redireciona para a página da agenda.
        TemplateResponse: Em caso de falha em qualquer uma das validações, re-renderiza a página de edição,
        com uma mensagem de erro apropriada.
    """
    # ... (código da função handle_form_editar_agendamento)
    db_agendamento = db.query(models.Agendamento).options(
        joinedload(models.Agendamento.servico),
        joinedload(models.Agendamento.cliente)
    ).filter(models.Agendamento.id == agendamento_id).first()
    if not db_agendamento:
        raise HTTPException(status_code=404, detail="Agendamento não encontrado")
    horario_termino_agendamento = db_agendamento.data_hora + timedelta(minutes=db_agendamento.duracao_efetiva_minutos)
    prazo_limite_edicao = horario_termino_agendamento + timedelta(hours=1)
    if datetime.now() > prazo_limite_edicao:
        error_message = "O prazo para editar este agendamento expirou (1 hora após o término do serviço)."
        context = {"request": request, "agendamento": db_agendamento, "error": error_message, "user": user}
        return templates.TemplateResponse("editar_agendamento.html", context)
    if db_agendamento.status != 'Agendado':
        error_message = f"Não é possível editar um agendamento com status '{db_agendamento.status}'."
        context = {"request": request, "agendamento": db_agendamento, "error": error_message, "user": user}
        return templates.TemplateResponse("editar_agendamento.html", context)
    preco_minimo_servico = db_agendamento.servico.preco_minimo
    if preco_final < preco_minimo_servico:
        error_message = f"O preço final não pode ser menor que o preço mínimo do serviço (R$ {preco_minimo_servico})."
        context = {"request": request, "agendamento": db_agendamento, "error": error_message, "user": user}
        return templates.TemplateResponse("editar_agendamento.html", context)
    if db_agendamento.preco_final != preco_final:
        valor_antigo = str(db_agendamento.preco_final)
        novo_log = models.LogAlteracao(
            agendamento_id=agendamento_id, funcionario_id=user.id,
            campo_alterado="preco_final", valor_antigo=valor_antigo, valor_novo=str(preco_final)
        )
        db.add(novo_log)
        db_agendamento.preco_final = preco_final
        db.commit()
    funcionario_id = db_agendamento.funcionario_id
    data_agendamento = db_agendamento.data_hora.date()
    return RedirectResponse(url=f"/painel/funcionarios/{funcionario_id}?data={data_agendamento.isoformat()}",
                            status_code=status.HTTP_303_SEE_OTHER)



@router.post("/bloqueios/{bloqueio_id}/cancelar")
async def cancelar_bloqueio(
    bloqueio_id: int, db: Session = Depends(get_db), user: dict = Depends(get_current_user)
):
    """
    Processa a remoção (cancelamento) de um bloqueio de tempo na agenda.

    Esta rota POST é responsável por excluir permanentemente um registro de
    'Bloqueio' do banco de dados. Diferente do cancelamento de agendamentos,
    que apenas altera um status para preservar o histórico, esta operação é
    uma exclusão definitiva.

    A função garante que, após a remoção, o usuário seja redirecionado de volta
    para a visualização correta da agenda do dia em que o bloqueio existia.

    Args:
        bloqueio_id (int): O ID do bloqueio a ser removido, vindo da URL.
        db (Session): A sessão do banco de dados, injetada como dependência.
        user (dict): Os dados do usuário logado que está realizando a ação.

    Returns:
        RedirectResponse: Redireciona o usuário de volta para a página da agenda do funcionário,
        mostrando o dia do bloqueio removido.
    """
    # ... (código da função cancelar_bloqueio)
    db_bloqueio = db.query(models.Bloqueio).filter(models.Bloqueio.id == bloqueio_id).first()
    if not db_bloqueio:
        raise HTTPException(status_code=404, detail="Bloqueio não encontrado")
    funcionario_id = db_bloqueio.funcionario_id
    data_bloqueio = db_bloqueio.inicio.date()
    db.delete(db_bloqueio)
    db.commit()
    return RedirectResponse(url=f"/painel/funcionarios/{funcionario_id}?data={data_bloqueio.isoformat()}",
                            status_code=status.HTTP_303_SEE_OTHER)



@router.get("/alterar-senha", response_class=HTMLResponse)
async def get_pagina_alterar_senha(
    request: Request,
    user: dict = Depends(get_current_user),
    success: str | None = Query(default=None),
    error: str | None = Query(default=None)
):
    """
    Exibe a página com o formulário para o usuário alterar a sua própria senha.

    Args:
        request (Request): O objeto de requisição do FastAPI.
        user (dict): Os dados do usuário logado.
        success (str, optional): Mensagem de sucesso a ser exibida.
        error (str, optional): Mensagem de erro a ser exibida.

    Returns:
        TemplateResponse: Renderiza a página 'alterar_senha.html'.
    """
    context = {
        "request": request,
        "user": user,
        "success": success,
        "error": error
    }
    return templates.TemplateResponse("alterar_senha.html", context)



@router.post("/alterar-senha")
async def handle_form_alterar_senha(
    request: Request,
    db: Session = Depends(get_db),
    user: dict = Depends(get_current_user),
    senha_atual: str = Form(...),
    nova_senha: str = Form(...),
    confirmar_nova_senha: str = Form(...)
):
    """
    Processa a alteração de senha do usuário logado.

    Realiza uma série de validações de segurança:
    1. Verifica se a nova senha e a sua confirmação são idênticas.
    2. Verifica se a "senha atual" fornecida corresponde à senha armazenada no banco de dados.

    Se as validações passarem, a nova senha é 'hasheada' e atualizada no banco.

    Args:
        request (Request): O objeto de requisição do FastAPI.
        db (Session): A sessão do banco de dados.
        user (dict): Os dados do usuário logado.
        senha_atual (str): A senha atual do usuário, para verificação.
        nova_senha (str): A nova senha desejada.
        confirmar_nova_senha (str): A confirmação da nova senha.

    Returns:
        RedirectResponse: Redireciona de volta para a página de alterar senha
                          com uma mensagem de sucesso ou erro.
    """
    # Validação do frontend já verifica isto, mas é uma boa prática re-validar no backend.
    if nova_senha != confirmar_nova_senha:
        return RedirectResponse(
            url="/painel/alterar-senha?error=A nova senha e a confirmação não coincidem.",
            status_code=status.HTTP_303_SEE_OTHER
        )

    db_funcionario = db.query(models.Funcionario).filter(models.Funcionario.id == user.id).first()

    # Validação de segurança crucial: verificar se a senha atual está correta
    if not verificar_senha(senha_atual, db_funcionario.senha_hash):
        return RedirectResponse(
            url="/painel/alterar-senha?error=A senha atual está incorreta.",
            status_code=status.HTTP_303_SEE_OTHER
        )

    # Se tudo estiver correto, atualiza a senha
    novo_hash_senha = gerar_hash_senha(nova_senha)
    db_funcionario.senha_hash = novo_hash_senha
    db.commit()

    return RedirectResponse(
        url="/painel/alterar-senha?success=Senha alterada com sucesso!",
        status_code=status.HTTP_303_SEE_OTHER
    )



@router.get("/logs", response_class=HTMLResponse)
async def get_pagina_logs(
    request: Request, db: Session = Depends(get_db), user: dict = Depends(get_current_user)
):
    """
       Exibe a página de auditoria com o histórico de todas as alterações.

       Esta rota é responsável por fornecer uma visão completa e transparente de
       todas as alterações significativas registadas no sistema. A sua principal
       tarefa é realizar uma consulta complexa e eficiente para agregar todos os
       dados necessários:

       1.  Busca todos os registros de 'LogAlteracao'.
       2.  Utiliza 'eager loading' (joinedload) de forma aninhada para carregar
           eficientemente os dados do funcionário que fez a alteração do
           agendamento afetado, e também do serviço e cliente relacionados
           a esse agendamento.
       3.  Realiza um ajuste de fuso horário para exibir a hora local.

       Args:
           request (Request): O objeto de requisição do FastAPI.
           db (Session): A sessão do banco de dados, injetada como dependência.
           user (dict): Os dados do usuário logado, obtidos da sessão.

       Returns:
           TemplateResponse: Uma resposta HTML que renderiza a página 'logs.html',
           populada com a lista completa de registros de auditoria.
       """
    logs = db.query(models.LogAlteracao).options(
        joinedload(models.LogAlteracao.funcionario),
        joinedload(models.LogAlteracao.agendamento).joinedload(models.Agendamento.servico),
        joinedload(models.LogAlteracao.agendamento).joinedload(models.Agendamento.cliente)
    ).order_by(models.LogAlteracao.data_hora.desc()).all()

    for log in logs:
        log.data_hora_local = log.data_hora - timedelta(hours=3)
        campo = log.campo_alterado
        valor_novo = log.valor_novo

        if campo == "status" and valor_novo == models.StatusAgendamento.CONCLUIDO:
            log.acao_amigavel = "Finalizou Serviço"
        elif campo == "status" and valor_novo == models.StatusAgendamento.CANCELADO:
            log.acao_amigavel = "Cancelou Agendamento"
        elif campo == "preco_final":
            log.acao_amigavel = "Alterou Preço"
        elif campo == "data_hora":
            log.acao_amigavel = "Reagendou Serviço"
        elif campo == "duracao_efetiva_minutos":
            log.acao_amigavel = "Ajustou Duração"
        else:
            # Um valor padrão para campos não mapeados, para não quebrar a visualização
            log.acao_amigavel = f"Alterou '{campo.replace('_', ' ').title()}'"

    context = {"request": request, "logs": logs, "user": user}
    return templates.TemplateResponse("logs.html", context)

