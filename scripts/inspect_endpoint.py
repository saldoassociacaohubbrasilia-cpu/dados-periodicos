"""
Uso:
    python scripts/inspect_endpoint.py /report/players --limit 2

Busca uma amostra pequena de um endpoint da Ludos e imprime o JSON
formatado, para você conferir os nomes reais dos campos antes de
ajustar app/ingestion/transform.py.
"""
import argparse
import json
import os
import sys

import httpx

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.ludos_client import LudosClient  # noqa: E402


def main():
    parser = argparse.ArgumentParser(description="Inspeciona a resposta crua de um endpoint da Ludos Pro.")
    parser.add_argument("endpoint", help="Ex: /report/players")
    parser.add_argument("--limit", type=int, default=2, help="Quantos registros pedir (per_page)")
    args = parser.parse_args()

    client = LudosClient()
    try:
        data = client._get(args.endpoint, params={"page": 1, "per_page": args.limit})
        print(json.dumps(data, indent=2, ensure_ascii=False))
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code == 403:
            print(f"Cota da API excedida (403) em {args.endpoint}. Espera a cota resetar e tenta de novo.")
        else:
            print(f"Erro {exc.response.status_code} em {args.endpoint}: {exc.response.text[:300]}")
    finally:
        client.close()


if __name__ == "__main__":
    main()
