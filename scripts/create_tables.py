# DEPRECADO: schema agora é gerenciado pelo Alembic (ver alembic/versions/
# e README). Pra criar as tabelas num banco novo, rode `alembic upgrade
# head` em vez deste script — create_all() só cria tabela que não existe,
# nunca aplica uma migração incremental numa tabela já existente.

from app.database import engine
from app.models import Base

def criar_tabelas():
    print("Iniciando a conexão com o Supabase...")
    # O comando abaixo pega todas as classes do models.py e cria as tabelas no PostgreSQL
    Base.metadata.create_all(bind=engine)
    print("Tabelas criadas com sucesso! 🎉")

if __name__ == "__main__":
    criar_tabelas()