#  Saldo+ · Backend de Indicadores

<p>
  <img alt="Python" src="https://img.shields.io/badge/python-3.11%2B-3776AB?logo=python&logoColor=white">
  <img alt="FastAPI" src="https://img.shields.io/badge/FastAPI-009688?logo=fastapi&logoColor=white">
  <img alt="PostgreSQL" src="https://img.shields.io/badge/PostgreSQL-Supabase-336791?logo=postgresql&logoColor=white">
  <img alt="Status" src="https://img.shields.io/badge/status-em%20desenvolvimento-yellow">
</p>

Backend que sincroniza dados da **API Ludos Pro** (plataforma de gamificação da **Trilha Saldo+**), calcula os indicadores de acompanhamento por instituição, escola/turma e módulo, e serve tudo pronto pro dashboard consumir via REST.

> Projeto do **Impact Hub Brasília** para o programa **Saldo+** (educação financeira gamificada para estudantes do ensino médio da rede pública do DF), em parceria com a **Secretaria de Educação** e a **CVP**.

---

## 📑 Sumário

- [Como funciona](#-como-funciona)
- [Setup rápido](#-setup-rápido)
- [Configurando instituições e mapa](#-configurando-instituições-e-mapa)
- [Endpoints da API](#-endpoints-da-api)
- [Estrutura do projeto](#-estrutura-do-projeto)
- [Gotchas conhecidos](#-gotchas-conhecidos-clique-para-expandir)
- [Pendências](#-pendências)

---

## 🔄 Como funciona

```mermaid
flowchart LR
    A[("Ludos Pro API")] -->|sync periódico| B[["raw_ludos_snapshot<br/>(JSONB cru)"]]
    B --> C{{"transform.py<br/>junta players + performance<br/>pelo playerId"}}
    C --> D[["metric_snapshot<br/>geral · escola · módulo<br/>x instituição"]]
    D --> E(["/api/v1/dashboard"])
    E --> F[["dashboard.html<br/>Chart.js + Leaflet"]]
```

A Ludos manda dois relatórios que precisam ser cruzados pelo `playerId`:

| Relatório | O que tem | O que NÃO tem |
|---|---|---|
| `/report/performance` | `courseId`, `playerId`, `progression` | turma, escola, pontuação |
| `/report/players` | `groups[].groupName`, `coins`, `score` | curso/progresso |

`transform.py` faz esse cruzamento antes de calcular qualquer métrica — só entra no cálculo quem tem `courseId == 41` (Trilha Saldo+).

---

## 🚀 Setup rápido

```bash
python -m venv .venv
.venv\Scripts\Activate.ps1        # Windows (PowerShell)
# source .venv/bin/activate       # Mac/Linux

pip install -r requirements.txt
```

Configure o `.env`:

```env
DATABASE_URL=postgresql+pg8000://usuario:senha@host:5432/postgres
LUDOS_API_BASE_URL=https://api.ludos.pro/api3
LUDOS_API_KEY=sua_chave
SYNC_INTERVAL_HOURS=6
FRONTEND_ORIGIN=http://localhost:5500
```

Crie/atualize as tabelas com o Alembic:

```bash
alembic upgrade head
```

> **Banco já existente, criado antes do Alembic entrar no projeto?** Não rode `upgrade head` direto — as tabelas já existem e o comando tentaria recriá-las. Rode `alembic stamp head` uma única vez: isso só marca o banco como já estando na revisão `baseline schema` (que espelha exatamente o schema atual), sem executar nenhum `CREATE TABLE`. Depois disso, toda mudança de schema nova (nova coluna, nova tabela) vira uma migration incremental de verdade — nunca mais precisa de script de reset manual.

Suba a API:

```bash
uvicorn app.main:app --reload
```

Isso liga o agendador (o schema já foi criado/atualizado pelo Alembic no passo anterior). Pra não esperar o primeiro ciclo:

```bash
curl -X POST http://localhost:8000/api/v1/sync/run
```

Abra `frontend/dashboard.html` com o Live Server (porta 5500) e pronto.

> **Mudou `app/models.py`?** Gere a migration com `alembic revision --autogenerate -m "descrição da mudança"`, confira o arquivo gerado em `alembic/versions/` (autogenerate nem sempre acerta 100%) e rode `alembic upgrade head`.

---

## 🏫 Configurando instituições e mapa

`app/institutions.py` é o único lugar que você precisa editar à mão:

```python
GROUPNAME_TO_INSTITUTION = {
    "CVP - Turma Exemplo": "cvp",   # tudo que não estiver aqui = "secretaria"
}

SCHOOL_COORDINATES = {
    "CED Jardins": (-15.793, -47.882),   # sem coordenada = não aparece no mapa (mas aparece nos gráficos/tabela)
}
```

Pra saber os `GroupName` exatos que a Ludos manda, confira o campo `escolas[].nome` de:

```bash
curl "http://localhost:8000/api/v1/dashboard?instituicao=todas"
```

---

## 🔌 Endpoints da API

| Método | Rota | Parâmetro | Uso |
|---|---|---|---|
| `GET` | `/api/v1/dashboard` | `instituicao` = `todas`\|`secretaria`\|`cvp` | Painel completo: KPIs, escolas, módulos, turmas, destaques |
| `GET` | `/api/v1/overview` | `instituicao` | KPIs gerais isolados |
| `GET` | `/api/v1/trails` | `instituicao` | Distribuição por módulo |
| `POST` | `/api/v1/sync/run` | — | Força sincronização imediata com a Ludos |
| `GET` | `/health` | — | Healthcheck |

<details>
<summary><b>Ver exemplo de resposta do <code>/api/v1/dashboard</code></b></summary>

```json
{
  "kpis": {
    "escolas": 12,
    "inscritos": 1096,
    "engajados": 504,
    "taxa_engajamento": 46.0,
    "taxa_retencao": 33.3,
    "pontuacao_media": 87.5
  },
  "escolas": [
    { "nome": "CED Jardins", "inscritos": 143, "engajados": 66, "engajamento_pct": 46.1 }
  ],
  "modulos": [
    { "nome": "Boas-vindas", "total_alunos": 980 }
  ],
  "turmas": [
    { "nome": "CED Jardins", "escola": "CED Jardins", "total_alunos": 143, "alunos_engajados": 66, "progresso_medio": 46.1 }
  ],
  "destaque": {
    "escola_mais_inscritos": "CED Jardins",
    "escola_mais_engajados": "CED Jardins",
    "modulo_destaque": "Boas-vindas"
  }
}
```
</details>

---

## 📁 Estrutura do projeto
