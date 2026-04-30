from fastapi import APIRouter, Depends, Request, Form, Query, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse
from starlette import status
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import text, or_
from collections import defaultdict
from pathlib import Path
from fastapi.templating import Jinja2Templates
from datetime import datetime, date, time, timedelta
from decimal import Decimal
from typing import Optional
import math
import models
from dependencies import get_db, get_current_user
from security import verificar_senha, gerar_hash_senha
from utils.tempo import obter_agora_local

router = APIRouter(
    prefix="/painel",
    tags=["Painel Web"],
    dependencies=[Depends(get_current_user)]
)

# Configuração dos Templates
BASE_DIR = Path(__file__).resolve().parent.parent
templates = Jinja2Templates(directory=str(Path(BASE_DIR, 'templates')))


@router.get("/", response_class=HTMLResponse)
async def get_painel_gestao(request: Request, db: Session = Depends(get_db), user: dict = Depends(get_current_user)):
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
    if data:
        data_base = data
    else:
        # Substituído date.today() pela nova função centralizada
        hoje = obter_agora_local().date()
        if hoje.weekday() in [6, 0, 1, 2]:
            data_base = hoje - timedelta(days=7)
        else:
            data_base = hoje

    weekday_base = data_base.weekday()
    offset_para_terca = (weekday_base - 1 + 7) % 7
    data_inicio = data_base - timedelta(days=offset_para_terca)
    data_fim = data_inicio + timedelta(days=4)

    data_semana_anterior = data_inicio - timedelta(days=7)
    data_proxima_semana = data_inicio + timedelta(days=7)

    inicio_periodo = datetime.combine(data_inicio, time.min)
    fim_periodo = datetime.combine(data_fim, time.max)

    agendamentos_concluidos = db.query(models.Agendamento).filter(
        models.Agendamento.funcionario_id == user.id,
        models.Agendamento.status == models.StatusAgendamento.CONCLUIDO,
        models.Agendamento.data_hora.between(inicio_periodo, fim_periodo)
    ).all()
    total_vendas_servicos = sum(ag.preco_final for ag in agendamentos_concluidos if ag.preco_final is not None)

    vendas_produtos_comissionadas = db.query(models.FluxoCaixa).filter(
        models.FluxoCaixa.funcionario_id == user.id,
        models.FluxoCaixa.tipo == models.TipoFluxoCaixa.ENTRADA,
        models.FluxoCaixa.produto_id != None,
        models.FluxoCaixa.comissao_percentual > 0,
        models.FluxoCaixa.data_hora_registro.between(inicio_periodo, fim_periodo)
    ).all()
    total_vendas_produtos = sum(venda.valor for venda in vendas_produtos_comissionadas)

    total_vendas = total_vendas_servicos + total_vendas_produtos

    context = {
        "request": request,
        "user": user,
        "agendamentos_concluidos": agendamentos_concluidos,
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
    data_inicio = date.fromisoformat(data_inicio_str) if data_inicio_str else None
    data_fim = date.fromisoformat(data_fim_str) if data_fim_str else None
    cliente_id = int(cliente_id_str) if cliente_id_str else None
    servico_id = int(servico_id_str) if servico_id_str else None

    query = db.query(models.Agendamento).options(
        joinedload(models.Agendamento.cliente),
        joinedload(models.Agendamento.servico)
    ).filter(
        models.Agendamento.funcionario_id == user.id,
        models.Agendamento.status == models.StatusAgendamento.CONCLUIDO
    )

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
    produtos_ativos = db.query(models.Produto).filter(
        models.Produto.is_ativo == True
    ).order_by(models.Produto.nome).all()

    comissao_maxima_obj = db.query(models.Configuracao).filter(
        models.Configuracao.chave == "COMISSAO_MAXIMA_PRODUTO"
    ).first()
    comissao_maxima = comissao_maxima_obj.valor if comissao_maxima_obj else "10"
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
    comissao_maxima_obj = db.query(models.Configuracao).filter(
        models.Configuracao.chave == "COMISSAO_MAXIMA_PRODUTO"
    ).first()
    limite_comissao = Decimal(comissao_maxima_obj.valor) if comissao_maxima_obj else Decimal("10")
    comissao_a_registrar = comissao_percentual if comissao_percentual is not None else Decimal("0.00")

    if not (0 <= comissao_a_registrar <= limite_comissao):
        produtos_ativos = db.query(models.Produto).filter(models.Produto.is_ativo == True).order_by(
            models.Produto.nome).all()
        produtos_json = {p.id: {"nome": p.nome, "valor": float(p.valor)} for p in produtos_ativos}
        context = {
            "request": request, "user": user, "produtos": produtos_ativos, "produtos_json": produtos_json,
            "comissao_maxima": limite_comissao,
            "error": f"A comissão deve estar entre 0% e {limite_comissao}%."
        }
        return templates.TemplateResponse("vender_produto.html", context, status_code=400)

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
    context = {"request": request, "user": user, "error": error}
    return templates.TemplateResponse("painel_cliente_form.html", context)


@router.post("/clientes/novo")
async def handle_form_novo_cliente(
    request: Request, db: Session = Depends(get_db), user: dict = Depends(get_current_user),
    nome: str = Form(...), whatsapp: str = Form(...)
):
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
    funcionario_selecionado = db.query(models.Funcionario).filter(models.Funcionario.id == funcionario_id).first()
    if not funcionario_selecionado:
        return templates.TemplateResponse("404.html", {"request": request}, status_code=404)
    todos_funcionarios_ativos = db.query(models.Funcionario).filter(models.Funcionario.is_ativo == True).order_by(models.Funcionario.nome).all()
    
    # Substituído date.today() pela nova função centralizada
    if data is None: data = obter_agora_local().date()
    
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
    
    # Substituídos date.today() e datetime.now() pela nova função
    agora_local = obter_agora_local()
    context = {
        "request": request, "funcionario": funcionario_selecionado,
        "todos_funcionarios_ativos": todos_funcionarios_ativos,
        "agenda_completa": agenda_completa, "agendamentos_cancelados": agendamentos_cancelados,
        "data_exibida_str": data.strftime("%d/%m/%Y"), "data_atual_iso": data.isoformat(),
        "dia_anterior_str": dia_anterior.isoformat(), "proximo_dia_str": proximo_dia.isoformat(),
        "servicos_agrupados": servicos_agrupados, "servicos": servicos_ativos,
        "horarios_selecao": horarios_selecao, "data_hoje_obj": agora_local.date(),
        "agora_local": agora_local, "user": user, "error": error
    }
    return templates.TemplateResponse("funcionario_agenda.html", context)


@router.post("/funcionarios/{funcionario_id}/agendar")
async def handle_form_agendamento(
    request: Request, funcionario_id: int, db: Session = Depends(get_db), user: dict = Depends(get_current_user),
    nome_cliente: str = Form(...), whatsapp_cliente: str = Form(...),
    data_agendamento: date = Form(...), hora_agendamento: time = Form(...),
    servico_id: int = Form(...), duracao_efetiva: int = Form(...)
):
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
        error_message = "Conflito de horário! O período selecionado já está ocupado."
        return await get_detalhes_funcionario(request, funcionario_id, db, data_agendamento, user, error=error_message)
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
    inicio_completo = datetime.combine(inicio_data, inicio_hora)
    fim_completo = datetime.combine(fim_data, fim_hora)
    if fim_completo <= inicio_completo:
        error_message = "O horário de término do bloqueio deve ser posterior ao horário de início."
        return await get_detalhes_funcionario(request, funcionario_id, db, inicio_data, user, error=error_message)
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
        error_message = "Conflito de horário! O período selecionado já está ocupado por um agendamento ou outro bloqueio."
        return await get_detalhes_funcionario(request, funcionario_id, db, inicio_data, user, error=error_message)
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
    db_agendamento = db.query(models.Agendamento).options(
        joinedload(models.Agendamento.servico),
        joinedload(models.Agendamento.cliente),
        joinedload(models.Agendamento.funcionario)
    ).filter(models.Agendamento.id == agendamento_id).first()

    if not db_agendamento:
        raise HTTPException(status_code=404, detail="Agendamento não encontrado")

    # Substituído datetime.now(sao_paulo_tz) pela nova função. 
    # Assumindo que obter_agora_local() já retorna um objeto aware compatível com o DB.
    agora_local_aware = obter_agora_local()
    
    # Fazemos a comparação de datas (Naive vs Aware deve ser tratada pela função ou DB)
    if db_agendamento.data_hora > agora_local_aware.replace(tzinfo=None):
        raise HTTPException(status_code=403, detail="Não é possível finalizar um agendamento futuro.")

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

        else:
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
    db_agendamento = db.query(models.Agendamento).filter(models.Agendamento.id == agendamento_id).first()
    if not db_agendamento:
        raise HTTPException(status_code=404, detail="Agendamento não encontrado")
    
    # Substituído date.today() pela nova função
    if db_agendamento.data_hora.date() < obter_agora_local().date():
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
    db_agendamento = db.query(models.Agendamento).options(
        joinedload(models.Agendamento.servico),
        joinedload(models.Agendamento.cliente)
    ).filter(models.Agendamento.id == agendamento_id).first()
    if not db_agendamento:
        raise HTTPException(status_code=404, detail="Agendamento não encontrado")
    
    horario_termino_agendamento = db_agendamento.data_hora + timedelta(minutes=db_agendamento.duracao_efetiva_minutos)
    prazo_limite_edicao = horario_termino_agendamento + timedelta(hours=1)
    
    # Substituído datetime.now() pela nova função
    if obter_agora_local().replace(tzinfo=None) > prazo_limite_edicao:
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
    if nova_senha != confirmar_nova_senha:
        return RedirectResponse(
            url="/painel/alterar-senha?error=A nova senha e a confirmação não coincidem.",
            status_code=status.HTTP_303_SEE_OTHER
        )

    db_funcionario = db.query(models.Funcionario).filter(models.Funcionario.id == user.id).first()
    if not verificar_senha(senha_atual, db_funcionario.senha_hash):
        return RedirectResponse(
            url="/painel/alterar-senha?error=A senha atual está incorreta.",
            status_code=status.HTTP_303_SEE_OTHER
        )

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
    logs = db.query(models.LogAlteracao).options(
        joinedload(models.LogAlteracao.funcionario),
        joinedload(models.LogAlteracao.agendamento).joinedload(models.Agendamento.servico),
        joinedload(models.LogAlteracao.agendamento).joinedload(models.Agendamento.cliente)
    ).order_by(models.LogAlteracao.data_hora.desc()).all()

    for log in logs:
        # Removido o ajuste manual de fuso horário (timedelta(hours=3)) 
        # pois a função centralizada agora cuida disso.
        log.data_hora_local = log.data_hora 
        
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
            log.acao_amigavel = f"Alterou '{campo.replace('_', ' ').title()}'"

    context = {"request": request, "logs": logs, "user": user}
    return templates.TemplateResponse("logs.html", context)