"""
Integration test: perception layer -> edge gateway.

This is the first end-to-end slice of the artefact: simulated tags produce
raw backscatter, the gateway authenticates and translates it. Also proves
the security requirement from the proposal's Testing and Evaluation section
-- that non-authenticated rogue signals are rejected.

Run with: python3 -m pytest -v
"""

import sys
from pathlib import Path

repo_root = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(repo_root / "perception-layer" / "app"))
sys.path.insert(0, str(repo_root / "edge-gateway" / "app"))

from tag_simulator import TagSwarm  # noqa: E402
from auth_bridge import EdgeGateway, UnknownTagError, inject_rogue_packet  # noqa: E402


def test_legitimate_tags_are_accepted_and_translated():
    swarm = TagSwarm(zones=["greenhouse-A"], tags_per_zone=10, seed=1)
    gateway = EdgeGateway(known_keys=swarm.keys_by_tag_id())

    raw_packets = []
    for _ in range(5):
        raw_packets.extend(swarm.poll_cycle())

    assert raw_packets, "simulator produced no traffic across 5 cycles -- check harvest_threshold"

    translated = gateway.ingest_batch(raw_packets)

    assert len(translated) == len(raw_packets), "every legitimate packet should be accepted"
    assert gateway.stats.accepted == len(raw_packets)
    assert gateway.stats.rejected_unknown_tag == 0

    topic, mqtt_json = translated[0].to_mqtt()
    assert topic.startswith("aiot/telemetry/greenhouse-A/")
    assert "tag_id" in mqtt_json


def test_rogue_packet_is_rejected():
    swarm = TagSwarm(zones=["greenhouse-A"], tags_per_zone=5, seed=2)
    gateway = EdgeGateway(known_keys=swarm.keys_by_tag_id())

    rogue = inject_rogue_packet()

    try:
        gateway.ingest(rogue)
        assert False, "rogue packet should have raised UnknownTagError"
    except UnknownTagError:
        pass

    assert gateway.stats.rejected_unknown_tag == 1
    assert gateway.stats.accepted == 0


def test_mixed_batch_rejects_rogue_but_keeps_legitimate():
    swarm = TagSwarm(zones=["greenhouse-A"], tags_per_zone=5, seed=3)
    gateway = EdgeGateway(known_keys=swarm.keys_by_tag_id())

    legit = swarm.poll_cycle()
    rogue = inject_rogue_packet()
    batch = legit + [rogue]

    translated = gateway.ingest_batch(batch)

    assert len(translated) == len(legit)
    assert gateway.stats.rejected_unknown_tag == 1
    assert gateway.stats.accepted == len(legit)


if __name__ == "__main__":
    test_legitimate_tags_are_accepted_and_translated()
    test_rogue_packet_is_rejected()
    test_mixed_batch_rejects_rogue_but_keeps_legitimate()
    print("all checks passed")
