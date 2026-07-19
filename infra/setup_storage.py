"""
Storage provisioning script.

Creates the S3 bucket (cold store) and DynamoDB table (hot store)
needed to complete the full production pipeline:

  AWS IoT Core
       ↓
  Hot-path Lambda  →  DynamoDB (hot store)  ← real-time queries
  Cold-path Lambda →  S3 bucket (cold store) ← Tableau connects here

Run once after setup_aws_iot.py:
    python3 infra/setup_storage.py

Then redeploy the Lambdas:
    python3 infra/deploy_lambdas.py
"""

from __future__ import annotations

import json
import time
from pathlib import Path

import boto3
from botocore.exceptions import ClientError

REGION         = "eu-west-2"
S3_BUCKET      = "aiot-cold-store-255195626087"   # must be globally unique
DYNAMODB_TABLE = "aiot-telemetry"
CONFIG_PATH    = Path(__file__).parent / "aws_config.json"


def create_s3_bucket(s3: any) -> str:
    """Create the S3 cold store bucket."""
    try:
        s3.create_bucket(
            Bucket=S3_BUCKET,
            CreateBucketConfiguration={"LocationConstraint": REGION},
        )
        # Block all public access
        s3.put_public_access_block(
            Bucket=S3_BUCKET,
            PublicAccessBlockConfiguration={
                "BlockPublicAcls": True,
                "IgnorePublicAcls": True,
                "BlockPublicPolicy": True,
                "RestrictPublicBuckets": True,
            },
        )
        print(f"  ✅ S3 bucket created: {S3_BUCKET}")
        print(f"     Region  : {REGION}")
        print(f"     Access  : private (public access blocked)")
    except ClientError as e:
        if e.response["Error"]["Code"] in (
            "BucketAlreadyOwnedByYou", "BucketAlreadyExists"
        ):
            print(f"  ℹ️  S3 bucket already exists: {S3_BUCKET}")
        else:
            raise
    return S3_BUCKET


def create_dynamodb_table(dynamodb: any) -> str:
    """Create the DynamoDB hot store table."""
    try:
        table = dynamodb.create_table(
            TableName=DYNAMODB_TABLE,
            KeySchema=[
                {"AttributeName": "tag_id",   "KeyType": "HASH"},
                {"AttributeName": "timestamp", "KeyType": "RANGE"},
            ],
            AttributeDefinitions=[
                {"AttributeName": "tag_id",   "AttributeType": "S"},
                {"AttributeName": "timestamp", "AttributeType": "S"},
            ],
            BillingMode="PAY_PER_REQUEST",  # no capacity planning needed
            Tags=[
                {"Key": "project", "Value": "ambient-iot-pipeline"},
                {"Key": "stage",   "Value": "hot-store"},
            ],
        )
        # Wait for table to be active
        print(f"  ⏳ Waiting for DynamoDB table to be active...")
        waiter = dynamodb.get_waiter("table_exists")
        waiter.wait(TableName=DYNAMODB_TABLE)
        print(f"  ✅ DynamoDB table created: {DYNAMODB_TABLE}")
        print(f"     Partition key : tag_id (String)")
        print(f"     Sort key      : timestamp (String)")
        print(f"     Billing       : Pay-per-request")
    except ClientError as e:
        if e.response["Error"]["Code"] == "ResourceInUseException":
            print(f"  ℹ️  DynamoDB table already exists: {DYNAMODB_TABLE}")
        else:
            raise
    return DYNAMODB_TABLE


def update_config(s3_bucket: str, dynamodb_table: str) -> None:
    """Add storage config to aws_config.json."""
    if not CONFIG_PATH.exists():
        print(f"  ⚠️  {CONFIG_PATH} not found — run setup_aws_iot.py first")
        return
    config = json.loads(CONFIG_PATH.read_text())
    config["s3_bucket"]      = s3_bucket
    config["dynamodb_table"] = dynamodb_table
    CONFIG_PATH.write_text(json.dumps(config, indent=2))
    print(f"  ✅ Config updated: {CONFIG_PATH}")


def grant_lambda_storage_access(iam: any) -> None:
    """
    Attach S3 and DynamoDB policies to the Lambda execution role
    so both functions can write to storage.
    """
    role_name = "aiot-lambda-role"
    policies = [
        "arn:aws:iam::aws:policy/AmazonDynamoDBFullAccess",
        "arn:aws:iam::aws:policy/AmazonS3FullAccess",
    ]
    for policy_arn in policies:
        try:
            iam.attach_role_policy(RoleName=role_name, PolicyArn=policy_arn)
            print(f"  ✅ Attached: {policy_arn.split('/')[-1]}")
        except ClientError as e:
            if "already attached" not in str(e).lower():
                print(f"  ⚠️  {e}")


def run() -> None:
    print("\n" + "=" * 60)
    print("  AWS STORAGE SETUP — eu-west-2 (London)")
    print("=" * 60)

    session  = boto3.Session(region_name=REGION)
    s3       = session.client("s3")
    dynamodb = session.client("dynamodb")
    iam      = session.client("iam")

    print("\n1. Creating S3 cold store bucket...")
    s3_bucket = create_s3_bucket(s3)

    print("\n2. Creating DynamoDB hot store table...")
    dynamodb_table = create_dynamodb_table(dynamodb)

    print("\n3. Granting Lambda storage permissions...")
    grant_lambda_storage_access(iam)

    print("\n4. Updating config...")
    update_config(s3_bucket, dynamodb_table)

    print("\n" + "=" * 60)
    print("  STORAGE SETUP COMPLETE")
    print("=" * 60)
    print(f"\n  S3 bucket      : {s3_bucket}")
    print(f"  DynamoDB table : {dynamodb_table}")
    print(f"\n  Next step:")
    print(f"  python3 infra/deploy_lambdas.py")
    print("=" * 60)


if __name__ == "__main__":
    run()