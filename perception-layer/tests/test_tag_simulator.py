"""
Unit tests for the ambient tag simulator.
"""

import sys
from pathlib import Path

repo_root = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(repo_root / "perception-layer" / "app"))

from tag_simulator import AmbientTag, TagSwarm, TagType  # noqa: E402


def test_swarm_produces_keys_for_all_tags():
    swarm = TagSwarm(zones=["greenhouse-A", "greenhouse-B"], tags_per_zone=2, seed=7)

    keys = swarm.keys_by_tag_id()

    assert len(keys) == 4
    assert all(len(tag_id) == 12 for tag_id in keys)


def test_backscatter_payload_is_bytes_or_none():
    tag = AmbientTag.new(TagType.TEMPERATURE, "greenhouse-A")

    packet = tag.backscatter()

    assert packet is None or isinstance(packet, bytes)