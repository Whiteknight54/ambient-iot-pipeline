# Perception Layer

Simulates a swarm of battery-less backscatter tags.

`app/tag_simulator.py` models energy-harvesting behaviour probabilistically: each
tag transmits only when a simulated harvest threshold is met, producing the ~60%
packet loss characteristic of real backscatter deployments. Readings follow a
diurnal temperature curve with Gaussian noise and engineered anomaly windows,
calibrated against publicly available greenhouse telemetry.

Each tag holds a pre-shared key and attaches an HMAC-SHA256 tag over a canonical
serialisation of its payload. This is the single cryptographic operation the
device class can plausibly afford: one keyed hash over a few dozen bytes, with no
handshake, no session state and no certificate storage.

Output is raw bytes rather than MQTT — the tag speaks no IP-based protocol.
Translation happens at the gateway.

Tests: `python -m pytest perception-layer/tests -v` (2 tests)