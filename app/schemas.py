from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, EmailStr


class LoginIn(BaseModel):
    email: EmailStr
    senha: str


class UsuarioOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    email: str
    name: Optional[str] = None
    role: str
    is_active: bool
    created_at: datetime
    last_login: Optional[datetime] = None


class LoginOut(BaseModel):
    access_token: str
    token_type: str = "bearer"
    usuario: UsuarioOut


class UsuarioCreateIn(BaseModel):
    email: EmailStr
    senha: str
    name: Optional[str] = None
    role: str = "usuario"


class UsuarioUpdateIn(BaseModel):
    name: Optional[str] = None
    role: Optional[str] = None
    is_active: Optional[bool] = None


class OverviewOut(BaseModel):
    inscritos: int
    engajados: int
    concluintes: int
    taxa_ativacao: float
    taxa_conclusao: float
    taxa_retencao: float
    atualizado_em: str


class TrailShareOut(BaseModel):
    trilha: str
    total_alunos: int
    percentual: float


class SchoolRankingOut(BaseModel):
    escola: str
    inscritos: int
    taxa_ativacao: float
