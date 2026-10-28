"""Scheduled offline evaluations use fictional fixtures, never departmental records."""
import asyncio
import json

from celery import shared_task
from fastapi import APIRouter, Depends, HTTPException

from app import storage
from app.auth import Principal, get_principal, require_permission
from app.evaluation import evaluate

router = APIRouter(tags=["evaluations"])
REPORT_KEY = "evaluations/deterministic/latest.json"


@shared_task(name="app.evaluations.run_scheduled_evaluation", max_retries=3,
             autoretry_for=(OSError,), retry_backoff=60, retry_backoff_max=600)
def run_scheduled_evaluation():
    report = asyncio.run(evaluate(live=False))
    storage.put(REPORT_KEY, json.dumps(report).encode(), "application/json")
    # Celery result/log metadata contains no model inputs or document contents.
    return {"status": "completed", "mode": report["mode"], "evaluated_at": report["evaluated_at"]}


@router.get("/evaluations/latest")
def latest_evaluation(p: Principal = Depends(get_principal)):
    require_permission(p, "platform:admin")
    try:
        return json.loads(storage.get(REPORT_KEY))
    except FileNotFoundError:
        raise HTTPException(404, "No scheduled evaluation report is available yet") from None
    except Exception as exc:
        # Distinguish a missing S3 object from a broken storage connection.
        from botocore.exceptions import ClientError
        if isinstance(exc, ClientError) and exc.response.get("Error", {}).get("Code") in {"NoSuchKey", "404"}:
            raise HTTPException(404, "No scheduled evaluation report is available yet") from None
        raise HTTPException(503, "Evaluation report storage is unavailable") from None
