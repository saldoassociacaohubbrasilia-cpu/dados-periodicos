from pydantic import BaseModel


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
