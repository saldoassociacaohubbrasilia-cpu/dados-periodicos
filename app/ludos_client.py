import time
import logging
from typing import Any, Optional

import httpx

from app.config import settings

logger = logging.getLogger("ludos_client")

# Endpoint confirmado na documentação oficial da Ludos (/doc):
# devolve o log de acessos dos jogadores [{idPlayer, dtLog, txData}].
LOGIN_LOG_PATH = "/report/logs"


class LudosAPIError(Exception):
    pass


class LudosClient:
    """
    Cliente HTTP para a API Ludos Pro (base: https://api.ludos.pro/api3).

    Cuidados que essa classe já resolve:
    - Intervalo mínimo entre chamadas (LUDOS_MIN_REQUEST_INTERVAL_SECONDS)
      para não sobrecarregar a API deles.
    - Retry com backoff exponencial em 429/5xx (limitado a LUDOS_MAX_RETRIES,
      sem loop cascata infinito).
    - Erros 400 (ex: endpoint que não aceita paginação) são capturados e
      logados em vez de derrubar a sincronização inteira.
    - Tratamento de Cota Excedida (403): Interrompe a paginação graciosamente
      e retorna os registros processados até o momento.
    """

    def __init__(self):
        self._base_url = settings.ludos_api_base_url.rstrip("/")
        self._client = httpx.Client(
            base_url=self._base_url,
            headers={"Ocp-Apim-Subscription-Key": settings.ludos_api_key},
            timeout=30.0,
        )
        self._min_interval = settings.ludos_min_request_interval_seconds
        self._max_retries = settings.ludos_max_retries
        self._last_call_ts: float = 0.0

    def _throttle(self):
        elapsed = time.monotonic() - self._last_call_ts
        wait = self._min_interval - elapsed
        if wait > 0:
            time.sleep(wait)

    def _get(self, path: str, params: Optional[dict] = None) -> Any:
        params = params or {}
        attempt = 0
        while True:
            self._throttle()
            self._last_call_ts = time.monotonic()
            try:
                resp = self._client.get(path, params=params)
            except httpx.RequestError as exc:
                attempt += 1
                if attempt > self._max_retries:
                    raise LudosAPIError(f"Falha de rede em {path}: {exc}") from exc
                time.sleep(2 ** attempt)
                continue

            if resp.status_code == 400:
                logger.warning("400 em %s params=%s: %s", path, params, resp.text[:300])
                raise LudosAPIError(f"400 em {path}: {resp.text[:300]}")

            if resp.status_code in (429, 500, 502, 503, 504):
                attempt += 1
                if attempt > self._max_retries:
                    raise LudosAPIError(f"{resp.status_code} persistente em {path}")
                sleep_s = min(2 ** attempt, 30)
                logger.info(
                    "Retry %s/%s em %s após %ss (status %s)",
                    attempt, self._max_retries, path, sleep_s, resp.status_code,
                )
                time.sleep(sleep_s)
                continue

            resp.raise_for_status()
            return resp.json()

    def _get_paginated(self, path: str, params: Optional[dict] = None, page_size: int = 100) -> list:
        """
        Paginação genérica (page/per_page) — SÓ use isso se a documentação
        de um endpoint confirmar que ele realmente pagina. Nenhum dos
        endpoints "bulk" atuais (players/trails/performance/trails-
        performance/logs/certificates/courses) documenta page/per_page;
        use _get_single() para esses.
        """
        params = dict(params or {})
        page = 1
        results: list = []
        while True:
            params.update({"page": page, "per_page": page_size})

            try:
                data = self._get(path, params=params)
            except httpx.HTTPStatusError as exc:
                # Captura o erro 403 (Cota Excedida) e salva o progresso atual
                if exc.response.status_code == 403:
                    logger.warning(
                        "Cota excedida na API (403) na página %s de %s. "
                        "Interrompendo e retornando os %s usuários/registros já coletados.",
                        page, path, len(results)
                    )
                    break
                # Se for outro erro HTTP, continua a lançar a exceção
                raise

            items = data.get("data", data) if isinstance(data, dict) else data
            if not items:
                break
            results.extend(items)
            if len(items) < page_size:
                break
            page += 1
        return results

    def _get_single(self, path: str) -> list:
        """
        Busca um endpoint que devolve a lista INTEIRA numa chamada só —
        a documentação oficial da Ludos (/doc) não lista parâmetro de
        página pra nenhum dos endpoints "bulk" de relatório. Só os
        endpoints por curso (/report/*/course) aceitam parâmetro, e é
        filtro (code), não paginação.

        Antes, esses endpoints eram chamados com _get_paginated() — como
        a API ignora page/per_page (não documentados), ela devolvia a
        lista inteira de novo a cada "página", e o código achava que
        ainda faltava mais e pedia de novo. Resultado: a mesma resposta
        sendo buscada dezenas de vezes por sync, estourando a cota em
        repetição, não em dado novo de verdade.
        """
        try:
            data = self._get(path)
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 403:
                logger.warning("Cota excedida na API (403) em %s. Retornando lista vazia.", path)
                return []
            raise
        items = data.get("data", data) if isinstance(data, dict) else data
        return items or []

    # --- endpoints usados pelo dashboard (conferidos na doc /doc/index.html#servers) ---

    def get_players(self) -> list:
        return self._get_single("/report/players")

    def get_trails(self) -> list:
        return self._get_single("/report/trails")

    def get_courses(self) -> list:
        return self._get_single("/report/courses")

    def get_performance(self) -> list:
        return self._get_single("/report/performance")

    def get_trails_performance(self) -> list:
        return self._get_single("/report/trails-performance")

    def get_certificates(self) -> list:
        return self._get_single("/report/certificates")

    def get_login_log(self) -> list:
        """Log de acessos: [{idPlayer, dtLog, txData}, ...]. Usado pelo
        Sistema de Alertas (dias sem acessar)."""
        return self._get_single(LOGIN_LOG_PATH)

    def close(self):
        self._client.close()