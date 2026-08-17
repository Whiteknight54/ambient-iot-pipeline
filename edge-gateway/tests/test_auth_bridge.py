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
from auth_bridge import (
    AuthenticationError,
    EdgeGateway,
    UnknownTagError,
    inject_rogue_packet,
    inject_spoofed_packet,
    inject_tampered_packet,
)  # noqa: E402


def test_legitimate_tags_are_accepted_and_translated():
    swarm = TagSwarm(zones=["zone-a"], tags_per_zone=10, seed=1)
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
    assert topic.startswith("aiot/telemetry/zone-a/")
    assert "tag_id" in mqtt_json


def test_rogue_packet_is_rejected():
    swarm = TagSwarm(zones=["zone-a"], tags_per_zone=5, seed=2)
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
    swarm = TagSwarm(zones=["zone-a"], tags_per_zone=5, seed=3)
    gateway = EdgeGateway(known_keys=swarm.keys_by_tag_id())

    legit = swarm.poll_cycle()
    rogue = inject_rogue_packet()
    batch = legit + [rogue]

    translated = gateway.ingest_batch(batch)

    assert len(translated) == len(legit)
    assert gateway.stats.rejected_unknown_tag == 1
    assert gateway.stats.accepted == len(legit)

def test_spoofed_packet_with_valid_tag_id_is_rejected():
    """An adversary who has harvested a legitimate tag id over the air, but
    does not hold the pre-shared key, must still be rejected."""
    swarm = TagSwarm(zones=["zone-a"], tags_per_zone=5, seed=4)
    gateway = EdgeGateway(known_keys=swarm.keys_by_tag_id())

    legit_tag_id = next(iter(swarm.keys_by_tag_id()))
    spoofed = inject_spoofed_packet(legit_tag_id)

    try:
        gateway.ingest(spoofed)
        assert False, "spoofed packet should have raised AuthenticationError"
    except AuthenticationError:
        pass

    assert gateway.stats.rejected_bad_auth == 1
    assert gateway.stats.rejected_unknown_tag == 0
    assert gateway.stats.accepted == 0


def test_tampered_payload_is_rejected():
    """A genuine packet whose reading is altered in transit must fail the
    MAC check -- this is integrity, not just origin authentication."""
    swarm = TagSwarm(zones=["zone-a"], tags_per_zone=10, seed=5)
    gateway = EdgeGateway(known_keys=swarm.keys_by_tag_id())

    genuine = None
    for _ in range(10):
        packets = swarm.poll_cycle()
        if packets:
            genuine = packets[0]
            break
    assert genuine is not None, "simulator produced no traffic"

    tampered = inject_tampered_packet(genuine)

    try:
        gateway.ingest(tampered)
        assert False, "tampered packet should have raised AuthenticationError"
    except AuthenticationError:
        pass

    assert gateway.stats.rejected_bad_auth == 1


def test_mac_is_not_forwarded_to_cloud():
    """The MAC is consumed at the gateway; it must not leak downstream."""
    swarm = TagSwarm(zones=["zone-a"], tags_per_zone=10, seed=6)
    gateway = EdgeGateway(known_keys=swarm.keys_by_tag_id())

    packets = []
    while not packets:
        packets = swarm.poll_cycle()

    translated = gateway.ingest_batch(packets)
    assert translated
    assert "mac" not in translated[0].payload

if __name__ == "__main__":
    test_legitimate_tags_are_accepted_and_translated()
    test_rogue_packet_is_rejected()
    test_mixed_batch_rejects_rogue_but_keeps_legitimate()
    test_spoofed_packet_with_valid_tag_id_is_rejected()
    test_tampered_payload_is_rejected()
    test_mac_is_not_forwarded_to_cloud()
    print("all checks passed")
