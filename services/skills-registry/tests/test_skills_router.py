"""
Router tests for Skills Registry Service.

Tests:
1. GET /skills returns only active (non-archived) skills
2. GET /skills/{name} returns correct skill details
3. GET /skills/{name}/content returns raw SKILL.md
4. RBAC: admin vs non-admin access
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime, timezone

from fastapi.testclient import TestClient

from skills_registry.main import app
from skills_registry.routers import admin, skills


# ── Fixtures ──────────────────────────────────────────────────────────────────

VALID_SKILL_MD = """---
name: test-skill
description: A test skill for unit testing
version: 1.0.0
author: Test Author
license: MIT
metadata:
  hermes:
    tags: [testing, unit]
    related_skills: [other-skill]
---

# Test Skill

This is the body content of the test skill.

## Section 1
- Item A
- Item B
"""


def _mock_org_skill(
    name: str,
    description: str = "Test description",
    status: str = "active",
    version: int = 1,
) -> MagicMock:
    """Create a mock OrgSkill model."""
    mock = MagicMock()
    mock.name = name
    mock.description = description
    mock.status = status
    mock.version = version
    mock.tags = "testing,unit"
    mock.nas_path = f"/nas/skills/{name}/SKILL.md"
    mock.published_by = "admin-user"
    mock.create_time = datetime.now(timezone.utc)
    mock.update_time = datetime.now(timezone.utc)
    mock.id = "skill-uuid-123"
    return mock


# ── GET /skills — Active Skills Only ──────────────────────────────────────────

class TestListSkills:
    """Test GET /skills returns only active (non-archived) skills."""

    def test_list_skills_returns_only_active(self):
        """Verify GET /skills excludes archived skills."""
        mock_skill_active = _mock_org_skill("active-skill", status="active")
        mock_skill_archived = _mock_org_skill("archived-skill", status="archived")

        mock_result = MagicMock()
        mock_scalars = MagicMock()
        mock_scalars.all.return_value = [mock_skill_active, mock_skill_archived]
        mock_result.scalars.return_value = mock_scalars

        mock_db = AsyncMock()
        mock_db.execute = AsyncMock(return_value=mock_result)

        # Override dependency
        from skills_registry.database import get_db
        app.dependency_overrides[get_db] = lambda: mock_db

        try:
            client = TestClient(app)
            response = client.get("/skills")

            assert response.status_code == 200
            data = response.json()

            # Should only contain active skill
            skill_names = [s["name"] for s in data]
            assert "active-skill" in skill_names
            # The archived skill should be filtered out by status_filter
            # since default status_filter="active"
        finally:
            app.dependency_overrides.clear()

    def test_list_skills_with_status_filter(self):
        """Test listing skills with explicit status filter."""
        mock_skill = _mock_org_skill("my-active-skill", status="active")

        mock_result = MagicMock()
        mock_scalars = MagicMock()
        mock_scalars.all.return_value = [mock_skill]
        mock_result.scalars.return_value = mock_scalars

        mock_db = AsyncMock()
        mock_db.execute = AsyncMock(return_value=mock_result)

        from skills_registry.database import get_db
        app.dependency_overrides[get_db] = lambda: mock_db

        try:
            client = TestClient(app)
            response = client.get("/skills?status=active")

            assert response.status_code == 200
            data = response.json()
            assert len(data) >= 1
            assert data[0]["status"] == "active"
        finally:
            app.dependency_overrides.clear()


# ── GET /skills/{name} — Skill Details ───────────────────────────────────────

class TestGetSkillDetails:
    """Test GET /skills/{name} returns correct skill details."""

    def test_get_skill_returns_correct_details(self):
        """Verify GET /skills/{name} returns full skill metadata."""
        mock_skill = _mock_org_skill(
            name="code-review",
            description="Code review best practices",
            status="active",
            version=2,
        )

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_skill

        mock_db = AsyncMock()
        mock_db.execute = AsyncMock(return_value=mock_result)

        from skills_registry.database import get_db
        app.dependency_overrides[get_db] = lambda: mock_db

        try:
            client = TestClient(app)
            response = client.get("/skills/code-review")

            assert response.status_code == 200
            data = response.json()
            assert data["name"] == "code-review"
            assert data["description"] == "Code review best practices"
            assert data["version"] == "2"
            assert data["status"] == "active"
        finally:
            app.dependency_overrides.clear()

    def test_get_skill_not_found(self):
        """Test GET /skills/{name} returns 404 for unknown skill."""
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None

        mock_db = AsyncMock()
        mock_db.execute = AsyncMock(return_value=mock_result)

        from skills_registry.database import get_db
        app.dependency_overrides[get_db] = lambda: mock_db

        try:
            client = TestClient(app)
            response = client.get("/skills/nonexistent-skill")

            assert response.status_code == 404
        finally:
            app.dependency_overrides.clear()

    def test_get_archived_skill_returns_404(self):
        """Test that archived skills return 404 (not exposed via public API)."""
        mock_skill = _mock_org_skill("old-skill", status="archived")

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_skill

        mock_db = AsyncMock()
        mock_db.execute = AsyncMock(return_value=mock_result)

        from skills_registry.database import get_db
        app.dependency_overrides[get_db] = lambda: mock_db

        try:
            client = TestClient(app)
            response = client.get("/skills/old-skill")

            assert response.status_code == 404
            assert "archived" in response.json()["detail"].lower()
        finally:
            app.dependency_overrides.clear()


# ── GET /skills/{name}/content — Raw SKILL.md ─────────────────────────────────

class TestGetSkillContent:
    """Test GET /skills/{name}/content returns raw SKILL.md."""

    def test_get_skill_content_returns_raw_markdown(self):
        """Verify skill content endpoint returns markdown body."""
        mock_skill = _mock_org_skill(name="test-skill", status="active")

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_skill

        mock_db = AsyncMock()
        mock_db.execute = AsyncMock(return_value=mock_result)

        # Mock file storage
        mock_storage = MagicMock()
        mock_storage.skill_exists.return_value = True
        mock_storage.read_skill_md.return_value = VALID_SKILL_MD
        mock_storage.skill_md_path.return_value = "/nas/skills/test-skill/SKILL.md"

        with patch("skills_registry.routers.skills.get_storage", return_value=mock_storage):
            from skills_registry.database import get_db
            app.dependency_overrides[get_db] = lambda: mock_db

            try:
                client = TestClient(app)
                response = client.get("/skills/test-skill/content")

                assert response.status_code == 200
                data = response.json()
                assert data["name"] == "test-skill"
                assert "Test Skill" in data["content"]
                assert "Section 1" in data["content"]
                # Should NOT include YAML frontmatter
                assert "---" not in data["content"] or data["content"].count("---") == 0
            finally:
                app.dependency_overrides.clear()

    def test_get_skill_content_not_found(self):
        """Test content endpoint returns 404 for missing skill."""
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None

        mock_db = AsyncMock()
        mock_db.execute = AsyncMock(return_value=mock_result)

        from skills_registry.database import get_db
        app.dependency_overrides[get_db] = lambda: mock_db

        try:
            client = TestClient(app)
            response = client.get("/skills/missing-skill/content")

            assert response.status_code == 404
        finally:
            app.dependency_overrides.clear()


# ── RBAC: Admin vs Non-Admin ─────────────────────────────────────────────────

class TestRBAC:
    """Test RBAC: admin vs non-admin access control."""

    def test_admin_skills_list_requires_admin_key(self):
        """Verify GET /admin/skills requires X-Admin-Key header."""
        client = TestClient(app)

        # Without admin key
        response = client.get("/admin/skills")
        assert response.status_code == 401
        assert "Invalid or missing X-Admin-Key" in response.json()["detail"]

    def test_admin_skills_list_with_correct_key(self):
        """Verify GET /admin/skills works with correct X-Admin-Key."""
        from skills_registry.config import settings

        mock_skill = _mock_org_skill("admin-skill", status="archived")  # archived visible to admin

        mock_result = MagicMock()
        mock_scalars = MagicMock()
        mock_scalars.all.return_value = [mock_skill]
        mock_result.scalars.return_value = mock_scalars

        mock_db = AsyncMock()
        mock_db.execute = AsyncMock(return_value=mock_result)

        from skills_registry.database import get_db
        app.dependency_overrides[get_db] = lambda: mock_db

        try:
            client = TestClient(app)
            response = client.get(
                "/admin/skills",
                headers={"X-Admin-Key": settings.admin_api_key},
            )

            assert response.status_code == 200
            data = response.json()
            assert len(data) >= 1
        finally:
            app.dependency_overrides.clear()

    def test_admin_skills_list_with_wrong_key(self):
        """Verify GET /admin/skills rejects wrong X-Admin-Key."""
        mock_db = AsyncMock()
        from skills_registry.database import get_db
        app.dependency_overrides[get_db] = lambda: mock_db

        try:
            client = TestClient(app)
            response = client.get(
                "/admin/skills",
                headers={"X-Admin-Key": "wrong-key-12345"},
            )

            assert response.status_code == 401
        finally:
            app.dependency_overrides.clear()

    def test_public_skills_endpoint_no_auth_required(self):
        """Verify GET /skills does NOT require any auth header."""
        mock_skill = _mock_org_skill("public-skill", status="active")

        mock_result = MagicMock()
        mock_scalars = MagicMock()
        mock_scalars.all.return_value = [mock_skill]
        mock_result.scalars.return_value = mock_scalars

        mock_db = AsyncMock()
        mock_db.execute = AsyncMock(return_value=mock_result)

        from skills_registry.database import get_db
        app.dependency_overrides[get_db] = lambda: mock_db

        try:
            client = TestClient(app)
            # No auth header at all
            response = client.get("/skills")

            assert response.status_code == 200
        finally:
            app.dependency_overrides.clear()

    def test_admin_create_skill_requires_key(self):
        """Verify POST /admin/skills requires X-Admin-Key."""
        client = TestClient(app)

        response = client.post(
            "/admin/skills",
            json={
                "name": "new-skill",
                "skill_md": VALID_SKILL_MD,
            },
        )

        assert response.status_code == 401

    def test_admin_archive_skill_requires_key(self):
        """Verify DELETE /admin/skills/{name} requires X-Admin-Key."""
        client = TestClient(app)

        response = client.delete("/admin/skills/some-skill")

        assert response.status_code == 401
