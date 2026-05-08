# Guia de Contribuição — Web Beauty Parlor Management

## Visão Geral

Cada integrante do grupo é responsável por um commit específico, mapeado no Plano de Ação. Este guia descreve o fluxo completo: desde preparar o ambiente local até ter o código aceito no repositório oficial.

---

## Branches principais

| Branch | Propósito |
|---|---|
| `master` | Código estável, aprovado e testado. Nunca recebe commits diretos. |
| `develop` | Branch de integração. Todos os PRs devem ser abertos para cá. |

O fluxo correto é:
```
branch pessoal → PR para develop → revisão e testes → merge em develop
                                                              ↓
                                          (quando fase inteira estiver estável)
                                                              ↓
                                                   PR de develop para master
```

---

## Para todos os contribuidores

### 1. Preparar o ambiente antes de começar

Antes de escrever qualquer linha de código, garanta que sua cópia local está atualizada com o repositório principal.

```bash
# Adicionar o repositório principal como "upstream" (fazer apenas uma vez)
git remote add upstream https://github.com/perinotti/web-beautyparlor-management.git

# Sempre que for começar um trabalho novo, atualize sua develop local
git checkout develop
git pull upstream develop
```

---

### 2. Criar uma branch para o seu trabalho

Nunca trabalhe diretamente na branch `develop` ou `master`. Crie uma branch com um nome descritivo que identifique o commit que você está fazendo.

O padrão de nome é: `tipo/descricao-curta`

```bash
# Exemplos:
git checkout -b fix/crash-pagamento-credito        # Commit 1
git checkout -b fix/imports-deprecados             # Commit 2
git checkout -b fix/remove-create-all-alembic      # Commit 3
git checkout -b fix/status-http-401-login          # Commit 4
```

---

### 3. Fazer as alterações

- Faça apenas as alterações descritas no seu commit. Não aproveite para corrigir outras coisas — isso dificulta a revisão e mistura responsabilidades no histórico.
- Teste localmente antes de enviar:

```bash
# Ativar o ambiente virtual
# Linux/macOS:
source venv/bin/activate

# Windows:
venv\Scripts\activate

# Rodar o servidor
uvicorn main:app --reload
```

Verifique se a aplicação sobe sem erros no terminal e se a funcionalidade que você alterou continua funcionando no navegador.

---

### 4. Fazer o commit

Use a mensagem de commit exatamente como definida no Plano de Ação. O padrão utilizado é o **Conventional Commits**.

```bash
# Adicionar apenas os arquivos que você alterou
git add database.py models.py routers/painel.py

# Commitar com a mensagem definida no plano
git commit -m "fix: corrige imports deprecados, relacionamento quebrado e import duplicado"
```

Evite usar `git add .` — ele adiciona tudo indiscriminadamente e pode incluir arquivos indesejados como o `.env` ou arquivos de cache.

---

### 5. Enviar para o GitHub

```bash
# Enviar sua branch para o GitHub (origin = seu fork)
git push origin fix/imports-deprecados
```

---

### 6. Abrir um Pull Request (PR)

1. Acesse seu repositório no GitHub
2. Clique em **"Compare & pull request"**
3. **Atenção:** certifique-se de que o destino é a branch `develop` do repositório principal, não `master`
4. Preencha o PR da seguinte forma:

**Título:** igual à mensagem do commit
`fix: corrige imports deprecados, relacionamento quebrado e import duplicado`

**Descrição:** use o template abaixo:

```
## O que foi alterado
- database.py: movido import de `declarative_base` de `sqlalchemy.ext.declarative` (deprecado) para `sqlalchemy.orm`
- models.py: adicionado `back_populates="vendas"` no relacionamento `FluxoCaixa.produto`
- routers/painel.py: removido import duplicado de `collections.defaultdict`

## Por que foi alterado
Correções de qualidade identificadas no mapeamento inicial do projeto.

## Como testar
1. Rodar `uvicorn main:app --reload`
2. Verificar que nenhum aviso de deprecação aparece no terminal ao iniciar
3. Navegar pelo painel e verificar que produtos carregam normalmente

## Migration necessária?
[ ] Sim — rodar `alembic upgrade head` antes de testar
[x] Não
```

5. Clique em **"Create pull request"**

---

## Para o dono do repositório

### Como testar um Pull Request antes de aceitar

**1. Buscar a branch do colega localmente:**
```bash
git fetch origin
git checkout nome-da-branch-do-colega
```

**2. Atualizar o banco se houver migration nova:**
```bash
alembic upgrade head
```

**3. Rodar o servidor e testar:**
```bash
source venv/bin/activate  # ou venv\Scripts\activate no Windows
uvicorn main:app --reload
```

Use o checklist do card do Trello como roteiro de teste — marque cada item enquanto verifica.

**4. Se tiver problema:**
Comente no PR do GitHub apontando o que encontrou, na aba **"Files changed"** você pode comentar diretamente na linha problemática. O colega corrige e faz push na mesma branch — o PR atualiza automaticamente.

**5. Se estiver tudo certo:**
Clique em **"Merge pull request"** → **"Confirm merge"** no GitHub.

---

### Checklist rápido antes de aceitar qualquer PR

- [ ] As alterações correspondem ao commit descrito no Plano de Ação?
- [ ] Nenhuma outra parte do código foi modificada sem necessidade?
- [ ] A mensagem do commit segue o padrão?
- [ ] O servidor sobe sem erros no terminal?
- [ ] As páginas afetadas pelo commit funcionam sem erro 500?
- [ ] Se teve migration, o `alembic upgrade head` rodou sem erro?
- [ ] O `alembic current` mostra `(head)` depois?

---

### Ordem recomendada para aceitar os PRs

Respeite as dependências definidas no documento "Dependências Importantes":

**Fase 1** — Commits 1, 2 e 3 podem ser mergeados em qualquer ordem entre si.

**Fase 2** — Mergear Commits 1, 2 e 3 antes de qualquer coisa da Fase 2. O Commit de magic strings depende do Commit de remoção do `create_all`. Os Commits de sessão e magic strings não devem ser mergeados ao mesmo tempo — um por vez.

### Como promover develop para master (ao final de uma fase)

Após todos os commits de uma fase estarem mergeados em `develop` e testados:

```bash
git checkout master
git pull upstream master
git merge develop
git push origin master
```

Ou pelo GitHub: abra um PR de `develop` para `master`.

---

### Como atualizar o repositório local após um merge

```bash
git checkout develop
git pull upstream develop
```

---

## Resumo do fluxo em uma linha

`pull upstream develop` → `nova branch` → `alterar` → `testar` → `commit` → `push` → `Pull Request para develop` → `revisão` → `merge`
