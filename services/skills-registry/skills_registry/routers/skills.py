"""Public Skills endpoints — GET /skills, GET /skills/{name}."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import get_db
from ..file_storage import FileStorage, get_storage
from ..models import OrgSkill
from ..schemas import SkillContent, SkillDetail, SkillSummary
from ..skill_parser import deserialize_tags, parse_skill_md

router = APIRouter(tags=["Skills"])


def _skill_model_to_detail(row: OrgSkill) -> SkillDetail:
    """Convert SQLAlchemy model to SkillDetail schema."""
    tags = deserialize_tags(row.tags)
    # Parse SKILL.md for additional metadata
    parsed = None
    try:
        storage = get_storage()
        raw = storage.read_skill_md(row.name)
        parsed = parse_skill_md(raw)
    except Exception:
        pass

    return SkillDetail(
        id=str(row.id),
        name=row.name,
        description=row.description,
        version=str(row.version),
        status=row.status,
        nas_path=row.nas_path,
        published_by=str(row.published_by) if row.published_by else None,
        tags=tags or (parsed.tags if parsed else []),
        related_skills=parsed.related_skills if parsed else [],
        author=parsed.author if parsed else "",
        license=parsed.license if parsed else "",
        create_time=row.create_time,
        update_time=row.update_time,
    )


def _skill_model_to_summary(row: OrgSkill) -> SkillSummary:
    """Convert SQLAlchemy model to SkillSummary schema."""
    tags = deserialize_tags(row.tags)
    return SkillSummary(
        name=row.name,
        description=row.description,
        version=str(row.version),
        status=row.status,
        tags=tags,
        author="",
        update_time=row.update_time,
    )


@router.get(
    "/skills",
    response_model=list[SkillSummary],
    summary="List all active Skills",
    description="Returns a paginated list of all active org-level skills.",
)
async def list_skills(
    db: Annotated[AsyncSession, Depends(get_db)],
    status_filter: Annotated[str | None, Query(alias="status")] = "active",
    tags_filter: Annotated[str | None, Query(description="Comma-separated tags")] = None,
    search: Annotated[str | None, Query(max_length=128)] = None,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
) -> list[SkillSummary]:
    """List skills with optional filtering."""
    query = select(OrgSkill)
    if status_filter:
        query = query.where(OrgSkill.status == status_filter)
    if search:
        pattern = f"%{search}%"
        query = query.where(
            (OrgSkill.name.ilike(pattern)) | (OrgSkill.description.ilike(pattern))
        )

    query = query.order_by(OrgSkill.update_time.desc())
    query = query.offset((page - 1) * page_size).limit(page_size)

    result = await db.execute(query)
    rows = result.scalars().all()

    summaries = [_skill_model_to_summary(row) for row in rows]

    # Tag filtering (applied in Python since tags is a serialized Text column)
    if tags_filter:
        filter_tags = {t.strip() for t in tags_filter.split(",")}
        summaries = [
            s for s in summaries if filter_tags & set(s.tags)  # intersection
        ]

    return summaries


@router.get(
    "/skills/{skill_name}",
    response_model=SkillDetail,
    summary="Get Skill details",
    description="Returns full metadata for a specific skill.",
)
async def get_skill(
    skill_name: str,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> SkillDetail:
    """Get full details for a specific skill."""
    result = await db.execute(
        select(OrgSkill).where(OrgSkill.name == skill_name)
    )
    row = result.scalar_one_or_none()

    if not row:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Skill '{skill_name}' not found",
        )

    if row.status == "archived":
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Skill '{skill_name}' is archived",
        )

    return _skill_model_to_detail(row)


@router.get(
    "/skills/{skill_name}/content",
    response_model=SkillContent,
    summary="Get Skill SKILL.md content",
    description="Returns the raw SKILL.md markdown content (body only, no frontmatter).",
)
async def get_skill_content(
    skill_name: str,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> SkillContent:
    """Get the markdown body of a SKILL.md file."""
    result = await db.execute(
        select(OrgSkill).where(OrgSkill.name == skill_name)
    )
    row = result.scalar_one_or_none()

    if not row:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Skill '{skill_name}' not found",
        )

    storage = get_storage()
    if not storage.skill_exists(skill_name):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"SKILL.md file for '{skill_name}' not found on storage",
        )

    raw = storage.read_skill_md(skill_name)
    parsed = parse_skill_md(raw)

    return SkillContent(
        name=skill_name,
        version=parsed.version,
        nas_path=row.nas_path,
        content=parsed.body,
    )
