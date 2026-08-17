"""
Edge gateway: lightweight authentication and protocol translation.

This is the software model of the "Edge Bridge" described in the project
proposal -- in deployment this logic is intended to run on/behind a
MikroTik device, translating raw ambient IoT backscatter into authenticated
MQTT messages before they reach the cloud. It is built as a standalone
Python module first so it can be unit-tested deterministically; the same
logic can later be exposed as a service that a MikroTik script (RouterOS
container, or a script feeding a local bridge) calls into.

Security model (for the dissertation's Security section):
  - Ambient IoT tags are too constrained to perform a TLS/SSL handshake, so
    a full end-to-end encrypted session between tag and cloud is out of
    scope (this is stated explicitly in the project proposal's exclusions).
  - Instead, authentication happens at the gateway: each tag is provisioned
    with a pre-shared key (PSK). The gateway computes an HMAC over the raw
    payload using the tag's known PSK and compares it against a tag-supplied
    MAC. Unknown tag IDs, or packets that fail the MAC check, are rejected
    as "rogue signals" -- directly addressing the Testing and Evaluation
    criterion in the proposal ("non-authenticated rogue signals are
    rejected").
  - This is intentionally lightweight (HMAC-SHA256 over a few bytes) rather
    than a full handshake, matching the computational ceiling of the device
    class being modelled.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import time
from dataclasses import dataclass, field

logger = logging.getLogger("edge_gateway")


class GatewayError(Exception):
    """Base class for gateway-side rejections."""


class UnknownTagError(GatewayError):
    pass


class AuthenticationError(GatewayError):
    pass


class MalformedPacketError(GatewayError):
    pass


def canonical_body(payload: dict) -> bytes:
    """Deterministic byte serialisation of a payload, excluding the MAC field.

    Must match the tag-side canonicalisation in tag_simulator.py exactly:
    same separators, same key ordering. Any divergence causes every MAC
    check to fail.
    """
    return json.dumps(
        {k: v for k, v in payload.items() if k != "mac"},
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def compute_mac(psk: str, payload: dict) -> str:
    """Compute the expected HMAC-SHA256 tag for a payload under a given PSK.

    The tag computes this on-device within its power budget and appends it
    to the backscatter transmission; the gateway recomputes it from its own
    copy of the key and compares. A single keyed hash is used rather than a
    handshake because the device class being modelled cannot hold session
    state between transmissions (3GPP, 2025).
    """
    return hmac.new(psk.encode("utf-8"), canonical_body(payload), hashlib.sha256).hexdigest()


@dataclass
class TranslatedMessage:
    """Clean, authenticated MQTT-ready message produced by the gateway."""

    topic: str
    payload: dict
    received_at: float = field(default_factory=time.time)

    def to_mqtt(self) -> tuple[str, str]:
        """Return (topic, json_payload) ready for an MQTT publish call."""
        return self.topic, json.dumps(self.payload, separators=(",", ":"))


@dataclass
class GatewayStats:
    accepted: int = 0
    rejected_unknown_tag: int = 0
    rejected_bad_auth: int = 0
    rejected_malformed: int = 0

    @property
    def total_seen(self) -> int:
        return (
            self.accepted
            + self.rejected_unknown_tag
            + self.rejected_bad_auth
            + self.rejected_malformed
        )

    def as_dict(self) -> dict:
        return {
            "accepted": self.accepted,
            "rejected_unknown_tag": self.rejected_unknown_tag,
            "rejected_bad_auth": self.rejected_bad_auth,
            "rejected_malformed": self.rejected_malformed,
            "total_seen": self.total_seen,
        }

class EdgeGateway:
    """Validates and translates raw ambient IoT backscatter into MQTT.

    known_keys: mapping of tag_id -> pre-shared key, representing the
    gateway's local trust store (provisioned out-of-band in a real
    deployment).
    """

    def __init__(self, known_keys: dict[str, str], mqtt_topic_prefix: str = "aiot/telemetry"):
        self.known_keys = known_keys
        self.mqtt_topic_prefix = mqtt_topic_prefix
        self.stats = GatewayStats()

    def _parse(self, raw: bytes) -> dict:
        try:
            return json.loads(raw.decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise MalformedPacketError(str(exc)) from exc

    def _authenticate(self, tag_id: str, payload: dict) -> None:
        """Two-stage rejection, counted separately for evaluation purposes.

        Stage 1 rejects tag IDs the gateway has never been provisioned for.
        Stage 2 rejects packets whose MAC does not verify under the known
        key -- this catches an adversary who has observed a legitimate tag
        ID (trivially available over the air) but does not hold its key,
        and it catches payloads altered in transit.
        """
        if tag_id not in self.known_keys:
            raise UnknownTagError(tag_id)

        supplied_mac = payload.get("mac")
        if not isinstance(supplied_mac, str):
            raise AuthenticationError(f"{tag_id}: no MAC supplied")

        expected_mac = compute_mac(self.known_keys[tag_id], payload)
        if not hmac.compare_digest(expected_mac, supplied_mac):
            raise AuthenticationError(f"{tag_id}: MAC verification failed")

    def ingest(self, raw: bytes) -> TranslatedMessage | None:
        """Process one raw backscatter packet. Returns a TranslatedMessage
        on success, or raises a GatewayError subclass on rejection.

        Callers (e.g. a polling loop) are expected to catch GatewayError and
        log/count it -- rejections are an expected, measured part of normal
        operation, not a crash condition.
        """
        payload = self._parse(raw)

        tag_id = payload.get("id")
        if not tag_id:
            self.stats.rejected_malformed += 1
            raise MalformedPacketError("missing tag id")

        try:
            self._authenticate(tag_id, payload)
        except UnknownTagError:
            self.stats.rejected_unknown_tag += 1
            raise
        except AuthenticationError:
            self.stats.rejected_bad_auth += 1
            raise

        self.stats.accepted += 1
        zone = payload.get("zone", "unknown")
        topic = f"{self.mqtt_topic_prefix}/{zone}/{tag_id}"
        clean_payload = {
            "tag_id": tag_id,
            "zone": zone,
            "metric": payload.get("metric"),
            "value": payload.get("value"),
            "tag_ts": payload.get("ts"),
            "gateway_ts": time.time(),
        }
        return TranslatedMessage(topic=topic, payload=clean_payload)

    def ingest_batch(self, raw_packets: list[bytes]) -> list[TranslatedMessage]:
        """Process a batch, swallowing and logging individual rejections so
        one bad packet doesn't stop processing of the rest."""
        out = []
        for raw in raw_packets:
            try:
                msg = self.ingest(raw)
                if msg:
                    out.append(msg)
            except GatewayError as exc:
                logger.warning("rejected packet: %s: %s", type(exc).__name__, exc)
        return out

def inject_rogue_packet(zone: str = "zone-a") -> bytes:
    """Build a packet impersonating a tag id the gateway has never seen --
    used in tests/evaluation to demonstrate unknown-tag rejection."""
    payload = {
        "id": "deadbeef0000",
        "zone": zone,
        "ts": time.time(),
        "metric": "temperature_c",
        "value": 999.9,
    }
    payload["mac"] = compute_mac("not-the-real-key", payload)
    return json.dumps(payload, separators=(",", ":")).encode("utf-8")

def inject_spoofed_packet(tag_id: str, zone: str = "zone-a") -> bytes:
    """Build a packet using a *legitimate* tag id but the wrong key.

    Models the realistic adversary: tag identifiers travel unencrypted over
    the air and can be harvested by any listener, so an allowlist alone is
    insufficient. Only MAC verification rejects this.
    """
    payload = {
        "id": tag_id,
        "zone": zone,
        "ts": time.time(),
        "metric": "temperature_c",
        "value": 999.9,
    }
    payload["mac"] = compute_mac("attacker-guessed-key", payload)
    return json.dumps(payload, separators=(",", ":")).encode("utf-8")

def inject_tampered_packet(raw: bytes, new_value: float = 999.9) -> bytes:
    """Take a genuine packet and alter its reading, leaving the MAC intact.

    Demonstrates payload integrity rather than origin authentication: the
    tag id and MAC are authentic, but the value no longer matches.
    """
    payload = json.loads(raw.decode("utf-8"))
    payload["value"] = new_value
    return json.dumps(payload, separators=(",", ":")).encode("utf-8")
