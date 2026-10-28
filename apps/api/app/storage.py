"""Private object access. The application never accepts object URLs or filesystem paths from users."""
from pathlib import Path

import boto3

from app.core.config import get_settings


def client():
    s = get_settings()
    return boto3.client("s3", endpoint_url=s.s3_endpoint_url or None, region_name=s.s3_region, aws_access_key_id=s.s3_access_key or None, aws_secret_access_key=s.s3_secret_key or None)


def local_path(key: str) -> Path:
    root = Path(get_settings().storage_path).resolve()
    path = (root / key).resolve()
    if not path.is_relative_to(root):
        raise ValueError("Invalid storage key")
    return path


def put(key: str, data: bytes, content_type: str):
    s = get_settings()
    if s.storage_backend == "s3":
        args = {"Bucket": s.s3_bucket, "Key": key, "Body": data, "ContentType": content_type}
        if not s.s3_endpoint_url:
            args["ServerSideEncryption"] = "AES256"
        client().put_object(**args)
    else:
        path = local_path(key)
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        path.write_bytes(data)
        path.chmod(0o600)


def get(key: str) -> bytes:
    s = get_settings()
    if s.storage_backend == "s3":
        return client().get_object(Bucket=s.s3_bucket, Key=key)["Body"].read(s.max_upload_mb * 1024 * 1024 + 1)
    return local_path(key).read_bytes()


def delete(key: str):
    s = get_settings()
    if s.storage_backend == "s3":
        s3 = client()
        # Delete all versions, not just add a delete marker to a versioned bucket.
        for page in s3.get_paginator("list_object_versions").paginate(Bucket=s.s3_bucket, Prefix=key):
            objects = [{"Key": obj["Key"], "VersionId": obj["VersionId"]} for group in ("Versions", "DeleteMarkers") for obj in page.get(group, []) if obj["Key"] == key]
            if objects:
                s3.delete_objects(Bucket=s.s3_bucket, Delete={"Objects": objects})
        s3.delete_object(Bucket=s.s3_bucket, Key=key)
    else:
        local_path(key).unlink(missing_ok=True)
