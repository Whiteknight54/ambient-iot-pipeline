"""
AWS pipeline runner.

Same as scripts/run_pipeline.py but publishes to AWS IoT Core
over TLS (port 8883) instead of local Mosquitto (port 1883).

Run setup first:
    python3 infra/setup_aws_iot.py

Then run this:
    python3 scripts/run_pipeline_aws.py

Watch messages in AWS Console:
    IoT Core → Test → Subscribe to aiot/telemetry/#
"""

from __future__ import annotations

import json
import logging
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

repo_root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(repo_root / "perception-layer" / "app"))
sys.path.insert(0, str(repo_root / "edge-gateway" / "app"))

from tag_simulator import TagSwarm
from auth_bridge import EdgeGateway, inject_rogue_packet
from mqtt_publisher import MQTTPublisher

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("pipeline_aws")

CONFIG_PATH  = repo_root / "infra" / "aws_config.json"
METRICS_OUT  = repo_root / "docs" / "evaluation" / "aiot_metrics_aws.json"

ZONES        = ["greenhouse-A", "greenhouse-B"]
TAGS_PER_ZONE = 5
POLL_CYCLES  = 10
POLL_INTERVAL_S = 0.5
INJECT_ROGUES = True
SEED         = 42


def load_config() -> dict:
    if not CONFIG_PATH.exists():
        print(f"\n❌ Config not found at {CONFIG_PATH}")
        print("   Run setup first: python3 infra/setup_aws_iot.py")
        sys.exit(1)
    return json.loads(CONFIG_PATH.read_text())


def run() -> None:
    config = load_config()

    print("\n" + "=" * 60)
    print("  AMBIENT IoT PIPELINE — AWS IoT Core")
    print("=" * 60)
    print(f"  Endpoint : {config['endpoint']}")
    print(f"  Region   : {config['region']}")
    print(f"  Thing    : {config['thing_name']}")
    print("=" * 60 + "\n")

    # Perception layer
    swarm = TagSwarm(zones=ZONES, tags_per_zone=TAGS_PER_ZONE, seed=SEED)
    logger.info("swarm: %s tags across zones %s", len(swarm.tags), ZONES)

    # Edge gateway
    gateway = EdgeGateway(known_keys=swarm.keys_by_tag_id())

    # AWS IoT Core publisher (TLS)
    publisher = MQTTPublisher(
        broker_host=config["endpoint"],
        broker_port=config["mqtt_port"],       # 8883
        client_id=config["thing_name"],
        tls_cert=config["cert_file"],
        tls_key=config["key_file"],
        tls_ca=config["ca_file"],
    )

    connected = publisher.connect()
    if not connected:
        logger.error("Could not connect to AWS IoT Core — check certs and endpoint")
        sys.exit(1)

    logger.info("Connected to AWS IoT Core ✅")
    logger.info("Running %s poll cycles...", POLL_CYCLES)
    run_start = time.time()

    for cycle_num in range(1, POLL_CYCLES + 1):
        raw_packets = swarm.poll_cycle()

        if INJECT_ROGUES and cycle_num % 3 == 0:
            raw_packets.append(inject_rogue_packet())

        translated = gateway.ingest_batch(raw_packets)
        results    = publisher.publish_batch(translated)
        published  = sum(1 for r in results if r.success)

        logger.info(
            "cycle %02d | polled=%d auth_ok=%d published=%d rogues=%d",
            cycle_num, len(raw_packets), len(translated),
            published, gateway.stats.rejected_unknown_tag,
        )
        time.sleep(POLL_INTERVAL_S)

    run_duration_s = round(time.time() - run_start, 2)

    metrics = {
        "run_at":    datetime.now(timezone.utc).isoformat(),
        "target":    "aws_iot_core",
        "endpoint":  config["endpoint"],
        "region":    config["region"],
        "config": {
            "zones": ZONES, "tags_per_zone": TAGS_PER_ZONE,
            "poll_cycles": POLL_CYCLES, "seed": SEED,
        },
        "gateway_stats":   gateway.stats.as_dict(),
        "publisher_stats": publisher.metrics.as_dict(),
        "run_duration_s":  run_duration_s,
        "throughput_msgs_per_s": round(
            publisher.metrics.total_published / run_duration_s, 2
        ) if run_duration_s > 0 else 0,
    }

    METRICS_OUT.parent.mkdir(parents=True, exist_ok=True)
    METRICS_OUT.write_text(json.dumps(metrics, indent=2))

    pub = metrics["publisher_stats"]
    gw  = metrics["gateway_stats"]

    print("\n" + "=" * 60)
    print("  AWS PIPELINE RUN SUMMARY")
    print("=" * 60)
    print(f"  Total packets seen      : {gw['total_seen']}")
    print(f"  Authenticated           : {gw['accepted']}")
    print(f"  Rogue rejections        : {gw['rejected_unknown_tag']}")
    print(f"  Published to IoT Core   : {pub['total_published']}")
    print(f"  Avg pipeline latency    : {pub['avg_latency_ms']} ms")
    print(f"  Throughput              : {metrics['throughput_msgs_per_s']} msg/s")
    print(f"  Run duration            : {run_duration_s}s")
    print(f"  Metrics saved to        : {METRICS_OUT}")
    print("=" * 60)
    print("\n  Check AWS Console:")
    print("  IoT Core → Test → Subscribe to aiot/telemetry/#")

    publisher.disconnect()


if __name__ == "__main__":
    run()