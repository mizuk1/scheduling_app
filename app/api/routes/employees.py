from fastapi import APIRouter, Depends
from sqlmodel import Session, select

from app.api.deps import get_db
from app.models.scheduling import Employee
from app.schemas.scheduling import EmployeeRead

router = APIRouter()


@router.get("/employees", response_model=list[EmployeeRead])
def list_employees(session: Session = Depends(get_db)) -> list[EmployeeRead]:
    return session.exec(select(Employee).order_by(Employee.name)).all()
