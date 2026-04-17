"""Unit tests for Skills Registry Service."""

import pytest

from skills_registry.skill_parser import (
    deserialize_tags,
    parse_skill_md,
    serialize_tags,
)
from skills_registry.schemas import (
    SkillCreateRequest,
    SkillMetadata,
    SkillSummary,
    SkillUpdateNotification,
    SkillUpdateRequest,
)


# ── SKILL.md Parser Tests ──────────────────────────────────────────────────


VALID_SKILL_MD = """---
name: code-review-guide
description: Org-wide code review best practices for Hermes Agent
version: 1.2.0
author: Platform Team
license: MIT
metadata:
  hermes:
    tags: [code-review, quality, development]
    related_skills: [test-driven-development, writing-plans]
---

# Code Review Guide

Use this skill when performing code reviews.

## Checklist
- [ ] Tests exist
- [ ] No hardcoded secrets
- [ ] Error handling complete
"""

EMPTY_FRONT_MATTER_MD = """---
---

# Minimal Skill

Content here.
"""

NO_FRONT_MATTER_MD = """# No Frontmatter Skill

Just markdown content.
"""


class TestSkillParser:
    def test_parse_valid_skill_md(self):
        parsed = parse_skill_md(VALID_SKILL_MD)
        assert parsed.name == "code-review-guide"
        assert parsed.description == "Org-wide code review best practices for Hermes Agent"
        assert parsed.version == "1.2.0"
        assert parsed.author == "Platform Team"
        assert parsed.license == "MIT"
        assert parsed.tags == ["code-review", "quality", "development"]
        assert parsed.related_skills == ["test-driven-development", "writing-plans"]
        assert "# Code Review Guide" in parsed.body
        assert "## Checklist" in parsed.body

    def test_parse_empty_frontmatter(self):
        parsed = parse_skill_md(EMPTY_FRONT_MATTER_MD)
        # Should extract name from first heading
        assert parsed.name == "minimal-skill"
        assert parsed.description == ""
        assert parsed.version == "1.0.0"

    def test_parse_no_frontmatter(self):
        parsed = parse_skill_md(NO_FRONT_MATTER_MD)
        assert parsed.name == "no-frontmatter-skill"
        assert "Just markdown content." in parsed.body

    def test_parse_empty_content_raises(self):
        with pytest.raises(ValueError, match="empty"):
            parse_skill_md("")

    def test_parse_whitespace_only_raises(self):
        with pytest.raises(ValueError, match="empty"):
            parse_skill_md("   \n   ")

    def test_parse_name_with_spaces_normalized(self):
        md = """---
name: My Test Skill
description: Test
---
# Body
"""
        parsed = parse_skill_md(md)
        assert parsed.name == "my-test-skill"

    def test_parse_version_as_int(self):
        md = """---
name: ver-test
version: 2
---
"""
        parsed = parse_skill_md(md)
        assert parsed.version == "2"

    def test_parse_tags_as_string(self):
        md = """---
name: tag-test
metadata:
  hermes:
    tags: tag1, tag2, tag3
---
"""
        parsed = parse_skill_md(md)
        assert parsed.tags == ["tag1", "tag2", "tag3"]

    def test_parse_related_skills_as_string(self):
        md = """---
name: related-test
metadata:
  hermes:
    related_skills: skill-a, skill-b
---
"""
        parsed = parse_skill_md(md)
        assert parsed.related_skills == ["skill-a", "skill-b"]

    def test_serialize_deserialize_tags(self):
        tags = ["code-review", "quality", "development"]
        serialized = serialize_tags(tags)
        assert serialized == "code-review,quality,development"
        deserialized = deserialize_tags(serialized)
        assert deserialized == tags

    def test_deserialize_empty_tags(self):
        assert deserialize_tags("") == []
        assert deserialize_tags(None) == []
        assert deserialize_tags("  ") == []


# ── Schema Tests ───────────────────────────────────────────────────────────


class TestSchemas:
    def test_skill_create_request_valid_name(self):
        req = SkillCreateRequest(name="test-skill", skill_md=VALID_SKILL_MD)
        assert req.name == "test-skill"
        assert req.tags == []
        assert req.published_by is None

    def test_skill_create_request_invalid_name_chars(self):
        with pytest.raises(Exception):  # pydantic ValidationError
            SkillCreateRequest(name="invalid name!", skill_md=VALID_SKILL_MD)

    def test_skill_create_request_max_length(self):
        long_name = "a" * 100
        with pytest.raises(Exception):
            SkillCreateRequest(name=long_name, skill_md=VALID_SKILL_MD)

    def test_skill_update_request_partial(self):
        req = SkillUpdateRequest(description="Updated desc")
        assert req.description == "Updated desc"
        assert req.skill_md is None
        assert req.tags is None
        assert req.status is None

    def test_skill_update_request_invalid_status(self):
        with pytest.raises(Exception):
            SkillUpdateRequest(status="deleted")  # only active|archived allowed

    def test_skill_update_notification(self):
        n = SkillUpdateNotification(
            skill_name="test",
            version="1.0.0",
            action="updated",
        )
        assert n.skill_name == "test"
        assert n.action == "updated"

    def test_skill_update_notification_invalid_action(self):
        with pytest.raises(Exception):
            SkillUpdateNotification(
                skill_name="test",
                version="1.0.0",
                action="deleted",  # must be created|updated|archived
            )


# ── FileStorage Tests ─────────────────────────────────────────────────────


import tempfile
from pathlib import Path

from skills_registry.file_storage import FileStorage


class TestFileStorage:
    def test_write_and_read_skill(self, tmp_path: Path):
        storage = FileStorage(root=str(tmp_path))
        storage.write_skill("my-skill", "# My Skill\nContent here.")
        content = storage.read_skill_md("my-skill")
        assert "# My Skill" in content
        assert "Content here." in content

    def test_skill_exists(self, tmp_path: Path):
        storage = FileStorage(root=str(tmp_path))
        assert not storage.skill_exists("my-skill")
        storage.write_skill("my-skill", "# My Skill\n")
        assert storage.skill_exists("my-skill")

    def test_read_nonexistent_raises(self, tmp_path: Path):
        storage = FileStorage(root=str(tmp_path))
        with pytest.raises(FileNotFoundError):
            storage.read_skill_md("nonexistent")

    def test_list_skills(self, tmp_path: Path):
        storage = FileStorage(root=str(tmp_path))
        storage.write_skill("skill-a", "# A")
        storage.write_skill("skill-b", "# B")
        storage.write_skill("skill-c", "# C")
        names = storage.list_skills()
        assert names == ["skill-a", "skill-b", "skill-c"]

    def test_list_skills_empty_root(self, tmp_path: Path):
        storage = FileStorage(root=str(tmp_path))
        assert storage.list_skills() == []

    def test_delete_skill(self, tmp_path: Path):
        storage = FileStorage(root=str(tmp_path))
        storage.write_skill("to-delete", "# Delete Me")
        assert storage.skill_exists("to-delete")
        storage.delete_skill("to-delete")
        assert not storage.skill_exists("to-delete")

    def test_write_reference(self, tmp_path: Path):
        storage = FileStorage(root=str(tmp_path))
        storage.write_skill("ref-skill", "# Ref Skill")
        storage.write_reference("ref-skill", "example.py", b"print('hello')")
        ref_path = storage.references_dir("ref-skill") / "example.py"
        assert ref_path.exists()
        assert ref_path.read_bytes() == b"print('hello')"

    def test_write_reference_blocked_path_separators(self, tmp_path: Path):
        storage = FileStorage(root=str(tmp_path))
        storage.write_skill("ref-skill", "# Ref Skill")
        with pytest.raises(ValueError, match="path separators"):
            storage.write_reference("ref-skill", "../evil.py", b"bad")

    def test_health_check_existing_root(self, tmp_path: Path):
        storage = FileStorage(root=str(tmp_path))
        assert storage.health_check() is True

    def test_health_check_creates_missing_root(self, tmp_path: Path):
        storage = FileStorage(root=str(tmp_path / "new" / "deep"))
        assert storage.health_check() is True
        assert (tmp_path / "new" / "deep").exists()


# ── Config Tests ───────────────────────────────────────────────────────────


from skills_registry.config import Settings


class TestConfig:
    def test_settings_defaults(self):
        s = Settings(_env_file="nonexistent")
        assert s.port == 8004
        assert s.host == "0.0.0.0"
        assert s.debug is False
        assert s.skills_local_dev_path == "./dev-skills"

    def test_skills_root_dev_mode(self):
        s = Settings(_env_file="nonexistent", debug=True)
        assert s.skills_root == "./dev-skills"

    def test_skills_root_prod_mode(self):
        s = Settings(_env_file="nonexistent", debug=False)
        assert s.skills_root == "/nas/org-skills"

    def test_database_url(self):
        s = Settings(
            _env_file="nonexistent",
            postgres_user="u",
            postgres_password="p",
            postgres_host="h",
            postgres_port=5432,
            postgres_db="d",
        )
        assert "postgresql+asyncpg://" in s.database_url
        assert "u:p@h:5432/d" in s.database_url

    def test_redis_url(self):
        s = Settings(_env_file="nonexistent", redis_host="r", redis_port=6380)
        assert s.redis_url == "redis://r:6380/0"
