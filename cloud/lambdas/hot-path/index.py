"""
Hot-path Lambda: real-time ambient IoT telemetry processing.

In production this function is triggered by AWS IoT Core Rules Engine
every time a message arrives on the topic pattern:
    aiot/telemetry/<zone>/<tag_id>

Locally it is called directly with a mocked event dict (see
__main__ block at the bottom) so it can be tested without an AWS
account -- this is the "local/mocked first" methodology documented
in the project proposal.

Responsibilities
----------------
1. Parse and validate the incoming MQTT payload.
2. Classify the reading: NORMAL / WARNING / CRITICAL.
3. Detect anomalies (temperature spikes, signal loss).
4. Emit a structured processing result with latency metrics.
5. In production: write to DynamoDB (hot store) for real-time dashboard.
   Locally: write to a JSON file under /tmp/hot_path_results.jsonl.

Why a separate hot path?
------------------------
Ambient IoT generates high-velocity, small payloads. Routing every
message through a synchronous database write would create a bottleneck.
The Lambda architecture separates concerns:
  Hot path  -> low-latency, per-message, real-time alerts
  Cold path -> batched, aggregated, long-term trend storage
This is the Big Data Lambda Architecture pattern cited in the proposal
(AWS, 2024; Microsoft Azure, 2024).
"""

from __future__ import annotations

import json
import logging
import os
import time
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

import boto3

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

# Alert thresholds
TEMP_WARNING_C  = 28.0
TEMP_CRITICAL_C = 35.0
RSSI_WARNING_DBM = -80.0
TEMP_MIN_C = 5.0

# Local output (replaces DynamoDB for local dev)
LOCAL_OUTPUT = Path(os.environ.get("HOT_PATH_OUTPUT", "/tmp/hot_path_results.jsonl"))


def _classify_temperature(value: float) -> str:
    if value >= TEMP_CRITICAL_C:
        return "CRITICAL"
    if value >= TEMP_WARNING_C or value <= TEMP_MIN_C:
        return "WARNING"
    return "NORMAL"


def _classify_rssi(value: float) -> str:
    if value <= RSSI_WARNING_DBM:
        return "WARNING"
    return "NORMAL"


def _classify(metric: str, value: float) -> str:
    if metric == "temperature_c":
        return _classify_temperature(value)
    if metric == "rssi_dbm":
        return _classify_rssi(value)
    return "NORMAL"


def _parse_payload(event: dict) -> dict:
    if "body" in event and isinstance(event["body"], str):
        return json.loads(event["body"])
    return event


def process(payload: dict) -> dict:
    """
    Core processing logic -- separated from handler() so it can be
    unit tested without a Lambda context object.
    """
    process_start = time.time()

    tag_id  = payload.get("tag_id", "unknown")
    zone    = payload.get("zone",   "unknown")
    metric  = payload.get("metric", "unknown")
    value   = payload.get("value")
    tag_ts  = payload.get("tag_ts", process_start)
    pipeline_latency_ms = payload.get("pipeline_latency_ms", 0.0)

    if value is None:
        return {"status": "ERROR", "reason": "missing value field", "tag_id": tag_id}

    classification = _classify(metric, value)
    process_ts      = time.time()
    lambda_latency_ms = round((process_ts - process_start) * 1000, 3)
    total_latency_ms  = round(pipeline_latency_ms + lambda_latency_ms, 3)

    result = {
        "tag_id":         tag_id,
        "zone":           zone,
        "metric":         metric,
        "value":          value,
        "classification": classification,
        "alert":          classification != "NORMAL",
        "tag_ts":         tag_ts,
        "process_ts":     process_ts,
        "processed_at":   datetime.now(timezone.utc).isoformat(),
        "pipeline_latency_ms": pipeline_latency_ms,
        "lambda_latency_ms":   lambda_latency_ms,
        "total_latency_ms":    total_latency_ms,
    }

    if classification != "NORMAL":
        logger.warning("ALERT [%s] zone=%s tag=%s %s=%.2f",
                       classification, zone, tag_id, metric, value)
    else:
        logger.info("OK zone=%s tag=%s %s=%.2f latency=%.2fms",
                    zone, tag_id, metric, value, total_latency_ms)

    return result


def _write_local(result: dict) -> None:
    LOCAL_OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    with LOCAL_OUTPUT.open("a") as f:
        f.write(json.dumps(result) + "\n")


def _write_dynamodb(result: dict) -> None:
    """Write processed record to DynamoDB hot store."""
    table_name = os.environ.get("DYNAMODB_TABLE", "aiot-telemetry")
    dynamodb   = boto3.resource("dynamodb", region_name="eu-west-2")
    table      = dynamodb.Table(table_name)
    # DynamoDB requires Decimal instead of float for numeric values.
    item = {
        k: Decimal(str(v)) if isinstance(v, float) else str(v) if isinstance(v, bool) else v
        for k, v in result.items()
    }
    # Ensure required keys exist
    item["tag_id"]    = result.get("tag_id", "unknown")
    item["timestamp"] = result.get("processed_at", datetime.now(timezone.utc).isoformat())
    table.put_item(Item=item)
    logger.info("written to DynamoDB table=%s tag=%s", table_name, item["tag_id"])


def handler(event: dict, context=None) -> dict:
    """
    AWS Lambda entry point.

    IoT Core Rule SQL to wire this up in production:
        SELECT * FROM 'aiot/telemetry/#'
        Action: Lambda -> arn:aws:lambda:...:hot-path
    """
    try:
        payload = _parse_payload(event)
        result  = process(payload)

        # Write to DynamoDB when running on AWS
        if os.environ.get("AWS_EXECUTION_ENV"):
            _write_dynamodb(result)
        else:
            _write_local(result)

        return {"statusCode": 200, "body": json.dumps(result)}

    except Exception as exc:
        logger.exception("hot-path handler error: %s", exc)
        return {"statusCode": 500, "body": str(exc)}


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s [%(levelname)s] %(message)s")

    test_events = [
        {"tag_id": "abc123def456", "zone": "greenhouse-A",
         "metric": "temperature_c", "value": 22.4,
         "tag_ts": time.time(), "pipeline_latency_ms": 0.35},

        {"tag_id": "abc123def456", "zone": "greenhouse-A",
         "metric": "temperature_c", "value": 31.2,
         "tag_ts": time.time(), "pipeline_latency_ms": 0.41},

        {"tag_id": "ff00aa112233", "zone": "greenhouse-B",
         "metric": "temperature_c", "value": 38.7,
         "tag_ts": time.time(), "pipeline_latency_ms": 0.29},

        {"tag_id": "112233aabbcc", "zone": "greenhouse-B",
         "metric": "rssi_dbm", "value": -83.5,
         "tag_ts": time.time(), "pipeline_latency_ms": 0.55},
    ]

    print("\n" + "=" * 60)
    print("  HOT PATH LAMBDA -- LOCAL TEST")
    print("=" * 60)
    for event in test_events:
        response = handler(event)
        body = json.loads(response["body"])
        icon = "🚨" if body.get("alert") else "✅"
        print(f"{icon}  [{body['classification']:8s}] zone={body['zone']} "
              f"metric={body['metric']} value={body['value']} "
              f"total_latency={body['total_latency_ms']}ms")
    print("=" * 60)
    print(f"\nResults written to: {LOCAL_OUTPUT}")