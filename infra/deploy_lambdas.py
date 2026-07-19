"""
Lambda redeployment script.

Updates both hot-path and cold-path Lambda functions with the
storage-wired versions and sets the required environment variables:
  - DYNAMODB_TABLE  → hot-path Lambda
  - S3_BUCKET       → cold-path Lambda

Run after setup_storage.py:
    python3 infra/deploy_lambdas.py
"""

from __future__ import annotations

import io
import json
import zipfile
from pathlib import Path

import boto3
from botocore.exceptions import ClientError

REGION     = "eu-west-2"
CONFIG     = Path(__file__).parent / "aws_config.json"
REPO_ROOT  = Path(__file__).resolve().parents[1]

HOT_PATH   = REPO_ROOT / "cloud" / "lambdas" / "hot-path"  / "index.py"
COLD_PATH  = REPO_ROOT / "cloud" / "lambdas" / "cold-path" / "index.py"


def _zip(source: Path) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.write(source, "index.py")
    return buf.getvalue()


def _update(lam, name: str, source: Path, env_vars: dict) -> None:
    print(f"\n  Updating {name}...")

    # Update code
    lam.update_function_code(
        FunctionName=name,
        ZipFile=_zip(source),
    )

    # Wait for update to complete
    waiter = lam.get_waiter("function_updated")
    waiter.wait(FunctionName=name)

    # Update environment variables
    lam.update_function_configuration(
        FunctionName=name,
        Environment={"Variables": env_vars},
    )

    waiter.wait(FunctionName=name)
    print(f"  ✅ {name} updated")
    for k, v in env_vars.items():
        print(f"     {k} = {v}")


def run() -> None:
    print("\n" + "=" * 60)
    print("  LAMBDA REDEPLOYMENT — eu-west-2 (London)")
    print("=" * 60)

    if not CONFIG.exists():
        print(f"\n❌ Config not found: {CONFIG}")
        print("   Run setup_aws_iot.py and setup_storage.py first")
        return

    cfg = json.loads(CONFIG.read_text())
    s3_bucket  = cfg.get("s3_bucket",      "aiot-cold-store-255195626087")
    ddb_table  = cfg.get("dynamodb_table", "aiot-telemetry")

    lam = boto3.client("lambda", region_name=REGION)

    _update(
        lam,
        "aiot-hot-path",
        HOT_PATH,
        {
            "AWS_EXECUTION_ENV": "AWS_Lambda_python3.12",
            "DYNAMODB_TABLE":    ddb_table,
        },
    )

    _update(
        lam,
        "aiot-cold-path",
        COLD_PATH,
        {
            "AWS_EXECUTION_ENV": "AWS_Lambda_python3.12",
            "S3_BUCKET":         s3_bucket,
        },
    )

    print("\n" + "=" * 60)
    print("  REDEPLOYMENT COMPLETE")
    print("=" * 60)
    print("\n  Both Lambdas now write to storage:")
    print(f"  Hot-path  → DynamoDB  : {ddb_table}")
    print(f"  Cold-path → S3 bucket : {s3_bucket}")
    print("\n  Next step:")
    print("  python3 scripts/run_pipeline_aws.py")
    print("\n  Then connect Tableau to S3:")
    print(f"  Bucket : {s3_bucket}")
    print(f"  Prefix : aggregates/")
    print("=" * 60)


if __name__ == "__main__":
    run()