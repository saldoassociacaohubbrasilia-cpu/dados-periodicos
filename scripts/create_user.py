"""
Cria (ou promove) um usuário do dashboard direto no banco — usado pra
criar o primeiro usuário admin, já que ainda não existe tela de
administração (a API /api/v1/usuarios existe, mas exige um admin
logado pra usar... e o primeiro admin precisa vir de algum lugar).

A senha é pedida na hora, escondida (getpass) — nunca fica no
histórico do terminal nem em log nenhum.

Uso:
    python scripts/create_user.py
    python scripts/create_user.py --email voce@exemplo.com --role admin
"""
import argparse
import getpass
import os
import re
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from sqlalchemy import select  # noqa: E402

from app.auth import PAPEIS_VALIDOS, hash_senha  # noqa: E402
from app.database import SessionLocal  # noqa: E402
from app.models import User  # noqa: E402

EMAIL_REGEX = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--email")
    parser.add_argument("--name")
    parser.add_argument("--role", choices=sorted(PAPEIS_VALIDOS), default="admin")
    args = parser.parse_args()

    email = (args.email or input("E-mail: ")).strip().lower()
    if not EMAIL_REGEX.match(email):
        sys.exit(f"'{email}' não parece um e-mail válido.")

    name = args.name if args.name is not None else input("Nome (opcional): ").strip() or None

    senha = getpass.getpass("Senha: ")
    if len(senha) < 8:
        sys.exit("A senha precisa ter pelo menos 8 caracteres.")
    if senha != getpass.getpass("Confirme a senha: "):
        sys.exit("As senhas não bateram.")

    db = SessionLocal()
    try:
        existente = db.execute(select(User).where(User.email == email)).scalar_one_or_none()
        if existente is not None:
            existente.password_hash = hash_senha(senha)
            existente.role = args.role
            existente.name = name or existente.name
            existente.is_active = True
            db.commit()
            print(f"Usuário '{email}' já existia — senha/papel atualizados (role={args.role}).")
            return

        usuario = User(email=email, password_hash=hash_senha(senha), name=name, role=args.role)
        db.add(usuario)
        db.commit()
        print(f"Usuário '{email}' criado com papel '{args.role}'.")
    finally:
        db.close()


if __name__ == "__main__":
    main()
