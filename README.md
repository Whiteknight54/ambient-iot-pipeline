# Ambient IoT Pipeline

**A Strategic Framework and Technical Artefact for Secure Big Data Ingestion of Ambient IoT in Cloud-Native Environments**

MSc Information Technology - UFCF9Y-60-M CSCT Masters Project
Student: Oyinlayefa Mezeh (25053829) | University of the West of England, Bristol
Supervisor: Dr. Odayne Haughton | Submission: 3 September 2026

---

## Research Objective

Ambient IoT devices - battery-less sensors powered by harvested RF energy - cannot execute standard IP-based communication or conventional cryptographic handshakes. The constraint is physical rather than incidental: a device drawing roughly one microwatt, with an envelope-detector receiver and no session state between transmissions, cannot participate in a TLS handshake at all.

This project designs and implements an end-to-end Big Data pipeline that bridges such devices to enterprise cloud infrastructure, demonstrating that relocating trust to the first mains-powered hop secures high-velocity backscatter data at scale without requiring cryptographic capability on the device.

**Core research question:** Can a lightweight edge authentication framework, combined with a Big Data Lambda architecture separating real-time hot paths from cold batch processing, provide a secure and scalable ingestion pathway for battery-less ambient IoT sensors in a cloud-native environment?

**Project objectives:**

1. Design and develop a technical artefact - a high-fidelity simulation calibrated against publicly available greenhouse telemetry - that translates raw ambient IoT backscatter signals into secure MQTT data streams.
2. Implement a lightweight authentication and security framework at the edge layer, combining HMAC-SHA256 payload authentication with VLAN segmentation and default-deny firewalling, to protect data integrity for devices incapable of traditional SSL/TLS handshakes.
3. Architect a Big Data Lambda infrastructure managing high-velocity ingestion, separating real-time hot paths for immediate insight from cold batch processing for long-term trend analysis.
4. Evaluate the strategic value of ambient IoT through a Business Intelligence dashboard, measuring operational and sustainability indicators against traditional battery-powered IoT.

---

## Architecture

```
┌─────────────────────┐     Raw backscatter       ┌──────────────────────────┐
│   Perception Layer  │ ───────────────────────►  │    Edge Gateway          │
│  Python tag sim     │     (no IP, no TLS)       │    MikroTik hEX S        │
│  HMAC-SHA256 on-tag │     + HMAC tag            │    MAC verify + MQTT xlt │
└─────────────────────┘                           │    VLAN + firewall rules │
                                                  └────────────┬─────────────┘
                                                               │ MQTT/TLS :8883
                                                               ▼
                                                  ┌──────────────────────────┐
                                                  │    Cloud Ingestion       │
                                                  │    AWS IoT Core          │
                                                  │    Lambda hot/cold paths │
                                                  └────────────┬─────────────┘
                                                               │ Aggregated data
                                                               ▼
                                                  ┌──────────────────────────┐
                                                  │    BI Dashboard          │
                                                  │    Tableau               │
                                                  │    Star schema model     │
                                                  └──────────────────────────┘
```

Full diagrams: [`docs/architecture/`](docs/architecture/)

---

## Security Model

Authentication operates at two layers, addressing distinct threats.

**Application layer - identity and integrity.** Each tag holds a pre-shared key and attaches an HMAC-SHA256 tag computed over a canonical serialisation of its payload. The gateway recomputes the MAC from its own copy of the key and compares using `hmac.compare_digest`. Rejection is two-stage and counted separately:

| Stage | Rejects | Counter |
|---|---|---|
| 1 | Tag identifiers never provisioned | `rejected_unknown_tag` |
| 2 | Valid identifier, MAC does not verify | `rejected_bad_auth` |

Stage 2 addresses the realistic adversary. Tag identifiers travel unencrypted over the air and can be harvested by any listener, so an allowlist alone would admit a spoofed transmission. It also detects payloads altered in transit. The MAC is stripped at the gateway and never published to the cloud.

Three adversary injectors support evaluation: `inject_rogue_packet` (unknown identifier), `inject_spoofed_packet` (harvested identifier, wrong key), and `inject_tampered_packet` (authentic packet, altered reading).

**Network layer - destination restriction.** The gateway runs behind a MikroTik hEX S (RouterOS 7.23.3) configured from `edge-gateway/configs/mikrotik_config.rsc`: VLAN 10 for management, VLAN 20 for the IoT segment, and a ten-rule firewall terminating in default-deny on both input and forward chains. Egress from the IoT segment is permitted only to TCP 8883, and only to a dynamically resolved address list containing the account-specific AWS IoT Core endpoint. Inter-VLAN traffic is blocked bidirectionally.

The two layers are complementary: the application layer rejects rogue *sources*, the network layer rejects rogue *destinations*.

---

## Quick Start

Works identically on Windows, macOS and Linux.

### 1. Install Python dependencies

```bash
python -m pip install -r requirements.txt
```

Requires Python 3.10 or later.

### 2. Run the tests

```bash
python -m pytest -v
```

Expect **21 passed**.

| Layer | Tests | Coverage |
|---|---|---|
| `perception-layer/tests` | 2 | Tag simulation, energy-harvesting model |
| `edge-gateway/tests` | 6 | Acceptance, unknown-tag rejection, mixed batch, spoofed tag, tampered payload, MAC non-leakage |
| `cloud/tests` | 13 | Hot/cold path classification and aggregation |

The tests require no broker, no AWS credentials and no network access. This is the fastest way to verify the artefact works.

### 3. Run the local pipeline

Requires an MQTT broker on localhost:1883.

| Platform | Install |
|---|---|
| macOS | `brew install mosquitto` |
| Ubuntu/Debian | `sudo apt install mosquitto mosquitto-clients` |
| Windows | Download from [mosquitto.org/download](https://mosquitto.org/download/). The installer does **not** add Mosquitto to PATH - add `C:\Program Files\mosquitto` manually, or start the broker separately before running the pipeline. |

Then:

```bash
python scripts/run_pipeline.py
```

Metrics are written to `docs/evaluation/aiot_metrics.json`.

To watch messages live in a second terminal:

```bash
mosquitto_sub -h localhost -t "aiot/telemetry/#" -v
```

Broker host and port can be overridden with the `AIOT_BROKER_HOST` and `AIOT_BROKER_PORT` environment variables.

### 4. Regenerate the BI dataset

```bash
python bi/generate_dataset.py
```

---

## Results

All figures below are reproducible from the committed metrics files in [`docs/evaluation/`](docs/evaluation/). The simulation uses a fixed seed, so authentication outcomes are deterministic - repeated runs return identical packet counts, while latency varies with the host and network.

### Authentication

| | Baseline | Stress |
|---|---|---|
| Configuration | 2 zones × 5 tags × 10 cycles | 4 zones × 25 tags × 75 cycles |
| Total packets seen | 42 | 3,086 |
| Authenticated and accepted | 37 | 3,046 |
| Unknown-tag rejections | 3 | 25 |
| MAC-failure rejections | 2 | 15 |
| Rejection rate | 100% of injected adversaries | 100% of injected adversaries |

Identical gateway statistics were produced by both the local broker run and the AWS run at each scale, confirming that authentication behaviour is independent of transport.

### Throughput and latency

| Run | Throughput | Mean publish latency | Duration |
|---|---|---|---|
| Local baseline | 7.23 msg/s | 5.804 ms | 5.12 s |
| AWS baseline | 7.34 msg/s | 1.583 ms | 5.04 s |
| Local stress | 192.54 msg/s | 6.596 ms | 15.82 s |
| AWS stress | 192.42 msg/s | 5.385 ms | 15.83 s |

Reported throughput measures the rate at which messages were queued by the client library, not the rate of delivery. AWS IoT Core enforces a non-adjustable quota of 100 publish requests per second per connection, so the offered rate exceeded what a single connection could accept.

### Cloud delivery (AWS stress run)

Verified independently of publisher output:

| Measure | Value |
|---|---|
| Messages published | 3,046 |
| Rows persisted to DynamoDB | 3,020 (99.1%) |
| Peak DynamoDB throttle events | 719 |
| Lambda errors reported | 0 |

Under a sustained burst of approximately 192 msg/s the on-demand DynamoDB table's write capacity was exceeded, producing 719 throttle events at peak. SDK retry logic absorbed these and delivery completed, but with write latency extended several minutes beyond the publishing window. CloudWatch reported 100% Lambda success throughout, because the hot-path handler catches all exceptions and returns a 500 status in a normal return - a status the direct IoT Core invocation never inspects. Throttling was therefore invisible in the function's own error metrics and detectable only in the table's `ThrottledRequests` metric. This is documented as an observability limitation in the evaluation chapter.

### Hardware deployment

The RouterOS configuration was deployed to physical hardware and the full pipeline executed through the segmented network. Firewall counters confirmed enforcement in both directions: unauthorised egress and inter-VLAN traffic were discarded at the gateway, while the sanctioned MQTT/TLS path carried the full telemetry load.

Note on counter interpretation: the rule permitting MQTT egress increments only on the connection-initiating packet, after which the preceding `established,related` rule admits the remainder of the session. Policy is evaluated once per connection by design, not once per packet.

Evidence: [`docs/screenshots/`](docs/screenshots/)

---

## Repository Structure

```
ambient-iot-pipeline/
│
├── perception-layer/          # Stage 1: simulated battery-less tag engine
│   ├── app/tag_simulator.py   # Energy-harvesting model + on-tag HMAC
│   ├── config/config.json     # Zone configuration
│   └── tests/                 # 2 unit tests
│
├── edge-gateway/              # Stage 2: authentication + protocol translation
│   ├── app/auth_bridge.py     # Two-stage rejection, adversary injectors
│   ├── app/mqtt_publisher.py  # MQTT publish with latency instrumentation
│   ├── configs/               # RouterOS config (.rsc): VLAN + firewall
│   └── tests/                 # 6 integration tests
│
├── cloud/                     # Stage 3: AWS serverless ingestion
│   ├── lambdas/hot-path/      # Real-time classification + alerting
│   ├── lambdas/cold-path/     # Batch aggregation → CSV
│   ├── iot-core/rules.json    # IoT Core message routing
│   └── tests/                 # 13 Lambda unit tests
│
├── bi/                        # Stage 4: Business Intelligence
│   ├── generate_dataset.py    # 7-day dataset generator
│   ├── star_schema/           # Dimensional model for Tableau
│   └── Book1.twb
│
├── docs/
│   ├── architecture/          # SVG pipeline, sequence, deployment diagrams
│   ├── ethics/                # Ethics approval
│   ├── evaluation/            # Metrics JSON from every run
│   ├── meetings/              # Supervisor meeting log
│   └── screenshots/           # Deployment and evaluation evidence
│
├── scripts/
│   ├── run_pipeline.py            # Local broker, baseline config
│   ├── run_pipeline_aws.py        # AWS IoT Core, baseline config
│   └── run_pipeline_aws_stress.py # AWS IoT Core, stress config
│
├── infra/terraform/           # AWS infrastructure as code
└── pytest.ini                 # Test runner config
```

---

## Cloud Deployment (AWS)

The local pipeline should pass all 21 tests before cloud deployment - a staged deployment strategy documented in the project methodology.

**Prerequisites:** an AWS account with IoT Core, Lambda, DynamoDB and S3 access, and `aws configure` completed.

**IoT Core rule** connecting gateway MQTT to the hot-path Lambda:

```sql
SELECT * FROM 'aiot/telemetry/#'
```

**Hot-path Lambda environment:**

```
DYNAMODB_TABLE=aiot-telemetry
AWS_EXECUTION_ENV=AWS_Lambda_python3.12
```

**Cold-path Lambda environment:**

```
S3_BUCKET=aiot-cold-storage
AWS_EXECUTION_ENV=AWS_Lambda_python3.12
```

Device certificates are not committed. Place `device.pem.crt`, `private.pem.key` and `AmazonRootCA1.pem` in `infra/certs/` and set the endpoint in `aws_config.json`.

---

## Tableau Dashboard

Import the star schema CSVs from `bi/star_schema/` in this order:

1. `Dim_Zone.csv`
2. `Dim_Tag.csv`
3. `Fact_Telemetry.csv`
4. `Fact_Gateway_Metrics.csv`

**Relationships:**
- `Fact_Telemetry[zone]` → `Dim_Zone[zone_id]`
- `Fact_Telemetry[tag_id]` → `Dim_Tag[tag_id]`

**Calculated fields:**

```
// Avg_Ingestion_Latency
AVG([Pipeline Latency Ms])

// Alert_Rate_Pct
SUM(IF [Alert] THEN 1 ELSE 0 END) / COUNT([Reading Id]) * 100

// Unknown_Tag_Rejection_Rate_Pct
SUM([Rejected Unknown Tag]) / SUM([Total Seen]) * 100

// MAC_Failure_Rejection_Rate_Pct
SUM([Rejected Bad Auth]) / SUM([Total Seen]) * 100

// CO2_Saved_g
MAX([Battery Co2 Saved G])
```

**Dashboard pages:**
- Strategic Health - active tags, zone temperature averages, alert KPIs
- Infrastructure Performance - latency over time, throughput, packet loss rate
- Security Posture - classification breakdown, rejection rates by category

---

## Key References

- 3GPP (2025) *Release 19: Ambient IoT for 5G-Advanced*
- Alsaedi, A., Moustafa, N., Tari, Z., Mahmood, A. and Anwar, A. (2020) 'TON_IoT telemetry dataset', *IEEE Access*, 8, pp. 165130-165150. doi:10.1109/ACCESS.2020.3022862
- An, Y., Park, H. and Lee, W. (2023) 'Signal strength balanced scheduling for secure ambient backscatter networks', *ICOIN 2023*, pp. 56-61. doi:10.1109/ICOIN56518.2023.10049059
- Hussein, N. and Nhlabatsi, A. (2022) 'Living in the dark: MQTT-based exploitation of IoT security vulnerabilities in ZigBee networks', *IoT*, 3(4)
- ISO/IEC (2022) *ISO/IEC 27001:2022 - Information Security Management Systems*
- Kaplan, A. (2024) *Signal processing aspects of bistatic backscatter communication*. Licentiate thesis. Linköping University. doi:10.3384/9789180755955
- Lakshminarayana, S., Praseed, A. and Thilagam, P.S. (2024) 'Securing the IoT application layer from an MQTT protocol perspective', *IEEE Communications Surveys & Tutorials*, 26(4)
- Maistriaux, P., Pirson, T., Schramme, M., Louveaux, J. and Bol, D. (2022) 'Modeling the carbon footprint of battery-powered IoT sensor nodes for environmental-monitoring applications', *IoT '22*, ACM. doi:10.1145/3567445.3567448
- Muppa, N.R. (2025) 'Event-driven architectures in cloud-native systems', *WJARR*
- NIST (2022) *SP 800-160: Engineering Trustworthy Secure Systems*
- Rehman et al. (2025) 'Immersive embedded consumer model leveraging AI with zero-trust architecture for cyber-physical systems', *IEEE Transactions on Consumer Electronics*. doi:10.1109/TCE.2025.3554095
- Simanjuntak, R. and Surantha, N. (2022) 'Time-series database design for IoT monitoring', *Journal of Big Data*
- Song et al. (2026) 'Dynamic multi-channel random access for 6G-enabled ambient IoT'

Full reference list in the dissertation report.

---

## Project Status

| Stage | Component | Status |
|---|---|---|
| 1 | Perception layer with on-tag HMAC | Complete |
| 2 | Edge gateway: two-stage authentication | Complete |
| 2 | MikroTik hEX S: VLAN + firewall, deployed to hardware | Complete |
| 3 | AWS ingestion: IoT Core, hot/cold Lambda, DynamoDB, S3 | Complete |
| 4 | BI dashboard: star schema + Tableau | Complete |
| - | 21/21 tests passing | Complete |
| - | Evaluation metrics captured at two scales | Complete |
| - | Terraform IaC | Not implemented - see future work |
| - | Dissertation report | In progress |