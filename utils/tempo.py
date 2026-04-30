from datetime import datetime
from zoneinfo import ZoneInfo

def obter_agora_local():
    """Retorna a data e hora atual no fuso horário de São Paulo."""
    return datetime.now(ZoneInfo("America/Sao_Paulo"))

