from fastapi import APIRouter, Depends
from sqlmodel import Session, select

from app.api.deps import get_db
from app.models.scheduling import ScheduleRule
from app.schemas.scheduling import ScheduleRuleRead

router = APIRouter()


@router.get("/schedule-rules", response_model=list[ScheduleRuleRead])
def list_rules(session: Session = Depends(get_db)) -> list[ScheduleRuleRead]:
    return session.exec(select(ScheduleRule)).all()
