"""
Ambient IoT tag simulator.

Mimics the behaviour of battery-less, RF-energy-harvesting tags (modelled on
Wiliot Gen3 style pixels) that periodically "backscatter" small telemetry
packets to a nearby reader/gateway. Real ambient IoT tags cannot run TLS or
maintain a persistent IP session -- they harvest just enough energy to send a
short burst, then go dark again. This module reproduces that behaviour so the
rest of the pipeline (edge gateway, cloud ingestion, BI layer) can be built
and tested without physical hardware.

Design choices (documented for the dissertation "Design and Approach"
section):
  - Each tag has a fixed pseudo-random 12-hex-digit ID, mimicking an
    EPC-style identifier.
  - Energy harvesting is modelled probabilistically: a tag only "wakes up"
    and transmits if its simulated harvested energy crosses a threshold.
    This produces realistic packet loss / irregular transmission intervals,
    which is itself a property worth discussing in the artefact evaluation.
  - Payloads are intentionally tiny (a handful of bytes once encoded) to
    reflect the computational/power constraints of backscatter devices --
    this is why authentication has to happen at the gateway, not the tag.
"""

from __future__ import annotations

import json
import random
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum


class TagType(str, Enum):
    TEMPERATURE = "temperature"
    LOCATION = "location"


@dataclass
class AmbientTag:
    """A single simulated battery-less ambient IoT tag."""

    tag_id: str
    tag_type: TagType
    zone: str
    harvest_threshold: float = 0.6  # probability gate for "enough RF energy harvested"
    base_temp_c: float = 21.0
    psk: str = field(default_factory=lambda: uuid.uuid4().hex[:16])  # pre-shared key, edge-side auth

    @classmethod
    def new(cls, tag_type: TagType, zone: str) -> "AmbientTag":
        return cls(
            tag_id=uuid.uuid4().hex[:12],
            tag_type=tag_type,
            zone=zone,
        )

    def _harvested_enough_energy(self) -> bool:
        """Simulate probabilistic RF/vibration/thermal energy harvesting.

        Returns False most of the time a tag is polled, reproducing the
        irregular, lossy transmission pattern of real backscatter devices.
        """
        return random.random() > self.harvest_threshold

    def _raw_payload(self) -> dict | None:
        if not self._harvested_enough_energy():
            return None

        if self.tag_type is TagType.TEMPERATURE:
            value = round(self.base_temp_c + random.uniform(-1.5, 1.5), 2)
            reading = {"metric": "temperature_c", "value": value}
        else:
            # Coarse proximity-style location: which reader zone "heard" the tag,
            # plus a synthetic signal strength used downstream for zone inference.
            reading = {
                "metric": "rssi_dbm",
                "value": round(random.uniform(-85, -40), 1),
            }

        return {
            "id": self.tag_id,
            "zone": self.zone,
            "ts": time.time(),
            **reading,
        }

    def backscatter(self) -> bytes | None:
        """Produce one raw backscatter transmission, or None if the tag
        didn't harvest enough energy to transmit this cycle.

        Returns raw bytes (not JSON/MQTT) to model the fact that the tag
        itself speaks no IP-based protocol -- translation happens at the
        gateway, not here.
        """
        payload = self._raw_payload()
        if payload is None:
            return None
        # Minimal binary-ish encoding: compact JSON, no whitespace.
        # A real implementation would use a bit-packed format; compact JSON
        # is used here for readability while still being clearly distinct
        # from the gateway's MQTT/JSON output.
        return json.dumps(payload, separators=(",", ":")).encode("utf-8")


class TagSwarm:
    """Manages a population of simulated tags across zones, e.g. modelling
    the UWE Frenchay Greenhouse layout referenced in the project proposal."""

    def __init__(self, zones: list[str], tags_per_zone: int = 5, seed: int | None = None):
        if seed is not None:
            random.seed(seed)
        self.tags: list[AmbientTag] = []
        for zone in zones:
            for _ in range(tags_per_zone):
                tag_type = random.choice(list(TagType))
                self.tags.append(AmbientTag.new(tag_type, zone))

    def poll_cycle(self) -> list[bytes]:
        """One reader polling cycle: ask every tag to attempt a backscatter
        transmission. Most will fail (insufficient harvested energy) --
        that's expected and realistic."""
        out = []
        for tag in self.tags:
            packet = tag.backscatter()
            if packet is not None:
                out.append(packet)
        return out

    def keys_by_tag_id(self) -> dict[str, str]:
        """Pre-shared keys, keyed by tag id -- this is what the gateway
        needs to validate incoming backscatter packets. In a real system
        this would come from secure provisioning, not be shipped alongside
        the simulator; modelled separately here for traceability."""
        return {tag.tag_id: tag.psk for tag in self.tags}


def run_simulation(duration_s: int = 30, poll_interval_s: float = 1.0, zones=None, seed=None):
    """Run the simulator standalone and print backscatter traffic -- useful
    for sanity-checking the model before wiring it into the gateway."""
    zones = zones or ["greenhouse-A", "greenhouse-B"]
    swarm = TagSwarm(zones=zones, tags_per_zone=4, seed=seed)
    start = time.time()
    cycle = 0
    while time.time() - start < duration_s:
        cycle += 1
        packets = swarm.poll_cycle()
        ts = datetime.now(timezone.utc).isoformat(timespec="seconds")
        print(f"[{ts}] cycle {cycle}: {len(packets)}/{len(swarm.tags)} tags transmitted")
        for p in packets:
            print(f"  raw: {p.decode()}")
        time.sleep(poll_interval_s)


if __name__ == "__main__":
    run_simulation(duration_s=10, poll_interval_s=2.0, seed=42)
