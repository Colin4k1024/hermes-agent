"""File storage operations for Skills Registry.

Skills are stored on the local filesystem (dev) or NAS (prod):
  {skills_root}/
  ├── <skill-name>/
  │   ├── SKILL.md
  │   └── references/     # optional supporting files
  └── <skill-name>/       # one per skill
      └── SKILL.md
"""

import os
import shutil
from pathlib import Path

from .config import settings


class FileStorage:
    """Abstraction over skill file storage (local or NAS)."""

    def __init__(self, root: str | None = None) -> None:
        self.root = Path(root or settings.skills_root)

    # ── Path helpers ──────────────────────────────────────────────────────

    def skill_dir(self, name: str) -> Path:
        return self.root / name

    def skill_md_path(self, name: str) -> Path:
        return self.skill_dir(name) / "SKILL.md"

    def references_dir(self, name: str) -> Path:
        return self.skill_dir(name) / "references"

    # ── Read ────────────────────────────────────────────────────────────────

    def read_skill_md(self, name: str) -> str:
        """Read the SKILL.md content for a skill."""
        path = self.skill_md_path(name)
        if not path.exists():
            raise FileNotFoundError(f"SKILL.md not found: {path}")
        return path.read_text(encoding="utf-8")

    def skill_exists(self, name: str) -> bool:
        """Check if a skill directory with SKILL.md exists."""
        return self.skill_md_path(name).exists()

    def list_skills(self) -> list[str]:
        """List all skill names currently on disk."""
        if not self.root.exists():
            return []
        return sorted(
            d.name
            for d in self.root.iterdir()
            if d.is_dir() and (d / "SKILL.md").exists()
        )

    # ── Write ──────────────────────────────────────────────────────────────

    def write_skill(self, name: str, skill_md: str) -> Path:
        """Write (create or overwrite) a skill's SKILL.md file.

        Args:
            name: Skill directory name.
            skill_md: Full SKILL.md content.

        Returns:
            Path to the written SKILL.md file.
        """
        dir_path = self.skill_dir(name)
        dir_path.mkdir(parents=True, exist_ok=True)
        path = self.skill_md_path(name)
        path.write_text(skill_md, encoding="utf-8")
        return path

    def write_reference(self, name: str, filename: str, content: bytes) -> Path:
        """Write a supporting file under references/."""
        ref_dir = self.references_dir(name)
        ref_dir.mkdir(parents=True, exist_ok=True)
        if "/" in filename or "\\" in filename:
            raise ValueError("filename must not contain path separators")
        path = ref_dir / filename
        path.write_bytes(content)
        return path

    # ── Delete ─────────────────────────────────────────────────────────────

    def delete_skill(self, name: str) -> None:
        """Delete the entire skill directory."""
        dir_path = self.skill_dir(name)
        if dir_path.exists():
            shutil.rmtree(dir_path)

    # ── Health ─────────────────────────────────────────────────────────────

    def health_check(self) -> bool:
        """Check if the storage root is accessible."""
        try:
            # Try to list (works for both existing and empty dirs)
            list(self.root.iterdir())
            return True
        except PermissionError:
            return False
        except FileNotFoundError:
            # Root doesn't exist — try to create it
            try:
                self.root.mkdir(parents=True, exist_ok=True)
                return True
            except Exception:
                return False
        except Exception:
            return False


# Singleton for request-scoped use
_storage: FileStorage | None = None


def get_storage() -> FileStorage:
    global _storage
    if _storage is None:
        _storage = FileStorage()
    return _storage
