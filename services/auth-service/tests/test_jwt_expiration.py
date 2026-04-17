"""
JWT Expiration Tests for Auth Service.

Tests that:
1. An expired JWT is rejected by verify_jwt with appropriate error
2. A valid (non-expired) JWT is accepted
3. A JWT with wrong signature is rejected
"""
import pytest
from datetime import datetime, timedelta, timezone
from jose import jwt

from auth_service.service import create_access_token, verify_jwt
from auth_service.config import settings

ALGORITHM = "HS256"


class TestJwtExpiration:
    def test_expired_jwt_is_rejected(self):
        """Test that an expired JWT is rejected by verify_jwt."""
        # Create a token that expired 1 hour ago
        expired_time = datetime.now(timezone.utc) - timedelta(hours=1)
        expired_ts = int(expired_time.timestamp())

        payload = {
            "sub": "test-user-001",
            "role": "user",
            "type": "access",
            "exp": expired_ts,
            "iat": int(datetime.now(timezone.utc).timestamp()),
        }
        # Sign with the correct secret
        expired_token = jwt.encode(payload, settings.JWT_SECRET_KEY, algorithm=ALGORITHM)

        # verify_jwt should return None for expired tokens
        result = verify_jwt(expired_token)
        assert result is None, "Expired JWT should be rejected"

    def test_valid_jwt_is_accepted(self):
        """Test that a valid (non-expired) JWT is accepted."""
        user_id = "test-user-valid"
        role = "user"

        token, expires_in = create_access_token(user_id, role)

        # verify_jwt should return the payload for valid tokens
        result = verify_jwt(token)
        assert result is not None, "Valid JWT should be accepted"
        assert result["sub"] == user_id
        assert result["role"] == role
        assert result["type"] == "access"

    def test_jwt_with_wrong_signature_is_rejected(self):
        """Test that a JWT signed with wrong secret is rejected."""
        user_id = "test-user-tampered"
        role = "user"

        # Create a token with a different secret
        wrong_secret = "this-is-a-wrong-secret-key-that-nobody-knows"
        expires = datetime.now(timezone.utc) + timedelta(minutes=30)
        expires_ts = int(expires.timestamp())

        payload = {
            "sub": user_id,
            "role": role,
            "type": "access",
            "exp": expires_ts,
            "iat": int(datetime.now(timezone.utc).timestamp()),
        }
        bad_token = jwt.encode(payload, wrong_secret, algorithm=ALGORITHM)

        # verify_jwt should return None for tokens with wrong signature
        result = verify_jwt(bad_token)
        assert result is None, "JWT with wrong signature should be rejected"

    def test_jwt_just_before_expiry_is_accepted(self):
        """Test that a JWT that expires in a few seconds is still accepted."""
        user_id = "test-user-near-expiry"
        role = "user"

        # Create a token that expires in 10 seconds
        near_expiry_time = datetime.now(timezone.utc) + timedelta(seconds=10)
        near_expiry_ts = int(near_expiry_time.timestamp())

        payload = {
            "sub": user_id,
            "role": role,
            "type": "access",
            "exp": near_expiry_ts,
            "iat": int(datetime.now(timezone.utc).timestamp()),
        }
        near_expiry_token = jwt.encode(payload, settings.JWT_SECRET_KEY, algorithm=ALGORITHM)

        # verify_jwt should still accept it
        result = verify_jwt(near_expiry_token)
        assert result is not None, "JWT near expiry should still be accepted"
        assert result["sub"] == user_id

    def test_jwt_missing_type_field_is_rejected(self):
        """Test that a JWT without 'type: access' is rejected."""
        user_id = "test-user-wrong-type"
        role = "user"

        expires = datetime.now(timezone.utc) + timedelta(minutes=30)
        expires_ts = int(expires.timestamp())

        # Create token without 'type' field
        payload = {
            "sub": user_id,
            "role": role,
            "exp": expires_ts,
            "iat": int(datetime.now(timezone.utc).timestamp()),
        }
        token_without_type = jwt.encode(payload, settings.JWT_SECRET_KEY, algorithm=ALGORITHM)

        result = verify_jwt(token_without_type)
        assert result is None, "JWT without type=access should be rejected"

    def test_jwt_with_refresh_type_is_rejected(self):
        """Test that a JWT with type='refresh' is rejected by verify_jwt."""
        user_id = "test-user-refresh"
        role = "user"

        expires = datetime.now(timezone.utc) + timedelta(minutes=30)
        expires_ts = int(expires.timestamp())

        # Create token with type='refresh' instead of 'access'
        payload = {
            "sub": user_id,
            "role": role,
            "type": "refresh",
            "exp": expires_ts,
            "iat": int(datetime.now(timezone.utc).timestamp()),
        }
        refresh_token = jwt.encode(payload, settings.JWT_SECRET_KEY, algorithm=ALGORITHM)

        result = verify_jwt(refresh_token)
        assert result is None, "JWT with type=refresh should be rejected by verify_jwt"
