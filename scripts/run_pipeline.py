"""
Local pipeline runner.

Ties together all three completed stages:

  [Perception Layer]  ->  [Edge Gateway]  ->  [MQTT Broker]
   tag_simulator.py       auth_bridge.py     mqtt_publisher.py

Run this script to see the full local pipeline in action before
connecting to AWS IoT Core. It also saves an evaluation snapshot
(JSON) to /tmp/aiot_metrics.json after each run -- that file is
the raw data for your dissertation's Evaluation chapter figures.

Usage:
  # Start Mosquitto first (if not auto-started):
  mosquitto -d -p 1883

  # Then run the pipeline:
  python3 scripts/run_pipeline.py

  # Watch messages arrive (separate terminal):
  mosquitto_sub -h localhost -t "aiot/telemetry/#" -v
"""

from __future__ import annotations

import json
import logging
import subprocess
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
logger = logging.getLogger("pipeline")

# ── Config ────────────────────────────────────────────────────────────────────

ZONES = ["greenhouse-A", "greenhouse-B"]
TAGS_PER_ZONE = 5
POLL_CYCLES = 10
POLL_INTERVAL_S = 0.5
INJECT_ROGUES = True
METRICS_OUTPUT = Path("/tmp/aiot_metrics.json")
SEED = 42


def start_mosquitto() -> subprocess.Popen | None:
    try:
        proc = subprocess.Popen(
            ["mosquitto", "-p", "1883", "-v"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        time.sleep(0.5)
        if proc.poll() is None:
            logger.info("mosquitto started (pid=%s)", proc.pid)
            return proc
        else:
            return None
    except FileNotFoundError:
        logger.warning("mosquitto not found on PATH -- start it manually")
        return None


def run(cycles: int = POLL_CYCLES) -> dict:
    """Run the full local pipeline and return a metrics snapshot."""

    # 1 -- Bootstrap MQTT broker
    broker_proc = start_mosquitto()
    time.sleep(0.3)

    # 2 -- Perception layer
    swarm = TagSwarm(zones=ZONES, tags_per_zone=TAGS_PER_ZONE, seed=SEED)
    logger.info("swarm: %s tags across zones %s", len(swarm.tags), ZONES)

    # 3 -- Edge gateway
    gateway = EdgeGateway(known_keys=swarm.keys_by_tag_id())

    # 4 -- MQTT publisher
    publisher = MQTTPublisher(broker_host="localhost", broker_port=1883)
    connected = publisher.connect()
    if not connected:
        logger.error("could not connect to MQTT broker -- is Mosquitto running?")
        if broker_proc:
            broker_proc.terminate()
        return {}

    logger.info("pipeline ready -- running %s poll cycles", cycles)
    run_start = time.time()

    # 5 -- Main polling loop
    for cycle_num in range(1, cycles + 1):
        raw_packets = swarm.poll_cycle()

        if INJECT_ROGUES and cycle_num % 3 == 0:
            raw_packets.append(inject_rogue_packet())

        translated = gateway.ingest_batch(raw_packets)
        results = publisher.publish_batch(translated)

        published = sum(1 for r in results if r.success)
        logger.info(
            "cycle %02d | polled=%d auth_ok=%d published=%d rogues_seen=%d",
            cycle_num,
            len(raw_packets),
            len(translated),
            published,
            gateway.stats.rejected_unknown_tag,
        )
        time.sleep(POLL_INTERVAL_S)

    run_duration_s = round(time.time() - run_start, 2)

    # 6 -- Build evaluation snapshot
    metrics = {
        "run_at": datetime.now(timezone.utc).isoformat(),
        "config": {
            "zones": ZONES,
            "tags_per_zone": TAGS_PER_ZONE,
            "poll_cycles": cycles,
            "poll_interval_s": POLL_INTERVAL_S,
            "seed": SEED,
        },
        "gateway_stats": gateway.stats.as_dict(),
        "publisher_stats": publisher.metrics.as_dict(),
        "run_duration_s": run_duration_s,
        "throughput_msgs_per_s": round(
            publisher.metrics.total_published / run_duration_s, 2
        ) if run_duration_s > 0 else 0,
    }

    METRICS_OUTPUT.write_text(json.dumps(metrics, indent=2))
    logger.info("metrics saved to %s", METRICS_OUTPUT)

    # 7 -- Print summary
    print("\n" + "=" * 55)
    print("  PIPELINE RUN SUMMARY")
    print("=" * 55)
    gw = metrics["gateway_stats"]
    pub = metrics["publisher_stats"]
    print(f"  Total packets seen      : {gw['total_seen']}")
    print(f"  Authenticated (gateway) : {gw['accepted']}")
    print(f"  Rogue rejections        : {gw['rejected_unknown_tag']}")
    print(f"  Published to broker     : {pub['total_published']}")
    print(f"  Publish failures        : {pub['total_failed']}")
    print(f"  Avg pipeline latency    : {pub['avg_latency_ms']} ms")
    print(f"  Min / Max latency       : {pub['min_latency_ms']} / {pub['max_latency_ms']} ms")
    print(f"  Throughput              : {metrics['throughput_msgs_per_s']} msg/s")
    print(f"  Run duration            : {run_duration_s}s")
    print("=" * 55)

    publisher.disconnect()
    if broker_proc:
        broker_proc.terminate()

    return metrics


if __name__ == "__main__":
    run()