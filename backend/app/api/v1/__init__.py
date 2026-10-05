from fastapi import APIRouter
from backend.app.api.v1.auth import router as auth_router
from backend.app.api.v1.users import router as users_router
from backend.app.api.v1.generator import router as generator_router
from backend.app.api.v1.fuel import router as fuel_router
from backend.app.api.v1.maintenance import router as maintenance_router
from backend.app.api.v1.faults import router as faults_router
from backend.app.api.v1.audit import router as audit_router
from backend.app.api.v1.adjustments import router as adjustments_router
from backend.app.api.v1.reports import router as reports_router
from backend.app.api.v1.facilities import router as facilities_router

api_v1_router = APIRouter(prefix="/api/v1")
api_v1_router.include_router(auth_router)
api_v1_router.include_router(users_router)
api_v1_router.include_router(generator_router)
api_v1_router.include_router(fuel_router)
api_v1_router.include_router(maintenance_router)
api_v1_router.include_router(faults_router)
api_v1_router.include_router(audit_router)
api_v1_router.include_router(adjustments_router)
api_v1_router.include_router(reports_router)
api_v1_router.include_router(facilities_router)

__all__ = ["api_v1_router"]
