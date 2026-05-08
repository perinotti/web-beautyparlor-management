import enum
from sqlalchemy import Enum 
from sqlalchemy import Column, Integer, String, Boolean, Numeric, DateTime, Date, ForeignKey, func
from sqlalchemy.orm import relationship
from database import Base
from datetime import datetime


class StatusAgendamento(str, enum.Enum):
    AGENDADO = "Agendado"
    CONCLUIDO = "Concluído"
    CANCELADO = "Cancelado"

class TipoTransacao(str, enum.Enum):
    ADICAO = "Adição"
    USO = "Uso"
    DEBITO = "Débito"
    CREDITO = "Crédito"

class TipoFluxoCaixa(str, enum.Enum):
    ENTRADA = "Entrada"
    SAIDA = "Saída"

class Configuracao(Base):
    """
    Armazena configurações globais e regras de negócio do sistema.

    Esta tabela funciona como um cofre de 'chave-valor', permitindo que o
    administrador altere parâmetros críticos da aplicação (como limites de
    desconto e percentagens de comissão) diretamente pela interface, sem
    precisar modificar o código fonte. Isto desacopla as regras de negócio
    da lógica da aplicação, tornando o sistema mais flexível e atualizável.

    Attributes:
        chave (str): A chave única que identifica a configuração (ex: 'LIMITE_DESCONTO_PACOTE').
                     Atua como a chave primária da tabela.
        valor (str): O valor associado à chave, armazenado como uma string para
                     flexibilidade. A lógica da aplicação é responsável por converter
                     este valor para o tipo de dado apropriado (ex: int, Decimal).
    """
    __tablename__ = "configuracoes"
    chave = Column(String, primary_key=True)
    valor = Column(String, nullable=False)



class Categoria(Base):
    """
    Representa uma categoria para agrupar e organizar os serviços oferecidos.

    Esta tabela permite que o administrador crie agrupamentos lógicos para os
    serviços (ex: 'Cabelos', 'Unhas', 'Estética Facial'), melhorando a
    navegabilidade e a experiência do utilizador nas interfaces de agendamento
    e de relatórios, onde os serviços são apresentados de forma organizada.

    Attributes:
        id (int): A chave primária única para a categoria.
        nome (str): O nome da categoria, que deve ser único para evitar duplicatas.
        servicos (relationship): Uma relação one-to-many que liga a categoria a todos os serviços que a ela pertencem.
        O argumento 'back_populates' cria um vínculo bidirecional, permitindo o acesso a `servico.categoria`.
    """
    __tablename__ = "categorias"
    id = Column(Integer, primary_key=True, index=True)
    nome = Column(String, unique=True, index=True)
    servicos = relationship("Servico", back_populates="categoria")


class Cliente(Base):
    """
    Representa um cliente do salão de beleza.

    Esta tabela é a entidade central do módulo de CRM, armazenando as informações
    de identificação de cada cliente, bem como o seu saldo de créditos para
    pacotes de serviços. O número de WhatsApp é utilizado como o principal
    identificador único para buscas, e para evitar duplicatas no sistema.

    Attributes:
        id (int): A chave primária única para o cliente.
        nome (str): O nome do cliente.
        whatsapp (str): O número de WhatsApp do cliente, que deve ser único.
        saldo_credito (Numeric): O saldo monetário atual que o cliente possui em créditos,
        utilizado para o pagamento de serviços.
        agendamentos (relationship): Relação one-to-many que liga o cliente a todos os seus agendamentos (passados e futuros).
        transacoes_credito (relationship): Relação one-to-many que liga o cliente ao seu extrato completo
        de transações de crédito, ordenado da mais recente para a mais antiga.
    """
    __tablename__ = "clientes"
    id = Column(Integer, primary_key=True, index=True)
    nome = Column(String, index=True)
    whatsapp = Column(String, unique=True, index=True)
    saldo_credito = Column(Numeric(10, 2), nullable=False, default=0.0)
    agendamentos = relationship("Agendamento", back_populates="cliente")
    transacoes_credito = relationship("TransacaoCredito", back_populates="cliente", order_by="desc(TransacaoCredito.data_hora)")



class Funcionario(Base):
    """
    Representa um funcionário do salão, que também é um utilizador do sistema.

    Esta tabela é a central para a autenticação, permissões e gestão de pessoal.
    Ela armazena as credenciais de login, a função do utilizador no sistema
    (Admin vs. Funcionário), o seu estado (ativo/inativo) e a sua relação
    financeira com o salão através da conta corrente, utilizada principalmente
    para a gestão de comissões de permuta.

    Attributes:
        id (int): A chave primária única para o funcionário.
        nome (str): O nome do funcionário, utilizado como nome de utilizador para o login.
        cargo (str): A descrição do cargo do funcionário (ex: 'Cabeleireira').
        senha_hash (str): O hash seguro da senha do funcionário, nunca a senha em texto puro.
        funcao (str): O nível de permissão do utilizador no sistema ('Admin' ou 'Funcionario').
        is_ativo (bool): Sinalizador para "soft delete". Se 'False', o funcionário não pode
        fazer login, e não aparece nas listas de agendamento.
        saldo_conta_corrente (Numeric): O saldo da conta corrente do funcionário com o salão.
        Um valor negativo indica uma dívida do funcionário.
        agendamentos (relationship): Relação one-to-many com todos os seus agendamentos.
        bloqueios (relationship): Relação one-to-many com todos os seus bloqueios de tempo.
        transacoes_credito_processadas (relationship): Relação que regista todas as vendas de pacotes
        de crédito processadas por este funcionário.
        transacoes_conta_corrente (relationship): Relação com o extrato da sua conta corrente.
        O argumento 'foreign_keys' é usado para resolver a
        ambiguidade entre 'funcionario_id' e 'admin_id' na tabela de transações.
    """
    __tablename__ = "funcionarios"
    id = Column(Integer, primary_key=True, index=True)
    nome = Column(String, index=True)
    cargo = Column(String)
    senha_hash = Column(String)
    funcao = Column(String, default="Funcionario", nullable=False)
    is_ativo = Column(Boolean, default=True, nullable=False)
    saldo_conta_corrente = Column(Numeric(10, 2), nullable=False, default=0.0)
    agendamentos = relationship("Agendamento", back_populates="funcionario")
    bloqueios = relationship("Bloqueio", back_populates="funcionario")
    transacoes_credito_processadas = relationship("TransacaoCredito", back_populates="funcionario")
    transacoes_conta_corrente = relationship(
        "TransacaoContaCorrente",
        back_populates="funcionario",
        foreign_keys="[TransacaoContaCorrente.funcionario_id]",
        order_by="desc(TransacaoContaCorrente.data_hora)"
    )
    fechamentos_caixa = relationship("FechamentoCaixa", back_populates="funcionario")



class Servico(Base):
    """
    Representa um serviço individual oferecido pelo salão de beleza.

    Esta tabela forma o catálogo de serviços do negócio. Cada serviço possui
    propriedades essenciais como duração e preço, que servem como valores
    padrão no momento do agendamento. O campo 'is_ativo' implementa uma
    lógica de "soft delete", garantindo que um serviço possa ser descontinuado
    sem afetar a integridade dos registros históricos.

    Attributes:
        id (int): A chave primária única para o serviço.
        nome (str): O nome do serviço, que deve ser único.
        duracao_padrao_minutos (int): A duração padrão em minutos, usada para
        preencher automaticamente o formulário de agendamento.
        preco_minimo (Numeric): O preço base do serviço. O preço final de um
        agendamento pode ser diferente, mas não inferior a este.
        is_ativo (bool): Sinalizador para "soft delete". Se 'False', o serviço não
        aparece nas opções para novos agendamentos.
        categoria_id (int): A chave estrangeira que liga o serviço à sua respectiva categoria.
        categoria (relationship): Relação que permite o acesso direto ao objeto
        'Categoria' a partir de um serviço (ex: servico.categoria.nome).
    """
    __tablename__ = "servicos"
    id = Column(Integer, primary_key=True, index=True)
    nome = Column(String, unique=True, index=True)
    duracao_padrao_minutos = Column(Integer)
    preco_minimo = Column(Numeric(10, 2))
    is_ativo = Column(Boolean, default=True, nullable=False)
    categoria_id = Column(Integer, ForeignKey("categorias.id", ondelete="SET NULL"))
    categoria = relationship("Categoria", back_populates="servicos")



class Agendamento(Base):
    """
    Representa um agendamento de serviço, a principal entidade transacional do sistema.

    Esta tabela é o coração da aplicação, ligando um cliente, um funcionário e
    um serviço num evento com data e hora específicas. Ela armazena todos os
    detalhes da marcação, incluindo o seu estado (agendado, concluído, cancelado)
    e o valor final cobrado.

    Além disso, ela pode estar ligada a transações financeiras específicas,
    como um pagamento por crédito ou um débito por permuta, servindo como o
    ponto de origem para estas operações.

    Attributes:
        id (int): A chave primária única para o agendamento.
        data_hora (DateTime): A data e hora exatas do início do agendamento.
        duracao_efetiva_minutos (int): A duração real do serviço em minutos.
        preco_final (Numeric): O preço final efetivamente cobrado pelo serviço.
        status (str): O estado atual do agendamento (ex: 'agendado', 'concluído').
        cliente_id (int): Chave estrangeira para o cliente que agendou o serviço.
        funcionario_id (int): Chave estrangeira para o funcionário que irá realizar o serviço.
        servico_id (int): Chave estrangeira para o serviço que foi agendado.
        cliente (relationship): Relação many-to-one com a tabela cliente.
        funcionario (relationship): Relação many-to-one com a tabela funcionario.
        servico (relationship): Relação many-to-one com a tabela servico.
        transacao_credito_associada (relationship): Relação one-to-one que liga este agendamento
        ao seu eventual pagamento com créditos de cliente.
        `uselist=False` garante que um agendamento só pode ter uma transação de crédito.
        transacao_conta_corrente_associada (relationship): Relação one-to-one que liga este
        agendamento a um débito de permuta na conta corrente do funcionário.
    """
    __tablename__ = "agendamentos"
    id = Column(Integer, primary_key=True, index=True)
    data_hora = Column(DateTime, index=True)
    duracao_efetiva_minutos = Column(Integer)
    preco_final = Column(Numeric(10, 2))
    status = Column(String, default=StatusAgendamento.AGENDADO.value, index=True)
    cliente_id = Column(Integer, ForeignKey("clientes.id"))
    funcionario_id = Column(Integer, ForeignKey("funcionarios.id"))
    servico_id = Column(Integer, ForeignKey("servicos.id"))
    cliente = relationship("Cliente", back_populates="agendamentos")
    funcionario = relationship("Funcionario", back_populates="agendamentos")
    servico = relationship("Servico")
    transacao_credito_associada = relationship("TransacaoCredito", back_populates="agendamento", uselist=False)
    transacao_conta_corrente_associada = relationship("TransacaoContaCorrente", back_populates="agendamento", uselist=False)



class TransacaoCredito(Base):
    """
    Representa uma única transação no saldo de créditos de um cliente.

    Esta tabela funciona como um extrato financeiro (ledger) para o saldo de
    créditos de cada cliente, garantindo a total rastreabilidade das movimentações.
    Cada registro representa ou uma 'adição' de crédito (proveniente da venda de
    um pacote) ou um 'uso' de crédito (para o pagamento de um serviço agendado).

    Attributes:
        id (int): A chave primária única para a transação.
        data_hora (DateTime): O momento exato em que a transação foi registrada.
        tipo (str): O tipo de transação: 'adição' ou 'uso'.
        valor (Numeric): O valor monetário da transação.
        descricao (str): Uma descrição para a transação (ex: "pacote: 5x corte").
        cliente_id (int): Chave estrangeira para o cliente dono da transação.
        funcionario_id (int): Chave estrangeira para o funcionário que processou a transação.
        agendamento_id (int): Chave estrangeira para o agendamento que foi pago com créditos.
        É opcional (`nullable=True`), pois apenas transações do tipo 'uso' estão associadas a um agendamento.
        cliente (relationship): Relação many-to-one com a tabela cliente.
        funcionario (relationship): Relação many-to-one com a tabela funcionario.
        agendamento (relationship): Relação one-to-one com a tabela agendamento.
    """
    __tablename__ = "transacoes_credito"
    id = Column(Integer, primary_key=True, index=True)
    data_hora = Column(DateTime, default=datetime.now)
    tipo = Column(String, index=True)
    valor = Column(Numeric(10, 2), nullable=False)
    descricao = Column(String)
    cliente_id = Column(Integer, ForeignKey("clientes.id"), nullable=False)
    funcionario_id = Column(Integer, ForeignKey("funcionarios.id"), nullable=False)
    agendamento_id = Column(Integer, ForeignKey("agendamentos.id"), nullable=True)
    cliente = relationship("Cliente", back_populates="transacoes_credito")
    funcionario = relationship("Funcionario", back_populates="transacoes_credito_processadas")
    agendamento = relationship("Agendamento", back_populates="transacao_credito_associada")



class TransacaoContaCorrente(Base):
    """
    Representa uma única transação na conta corrente de um funcionário com o salão.

    Esta tabela funciona como um extrato financeiro (ledger) para cada funcionário,
    separando as dívidas internas (como comissões de permuta) do fluxo de caixa
    principal. Cada registro representa ou um 'débito' (uma dívida do funcionário
    para com o salão) ou um 'crédito' (um pagamento feito pelo funcionário ao salão).

    Attributes:
        id (int): A chave primária única para a transação.
        data_hora (DateTime): O momento exato em que a transação foi registrada.
        tipo (str): O tipo de transação: 'débito' ou 'crédito'.
        valor (Numeric): O valor monetário da transação.
        descricao (str): Uma descrição para a transação (ex: "comissão permuta...").
        funcionario_id (int): Chave estrangeira para o funcionário dono da conta corrente.
        agendamento_id (int): Chave estrangeira para o agendamento que originou um débito.
        É opcional, pois transações de 'crédito' (pagamentos) não estão ligadas a um agendamento específico.
        admin_id (int): Chave estrangeira para o administrador que registou um pagamento ('crédito').
        É opcional, pois 'débitos' são gerados automaticamente pelo sistema.
        funcionario (relationship): Relação many-to-one com a tabela funcionario, usando
        explicitamente a 'funcionario_id' para resolver a ambiguidade com a 'admin_id'.
        agendamento (relationship): Relação one-to-one com a tabela agendamento.
    """
    __tablename__ = "transacoes_conta_corrente"
    id = Column(Integer, primary_key=True, index=True)
    data_hora = Column(DateTime, default=datetime.now)
    tipo = Column(String, index=True)
    valor = Column(Numeric(10, 2), nullable=False)
    descricao = Column(String)
    funcionario_id = Column(Integer, ForeignKey("funcionarios.id"), nullable=False)
    agendamento_id = Column(Integer, ForeignKey("agendamentos.id"), nullable=True)
    admin_id = Column(Integer, ForeignKey("funcionarios.id"), nullable=True)
    funcionario = relationship("Funcionario", back_populates="transacoes_conta_corrente", foreign_keys=[funcionario_id])
    agendamento = relationship("Agendamento", back_populates="transacao_conta_corrente_associada")



class Bloqueio(Base):
    """
    Representa um bloqueio de tempo na agenda de um funcionário.

    Esta tabela é usada para marcar períodos em que um funcionário não está
    disponível para agendamentos, mas que não correspondem a um serviço
    (ex: pausa para almoço, consulta médica, folga).

    A lógica de verificação de conflitos do sistema consulta tanto esta tabela
    quanto a de agendamentos para garantir que nenhum novo evento seja marcado
    sobre um período já ocupado.

    Attributes:
        id (int): A chave primária única para o bloqueio.
        inicio (DateTime): A data e hora de início do período de bloqueio.
        fim (DateTime): A data e hora de fim do período de bloqueio.
        motivo (str, optional): Uma descrição opcional para o motivo do bloqueio.
        funcionario_id (int): Chave estrangeira para o funcionário cuja agenda está a ser bloqueada.
        funcionario (relationship): Relação many-to-one com a tabela funcionario.
    """
    __tablename__ = "bloqueios"
    id = Column(Integer, primary_key=True, index=True)
    inicio = Column(DateTime)
    fim = Column(DateTime)
    motivo = Column(String, nullable=True)
    funcionario_id = Column(Integer, ForeignKey("funcionarios.id"))
    funcionario = relationship("Funcionario", back_populates="bloqueios")



class LogAlteracao(Base):
    """
    Representa um registro na trilha de auditoria do sistema.

    Esta tabela é crucial para a rastreabilidade e a segurança, funcionando como
    um registro imutável de todas as alterações significativas feitas nos dados,
    como modificações de preço ou status de agendamentos.

    Cada entrada captura o 'quem, o quê, quando e como' de uma alteração,
    permitindo que os administradores e funcionários auditem o histórico de
    operações e entendam o ciclo de vida de um registro.

    Attributes:
        id (int): A chave primária única para o registo de log.
        data_hora (DateTime): O momento exato em que a alteração foi registrada.
        agendamento_id (int): Chave estrangeira para o agendamento que foi modificado.
        funcionario_id (int): Chave estrangeira para o funcionário que realizou a alteração.
        campo_alterado (str): O nome do campo que foi modificado (ex: 'preco_final').
        valor_antigo (str): O valor do campo antes da alteração, armazenado como string para flexibilidade.
        valor_novo (str): O valor do campo após a alteração, armazenado como string.
        funcionario (relationship): Relação que permite o acesso direto ao objeto 'Funcionario'.
        agendamento (relationship): Relação que permite o acesso direto ao objeto 'Agendamento'.
    """
    __tablename__ = "logs_alteracoes"
    id = Column(Integer, primary_key=True, index=True)
    data_hora = Column(DateTime, default=datetime.now)
    agendamento_id = Column(Integer, ForeignKey("agendamentos.id"))
    funcionario_id = Column(Integer, ForeignKey("funcionarios.id"))
    campo_alterado = Column(String)
    valor_antigo = Column(String)
    valor_novo = Column(String)
    funcionario = relationship("Funcionario")
    agendamento = relationship("Agendamento")



class FluxoCaixa(Base):
    """
    Representa um registro no fluxo de caixa principal do salão.

    Esta tabela funciona como o ledger financeiro primário, registrando todas as
    transações que envolvem a movimentação real de dinheiro (entradas e saídas).
    É a base para todos os relatórios financeiros e para o fechamento de caixa diário.

    Ela é distinta das tabelas de transações de crédito e de conta corrente,
    que lidam com créditos de clientes e dívidas internas, respectivamente,
    sem necessariamente representarem uma entrada imediata de dinheiro.

    Attributes:
        id (int): A chave primária única para a transação de caixa.
        data_hora_registro (DateTime): O momento exato em que a transação foi registrada.
        descricao (str): Uma descrição para a transação (ex: "Serviço: Corte Feminino").
        valor (Numeric): O valor monetário da transação.
        tipo (str): O tipo de transação: 'entrada' ou 'saída'.
        metodo_pagamento (str, optional): A forma de pagamento para transações de 'entrada'.
        funcionario_id (int): Chave estrangeira para o funcionário que processou a transação.
        agendamento_id (int, optional): Chave estrangeira para o agendamento que originou
        uma 'entrada'. É nulo para saídas ou para vendas de pacotes de crédito.
        funcionario (relationship): Relação que permite o acesso direto ao objeto 'Funcionario'.
        agendamento (relationship): Relação que permite o acesso direto ao objeto 'Agendamento'.
    """
    __tablename__ = "fluxo_caixa"
    id = Column(Integer, primary_key=True, index=True)
    data_hora_registro = Column(DateTime, default=datetime.now, index=True)
    descricao = Column(String, nullable=False)
    valor = Column(Numeric(10, 2), nullable=False)
    tipo = Column(String, index=True, nullable=False)
    metodo_pagamento = Column(String, nullable=True)
    funcionario_id = Column(Integer, ForeignKey("funcionarios.id"))
    agendamento_id = Column(Integer, ForeignKey("agendamentos.id"), nullable=True)
    funcionario = relationship("Funcionario")
    agendamento = relationship("Agendamento")
    produto_id = Column(Integer, ForeignKey("produtos.id"), nullable=True)
    quantidade = Column(Integer, server_default='1', nullable=True)
    comissao_percentual = Column(Numeric(5, 2), nullable=True)
    produto = relationship("Produto", back_populates="vendas")


class FechamentoCaixa(Base):
    """
    Representa o fechamento formal do caixa de um dia específico.

    O registro desta tabela serve como marco oficial de que o movimento
    financeiro daquele dia foi conferido e encerrado. A partir dele, o sistema
    pode bloquear alterações tardias em agendamentos vinculados à mesma data.
    """
    __tablename__ = "fechamentos_caixa"

    id = Column(Integer, primary_key=True, index=True)
    data_fechamento = Column(Date, nullable=False, unique=True, index=True)
    saldo_final = Column(Numeric(10, 2), nullable=False)
    data_hora_fechamento = Column(DateTime, default=datetime.now, nullable=False)
    funcionario_id = Column(Integer, ForeignKey("funcionarios.id"), nullable=False)

    funcionario = relationship("Funcionario", back_populates="fechamentos_caixa")


class Produto(Base):
    """
        Representa um produto físico ou serviço vendido no salão.

        Esta tabela armazena o catálogo de todos os produtos disponíveis para venda,
        que não são agendáveis como os serviços principais. Cada produto possui
        um nome, valor, e opcionalmente, uma imagem associada.

        A coluna 'is_ativo' implementa a funcionalidade de "soft delete", permitindo
        que um produto seja desativado do catálogo de vendas sem ser permanentemente
        removido do banco de dados, preservando a integridade de registros
        financeiros históricos.

        Attributes:
            id (int): A chave primária única para o produto.
            nome (str): O nome do produto, que deve ser único.
            valor (Numeric): O preço de venda do produto.
            caminho_foto (str, optional): O nome do ficheiro da imagem do produto, armazenado no sistema de ficheiros.
            is_ativo (bool): Um sinalizador que indica se o produto está disponível
                             para venda (True) ou se foi desativado (False).
        """
    __tablename__ = "produtos"

    id = Column(Integer, primary_key=True, index=True)
    nome = Column(String, index=True, nullable=False, unique=True)
    valor = Column(Numeric(10, 2), nullable=False)
    caminho_foto = Column(String, nullable=True)
    is_ativo = Column(Boolean, server_default='true', nullable=False)
    vendas = relationship("FluxoCaixa", back_populates="produto")   
