from fastapi import APIRouter, Depends, Request, Form, Query, HTTPException, UploadFile, File
import shutil
import uuid
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
from utils.tempo import obter_agora_local

router = APIRouter(
    prefix="/painel/admin",
    tags=["Administração"],
    dependencies=[Depends(get_current_admin_user)]
)

# Configuração dos Templates
BASE_DIR = Path(__file__).resolve().parent.parent
templates = Jinja2Templates(directory=str(Path(BASE_DIR, 'templates')))

######################################## PÁGINA DE ADMINISTRAÇÃO ########################################

@router.get("/", response_class=HTMLResponse)
async def get_admin_page(request: Request, user: dict = Depends(get_current_admin_user)):
    context = {"request": request, "user": user}
    return templates.TemplateResponse("admin_index.html", context)

@router.get("/dashboard", response_class=HTMLResponse)
async def get_admin_dashboard(
    request: Request,
    db: Session = Depends(get_db),
    user: dict = Depends(get_current_admin_user),
    data_inicio: Optional[date] = Query(None),
    data_fim: Optional[date] = Query(None)
):
    # Uso da função centralizada para definir datas padrão
    agora = obter_agora_local()
    if not data_inicio:
        data_inicio = (agora - timedelta(days=30)).date()
    if not data_fim:
        data_fim = agora.date()

    inicio_dt = datetime.combine(data_inicio, time.min)
    fim_dt = datetime.combine(data_fim, time.max)

    vendas_servicos = db.query(func.sum(models.Agendamento.preco_final)).filter(
        models.Agendamento.status == models.StatusAgendamento.CONCLUIDO,
        models.Agendamento.data_hora.between(inicio_dt, fim_dt)
    ).scalar() or Decimal(0)

    vendas_produtos = db.query(func.sum(models.FluxoCaixa.valor)).filter(
        models.FluxoCaixa.tipo == models.TipoFluxoCaixa.ENTRADA,
        models.FluxoCaixa.produto_id != None,
        models.FluxoCaixa.data_hora_registro.between(inicio_dt, fim_dt)
    ).scalar() or Decimal(0)

    faturamento_total = vendas_servicos + vendas_produtos

    # Exemplo de uso de data atual para lógica de "hoje"
    hoje_inicio = datetime.combine(agora.date(), time.min)
    hoje_fim = datetime.combine(agora.date(), time.max)
    
    agendamentos_hoje = db.query(models.Agendamento).filter(
        models.Agendamento.data_hora.between(hoje_inicio, hoje_fim)
    ).count()

    context = {
        "request": request,
        "user": user,
        "faturamento_total": faturamento_total,
        "vendas_servicos": vendas_servicos,
        "vendas_produtos": vendas_produtos,
        "agendamentos_hoje": agendamentos_hoje,
        "data_inicio": data_inicio,
        "data_fim": data_fim
    }
    return templates.TemplateResponse("admin_dashboard.html", context)

######################################## GESTÃO DE FUNCIONÁRIOS ########################################

@router.get("/funcionarios", response_class=HTMLResponse)
async def listar_funcionarios(db: Session = Depends(get_db), user: dict = Depends(get_current_admin_user), request: Request = None):
    funcionarios = db.query(models.Funcionario).order_by(models.Funcionario.nome).all()
    return templates.TemplateResponse("admin_funcionarios.html", {"request": request, "funcionarios": funcionarios, "user": user})

@router.post("/funcionarios/novo")
async def cadastrar_funcionario(
    nome: str = Form(...),
    email: str = Form(...),
    senha: str = Form(...),
    is_admin: bool = Form(False),
    db: Session = Depends(get_db),
    user: dict = Depends(get_current_admin_user)
):
    senha_hash = gerar_hash_senha(senha)
    novo_func = models.Funcionario(nome=nome, email=email, senha_hash=senha_hash, is_admin=is_admin)
    db.add(novo_func)
    db.commit()
    return RedirectResponse(url="/painel/admin/funcionarios", status_code=status.HTTP_303_SEE_OTHER)

@router.post("/funcionarios/{func_id}/toggle-status")
async def toggle_funcionario_status(func_id: int, db: Session = Depends(get_db), user: dict = Depends(get_current_admin_user)):
    func = db.query(models.Funcionario).filter(models.Funcionario.id == func_id).first()
    if func:
        func.is_ativo = not func.is_ativo
        db.commit()
    return RedirectResponse(url="/painel/admin/funcionarios", status_code=status.HTTP_303_SEE_OTHER)

######################################## GESTÃO DE SERVIÇOS ########################################

@router.get("/servicos", response_class=HTMLResponse)
async def listar_servicos(db: Session = Depends(get_db), user: dict = Depends(get_current_admin_user), request: Request = None):
    servicos = db.query(models.Servico).options(joinedload(models.Servico.categoria)).all()
    categorias = db.query(models.Categoria).all()
    return templates.TemplateResponse("admin_servicos.html", {"request": request, "servicos": servicos, "categorias": categorias, "user": user})

@router.post("/servicos/novo")
async def cadastrar_servico(
    nome: str = Form(...),
    preco_minimo: Decimal = Form(...),
    categoria_id: int = Form(...),
    db: Session = Depends(get_db),
    user: dict = Depends(get_current_admin_user)
):
    novo_servico = models.Servico(nome=nome, preco_minimo=preco_minimo, categoria_id=categoria_id)
    db.add(novo_servico)
    db.commit()
    return RedirectResponse(url="/painel/admin/servicos", status_code=status.HTTP_303_SEE_OTHER)

######################################## GESTÃO DE PRODUTOS ########################################

@router.get("/produtos", response_class=HTMLResponse)
async def listar_produtos(db: Session = Depends(get_db), user: dict = Depends(get_current_admin_user), request: Request = None):
    produtos = db.query(models.Produto).order_by(models.Produto.nome).all()
    return templates.TemplateResponse("admin_produtos.html", {"request": request, "produtos": produtos, "user": user})

@router.post("/produtos/novo")
async def cadastrar_produto(
    nome: str = Form(...),
    valor: Decimal = Form(...),
    foto: UploadFile = File(None),
    db: Session = Depends(get_db),
    user: dict = Depends(get_current_admin_user)
):
    novo_produto = models.Produto(nome=nome, valor=valor)
    
    if foto and foto.filename:
        extensao = Path(foto.filename).suffix
        nome_ficheiro = f"{uuid.uuid4()}{extensao}"
        caminho_directorio = Path("static/uploads/produtos")
        caminho_directorio.mkdir(parents=True, exist_ok=True)
        
        caminho_completo = caminho_directorio / nome_ficheiro
        with caminho_completo.open("wb") as buffer:
            shutil.copyfileobj(foto.file, buffer)
        
        novo_produto.caminho_foto = nome_ficheiro

    db.add(novo_produto)
    db.commit()
    return RedirectResponse(url="/painel/admin/produtos", status_code=status.HTTP_303_SEE_OTHER)

@router.post("/produtos/{produto_id}/editar")
async def editar_produto(
    produto_id: int,
    nome: str = Form(...),
    valor: Decimal = Form(...),
    foto: UploadFile = File(None),
    db: Session = Depends(get_db),
    user: dict = Depends(get_current_admin_user)
):
    db_produto = db.query(models.Produto).filter(models.Produto.id == produto_id).first()
    if not db_produto:
        raise HTTPException(status_code=404, detail="Produto não encontrado")

    if foto and foto.filename:
        extensao = Path(foto.filename).suffix
        nome_ficheiro_unico = f"{uuid.uuid4()}{extensao}"
        caminho_salvar = Path("static/uploads/produtos") / nome_ficheiro_unico
        
        contents = await foto.read()
        with open(caminho_salvar, "wb") as buffer:
            buffer.write(contents)
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
    db_produto = db.query(models.Produto).filter(models.Produto.id == produto_id).first()
    if db_produto:
        db_produto.is_ativo = not db_produto.is_ativo
        db.commit()
    return RedirectResponse(url="/painel/admin/produtos", status_code=status.HTTP_303_SEE_OTHER)

######################################## CONFIGURAÇÕES ########################################

@router.get("/configuracoes", response_class=HTMLResponse)
async def get_config_page(request: Request, db: Session = Depends(get_db), user: dict = Depends(get_current_admin_user)):
    configs = db.query(models.Configuracao).all()
    return templates.TemplateResponse("admin_configuracoes.html", {"request": request, "configs": configs, "user": user})

@router.post("/configuracoes/atualizar")
async def atualizar_configuracao(
    chave: str = Form(...),
    valor: str = Form(...),
    db: Session = Depends(get_db),
    user: dict = Depends(get_current_admin_user)
):
    config = db.query(models.Configuracao).filter(models.Configuracao.chave == chave).first()
    if config:
        config.valor = valor
        db.commit()
    return RedirectResponse(url="/painel/admin/configuracoes", status_code=status.HTTP_303_SEE_OTHER)
