# Edge Gateway

Authenticates inbound backscatter and translates it to MQTT/TLS.

`app/auth_bridge.py` performs two-stage rejection, counted separately for
evaluation:

- **Stage 1** rejects tag identifiers the gateway was never provisioned for
  (`rejected_unknown_tag`)
- **Stage 2** recomputes the HMAC from its own copy of the key and compares with
  `hmac.compare_digest`, rejecting packets whose MAC does not verify
  (`rejected_bad_auth`)

Stage 2 catches the realistic adversary: tag identifiers travel unencrypted over
the air and can be harvested by any listener, so an allowlist alone is
insufficient. It also catches payloads altered in transit. The MAC is stripped
before publishing and never reaches the cloud.

Canonicalisation is deliberately duplicated here and in `tag_simulator.py` rather
than shared. On real hardware the tag firmware and the gateway are separate
codebases; a shared import would misrepresent that boundary.

`configs/mikrotik_config.rsc` is the RouterOS configuration deployed to a
MikroTik hEX S: VLAN segmentation, a ten-rule default-deny firewall, and egress
pinned to TCP 8883 to a single resolved AWS IoT Core endpoint. Control mappings
to NIST SP 800-160 and ISO/IEC 27001:2022 are embedded as comments.

Tests: `python -m pytest edge-gateway/tests -v` (6 tests)