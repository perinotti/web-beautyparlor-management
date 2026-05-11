import uuid
from pathlib import Path
from fastapi import UploadFile

ALLOWED_EXTENSIONS = {"png", "jpg", "jpeg", "webp"}
MAX_FILE_SIZE_MB = 2
MAX_FILE_SIZE_BYTES = MAX_FILE_SIZE_MB * 1024 * 1024

BASE_DIR = Path(__file__).resolve().parent.parent


async def salvar_imagem_produto(foto: UploadFile) -> str:
    """Valida e salva a imagem de um produto, retornando o nome do ficheiro gerado."""
    extensao = foto.filename.split(".")[-1].lower()
    if extensao not in ALLOWED_EXTENSIONS:
        raise ValueError(f"Formato de ficheiro não permitido. Use: {', '.join(ALLOWED_EXTENSIONS)}")

    contents = await foto.read()
    if len(contents) > MAX_FILE_SIZE_BYTES:
        raise ValueError(f"O ficheiro é muito grande. O tamanho máximo é de {MAX_FILE_SIZE_MB} MB.")

    pasta_uploads = Path(BASE_DIR, "static", "uploads", "products")
    pasta_uploads.mkdir(parents=True, exist_ok=True)

    nome_ficheiro_unico = f"{uuid.uuid4()}.{extensao}"
    caminho_salvar = pasta_uploads / nome_ficheiro_unico

    with open(caminho_salvar, "wb") as buffer:
        buffer.write(contents)

    return nome_ficheiro_unico
