"""
Gestão de usuários do dashboard — quem pode logar e com qual papel.
Todo endpoint aqui exige o papel "admin" (ver app/auth.py:require_role).
Sem tela própria no dashboard ainda; dá pra usar via /docs até existir
uma tela de administração.
"""
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth import PAPEIS_VALIDOS, hash_senha, require_role
from app.database import get_db
from app.models import User
from app.schemas import UsuarioCreateIn, UsuarioOut, UsuarioUpdateIn

router = APIRouter(
    prefix="/api/v1/usuarios", tags=["usuarios"],
    dependencies=[Depends(require_role("admin"))],
)


def _validar_papel(role: str) -> None:
    if role not in PAPEIS_VALIDOS:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            f"Papel inválido: '{role}'. Use um de: {', '.join(sorted(PAPEIS_VALIDOS))}.",
        )


@router.get("", response_model=list[UsuarioOut])
def listar_usuarios(db: Session = Depends(get_db)):
    return db.execute(select(User).order_by(User.created_at)).scalars().all()


@router.post("", response_model=UsuarioOut, status_code=status.HTTP_201_CREATED)
def criar_usuario(dados: UsuarioCreateIn, db: Session = Depends(get_db)):
    _validar_papel(dados.role)
    email = dados.email.lower()
    if db.execute(select(User).where(User.email == email)).scalar_one_or_none():
        raise HTTPException(status.HTTP_409_CONFLICT, "Já existe um usuário com esse e-mail.")

    usuario = User(
        email=email, password_hash=hash_senha(dados.senha),
        name=dados.name, role=dados.role,
    )
    db.add(usuario)
    db.commit()
    db.refresh(usuario)
    return usuario


@router.patch("/{usuario_id}", response_model=UsuarioOut)
def atualizar_usuario(usuario_id: int, dados: UsuarioUpdateIn, db: Session = Depends(get_db)):
    usuario = db.get(User, usuario_id)
    if usuario is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Usuário não encontrado.")

    if dados.role is not None:
        _validar_papel(dados.role)
        usuario.role = dados.role
    if dados.name is not None:
        usuario.name = dados.name
    if dados.is_active is not None:
        usuario.is_active = dados.is_active

    db.commit()
    db.refresh(usuario)
    return usuario


@router.delete("/{usuario_id}", status_code=status.HTTP_204_NO_CONTENT)
def remover_usuario(usuario_id: int, db: Session = Depends(get_db)):
    usuario = db.get(User, usuario_id)
    if usuario is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Usuário não encontrado.")
    db.delete(usuario)
    db.commit()
