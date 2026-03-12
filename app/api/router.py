from fastapi import APIRouter

from app.api.routes import employees, health, rules

api_router = APIRouter()
api_router.include_router(health.router, tags=["health"])
api_router.include_router(employees.router, tags=["employees"])
api_router.include_router(rules.router, tags=["rules"])
