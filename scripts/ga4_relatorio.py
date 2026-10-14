"""
Extrai relatórios do GA4 (propriedade do Saldo+) e salva em Excel, uma aba por relatório.

Uso:
    python scripts/ga4_relatorio.py                      # últimos 30 dias
    python scripts/ga4_relatorio.py --inicio 2026-10-01 --fim 2026-10-31

Pré-requisitos:
    pip install google-analytics-data pandas openpyxl
    Autenticação (uma das duas):
      - gcloud auth application-default login --scopes=... (login com sua conta Google), ou
      - arquivo ga4-credenciais.json de conta de serviço com acesso de Leitor no GA4.
"""

import argparse
import os
from datetime import date

import pandas as pd
from google.analytics.data_v1beta import BetaAnalyticsDataClient
from google.analytics.data_v1beta.types import (
    DateRange,
    Dimension,
    Metric,
    OrderBy,
    RunReportRequest,
)

# ---------------------------------------------------------------------------
# Configuração
# ---------------------------------------------------------------------------
PROPERTY_ID = "557048713"  # Propriedade "Associação hub" (conta Saldo+)
CREDENCIAIS = os.getenv("GA4_CREDENCIAIS", "ga4-credenciais.json")

DIAS_SEMANA = {
    "Sunday": "Domingo", "Monday": "Segunda", "Tuesday": "Terça",
    "Wednesday": "Quarta", "Thursday": "Quinta", "Friday": "Sexta",
    "Saturday": "Sábado",
}

# Cada relatório: nome da aba -> (dimensões, métricas, coluna para ordenar)
RELATORIOS = {
    "Dia e hora": (
        ["dayOfWeekName", "hour"],
        ["activeUsers", "sessions"],
        "sessions",
    ),
    "Dispositivo": (
        ["deviceCategory"],
        ["activeUsers", "sessions", "averageSessionDuration"],
        "activeUsers",
    ),
    "Paginas": (
        # A plataforma usa #/ nas rotas; o título da página costuma separar
        # melhor as telas do que o caminho da URL.
        ["pageTitle"],
        ["screenPageViews", "activeUsers", "userEngagementDuration"],
        "screenPageViews",
    ),
    "Novos x recorrentes": (
        ["date", "newVsReturning"],
        ["activeUsers"],
        None,
    ),
    "Engajamento diario": (
        ["date"],
        ["activeUsers", "sessions", "averageSessionDuration", "engagementRate"],
        None,
    ),
    "Origem (UTM)": (
        ["sessionSource", "sessionMedium", "sessionCampaignName"],
        ["sessions", "activeUsers"],
        "sessions",
    ),
    "Cidade": (
        ["city"],
        ["activeUsers"],
        "activeUsers",
    ),
}


def rodar_relatorio(cliente, inicio, fim, dimensoes, metricas, ordenar_por):
    pedido = RunReportRequest(
        property=f"properties/{PROPERTY_ID}",
        dimensions=[Dimension(name=d) for d in dimensoes],
        metrics=[Metric(name=m) for m in metricas],
        date_ranges=[DateRange(start_date=inicio, end_date=fim)],
        limit=10000,
    )
    if ordenar_por:
        pedido.order_bys = [
            OrderBy(metric=OrderBy.MetricOrderBy(metric_name=ordenar_por), desc=True)
        ]

    resposta = cliente.run_report(pedido)

    linhas = []
    for row in resposta.rows:
        linha = {d: v.value for d, v in zip(dimensoes, row.dimension_values)}
        linha.update({m: v.value for m, v in zip(metricas, row.metric_values)})
        linhas.append(linha)

    df = pd.DataFrame(linhas, columns=dimensoes + metricas)
    for m in metricas:
        df[m] = pd.to_numeric(df[m], errors="coerce")
    return df


def tratar(df):
    """Ajustes de leitura: datas, dia da semana em português, minutos."""
    if "date" in df.columns:
        df["date"] = pd.to_datetime(df["date"], format="%Y%m%d").dt.date
        df = df.sort_values("date")
    if "dayOfWeekName" in df.columns:
        df["dayOfWeekName"] = df["dayOfWeekName"].map(DIAS_SEMANA).fillna(df["dayOfWeekName"])
    if "hour" in df.columns:
        df["hour"] = pd.to_numeric(df["hour"])
    for col in ("averageSessionDuration", "userEngagementDuration"):
        if col in df.columns:
            df[col] = (df[col] / 60).round(1)
            df = df.rename(columns={col: f"{col}_min"})
    if "engagementRate" in df.columns:
        df["engagementRate"] = (df["engagementRate"] * 100).round(1)
        df = df.rename(columns={"engagementRate": "engagementRate_%"})
    return df


def main():
    parser = argparse.ArgumentParser(description="Relatórios GA4 do Saldo+")
    parser.add_argument("--inicio", default="30daysAgo", help="AAAA-MM-DD ou '30daysAgo'")
    parser.add_argument("--fim", default="today", help="AAAA-MM-DD ou 'today'")
    parser.add_argument("--saida", default=f"ga4_saldo_{date.today():%Y-%m-%d}.xlsx")
    args = parser.parse_args()

    # Usa o JSON da conta de serviço se existir; senão, usa o login feito com
    # "gcloud auth application-default login".
    if os.path.exists(CREDENCIAIS):
        os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = CREDENCIAIS
    cliente = BetaAnalyticsDataClient()

    with pd.ExcelWriter(args.saida, engine="openpyxl") as writer:
        for aba, (dims, mets, ordem) in RELATORIOS.items():
            df = tratar(rodar_relatorio(cliente, args.inicio, args.fim, dims, mets, ordem))
            df.to_excel(writer, sheet_name=aba, index=False)
            print(f"{aba}: {len(df)} linhas")

    print(f"\nArquivo salvo: {args.saida}")


if __name__ == "__main__":
    main()
