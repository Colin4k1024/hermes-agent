"""
Auth Service — Tests
"""
import pytest
import hashlib
from datetime import datetime, timedelta, timezone

from auth_service.service import (
    hash_password,
    verify_password,
    generate_api_token,
    hash_token,
    create_access_token,
    verify_jwt,
)


class TestPasswordHashing:
    def test_hash_password(self):
        h = hash_password("testpassword")
        assert h != "testpassword"
        assert len(h) > 20

    def test_verify_password_correct(self):
        h = hash_password("testpassword")
        assert verify_password("testpassword", h) is True

    def test_verify_password_wrong(self):
        h = hash_password("testpassword")
        assert verify_password("wrongpassword", h) is False


class TestApiToken:
    def test_generate_api_token(self):
        token, prefix = generate_api_token()
        assert token.startswith("hms_")
        assert len(token) > 20
        assert prefix == token[:16]

    def test_hash_token(self):
        token = "hms_test_token_123"
        h = hash_token(token)
        assert h == hashlib.sha256(token.encode()).hexdigest()
        # Same input → same output
        assert hash_token(token) == h


class TestJwt:
    def test_create_and_verify_access_token(self):
        user_id = "test-user-001"
        role = "admin"
        token, expires_in = create_access_token(user_id, role)

        assert token is not None
        assert expires_in == 30 * 60  # 30 minutes in seconds

        payload = verify_jwt(token)
        assert payload is not None
        assert payload["sub"] == user_id
        assert payload["role"] == role
        assert payload["type"] == "access"

    def test_verify_invalid_jwt(self):
        result = verify_jwt("invalid.token.here")
        assert result is None

    def test_verify_tampered_jwt(self):
        token, _ = create_access_token("user", "user")
        # Tamper with the payload
        parts = token.split(".")
        parts[1] = parts[1] + "x"
        tampered = ".".join(parts)
        result = verify_jwt(tampered)
        assert result is None


class TestSchemas:
    def test_login_request_schema(self):
        from auth_service.schemas import LoginRequest
        req = LoginRequest(email="test@example.com", password="password123")
        assert req.email == "test@example.com"
        assert req.password == "password123"

    def test_user_response_schema(self):
        from auth_service.schemas import UserResponse
        now = datetime.now(timezone.utc)
        user = UserResponse(
            id="user-001",
            email="test@example.com",
            role="user",
            feishu_union_id=None,
            is_active=True,
            created_at=now,
            updated_at=now,
        )
        assert user.role == "user"
        assert user.is_active is True

    def test_api_token_create_response(self):
        from auth_service.schemas import ApiTokenCreateResponse
        now = datetime.now(timezone.utc)
        resp = ApiTokenCreateResponse(
            token="hms_test_token",
            token_prefix="hms_test_tok",
            expires_at=None,
            created_at=now,
        )
        assert resp.token.startswith("hms_")


class TestConfig:
    def test_settings_defaults(self):
        from auth_service.config import settings
        assert settings.SERVICE_PORT == 8001
        assert settings.JWT_ALGORITHM == "HS256"
        assert settings.OIDC_MOCK_ENABLED is True
        assert settings.JWT_ACCESS_TOKEN_EXPIRE_MINUTES == 30
