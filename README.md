# Ambient IoT Pipeline

**A Strategic Framework and Technical Artefact for Secure Big Data Ingestion of Ambient IoT in Cloud-Native Environments**

MSc Information Technology — UFCF9Y-60-M CSCT Masters Project
Student: Oyinlayefa Mezeh (25053829) | University of the West of England, Bristol
Supervisor: Dr. Rachel Long | Submission: 3 September 2026

---

## Research Objective

Ambient IoT devices (battery-less, RF-energy-harvesting sensors) cannot execute
standard IP-based communication or robust encryption protocols due to hardware
constraints. This project designs and implements an end-to-end Big Data pipeline that
bridges these constrained devices and enterprise cloud environments — demonstrating
that intelligence shifted to the Edge can secure and process high-velocity backscatter
data at scale without compromising data integrity.

**Core research question:** Can a lightweight edge authentication framework, combined
with a Big Data Lambda architecture separating real-time Hot paths from Cold batch
processing, provide a secure and scalable ingestion pathway for battery-less ambient
IoT sensors in a cloud-native environment?

**Project objectives:**

1. Design and develop a technical artefact (high-fidelity simulation of UWE Frenchay
   Greenhouse) that translates raw Ambient IoT backscatter signals into secure MQTT
   data streams.
2. Implement a lightweight authentication and security framework at the Edge layer —
   including VLAN segmentation and firewalling — to protect data integrity for devices
   incapable of traditional SSL/TLS handshakes.
3. Architect a Big Data Lambda infrastructure that manages high-velocity data ingestion,
   separating real-time Hot paths for immediate insights from Cold batch processing for
   long-term trend analysis.
4. Evaluate the strategic value of Ambient IoT through a Business Intelligence dashboard,
   measuring improvements in carbon footprint and operational cost compared to
   traditional battery-powered IoT.

---

## Architecture

```
┌─────────────────────┐     Raw backscatter       ┌──────────────────────────┐
│   Perception Layer  │ ───────────────────────►  │    Edge Gateway          │
│  Python tag sim     │     (no IP, no TLS)       │    MikroTik hEX S        │
│  Wiliot Gen3 model  │                           │    PSK auth + MQTT xlt   │
└─────────────────────┘                           │    VLAN + firewall rules │
                                                  └────────────┬─────────────┘
                                                               │ Secure MQTT
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
                                                  │    Power BI              │
                                                  │    Star Schema model     │
                                                  └──────────────────────────┘
```

Full diagrams: [`docs/architecture/`](docs/architecture/)

---

## Repository Structure

```
ambient-iot-pipeline/
│
├── perception-layer/          # Stage 1: Simulated battery-less tag engine
│   ├── app/tag_simulator.py   # Probabilistic energy-harvesting model
│   ├── config/config.json     # Zone configuration (UWE Frenchay Greenhouse)
│   └── tests/                 # 2 unit tests
│
├── edge-gateway/              # Stage 2: MikroTik auth + protocol translation
│   ├── app/auth_bridge.py     # PSK authentication, rogue signal rejection
│   ├── app/mqtt_publisher.py  # MQTT publish with latency instrumentation
│   ├── configs/               # RouterOS export (.rsc) — VLAN + firewall rules
│   └── tests/                 # 3 integration tests
│
├── cloud/                     # Stage 3: AWS serverless Big Data ingestion
│   ├── lambdas/hot-path/      # Real-time classification + alerting (hot path)
│   ├── lambdas/cold-path/     # Batch aggregation → CSV (cold path)
│   ├── iot-core/rules.json    # IoT Core message routing rules
│   └── tests/                 # 13 Lambda unit tests
│
├── bi/                        # Stage 4: Business Intelligence
│   ├── generate_dataset.py    # 7-day simulation dataset generator
│   ├── dataset_mock.csv       # 20,160 row flat dataset
│   ├── star_schema/           # Dimensional model for Power BI
│   │   ├── Fact_Telemetry.csv
│   │   ├── Fact_Gateway_Metrics.csv
│   │   ├── Dim_Zone.csv
│   │   └── Dim_Tag.csv
│   └── ambient_iot_dashboard.pbix
│
├── docs/
│   ├── architecture/          # SVG pipeline, sequence, deployment diagrams
│   ├── ethics/                # UWE ethics approval
│   ├── evaluation/            # aiot_metrics.json (pipeline run evidence)
│   └── meetings/              # Supervisor meeting log
│
├── scripts/
│   └── run_pipeline.py        # End-to-end local pipeline runner
│
├── infra/terraform/           # AWS infrastructure as code (IaC)
└── pytest.ini                 # Test runner config (18 tests across 3 layers)
```

---

## Pipeline Test Results

18/18 tests passing across all pipeline stages:

```
perception-layer/tests   2 passed   Tag simulation and energy-harvesting model
edge-gateway/tests       3 passed   Auth, rogue rejection, mixed batch handling
cloud/tests             13 passed   Hot/cold path classification and aggregation
```

Run from repo root:
```bash
pip install paho-mqtt
python3 -m pytest -v
```

---

## Evaluation Metrics (Baseline Run)

Captured from `scripts/run_pipeline.py` — 10 poll cycles, 10 tags across 2 zones:

| Metric | Value |
|---|---|
| Total packets seen | 40 |
| Authenticated and accepted | 37 (92.5%) |
| Rogue signals rejected | 3 (100% catch rate) |
| Packet loss (energy-harvesting gate) | 60.1% — expected, models real backscatter |
| Average pipeline latency | 0.381 ms |
| Min / Max latency | 0.107 ms / 0.821 ms |
| Throughput | 7.31 msg/s |
| Run duration | 5.06s |

Full metrics: [`docs/evaluation/aiot_metrics.json`](docs/evaluation/aiot_metrics.json)

---

## BI Dataset Summary (7-Day Simulation)

Generated by `bi/generate_dataset.py` — models UWE Frenchay Greenhouse deployment:

| Metric | Value |
|---|---|
| Total readings | 20,160 |
| Packets transmitted | ~8,045 (39.9% — energy-harvesting gate) |
| Packet loss rate | 60.1% — consistent with backscatter device model |
| Alert events | ~785 (9.8% alert rate) |
| Critical events | ~38 (Day 6 heat anomaly crosses 35°C threshold) |
| CO₂ saved vs battery-powered | 3,861g over 7 days |

Carbon savings methodology: Journal of Green Engineering (2023) —
0.50g CO₂ per battery-powered reading vs 0.02g per ambient IoT reading.

---

## Local Setup

### Prerequisites
- Python 3.10+
- Mosquitto MQTT broker

```bash
# Mac
brew install mosquitto

# Ubuntu / Debian
sudo apt install mosquitto mosquitto-clients
```

### Install dependencies
```bash
pip install paho-mqtt
```

### Run the full pipeline
```bash
# Terminal 1 — watch live MQTT messages
mosquitto_sub -h localhost -t "aiot/telemetry/#" -v

# Terminal 2 — run the pipeline
python3 scripts/run_pipeline.py
```

### Run tests
```bash
python3 -m pytest -v
```

### Generate BI dataset
```bash
python3 bi/generate_dataset.py
```

---

## Cloud Deployment (AWS)

> Local pipeline must pass all 18 tests before cloud deployment.
> This is the Staged Deployment Strategy documented in the project methodology.

### Prerequisites
- AWS account with IoT Core, Lambda, DynamoDB, S3 access
- AWS CLI configured: `aws configure`

### IoT Core Rule (connects gateway MQTT → hot-path Lambda)
```sql
SELECT * FROM 'aiot/telemetry/#'
```
Action: Lambda → `hot-path/index.py`

### Environment variables (hot path Lambda)
```
DYNAMODB_TABLE=aiot-telemetry
AWS_EXECUTION_ENV=AWS_Lambda_python3.12
```

### Environment variables (cold path Lambda)
```
S3_BUCKET=aiot-cold-storage
AWS_EXECUTION_ENV=AWS_Lambda_python3.12
```

Terraform IaC coming in `infra/terraform/` — provisions IoT Core,
Lambda functions, DynamoDB table, and S3 bucket in one apply.

---

## Power BI Dashboard

Import the Star Schema CSVs from `bi/star_schema/` in this order:

1. `Dim_Zone.csv`
2. `Dim_Tag.csv`
3. `Fact_Telemetry.csv`
4. `Fact_Gateway_Metrics.csv`

**Relationships:**
- `Fact_Telemetry[zone]` → `Dim_Zone[zone_id]`
- `Fact_Telemetry[tag_id]` → `Dim_Tag[tag_id]`

**DAX Measures:**
```dax
Avg_Ingestion_Latency =
AVERAGE(Fact_Telemetry[pipeline_latency_ms])

Alert_Rate_Pct =
DIVIDE(
    COUNTROWS(FILTER(Fact_Telemetry, Fact_Telemetry[alert] = TRUE())),
    COUNTROWS(Fact_Telemetry), 0
) * 100

Rogue_Rejection_Rate_Pct =
DIVIDE(
    SUM(Fact_Gateway_Metrics[rejected_unknown_tag]),
    SUM(Fact_Gateway_Metrics[total_seen]), 0
)

CO2_Saved_g =
MAX(Fact_Telemetry[battery_co2_saved_g])
```

**Dashboard pages:**
- Page 1 — Strategic Health: active tags, zone temperature averages, alert KPIs
- Page 2 — Infrastructure Performance: latency over time, throughput, packet loss rate
- Page 3 — Security Posture: classification donut, rogue rejection rate

---

## Key References

- 3GPP (2025) Release 19 Technical Specifications: Ambient IoT for 5G-Advanced
- Gartner (2024) Hype Cycle for Emerging Technologies
- ISO/IEC (2022) ISO/IEC 27001:2022 — Information Security Management Systems
- NIST SP 800-160 (2022) Engineering Trustworthy Secure Systems
- AWS (2024) Lambda Architecture Patterns for Big Data
- Microsoft Azure (2024) Cloud-Native Design Patterns: Lambda Architecture
- Journal of Green Engineering (2023) Carbon Footprint of Battery-less Sensors
- Rehman et al. (2025) Zero-Trust Architecture for Cyber-Physical Systems
- Lakshminarayana et al. (2024) Securing IoT from an MQTT Protocol Perspective
- Hussein & Nhlabatsi (2022) MQTT-Based Exploitation of IoT Security Vulnerabilities
- Wiliot (2024) Ambient IoT: Benefits, Use Cases and Future Trends

Full reference list in dissertation report.

---

## Project Status

| Stage | Component | Status |
|---|---|---|
| 1 | Perception layer (tag simulator) | ✅ Complete |
| 2 | Edge gateway (PSK auth + VLAN + MQTT) | ✅ Complete |
| 3 | Cloud Big Data ingestion (hot/cold Lambda) | ✅ Complete |
| 4 | BI dashboard (Star Schema + DAX) | ✅ Complete |
| — | 18/18 tests passing | ✅ |
| — | Evaluation metrics captured | ✅ |
| — | AWS deployment (IoT Core wiring) | 🔲 Pending |
| — | Dissertation report | 🔲 In progress |

---

*Submission deadline: 3 September 2026, 14:00 UTC — University of the West of England*