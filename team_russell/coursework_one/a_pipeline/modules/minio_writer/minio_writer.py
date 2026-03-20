"""Write raw JSON payloads to MinIO for audit and long-term storage."""

import io
import json
import logging
from datetime import datetime

from minio import Minio
from minio.error import S3Error

logger = logging.getLogger(__name__)


class MinioRawWriter:
    """Stores raw data files in MinIO under a structured path.

    Path format: russell/<data_type>/<SYMBOL>_<YYYYMMDDHHMMSS>.json

    Args:
        endpoint: MinIO host:port (e.g. 'localhost:9000').
        access_key: MinIO access key.
        secret_key: MinIO secret key.
        bucket: Target bucket name.
        secure: Use HTTPS if True.
    """

    def __init__(
        self,
        endpoint: str,
        access_key: str,
        secret_key: str,
        bucket: str,
        secure: bool = False,
    ) -> None:
        self._client = Minio(endpoint, access_key=access_key, secret_key=secret_key, secure=secure)
        self._bucket = bucket
        self._ensure_bucket()

    def _ensure_bucket(self) -> None:
        try:
            if not self._client.bucket_exists(self._bucket):
                self._client.make_bucket(self._bucket)
                logger.info(f"Created MinIO bucket: {self._bucket}")
        except S3Error as exc:
            logger.error(f"Could not ensure bucket {self._bucket}: {exc}")

    def write(self, symbol: str, data_type: str, data: dict) -> str:
        """Serialise data as JSON and upload to MinIO.

        Args:
            symbol: Ticker symbol (used in filename).
            data_type: Category label e.g. 'prices', 'balance_sheet'.
            data: Payload to store.

        Returns:
            MinIO object path of the uploaded file.
        """
        timestamp = datetime.utcnow().strftime("%Y%m%d%H%M%S")
        object_name = f"russell/{data_type}/{symbol.strip()}_{timestamp}.json"
        content = json.dumps(data, default=str).encode("utf-8")

        self._client.put_object(
            self._bucket,
            object_name,
            io.BytesIO(content),
            length=len(content),
            content_type="application/json",
        )
        logger.info(f"Uploaded {object_name} to MinIO bucket {self._bucket}")
        return object_name
