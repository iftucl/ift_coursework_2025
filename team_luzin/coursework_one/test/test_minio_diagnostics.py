"""
Unit tests for MinIODiagnostics module edge cases.

Tests validation functions without requiring live MinIO endpoint.
"""

import os

import pytest

from modules.minio_diagnostics import MinIODiagnostics


class TestValidateEndpoint:
    """Test endpoint validation without live connection."""

    def test_validate_endpoint_valid_with_port(self):
        """Valid endpoint with host:port format."""
        valid, error = MinIODiagnostics.validate_endpoint("localhost:9000")
        assert valid is True
        assert error is None

    def test_validate_endpoint_valid_hostname(self):
        """Valid endpoint with hostname only."""
        valid, error = MinIODiagnostics.validate_endpoint("minio-server")
        assert valid is True
        assert error is None

    def test_validate_endpoint_valid_ip(self):
        """Valid endpoint with IP address."""
        valid, error = MinIODiagnostics.validate_endpoint("192.168.1.100:9000")
        assert valid is True
        assert error is None

    def test_validate_endpoint_empty(self):
        """Empty endpoint should fail."""
        valid, error = MinIODiagnostics.validate_endpoint("")
        assert valid is False
        assert "empty" in error.lower()

    def test_validate_endpoint_invalid_format(self):
        """Invalid format with multiple colons."""
        valid, error = MinIODiagnostics.validate_endpoint("host:port:extra")
        assert valid is False
        assert "format" in error.lower()

    def test_validate_endpoint_invalid_port_range(self):
        """Port out of valid range."""
        valid, error = MinIODiagnostics.validate_endpoint("localhost:99999")
        assert valid is False
        assert "port" in error.lower()

    def test_validate_endpoint_invalid_port_zero(self):
        """Port 0 is invalid."""
        valid, error = MinIODiagnostics.validate_endpoint("localhost:0")
        assert valid is False
        assert "port" in error.lower()

    def test_validate_endpoint_nonnumeric_port(self):
        """Port must be numeric."""
        valid, error = MinIODiagnostics.validate_endpoint("localhost:abc")
        assert valid is False
        assert "port" in error.lower()

    def test_validate_endpoint_port_1(self):
        """Minimum valid port (1)."""
        valid, error = MinIODiagnostics.validate_endpoint("localhost:1")
        assert valid is True
        assert error is None

    def test_validate_endpoint_port_65535(self):
        """Maximum valid port (65535)."""
        valid, error = MinIODiagnostics.validate_endpoint("localhost:65535")
        assert valid is True
        assert error is None


class TestCheckEnvVars:
    """Test environment variable checking."""

    def test_check_env_vars_all_present(self):
        """All MinIO env vars present."""
        # Save current env
        saved_env = {
            "MINIO_ENDPOINT": os.getenv("MINIO_ENDPOINT"),
            "MINIO_ACCESS_KEY": os.getenv("MINIO_ACCESS_KEY"),
            "MINIO_SECRET_KEY": os.getenv("MINIO_SECRET_KEY"),
        }

        try:
            # Set required env vars
            os.environ["MINIO_ENDPOINT"] = "localhost:9000"
            os.environ["MINIO_ACCESS_KEY"] = "minioadmin"
            os.environ["MINIO_SECRET_KEY"] = "minioadmin"

            configured, error = MinIODiagnostics.check_env_vars()
            assert configured is True
            assert error is None
        finally:
            # Restore env
            for key, val in saved_env.items():
                if val:
                    os.environ[key] = val
                elif key in os.environ:
                    del os.environ[key]

    def test_check_env_vars_missing_endpoint(self):
        """Missing MINIO_ENDPOINT."""
        saved_endpoint = os.environ.pop("MINIO_ENDPOINT", None)

        try:
            os.environ["MINIO_ACCESS_KEY"] = "key"
            os.environ["MINIO_SECRET_KEY"] = "secret"

            configured, error = MinIODiagnostics.check_env_vars()
            assert configured is False
            assert "ENDPOINT" in error
        finally:
            if saved_endpoint:
                os.environ["MINIO_ENDPOINT"] = saved_endpoint

    def test_check_env_vars_missing_access_key(self):
        """Missing MINIO_ACCESS_KEY."""
        saved_key = os.environ.pop("MINIO_ACCESS_KEY", None)

        try:
            os.environ["MINIO_ENDPOINT"] = "localhost:9000"
            os.environ["MINIO_SECRET_KEY"] = "secret"

            configured, error = MinIODiagnostics.check_env_vars()
            assert configured is False
            assert "ACCESS_KEY" in error
        finally:
            if saved_key:
                os.environ["MINIO_ACCESS_KEY"] = saved_key

    def test_check_env_vars_missing_secret_key(self):
        """Missing MINIO_SECRET_KEY."""
        saved_secret = os.environ.pop("MINIO_SECRET_KEY", None)

        try:
            os.environ["MINIO_ENDPOINT"] = "localhost:9000"
            os.environ["MINIO_ACCESS_KEY"] = "key"

            configured, error = MinIODiagnostics.check_env_vars()
            assert configured is False
            assert "SECRET_KEY" in error
        finally:
            if saved_secret:
                os.environ["MINIO_SECRET_KEY"] = saved_secret

    def test_check_env_vars_all_missing(self):
        """All MinIO env vars missing."""
        saved_env = {
            "MINIO_ENDPOINT": os.environ.pop("MINIO_ENDPOINT", None),
            "MINIO_ACCESS_KEY": os.environ.pop("MINIO_ACCESS_KEY", None),
            "MINIO_SECRET_KEY": os.environ.pop("MINIO_SECRET_KEY", None),
        }

        try:
            configured, error = MinIODiagnostics.check_env_vars()
            assert configured is False
            assert (
                "ENDPOINT" in error and "ACCESS_KEY" in error and "SECRET_KEY" in error
            )
        finally:
            # Restore
            for key, val in saved_env.items():
                if val:
                    os.environ[key] = val


class TestMINIOSecureFlag:
    """Test MINIO_SECURE handling."""

    def test_minio_secure_true(self):
        """Parse MINIO_SECURE=true."""
        saved = os.getenv("MINIO_SECURE")
        try:
            os.environ["MINIO_SECURE"] = "true"
            secure = os.getenv("MINIO_SECURE", "false").lower() == "true"
            assert secure is True
        finally:
            if saved:
                os.environ["MINIO_SECURE"] = saved
            elif "MINIO_SECURE" in os.environ:
                del os.environ["MINIO_SECURE"]

    def test_minio_secure_false(self):
        """Parse MINIO_SECURE=false."""
        saved = os.getenv("MINIO_SECURE")
        try:
            os.environ["MINIO_SECURE"] = "false"
            secure = os.getenv("MINIO_SECURE", "false").lower() == "true"
            assert secure is False
        finally:
            if saved:
                os.environ["MINIO_SECURE"] = saved
            elif "MINIO_SECURE" in os.environ:
                del os.environ["MINIO_SECURE"]

    def test_minio_secure_default(self):
        """Default MINIO_SECURE is false."""
        saved = os.environ.pop("MINIO_SECURE", None)
        try:
            secure = os.getenv("MINIO_SECURE", "false").lower() == "true"
            assert secure is False
        finally:
            if saved:
                os.environ["MINIO_SECURE"] = saved
