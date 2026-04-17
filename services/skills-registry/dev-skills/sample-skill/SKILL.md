---
name: sample-skill
description: Sample org-level skill for Skills Registry local development testing
version: 1.0.0
author: Platform Team
license: MIT
metadata:
  hermes:
    tags: [sample, development, testing]
    related_skills: []
---

# Sample Skill

This is a sample org-level skill for local development and testing.

## Usage

Use this skill to verify the Skills Registry local development environment is working correctly.

## Verification Steps

1. Start Skills Registry: `uvicorn skills_registry.main:app --reload`
2. Call `GET /health`
3. Call `GET /skills`
4. Verify `GET /skills/sample-skill/content` returns this markdown body

## Notes

- Skills are stored in `./dev-skills/` when `SKILLS_REGISTRY_DEBUG=true`
- In production, skills are stored on NAS `/nas/org-skills/`
- Admin endpoints require `X-Admin-Key: <your-key>` header
