"""Admin endpoints — CRUD for Skills management."""

from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import settings
from ..database import get_db
from ..file_storage import get_storage
from ..models import OrgSkill
from ..redis_publisher import publish_skill_update
from ..schemas import (
    SkillCreateRequest,
    SkillDetail,
    SkillResponse,
    SkillSummary,
    SkillUpdateRequest,
)
from ..skill_parser import deserialize_tags, parse_skill_md, serialize_tags

router = APIRouter(prefix="/admin", tags=["Admin"])


async def _verify_admin_key(x_admin_key: Annotated[str | None, Header()] = None) -> None:
    """Simple API-key check for admin endpoints (Phase 1 placeholder)."""
    if x_admin_key != settings.admin_api_key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing X-Admin-Key header",
        )


def _row_to_summary(row: OrgSkill) -> SkillSummary:
    return SkillSummary(
        name=row.name,
        description=row.description,
        version=str(row.version),
        status=row.status,
        tags=deserialize_tags(row.tags),
        author="",
        update_time=row.update_time,
    )


def _row_to_detail(row: OrgSkill) -> SkillDetail:
    return SkillDetail(
        id=str(row.id),
        name=row.name,
        description=row.description,
        version=str(row.version),
        status=row.status,
        nas_path=row.nas_path,
        published_by=str(row.published_by) if row.published_by else None,
        tags=deserialize_tags(row.tags),
        related_skills=[],
        author="",
        license="",
        create_time=row.create_time,
        update_time=row.update_time,
    )




@router.get(
    "/skills",
    response_model=list[SkillSummary],
    summary="Admin: List all Skills (including archived)",
)
async def admin_list_skills(
    db: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[None, Depends(_verify_admin_key)],
) -> list[SkillSummary]:
    """List all skills (including archived) for admin view."""
    result = await db.execute(
        select(OrgSkill).order_by(OrgSkill.update_time.desc())
    )
    rows = result.scalars().all()
    return [_row_to_summary(row) for row in rows]


@router.post(
    "/skills",
    response_model=SkillResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Admin: Create a new Skill",
)
async def create_skill(
    req: SkillCreateRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[None, Depends(_verify_admin_key)],
) -> SkillResponse:
    """Create a new org-level skill.

    1. Parse SKILL.md frontmatter for metadata validation.
    2. Write SKILL.md to NAS / local filesystem.
    3. Insert metadata into PostgreSQL.
    4. Publish Redis notification for hot-update.
    """
    # Step 1: Parse and validate SKILL.md
    try:
        parsed = parse_skill_md(req.skill_md)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Invalid SKILL.md format: {e}",
        )

    # Use provided name or parsed name
    skill_name = req.name or parsed.name

    # Step 2: Check if already exists
    result = await db.execute(select(OrgSkill).where(OrgSkill.name == skill_name))
    if result.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Skill '{skill_name}' already exists",
        )

    # Step 3: Write file to storage
    storage = get_storage()
    storage.write_skill(skill_name, req.skill_md)
    nas_path = str(storage.skill_md_path(skill_name))

    # Step 4: Persist metadata
    tags_str = serialize_tags(req.tags or parsed.tags)
    skill = OrgSkill(
        name=skill_name,
        description=req.description or parsed.description,
        version=1,
        status="active",
        nas_path=nas_path,
        published_by=req.published_by,
        tags=tags_str,
    )
    db.add(skill)
    await db.commit()
    await db.refresh(skill)

    # Step 5: Publish hot-update notification
    await publish_skill_update(skill_name, str(skill.version), action="created")

    return SkillResponse(
        success=True,
        skill=_row_to_detail(skill),
        message=f"Skill '{skill_name}' created successfully",
    )


@router.put(
    "/skills/{skill_name}",
    response_model=SkillResponse,
    summary="Admin: Update an existing Skill",
)
async def update_skill(
    skill_name: str,
    req: SkillUpdateRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[None, Depends(_verify_admin_key)],
) -> SkillResponse:
    """Update an existing skill.

    - If skill_md is updated: rewrite file, bump version, publish notification.
    - If only description/tags/status: update DB only.
    """
    result = await db.execute(select(OrgSkill).where(OrgSkill.name == skill_name))
    skill = result.scalar_one_or_none()

    if not skill:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Skill '{skill_name}' not found",
        )

    version_bumped = False

    # Update SKILL.md file if provided
    if req.skill_md is not None:
        try:
            parsed = parse_skill_md(req.skill_md)
        except ValueError as e:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"Invalid SKILL.md format: {e}",
            )

        storage = get_storage()
        storage.write_skill(skill_name, req.skill_md)

        # Bump version
        skill.version = skill.version + 1
        version_bumped = True

        if req.description is None:
            skill.description = parsed.description

    if req.description is not None:
        skill.description = req.description

    if req.tags is not None:
        skill.tags = serialize_tags(req.tags)

    if req.status is not None:
        skill.status = req.status

    await db.commit()
    await db.refresh(skill)

    # Publish hot-update notification if active
    if skill.status == "active" or version_bumped:
        await publish_skill_update(skill_name, str(skill.version), action="updated")

    return SkillResponse(
        success=True,
        skill=_row_to_detail(skill),
        message=f"Skill '{skill_name}' updated to version {skill.version}",
    )


@router.delete(
    "/skills/{skill_name}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Admin: Archive a Skill",
)
async def archive_skill(
    skill_name: str,
    db: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[None, Depends(_verify_admin_key)],
) -> None:
    """Archive a skill (soft delete).

    Does NOT delete files from NAS — archived skills can be restored.
    Publishes notification so Router stops routing to this skill.
    """
    result = await db.execute(select(OrgSkill).where(OrgSkill.name == skill_name))
    skill = result.scalar_one_or_none()

    if not skill:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Skill '{skill_name}' not found",
        )

    skill.status = "archived"
    await db.commit()

    await publish_skill_update(skill_name, str(skill.version), action="archived")
