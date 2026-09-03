# Cloud Ingestion

AWS serverless ingestion: IoT Core routes each MQTT message to a hot-path
Lambda for real-time classification, while a cold-path Lambda batches and
aggregates readings for long-term trend storage. This is the Big Data
Lambda Architecture pattern - a low-latency hot path and a batched cold
path sharing one ingestion source, rather than routing every message
through a synchronous database write.

`iot-core/rules.json` wires the topic pattern `aiot/telemetry/#` to the
hot-path Lambda via the IoT Core Rules Engine.

## Hot path (`lambdas/hot-path/`)

Runs per message. Classifies each reading as `NORMAL` / `WARNING` /
`CRITICAL` against fixed thresholds (temperature, RSSI), computes
end-to-end latency by adding its own processing time to the
`pipeline_latency_ms` already stamped by the gateway, and writes one row
to DynamoDB (hot store) for real-time queries. Locally, DynamoDB is
replaced by a JSONL file so the handler is testable without an AWS
account - `process()` is factored out from `handler()` for exactly this
reason.

## Cold path (`lambdas/cold-path/`)

Runs on a schedule (production: EventBridge, every 5 minutes) or against
the hot path's local JSONL output. Groups readings by zone and metric,
computes count/mean/min/max/stddev and alert rate per group, and appends
one summary row per group to a CSV in S3 (cold store). This CSV is the
source dataset for the Tableau dashboard's trend and carbon-savings
pages. Locally it reads the hot path's JSONL file and writes to a local
CSV instead of S3.

## Observability limitation

Both handlers catch all exceptions and return `{"statusCode": 500, ...}`
as a normal Lambda return value rather than raising. IoT Core Rules
Engine invokes Lambda asynchronously and never inspects that status code,
so a functional failure inside the handler is invisible to CloudWatch's
Lambda error/success metrics - it only shows up in the target service's
own metrics (e.g. DynamoDB `ThrottledRequests`). This was observed
directly during the AWS stress run: CloudWatch reported 100% Lambda
success throughout, while DynamoDB recorded 719 throttle events at peak.
Documented as a limitation in the evaluation chapter rather than fixed,
since reproducing it was itself evidence for the finding.

Tests: `python -m pytest cloud/tests -v` (13 tests - 9 hot-path
classification/latency/error-handling cases, 4 cold-path aggregation
cases)
