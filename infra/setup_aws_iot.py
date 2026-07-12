"""
AWS IoT Core setup script.

Run this once to provision all required AWS resources for the
ambient IoT pipeline in eu-west-2 (London).

What this creates:
  1. IoT Thing        — represents the MikroTik edge gateway
  2. X.509 Certificate — TLS identity for the gateway connection
  3. IoT Policy       — grants the gateway permission to publish
  4. IoT Rule         — routes MQTT messages to the hot-path Lambda
  5. Lambda functions — deploys hot and cold path from local code

Outputs:
  infra/certs/          — certificate files (in .gitignore, never commit)
  infra/aws_config.json — endpoint + resource ARNs for the pipeline

Usage:
    python3 infra/setup_aws_iot.py

Requirements:
    pip install boto3
    aws configure   (with eu-west-2 and valid credentials)
"""

from __future__ import annotations

import json
import os
import sys
import zipfile
import io
from pathlib import Path

import boto3
from botocore.exceptions import ClientError

REGION      = "eu-west-2"
THING_NAME  = "aiot-edge-gateway"
POLICY_NAME = "aiot-gateway-policy"
RULE_NAME   = "aiot_hot_path_rule"
TOPIC       = "aiot/telemetry/#"

REPO_ROOT  = Path(__file__).resolve().parent.parent
CERT_DIR   = REPO_ROOT / "infra" / "certs"
CONFIG_OUT = REPO_ROOT / "infra" / "aws_config.json"

HOT_PATH_CODE  = REPO_ROOT / "cloud" / "lambdas" / "hot-path" / "index.py"
COLD_PATH_CODE = REPO_ROOT / "cloud" / "lambdas" / "cold-path" / "index.py"


def get_account_id(session: boto3.Session) -> str:
    return session.client("sts").get_caller_identity()["Account"]


def create_thing(iot: any) -> str:
    try:
        resp = iot.create_thing(thingName=THING_NAME)
        print(f"  ✅ Thing created: {THING_NAME}")
        return resp["thingArn"]
    except ClientError as e:
        if e.response["Error"]["Code"] == "ResourceAlreadyExistsException":
            resp = iot.describe_thing(thingName=THING_NAME)
            print(f"  ℹ️  Thing already exists: {THING_NAME}")
            return resp["thingArn"]
        raise


def create_certificates(iot: any) -> dict:
    CERT_DIR.mkdir(parents=True, exist_ok=True)

    cert_file = CERT_DIR / "device.pem.crt"
    key_file  = CERT_DIR / "private.pem.key"

    if cert_file.exists() and key_file.exists():
        print("  ℹ️  Certificates already exist, skipping creation")
        # Read existing cert ARN from config if available
        if CONFIG_OUT.exists():
            cfg = json.loads(CONFIG_OUT.read_text())
            return {"certificateArn": cfg.get("certificate_arn", ""), "certificateId": ""}
        return {}

    resp = iot.create_keys_and_certificate(setAsActive=True)

    cert_file.write_text(resp["certificatePem"])
    key_file.write_text(resp["keyPair"]["PrivateKey"])

    # Download Amazon Root CA
    import urllib.request
    ca_file = CERT_DIR / "AmazonRootCA1.pem"
    urllib.request.urlretrieve(
        "https://www.amazontrust.com/repository/AmazonRootCA1.pem",
        ca_file
    )

    print(f"  ✅ Certificates saved to {CERT_DIR}/")
    print(f"     device.pem.crt   — device certificate")
    print(f"     private.pem.key  — private key (keep secret)")
    print(f"     AmazonRootCA1.pem — AWS root CA")

    return {
        "certificateArn": resp["certificateArn"],
        "certificateId":  resp["certificateId"],
    }


def create_policy(iot: any) -> str:
    policy_doc = {
        "Version": "2012-10-17",
        "Statement": [
            {
                "Effect": "Allow",
                "Action": [
                    "iot:Connect",
                    "iot:Publish",
                    "iot:Subscribe",
                    "iot:Receive",
                ],
                "Resource": f"arn:aws:iot:{REGION}:*:*",
            }
        ],
    }
    try:
        resp = iot.create_policy(
            policyName=POLICY_NAME,
            policyDocument=json.dumps(policy_doc),
        )
        print(f"  ✅ Policy created: {POLICY_NAME}")
        return resp["policyArn"]
    except ClientError as e:
        if e.response["Error"]["Code"] == "ResourceAlreadyExistsException":
            resp = iot.get_policy(policyName=POLICY_NAME)
            print(f"  ℹ️  Policy already exists: {POLICY_NAME}")
            return resp["policyArn"]
        raise


def attach_resources(iot: any, cert_arn: str, policy_name: str, thing_name: str) -> None:
    if not cert_arn:
        print("  ⚠️  Skipping attach — no certificate ARN available")
        return
    try:
        iot.attach_policy(policyName=policy_name, target=cert_arn)
        print(f"  ✅ Policy attached to certificate")
    except ClientError as e:
        if "already attached" not in str(e).lower():
            print(f"  ⚠️  Policy attach: {e}")

    try:
        iot.attach_thing_principal(thingName=thing_name, principal=cert_arn)
        print(f"  ✅ Certificate attached to Thing")
    except ClientError as e:
        if "already attached" not in str(e).lower():
            print(f"  ⚠️  Thing attach: {e}")


def _zip_lambda(source_file: Path) -> bytes:
    """Package a single Lambda index.py into a zip buffer."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.write(source_file, "index.py")
    return buf.getvalue()


def deploy_lambda(
    lam: any,
    iam: any,
    account_id: str,
    function_name: str,
    source_file: Path,
    description: str,
) -> str:
    """Deploy or update a Lambda function. Returns its ARN."""

    # Ensure execution role exists
    role_name = "aiot-lambda-role"
    try:
        role_arn = iam.get_role(RoleName=role_name)["Role"]["Arn"]
        print(f"  ℹ️  Lambda role already exists")
    except ClientError:
        trust = {
            "Version": "2012-10-17",
            "Statement": [{
                "Effect": "Allow",
                "Principal": {"Service": "lambda.amazonaws.com"},
                "Action": "sts:AssumeRole",
            }],
        }
        role_arn = iam.create_role(
            RoleName=role_name,
            AssumeRolePolicyDocument=json.dumps(trust),
            Description="Execution role for ambient IoT Lambda functions",
        )["Role"]["Arn"]
        # Attach basic execution policy
        iam.attach_role_policy(
            RoleName=role_name,
            PolicyArn="arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole",
        )
        print(f"  ✅ Lambda execution role created")
        import time; time.sleep(10)  # IAM propagation delay

    zip_bytes = _zip_lambda(source_file)

    try:
        resp = lam.create_function(
            FunctionName=function_name,
            Runtime="python3.12",
            Role=role_arn,
            Handler="index.handler",
            Code={"ZipFile": zip_bytes},
            Description=description,
            Timeout=30,
            MemorySize=128,
            Environment={"Variables": {"AWS_EXECUTION_ENV": "AWS_Lambda_python3.12"}},
        )
        print(f"  ✅ Lambda created: {function_name}")
        return resp["FunctionArn"]
    except ClientError as e:
        if e.response["Error"]["Code"] == "ResourceConflictException":
            resp = lam.update_function_code(
                FunctionName=function_name,
                ZipFile=zip_bytes,
            )
            print(f"  ✅ Lambda updated: {function_name}")
            return resp["FunctionArn"]
        raise


def create_iot_rule(iot: any, lam: any, account_id: str, hot_lambda_arn: str) -> None:
    """Create IoT Core rule that routes MQTT messages to hot-path Lambda."""

    # Grant IoT Core permission to invoke Lambda
    try:
        lam.add_permission(
            FunctionName="aiot-hot-path",
            StatementId="iot-core-invoke",
            Action="lambda:InvokeFunction",
            Principal="iot.amazonaws.com",
        )
        print("  ✅ IoT Core → Lambda permission granted")
    except ClientError as e:
        if "already exists" not in str(e).lower():
            print(f"  ⚠️  Permission: {e}")

    rule_payload = {
        "sql": f"SELECT * FROM '{TOPIC}'",
        "description": "Route ambient IoT telemetry to hot-path Lambda",
        "actions": [{
            "lambda": {"functionArn": hot_lambda_arn}
        }],
        "ruleDisabled": False,
        "awsIotSqlVersion": "2016-03-23",
    }

    try:
        iot.create_topic_rule(
            ruleName=RULE_NAME,
            topicRulePayload=rule_payload,
        )
        print(f"  ✅ IoT Rule created: {RULE_NAME}")
    except ClientError as e:
        if "already exists" not in str(e).lower():
            print(f"  ⚠️  Rule: {e}")
        else:
            print(f"  ℹ️  IoT Rule already exists: {RULE_NAME}")


def get_endpoint(iot: any) -> str:
    return iot.describe_endpoint(endpointType="iot:Data-ATS")["endpointAddress"]


def save_config(config: dict) -> None:
    CONFIG_OUT.parent.mkdir(parents=True, exist_ok=True)
    CONFIG_OUT.write_text(json.dumps(config, indent=2))
    print(f"\n  ✅ Config saved to {CONFIG_OUT}")


def run() -> None:
    print("\n" + "=" * 60)
    print("  AWS IoT CORE SETUP — eu-west-2 (London)")
    print("=" * 60)

    session    = boto3.Session(region_name=REGION)
    iot        = session.client("iot")
    lam        = session.client("lambda")
    iam        = session.client("iam")
    account_id = get_account_id(session)
    print(f"\n  Account: {account_id} | Region: {REGION}\n")

    print("1. Creating IoT Thing...")
    thing_arn = create_thing(iot)

    print("\n2. Creating certificates...")
    cert_info = create_certificates(iot)

    print("\n3. Creating IoT policy...")
    policy_arn = create_policy(iot)

    print("\n4. Attaching policy + certificate to Thing...")
    attach_resources(iot, cert_info.get("certificateArn", ""), POLICY_NAME, THING_NAME)

    print("\n5. Deploying hot-path Lambda...")
    hot_arn = deploy_lambda(
        lam, iam, account_id,
        "aiot-hot-path",
        HOT_PATH_CODE,
        "Ambient IoT hot-path: real-time classification and alerting",
    )

    print("\n6. Deploying cold-path Lambda...")
    cold_arn = deploy_lambda(
        lam, iam, account_id,
        "aiot-cold-path",
        COLD_PATH_CODE,
        "Ambient IoT cold-path: batch aggregation",
    )

    print("\n7. Creating IoT Core rule...")
    create_iot_rule(iot, lam, account_id, hot_arn)

    print("\n8. Getting IoT endpoint...")
    endpoint = get_endpoint(iot)
    print(f"  ✅ Endpoint: {endpoint}")

    config = {
        "region":           REGION,
        "endpoint":         endpoint,
        "thing_name":       THING_NAME,
        "thing_arn":        thing_arn,
        "certificate_arn":  cert_info.get("certificateArn", ""),
        "cert_file":        str(CERT_DIR / "device.pem.crt"),
        "key_file":         str(CERT_DIR / "private.pem.key"),
        "ca_file":          str(CERT_DIR / "AmazonRootCA1.pem"),
        "hot_lambda_arn":   hot_arn,
        "cold_lambda_arn":  cold_arn,
        "mqtt_topic":       "aiot/telemetry",
        "mqtt_port":        8883,
    }
    save_config(config)

    print("\n" + "=" * 60)
    print("  SETUP COMPLETE")
    print("=" * 60)
    print(f"\n  IoT endpoint : {endpoint}")
    print(f"  Certs folder : {CERT_DIR}/")
    print(f"  Config file  : {CONFIG_OUT}")
    print("\n  Next step:")
    print("  python3 scripts/run_pipeline_aws.py")
    print("=" * 60)


if __name__ == "__main__":
    run()