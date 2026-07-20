"""
Cold-path Lambda: batch aggregation of ambient IoT telemetry.

In production this function is triggered on a schedule (e.g. every 5
minutes via EventBridge) or by an S3 PUT event when the hot path
buffers records into an S3 bucket. It reads a batch of hot-path
records, aggregates them by zone and metric, and writes a summary
to S3 as a CSV row (building up a long-term time-series dataset).

Locally it reads from the hot-path JSONL file written by the hot
path Lambda and writes a CSV to /tmp/cold_path_aggregates.csv.
This CSV is the source dataset for the Power BI dashboard.

Why batch aggregation matters for the dissertation
--------------------------------------------------
Real ambient IoT deployments produce thousands of readings per minute.
Storing every raw reading in a queryable database is expensive at scale.
The cold path solves this by:
  1. Aggregating readings into per-zone, per-metric summaries.
  2. Computing trend indicators (rolling avg, min/max, alert rate).
  3. Writing compact CSV rows to S3 for long-term storage.
Power BI then connects to S3 (or the local CSV) to build the
"Asset Health" and "Carbon Savings" dashboard described in the proposal.
"""

from __future__ import annotations

import csv
import io
import json
import logging
import os
import time
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from statistics import mean, stdev

import boto3

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

# Local I/O paths (replaced by S3 in production)
HOT_PATH_OUTPUT  = Path(os.environ.get("HOT_PATH_OUTPUT",  "/tmp/hot_path_results.jsonl"))
COLD_PATH_OUTPUT = Path(os.environ.get("COLD_PATH_OUTPUT", "/tmp/cold_path_aggregates.csv"))

CSV_HEADERS = [
    "aggregated_at", "zone", "metric",
    "reading_count", "avg_value", "min_value", "max_value", "stddev_value",
    "alert_count", "alert_rate_pct",
    "avg_total_latency_ms", "max_total_latency_ms",
]


def _load_records(source_path: Path) -> list[dict]:
    if not source_path.exists():
        logger.warning("no hot-path output found at %s", source_path)
        return []
    records = []
    with source_path.open() as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    records.append(json.loads(line))
                except json.JSONDecodeError:
                    logger.warning("skipping malformed line: %s", line[:60])
    return records


def _load_records_from_event(event: dict) -> list[dict]:
    if "Records" in event:
        records = []
        for rec in event["Records"]:
            try:
                payload = rec.get("kinesis", {}).get("data") or rec.get("body", "{}")
                records.append(json.loads(payload))
            except Exception:
                pass
        return records
    return _load_records(HOT_PATH_OUTPUT)


def aggregate(records: list[dict]) -> list[dict]:
    if not records:
        return []

    groups: dict[tuple, list[dict]] = defaultdict(list)
    for rec in records:
        key = (rec.get("zone", "unknown"), rec.get("metric", "unknown"))
        groups[key].append(rec)

    aggregated_at = datetime.now(timezone.utc).isoformat()
    summaries = []

    for (zone, metric), recs in sorted(groups.items()):
        values    = [r["value"] for r in recs if isinstance(r.get("value"), (int, float))]
        latencies = [r["total_latency_ms"] for r in recs if r.get("total_latency_ms")]
        alerts    = [r for r in recs if r.get("alert")]

        if not values:
            continue

        summary = {
            "aggregated_at":        aggregated_at,
            "zone":                 zone,
            "metric":               metric,
            "reading_count":        len(values),
            "avg_value":            round(mean(values), 3),
            "min_value":            round(min(values), 3),
            "max_value":            round(max(values), 3),
            "stddev_value":         round(stdev(values), 3) if len(values) > 1 else 0.0,
            "alert_count":          len(alerts),
            "alert_rate_pct":       round(len(alerts) / len(recs) * 100, 1),
            "avg_total_latency_ms": round(mean(latencies), 3) if latencies else 0.0,
            "max_total_latency_ms": round(max(latencies), 3) if latencies else 0.0,
        }
        summaries.append(summary)
        logger.info("aggregated zone=%s metric=%s readings=%d alerts=%d avg=%.2f",
                    zone, metric, len(values), len(alerts), summary["avg_value"])

    return summaries


def _write_csv(summaries: list[dict], output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    write_header = not output_path.exists()
    with output_path.open("a", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_HEADERS)
        if write_header:
            writer.writeheader()
        for row in summaries:
            writer.writerow({k: row.get(k, "") for k in CSV_HEADERS})
    logger.info("wrote %d rows to %s", len(summaries), output_path)


def _write_s3(summaries: list[dict]) -> str:
    """Write aggregated CSV to S3 cold store. Returns the S3 key."""
    bucket  = os.environ.get("S3_BUCKET", "aiot-cold-store-255195626087")
    s3      = boto3.client("s3", region_name="eu-west-2")
    date    = datetime.now(timezone.utc).strftime("%Y/%m/%d")
    ts      = datetime.now(timezone.utc).strftime("%H%M%S")
    key     = f"aggregates/{date}/cold_path_{ts}.csv"

    # Build CSV in memory
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=CSV_HEADERS)
    writer.writeheader()
    for row in summaries:
        writer.writerow({k: row.get(k, "") for k in CSV_HEADERS})

    s3.put_object(
        Bucket=bucket,
        Key=key,
        Body=buf.getvalue().encode("utf-8"),
        ContentType="text/csv",
    )
    logger.info("written to s3://%s/%s", bucket, key)
    return f"s3://{bucket}/{key}"


def handler(event: dict, context=None) -> dict:
    """
    AWS Lambda entry point.

    Production trigger: EventBridge schedule rate(5 minutes)
    or S3 ObjectCreated on the hot-path buffer bucket.
    """
    try:
        records = _load_records_from_event(event)
        if not records:
            return {"statusCode": 200, "body": "no records to process"}

        summaries = aggregate(records)

        # Write to S3 when running on AWS, local CSV otherwise
        if os.environ.get("AWS_EXECUTION_ENV"):
            output = _write_s3(summaries)
        else:
            _write_csv(summaries, COLD_PATH_OUTPUT)
            output = str(COLD_PATH_OUTPUT)

        return {
            "statusCode": 200,
            "body": json.dumps({
                "records_processed": len(records),
                "summaries_written": len(summaries),
                "output": output,
            }),
        }

    except Exception as exc:
        logger.exception("cold-path handler error: %s", exc)
        return {"statusCode": 500, "body": str(exc)}


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s [%(levelname)s] %(message)s")

    print("\n" + "=" * 60)
    print("  COLD PATH LAMBDA -- LOCAL TEST")
    print("=" * 60)

    if not HOT_PATH_OUTPUT.exists():
        print(f"No hot-path data at {HOT_PATH_OUTPUT}")
        print("Run hot-path/index.py first to generate input data.")
    else:
        response = handler({})
        body = json.loads(response["body"])
        print(f"\nRecords processed : {body['records_processed']}")
        print(f"Summaries written : {body['summaries_written']}")
        print(f"CSV output        : {body['output']}")
        print("\n--- Aggregated Results ---")
        with COLD_PATH_OUTPUT.open() as f:
            for line in f:
                print(line.strip())

    print("=" * 60)