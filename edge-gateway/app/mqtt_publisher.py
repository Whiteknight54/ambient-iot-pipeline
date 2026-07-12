"""
MQTT publisher: publishes authenticated gateway messages to a broker.

This module is the output side of the edge gateway -- it takes
TranslatedMessage objects from auth_bridge.py and publishes them
to an MQTT broker (Mosquitto locally, AWS IoT Core in production).

Latency instrumentation
-----------------------
Every publish call records two timestamps:
  - tag_ts    : when the simulated tag originally backscattered the packet
  - publish_ts: when the gateway successfully published to the broker

The difference (pipeline_latency_ms) is the end-to-end edge latency:
  raw backscatter -> auth -> protocol translation -> MQTT publish

This metric is captured in every published message AND in a local
metrics log, feeding directly into the dissertation Evaluation chapter
("Ingestion Latency during high-velocity data bursts").
"""

from __future__ import annotations

import json
import logging
import ssl
import time
from dataclasses import dataclass, field
from pathlib import Path

import paho.mqtt.client as mqtt

logger = logging.getLogger("mqtt_publisher")


@dataclass
class PublishResult:
    topic: str
    success: bool
    pipeline_latency_ms: float
    error: str | None = None


@dataclass
class PublisherMetrics:
    """Accumulates publish statistics for the evaluation chapter."""
    total_published: int = 0
    total_failed: int = 0
    latencies_ms: list = field(default_factory=list)

    @property
    def avg_latency_ms(self) -> float:
        if not self.latencies_ms:
            return 0.0
        return round(sum(self.latencies_ms) / len(self.latencies_ms), 3)

    @property
    def max_latency_ms(self) -> float:
        return round(max(self.latencies_ms), 3) if self.latencies_ms else 0.0

    @property
    def min_latency_ms(self) -> float:
        return round(min(self.latencies_ms), 3) if self.latencies_ms else 0.0

    def as_dict(self) -> dict:
        return {
            "total_published": self.total_published,
            "total_failed": self.total_failed,
            "avg_latency_ms": self.avg_latency_ms,
            "min_latency_ms": self.min_latency_ms,
            "max_latency_ms": self.max_latency_ms,
            "sample_count": len(self.latencies_ms),
        }


class MQTTPublisher:
    """
    Wraps paho-mqtt to publish authenticated gateway messages.

    Supports two modes:
      Local (Mosquitto) : broker_host=localhost, port=1883, no TLS
      AWS IoT Core      : broker_host=<endpoint>, port=8883, TLS certs

    The interface is identical in both modes -- only the constructor
    arguments change. This is the Staged Deployment Strategy: prove
    everything locally first, then swap to AWS by changing config only.
    """

    def __init__(
        self,
        broker_host: str = "localhost",
        broker_port: int = 1883,
        client_id: str = "aiot-edge-gateway",
        qos: int = 1,
        tls_cert: str | None = None,
        tls_key: str | None = None,
        tls_ca: str | None = None,
    ):
        self.broker_host = broker_host
        self.broker_port = broker_port
        self.qos = qos
        self.tls_cert = tls_cert
        self.tls_key = tls_key
        self.tls_ca = tls_ca
        self.metrics = PublisherMetrics()

        self._client = mqtt.Client(client_id=client_id)
        self._client.on_connect = self._on_connect
        self._client.on_publish = self._on_publish
        self._connected = False

    def _on_connect(self, client, userdata, flags, rc):
        if rc == 0:
            self._connected = True
            logger.info("connected to broker %s:%s", self.broker_host, self.broker_port)
        else:
            logger.error("broker connection failed, rc=%s", rc)

    def _on_publish(self, client, userdata, mid):
        logger.debug("message mid=%s acknowledged by broker", mid)

    def connect(self) -> bool:
        try:
            # Configure TLS if certificates are provided (AWS IoT Core mode)
            if self.tls_cert and self.tls_key and self.tls_ca:
                self._client.tls_set(
                    ca_certs=self.tls_ca,
                    certfile=self.tls_cert,
                    keyfile=self.tls_key,
                    tls_version=ssl.PROTOCOL_TLS_CLIENT,
                )
                logger.info("TLS configured for AWS IoT Core")

            self._client.connect(self.broker_host, self.broker_port, keepalive=60)
            self._client.loop_start()
            deadline = time.time() + 5
            while not self._connected and time.time() < deadline:
                time.sleep(0.05)
            return self._connected
        except Exception as exc:
            logger.error("could not connect to broker: %s", exc)
            return False

    def disconnect(self):
        self._client.loop_stop()
        self._client.disconnect()
        self._connected = False

    def publish(self, translated_message) -> PublishResult:
        """
        Publish one TranslatedMessage. Injects pipeline latency into the
        payload before publishing so downstream consumers (Lambda, Power BI)
        can see the latency per-message without needing a separate log.
        """
        topic, raw_json = translated_message.to_mqtt()
        payload_dict = json.loads(raw_json)

        publish_ts = time.time()
        tag_ts = payload_dict.get("tag_ts") or publish_ts
        latency_ms = round((publish_ts - tag_ts) * 1000, 3)

        payload_dict["publish_ts"] = publish_ts
        payload_dict["pipeline_latency_ms"] = latency_ms
        enriched_json = json.dumps(payload_dict, separators=(",", ":"))

        if not self._connected:
            self.metrics.total_failed += 1
            return PublishResult(
                topic=topic,
                success=False,
                pipeline_latency_ms=latency_ms,
                error="not connected to broker",
            )

        result = self._client.publish(topic, enriched_json, qos=self.qos)

        if result.rc == mqtt.MQTT_ERR_SUCCESS:
            self.metrics.total_published += 1
            self.metrics.latencies_ms.append(latency_ms)
            logger.debug("published to %s (latency=%.1fms)", topic, latency_ms)
            return PublishResult(topic=topic, success=True, pipeline_latency_ms=latency_ms)
        else:
            self.metrics.total_failed += 1
            return PublishResult(
                topic=topic,
                success=False,
                pipeline_latency_ms=latency_ms,
                error=f"paho rc={result.rc}",
            )

    def publish_batch(self, messages: list) -> list[PublishResult]:
        return [self.publish(msg) for msg in messages]