from fastapi import APIRouter, Depends
from sqlmodel import Session, select

from app.api.deps import get_db
from app.models.scheduling import Role
from app.schemas.scheduling import RoleRead

router = APIRouter()


@router.get("/roles", response_model=list[RoleRead])
def list_roles(session: Session = Depends(get_db)) -> list[RoleRead]:
    return session.exec(select(Role).order_by(Role.name)).all()
