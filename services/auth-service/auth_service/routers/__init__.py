"""Auth Service Routers package."""
from auth_service.routers.auth import router as auth_router
from auth_service.routers.users import router as users_router
from auth_service.routers.tokens import router as tokens_router
from auth_service.routers.tokens import _internal_router as internal_router
from auth_service.routers.admin import router as admin_router
from auth_service.routers.oidc import router as oidc_router

__all__ = ["auth_router", "users_router", "tokens_router", "internal_router", "admin_router", "oidc_router"]
