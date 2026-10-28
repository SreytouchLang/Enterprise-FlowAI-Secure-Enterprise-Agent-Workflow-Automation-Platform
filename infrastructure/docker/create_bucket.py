"""Idempotent development MinIO initialization; no credential values are logged."""
import time

from app.core.config import get_settings
from app.storage import client
from botocore.exceptions import ClientError, EndpointConnectionError


def initialize() -> None:
    settings = get_settings()
    if settings.is_production or not settings.s3_endpoint_url:
        raise RuntimeError("This initializer is limited to local S3-compatible development storage")
    storage = client()
    for attempt in range(60):
        try:
            storage.list_buckets()
            break
        except EndpointConnectionError:
            if attempt == 59:
                raise RuntimeError("Development object storage did not become available") from None
            time.sleep(2)
    try:
        storage.head_bucket(Bucket=settings.s3_bucket)
    except ClientError as error:
        if error.response["Error"]["Code"] not in {"404", "NoSuchBucket", "NotFound"}:
            raise
        storage.create_bucket(Bucket=settings.s3_bucket)
    storage.put_bucket_versioning(
        Bucket=settings.s3_bucket, VersioningConfiguration={"Status": "Enabled"}
    )
    print("Development document bucket is ready with versioning enabled.")


if __name__ == "__main__":
    initialize()
