"""Pydantic schemas for Skills Registry API."""

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field, field_validator


# ── Skill Metadata ──────────────────────────────────────────────────────────


class SkillMetadata(BaseModel):
    """Parsed metadata from SKILL.md YAML frontmatter."""

    name: str
    description: str = ""
    version: str = "1.0.0"
    author: str = ""
    license: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict)

    # Additional fields persisted in DB
    tags: list[str] = Field(default_factory=list)
    related_skills: list[str] = Field(default_factory=list)

    @field_validator("version", mode="before")
    @classmethod
    def coerce_version(cls, v: Any) -> str:
        if isinstance(v, (int, float)):
            return str(int(v))
        return str(v)


class SkillSummary(BaseModel):
    """Summary view for GET /skills listing."""

    name: str
    description: str
    version: str
    status: str
    tags: list[str] = Field(default_factory=list)
    author: str = ""
    update_time: datetime


class SkillDetail(BaseModel):
    """Full detail view for GET /skills/{name}."""

    id: str
    name: str
    description: str
    version: str
    status: str
    nas_path: str
    published_by: str | None
    tags: list[str] = Field(default_factory=list)
    related_skills: list[str] = Field(default_factory=list)
    author: str = ""
    license: str = ""
    create_time: datetime
    update_time: datetime


class SkillContent(BaseModel):
    """SKILL.md content for GET /skills/{name}/content."""

    name: str
    version: str
    nas_path: str
    content: str  # Raw markdown body (without YAML frontmatter)


# ── Admin: Create / Update ─────────────────────────────────────────────────


class SkillCreateRequest(BaseModel):
    """Body for POST /admin/skills."""

    name: str = Field(..., min_length=1, max_length=64, pattern=r"^[a-zA-Z0-9_-]+$")
    description: str = Field(default="", max_length=1024)
    skill_md: str = Field(..., description="Full SKILL.md content including YAML frontmatter")
    tags: list[str] = Field(default_factory=list)
    published_by: str | None = None


class SkillUpdateRequest(BaseModel):
    """Body for PUT /admin/skills/{name}."""

    description: str | None = Field(default=None, max_length=1024)
    skill_md: str | None = None
    tags: list[str] | None = None
    status: str | None = Field(default=None, pattern=r"^(active|archived)$")


class SkillResponse(BaseModel):
    """Response after create/update."""

    success: bool
    skill: SkillDetail
    message: str


# ── Internal ────────────────────────────────────────────────────────────────


class SkillUpdateNotification(BaseModel):
    """Payload published to Redis when a skill is updated."""

    skill_name: str
    version: str
    action: str = Field(..., pattern=r"^(created|updated|archived)$")


class InternalReloadResponse(BaseModel):
    """Response from /internal/skills/reload (consumed by Router)."""

    pod_id: str
    skill_name: str
    reloaded: bool
    version: str
    error: str | None = None


# ── Health ─────────────────────────────────────────────────────────────────


class HealthResponse(BaseModel):
    db_ok: bool
    storage_ok: bool
    redis_ok: bool
    version: str = "0.1.0"
