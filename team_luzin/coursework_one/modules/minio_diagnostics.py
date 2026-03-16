#!/usr/bin/env python3
"""
MinIO connection diagnostics and preflight checks.

Provides detailed error diagnosis to distinguish between:
- Missing/invalid endpoint
- Missing/invalid credentials
- Missing/inaccessible bucket
- Permission issues
"""

import logging
import os
from typing import Optional, Tuple

logger = logging.getLogger(__name__)


class MinIODiagnostics:
    """Diagnostic tools for MinIO configuration and connectivity."""

    @staticmethod
    def check_env_vars() -> Tuple[bool, Optional[str]]:
        """
        Check if MinIO environment variables are provided.

        Returns:
            (config_complete, error_message)
            - True if all required vars present
            - False with explanatory message if any missing
        """
        endpoint = os.getenv("MINIO_ENDPOINT")
        access_key = os.getenv("MINIO_ACCESS_KEY")
        secret_key = os.getenv("MINIO_SECRET_KEY")

        missing = []
        if not endpoint:
            missing.append("MINIO_ENDPOINT")
        if not access_key:
            missing.append("MINIO_ACCESS_KEY")
        if not secret_key:
            missing.append("MINIO_SECRET_KEY")

        if missing:
            msg = f"Missing MinIO config: {', '.join(missing)}"
            return False, msg

        return True, None

    @staticmethod
    def validate_endpoint(endpoint: str) -> Tuple[bool, Optional[str]]:
        """
        Validate MinIO endpoint format.

        Returns:
            (valid, error_message)
        """
        if not endpoint:
            return False, "Endpoint is empty"

        # MinIO endpoint can be hostname:port or IP:port
        parts = endpoint.split(":")
        if len(parts) not in [1, 2]:
            return False, f"Invalid endpoint format: {endpoint} (expected 'host:port')"

        if len(parts) == 2:
            try:
                port = int(parts[1])
                if not (1 <= port <= 65535):
                    return False, f"Invalid port: {port} (must be 1-65535)"
            except ValueError:
                return False, f"Invalid port number: {parts[1]}"

        logger.debug(f"✓ Endpoint format valid: {endpoint}")
        return True, None

    @staticmethod
    def preflight_check_connectivity(
        endpoint: str, access_key: str, secret_key: str, bucket: str
    ) -> Tuple[bool, Optional[str]]:
        """
        Attempt preflight MinIO connectivity check.

        Returns:
            (success, error_message)
            - Distinguishes between endpoint unreachable, bad credentials, and missing bucket
        """
        try:
            from minio import Minio
            from minio.error import S3Error
        except ImportError:
            return False, "MinIO library not installed (pip install minio)"

        try:
            # Validate endpoint first
            valid, err = MinIODiagnostics.validate_endpoint(endpoint)
            if not valid:
                return False, f"Endpoint validation failed: {err}"

            # Log what we're about to try (without exposing secrets)
            logger.debug(f"Preflight: Connecting to {endpoint}, bucket={bucket}")

            # Try to create client and test connectivity
            client = Minio(
                endpoint,
                access_key=access_key,
                secret_key=secret_key,
                secure=os.getenv("MINIO_SECURE", "false").lower() == "true",
            )

            # Test 1: Simple list buckets (light auth test)
            try:
                client.list_buckets()
                logger.debug(f"✓ Authentication successful, connected to {endpoint}")
            except S3Error as e:
                if "InvalidAccessKeyId" in str(e) or "invalid_grant" in str(e).lower():
                    return False, "Authentication failed: Invalid access key or secret"
                elif "AccessDenied" in str(e):
                    return (
                        False,
                        "Authentication failed: Access denied (permission issue)",
                    )
                else:
                    return False, f"Authentication error: {e}"

            # Test 2: Check bucket exists or can be created
            try:
                if client.bucket_exists(bucket):
                    logger.debug(f"✓ Bucket '{bucket}' exists and is accessible")
                else:
                    logger.debug(
                        f"ℹ Bucket '{bucket}' does not exist, will be created on first upload"
                    )
            except S3Error as e:
                if "NoSuchBucket" in str(e):
                    logger.debug(
                        f"ℹ Bucket '{bucket}' doesn't exist yet (will be created)"
                    )
                elif "AccessDenied" in str(e):
                    return (
                        False,
                        f"Bucket access failed: {bucket} (permission denied or doesn't exist)",
                    )
                else:
                    return False, f"Bucket check error: {e}"

            return True, None

        except Exception as e:
            # Attempt to classify the error
            error_str = str(e).lower()
            if (
                "connection" in error_str
                or "refused" in error_str
                or "unreachable" in error_str
            ):
                return False, f"Cannot connect to MinIO endpoint {endpoint}: {e}"
            elif "timeout" in error_str:
                return False, f"Connection timeout to {endpoint}: {e}"
            else:
                return False, f"Unexpected error: {e}"

    @staticmethod
    def log_configuration(
        endpoint: Optional[str],
        bucket: Optional[str],
        access_key_provided: bool,
        secret_key_provided: bool,
    ) -> None:
        """
        Log MinIO configuration (without exposing secrets).
        """
        logger.info("MinIO Configuration:")
        logger.info(f"  MINIO_ENDPOINT: {endpoint or '(not set)'}")
        logger.info(f"  MINIO_BUCKET: {bucket or '(not set)'}")
        logger.info(
            f"  MINIO_ACCESS_KEY: {'(provided)' if access_key_provided else '(not set)'}"
        )
        logger.info(
            f"  MINIO_SECRET_KEY: {'(provided)' if secret_key_provided else '(not set)'}"
        )
        logger.info(f"  MINIO_SECURE: {os.getenv('MINIO_SECURE', '(not set)')}")
