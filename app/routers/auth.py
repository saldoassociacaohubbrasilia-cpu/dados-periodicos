from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth import conferir_senha, criar_token, get_current_user
from app.database import get_db
from app.models import User
from app.schemas import LoginIn, LoginOut, UsuarioOut

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])


@router.post("/login", response_model=LoginOut)
def login(dados: LoginIn, db: Session = Depends(get_db)):
    usuario = db.execute(select(User).where(User.email == dados.email.lower())).scalar_one_or_none()
    # Mesma mensagem genérica pra e-mail inexistente e senha errada —
    # não dar pista de qual dos dois está errado pra quem está tentando
    # adivinhar.
    if usuario is None or not usuario.is_active or not conferir_senha(dados.senha, usuario.password_hash):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "E-mail ou senha inválidos.")

    usuario.last_login = datetime.now(timezone.utc)
    db.commit()
    db.refresh(usuario)

    return LoginOut(access_token=criar_token(usuario), usuario=usuario)


@router.get("/me", response_model=UsuarioOut)
def me(usuario_atual: User = Depends(get_current_user)):
    return usuario_atual
