from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    database_url: str
    ludos_api_base_url: str = "https://api.ludos.pro/api3"
    ludos_api_key: str

    sync_interval_hours: float = 6.0
    ludos_min_request_interval_seconds: float = 1.5
    ludos_max_retries: int = 3

    frontend_origin: str = "*"

    # Cada sync grava um lote novo de MetricSnapshot (geral + módulo +
    # escola/turma, x instituição, x trilha) e nada nunca apagava os
    # antigos — a tabela crescia sem limite. Só o snapshot_date mais
    # recente por trilha é lido pelo dashboard hoje; guardamos essa
    # janela (padrão 90 dias) pra sobrar espaço pra uma futura feature
    # de tendência histórica sem deixar a tabela crescer pra sempre.
    metric_snapshot_retention_days: int = 90

    # Login/autenticação. Sem default de propósito: sem essa variável
    # configurada (Render → Environment), a aplicação nem sobe — mais
    # seguro do que rodar com uma chave previsível.
    jwt_secret_key: str
    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = 60 * 24 * 7  # 7 dias — sessão persistente

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")


settings = Settings()
