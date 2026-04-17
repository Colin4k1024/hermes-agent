"""Internal endpoints for Router → Pod hot-update signaling."""

from typing import Annotated

from fastapi import APIRouter, Depends, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import settings
from ..database import get_db
from ..models import OrgSkill
from ..redis_publisher import publish_skill_update, redis_health_check
from ..schemas import InternalReloadResponse, SkillUpdateNotification

router = APIRouter(prefix="/internal", tags=["Internal"])


# ── Internal endpoints ───────────────────────────────────────────────────────


@router.post(
    "/skills/notify-update",
    summary="Internal: Trigger hot-update notification",
    description=(
        "Called by Admin Console or other services to trigger a Redis PubSub "
        "notification. Router subscribes and initiates batch Pod restarts "
        "(batch_size=20, interval=5s)."
    ),
)
async def notify_skill_update(
    body: SkillUpdateNotification,
) -> dict:
    """Manually trigger a skill-update notification (internal use)."""
    published = await publish_skill_update(
        body.skill_name,
        body.version,
        body.action,
    )
    return {
        "published": published,
        "channel": settings.skill_update_channel,
        "skill_name": body.skill_name,
    }


@router.get(
    "/skills/reload",
    response_model=list[InternalReloadResponse],
    summary=(
        "Internal: Reload skills on this Pod (called by Router during hot-update)"
    ),
    description=(
        "Router calls this endpoint on all active Pods after receiving "
        "a skill-update notification. Each Pod re-scans the org-skills directory.\n\n"
        "Note: In the Skills Registry service, this endpoint returns the current "
        "skill state. The actual Pod-level reload is performed by the Hermes "
        "Pod Sidecar which reads the notification and triggers "
        "entrypoint.sh re-initialization."
    ),
)
async def reload_skills(
    skill_name: str | None = None,
    db: Annotated[AsyncSession, Depends(get_db)] = None,
) -> list[InternalReloadResponse]:
    """Endpoint called by Router to report skill reload status on a Pod.

    The Skills Registry service itself doesn't host Hermes skills at runtime —
    it manages the SKILL.md files on NAS. This endpoint provides metadata
    about which skills would be reloaded.
    """
    responses: list[InternalReloadResponse] = []

    query = select(OrgSkill).where(OrgSkill.status == "active")
    if skill_name:
        query = query.where(OrgSkill.name == skill_name)

    result = await db.execute(query)
    rows = result.scalars().all()

    for row in rows:
        responses.append(
            InternalReloadResponse(
                pod_id="skills-registry",
                skill_name=row.name,
                reloaded=True,
                version=str(row.version),
                error=None,
            )
        )

    return responses


@router.get(
    "/health",
    summary="Internal: Lightweight health check",
)
async def internal_health() -> dict:
    """Lightweight health check (no DB/Redis to stay fast)."""
    return {"ok": True, "service": "skills-registry"}
