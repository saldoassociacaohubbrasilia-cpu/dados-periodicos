from app.database import engine
from app.models import Base

def criar_tabelas():
    print("Iniciando a conexão com o Supabase...")
    # O comando abaixo pega todas as classes do models.py e cria as tabelas no PostgreSQL
    Base.metadata.create_all(bind=engine)
    print("Tabelas criadas com sucesso! 🎉")

if __name__ == "__main__":
    criar_tabelas()