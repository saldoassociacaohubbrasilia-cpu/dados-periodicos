"""
Autenticação e controle de acesso ao dashboard — não tem relação com a
sincronização de dados da Ludos, é só sobre quem pode logar e ver os
dados já processados.

Frontend é 100% estático (GitHub Pages) chamando a API via fetch
cross-origin, então não dá pra usar sessão de servidor com cookie do
jeito comum. A solução é token JWT: o backend assina, o navegador guarda
no localStorage e manda em "Authorization: Bearer <token>" a cada
chamada — é isso que _get_current_user confere abaixo.
"""
import datetime as dt

import bcrypt
import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.models import User

# Papéis válidos hoje — "usuario" é o padrão de quem loga sem ninguém
# escolher nada. Adicionar um papel novo é só incluir aqui, sem migration
# (role é string livre no banco, ver app/models.py:User).
PAPEIS_VALIDOS = {"admin", "gestor", "usuario"}

_bearer_scheme = HTTPBearer(auto_error=False)


def hash_senha(senha_pura: str) -> str:
    return bcrypt.hashpw(senha_pura.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def conferir_senha(senha_pura: str, password_hash: str) -> bool:
    return bcrypt.checkpw(senha_pura.encode("utf-8"), password_hash.encode("utf-8"))


def criar_token(usuario: User) -> str:
    agora = dt.datetime.now(dt.timezone.utc)
    payload = {
        "sub": str(usuario.id),
        "email": usuario.email,
        "role": usuario.role,
        "iat": agora,
        "exp": agora + dt.timedelta(minutes=settings.jwt_expire_minutes),
    }
    return jwt.encode(payload, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)


def _decodificar_token(token: str) -> dict:
    try:
        return jwt.decode(token, settings.jwt_secret_key, algorithms=[settings.jwt_algorithm])
    except jwt.ExpiredSignatureError:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Sessão expirada, faça login de novo.")
    except jwt.InvalidTokenError:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Token inválido.")


def get_current_user(
    credenciais: HTTPAuthorizationCredentials | None = Depends(_bearer_scheme),
    db: Session = Depends(get_db),
) -> User:
    """Dependência de rota: exige um Bearer token válido, de um usuário
    que ainda existe e está ativo. Use em qualquer endpoint que só deve
    responder pra quem está logado — é a proteção de verdade (o
    frontend também bloqueia a tela, mas quem garante é a API)."""
    if credenciais is None:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED, "Não autenticado.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    payload = _decodificar_token(credenciais.credentials)
    usuario = db.execute(select(User).where(User.id == int(payload["sub"]))).scalar_one_or_none()
    if usuario is None or not usuario.is_active:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Usuário inválido ou desativado.")
    return usuario


def require_role(*papeis: str):
    """Fábrica de dependência: só deixa passar quem tem um dos papéis
    listados. Ex: Depends(require_role("admin")) — usada hoje em
    /sync/run (admin ou gestor) e em toda a gestão de usuários (só admin)."""
    def _checar(usuario: User = Depends(get_current_user)) -> User:
        if usuario.role not in papeis:
            raise HTTPException(
                status.HTTP_403_FORBIDDEN,
                f"Essa ação exige um dos papéis: {', '.join(papeis)}.",
            )
        return usuario
    return _checar
