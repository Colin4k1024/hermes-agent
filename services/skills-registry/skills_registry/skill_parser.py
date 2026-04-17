"""Parser for SKILL.md YAML frontmatter.

Mirrors the Hermes SKILL.md format:
  ---
  name: <skill-name>
  description: <description>
  version: <semver>
  author: <author>
  license: <license>
  metadata:
    hermes:
      tags: [...]
      related_skills: [...]
  ---

  # <Skill Title>

  <markdown content>
"""

import re
from typing import NamedTuple

import yaml


class ParsedSkill(NamedTuple):
    """Result of parsing a SKILL.md file."""

    name: str
    description: str
    version: str
    author: str
    license: str
    tags: list[str]
    related_skills: list[str]
    body: str  # Markdown content after frontmatter


def _extract_frontmatter(content: str) -> tuple[dict, str]:
    """Split content into YAML frontmatter dict and markdown body."""
    match = re.match(r"^---\s*\n(.*?)\n---\s*\n(.*)", content, re.DOTALL)
    if match:
        frontmatter_yaml = match.group(1)
        body = match.group(2).strip()
        try:
            data = yaml.safe_load(frontmatter_yaml) or {}
        except yaml.YAMLError:
            data = {}
        return data, body
    return {}, content.strip()


def parse_skill_md(content: str) -> ParsedSkill:
    """Parse a SKILL.md string and return structured metadata + body.

    Args:
        content: Raw SKILL.md file content.

    Returns:
        ParsedSkill with extracted fields.

    Raises:
        ValueError: If the SKILL.md has no YAML frontmatter or invalid name.
    """
    if not content.strip():
        raise ValueError("SKILL.md content is empty")

    frontmatter, body = _extract_frontmatter(content)

    name = frontmatter.get("name", "")
    if not name:
        # Fall back to the first heading in the body
        heading_match = re.search(r"^#\s+(.+)$", body, re.MULTILINE)
        if heading_match:
            name = heading_match.group(1).strip().lower().replace(" ", "-")
        if not name:
            raise ValueError("SKILL.md must have a 'name' in frontmatter or a # heading")

    # Normalize name: lowercase, replace spaces with hyphens
    name = re.sub(r"\s+", "-", name.strip()).lower()
    # Allow only alphanumeric, underscores, hyphens
    name = re.sub(r"[^a-z0-9_-]", "", name)

    description = str(frontmatter.get("description", ""))
    version = str(frontmatter.get("version", "1.0.0"))
    author = str(frontmatter.get("author", ""))
    license_ = str(frontmatter.get("license", ""))

    # Extract hermes metadata
    metadata = frontmatter.get("metadata", {})
    hermes_meta = metadata.get("hermes", {}) if isinstance(metadata, dict) else {}

    tags = hermes_meta.get("tags", [])
    if isinstance(tags, str):
        tags = [t.strip() for t in tags.split(",")]

    related_skills = hermes_meta.get("related_skills", [])
    if isinstance(related_skills, str):
        related_skills = [s.strip() for s in related_skills.split(",")]

    return ParsedSkill(
        name=name,
        description=description,
        version=version,
        author=author,
        license=license_,
        tags=tags,
        related_skills=related_skills,
        body=body,
    )


def serialize_tags(tags: list[str]) -> str:
    """Serialize tags list to a string for DB storage."""
    return ",".join(tags)


def deserialize_tags(raw: str | None) -> list[str]:
    """Deserialize tags from DB storage string."""
    if not raw:
        return []
    return [t.strip() for t in raw.split(",") if t.strip()]
