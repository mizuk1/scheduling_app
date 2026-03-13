from fastapi import APIRouter, Depends
from sqlmodel import Session, select

from app.api.deps import get_db
from app.models.scheduling import Availability
from app.schemas.scheduling import AvailabilityRead

router = APIRouter()


@router.get("/availabilities", response_model=list[AvailabilityRead])
def list_availabilities(session: Session = Depends(get_db)) -> list[AvailabilityRead]:
    return session.exec(select(Availability)).all()
