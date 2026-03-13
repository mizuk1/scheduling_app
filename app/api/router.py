from fastapi import APIRouter

from app.api.routes import availability, chat, employees, health, roles, rules, schedules

api_router = APIRouter()
api_router.include_router(health.router, tags=["health"])
api_router.include_router(employees.router, tags=["employees"])
api_router.include_router(roles.router, tags=["roles"])
api_router.include_router(availability.router, tags=["availability"])
api_router.include_router(rules.router, tags=["rules"])
api_router.include_router(schedules.router, tags=["schedules"])
api_router.include_router(chat.router, tags=["chat"])
