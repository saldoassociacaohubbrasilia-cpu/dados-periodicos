"""Cliente do Google Analytics 4 (Data API) — só leitura.

Mesmas consultas do scripts/ga4_relatorio.py, mas devolvendo linhas por
dia em vez de uma planilha, pra gravar em Ga4MetricaDiaria.
"""
import json
from datetime import date, datetime

import google.auth
import google.auth.exceptions
from google.analytics.data_v1beta import BetaAnalyticsDataClient
from google.analytics.data_v1beta.types import DateRange, Dimension, Metric, RunReportRequest
from google.oauth2 import credentials as user_credentials
from google.oauth2 import service_account

from app.config import settings

SCOPES = ["https://www.googleapis.com/auth/analytics.readonly"]

# recorte -> (dimensão do GA4 além de "date", métricas do GA4).
# Ordem das métricas: usuarios_ativos, sessoes, visualizacoes, tempo de
# engajamento — métrica que não faz sentido no recorte fica de fora e
# entra como 0 (ver _COLUNAS).
RECORTES = {
    "dia_hora": ("hour", ["activeUsers", "sessions"]),
    "dispositivo": ("deviceCategory", ["activeUsers", "sessions", "userEngagementDuration"]),
    "tela": ("unifiedScreenName", ["activeUsers", "screenPageViews", "userEngagementDuration"]),
    "novos_recorrentes": ("newVsReturning", ["activeUsers", "sessions"]),
}

_COLUNAS = {
    "activeUsers": "usuarios_ativos",
    "sessions": "sessoes",
    "screenPageViews": "visualizacoes",
    "userEngagementDuration": "tempo_engajamento_seg",
}


class Ga4NaoConfigurado(Exception):
    """Nenhuma credencial do GA4 disponível — o sync do GA4 é pulado."""


def _credenciais():
    if settings.ga4_credentials_json.strip():
        info = json.loads(settings.ga4_credentials_json)
        if info.get("type") == "service_account":
            return service_account.Credentials.from_service_account_info(info, scopes=SCOPES)
        return user_credentials.Credentials.from_authorized_user_info(info, scopes=SCOPES)
    try:
        creds, _ = google.auth.default(scopes=SCOPES)
    except google.auth.exceptions.DefaultCredentialsError as exc:
        raise Ga4NaoConfigurado(str(exc)) from exc
    return creds


class Ga4Client:
    def __init__(self):
        self._client = BetaAnalyticsDataClient(credentials=_credenciais())
        self._property = f"properties/{settings.ga4_property_id}"

    def buscar_recorte(self, recorte: str, inicio: date, fim: date) -> list[dict]:
        """Linhas {data, dimensao, usuarios_ativos, sessoes, visualizacoes,
        tempo_engajamento_seg} do recorte, uma por dia x valor da dimensão."""
        dimensao, metricas = RECORTES[recorte]
        resposta = self._client.run_report(RunReportRequest(
            property=self._property,
            dimensions=[Dimension(name="date"), Dimension(name=dimensao)],
            metrics=[Metric(name=m) for m in metricas],
            date_ranges=[DateRange(start_date=inicio.isoformat(), end_date=fim.isoformat())],
            limit=100000,
        ))
        linhas = []
        for row in resposta.rows:
            linha = {
                "data": datetime.strptime(row.dimension_values[0].value, "%Y%m%d").date(),
                "dimensao": row.dimension_values[1].value[:200],
                "usuarios_ativos": 0, "sessoes": 0, "visualizacoes": 0, "tempo_engajamento_seg": 0.0,
            }
            for metrica, valor in zip(metricas, row.metric_values):
                coluna = _COLUNAS[metrica]
                linha[coluna] = float(valor.value) if coluna == "tempo_engajamento_seg" else int(float(valor.value))
            linhas.append(linha)
        return linhas
