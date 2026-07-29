"""
Roda UMA VEZ depois de atualizar app/models.py (novas colunas
`institution` e `pontuacao_media` em MetricSnapshot).

Por que precisa disso: Base.metadata.create_all() só cria tabelas que
não existem — ele não adiciona colunas novas em tabelas já existentes.
Como metric_snapshot é 100% derivada (sempre recalculada do zero em
rebuild_metrics a cada sincronização), é seguro apagar só ela e deixar
o create_all recriar com o schema novo. Nenhum dado bruto (RawLudosSnapshot)
é perdido.

Uso:
    python scripts/reset_metric_snapshot.py
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.database import Base, engine  # noqa: E402
from app.models import MetricSnapshot  # noqa: E402,F401


def main():
    MetricSnapshot.__table__.drop(bind=engine, checkfirst=True)
    Base.metadata.create_all(bind=engine)
    print("Tabela metric_snapshot recriada com as colunas novas (institution, pontuacao_media).")
    print("Rode POST /api/v1/sync/run (ou espere o próximo ciclo do scheduler) para repopular.")


if __name__ == "__main__":
    main()