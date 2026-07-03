"""
BI mock dataset generator.

Generates a realistic 7-day time-series CSV dataset for the Power BI
dashboard described in the project proposal. The data simulates what
the cold-path Lambda would accumulate over a week of real deployment
at the UWE Frenchay Greenhouse.

Run:
    python3 bi/generate_dataset.py

Outputs:
    bi/dataset_mock.csv          - flat file (full dataset)
    bi/star_schema/Fact_Telemetry.csv
    bi/star_schema/Fact_Gateway_Metrics.csv
    bi/star_schema/Dim_Zone.csv
    bi/star_schema/Dim_Tag.csv

Dataset design
--------------
1. Asset Health      - temperature trends per zone over time
2. Alert Events      - when and where thresholds were breached
3. Signal Quality    - RSSI per zone (location/coverage health)
4. Carbon Savings    - battery-less vs battery-powered comparison
                       (Journal of Green Engineering, 2023)

Carbon savings model
--------------------
    battery_co2_g = readings * 0.5g   (AA battery amortised)
    ambient_co2_g = readings * 0.02g  (RF harvesting overhead)
"""

from __future__ import annotations

import csv
import json
import math
import random
from datetime import datetime, timedelta, timezone
from pathlib import Path

OUTPUT_FLAT   = Path(__file__).parent / "dataset_mock.csv"
OUTPUT_STAR   = Path(__file__).parent / "star_schema"
METRICS_PATH  = Path(__file__).parents[1] / "docs" / "evaluation" / "aiot_metrics.json"

ZONES = {
    "greenhouse-A": {"base_temp": 20.0, "rssi_base": -58.0,
                     "location": "North wing, UWE Frenchay",
                     "optimal_temp_range": "18-26°C"},
    "greenhouse-B": {"base_temp": 22.0, "rssi_base": -63.0,
                     "location": "South wing, UWE Frenchay",
                     "optimal_temp_range": "18-26°C"},
}

TAGS_PER_ZONE        = 5
POLL_INTERVAL_MINS   = 5
DAYS                 = 7
HARVEST_THRESHOLD    = 0.6

ANOMALY_WINDOWS = [
    (2, 14, 8.0),
    (4, 11, 6.5),
    (6, 15, 11.0),
]

BATTERY_CO2_PER_READING_G = 0.50
AMBIENT_CO2_PER_READING_G = 0.02

FLAT_HEADERS = [
    "timestamp", "day_of_week", "hour", "zone", "tag_id",
    "metric", "value", "classification", "alert",
    "pipeline_latency_ms", "packet_transmitted",
    "battery_co2_saved_g", "ambient_co2_overhead_g",
]

FACT_TELEMETRY_HEADERS = [
    "reading_id", "timestamp", "hour", "day_of_week",
    "zone", "tag_id", "metric", "value",
    "classification", "alert", "pipeline_latency_ms",
    "battery_co2_saved_g",
]

FACT_GATEWAY_HEADERS = [
    "run_id", "run_at", "zone_count", "tags_per_zone",
    "poll_cycles", "total_seen", "accepted",
    "rejected_unknown_tag", "rejected_bad_auth",
    "rejected_malformed", "total_published",
    "avg_latency_ms", "min_latency_ms", "max_latency_ms",
    "throughput_msgs_per_s", "run_duration_s",
]

DIM_ZONE_HEADERS = [
    "zone_id", "location", "optimal_temp_range",
    "base_temp_c", "rssi_base_dbm", "asset_type",
]

DIM_TAG_HEADERS = [
    "tag_id", "zone_id", "asset_type", "harvest_threshold",
]


# ── helpers ───────────────────────────────────────────────────────────────────

def _temp(hour: int, base: float, spike: float = 0.0) -> float:
    diurnal = 3.5 * math.sin(math.pi * (hour - 6) / 12)
    noise   = random.gauss(0, 0.4)
    return round(base + diurnal + noise + spike, 2)


def _rssi(hour: int, base: float) -> float:
    peak = -4.0 if 8 <= hour <= 18 else 0.0
    return round(base + peak + random.gauss(0, 1.5), 1)


def _anomaly(day: int, hour: int) -> float:
    for i, (s, e, spike) in enumerate(ANOMALY_WINDOWS):
        if day == i + 2 and s <= hour <= e:
            return spike * random.uniform(0.7, 1.0)
    return 0.0


def _classify_temp(v: float) -> tuple[str, bool]:
    if v >= 35.0: return "CRITICAL", True
    if v >= 28.0 or v <= 5.0: return "WARNING", True
    return "NORMAL", False


def _classify_rssi(v: float) -> tuple[str, bool]:
    return ("WARNING", True) if v <= -80.0 else ("NORMAL", False)


def _latency() -> float:
    base = random.gauss(0.38, 0.12)
    if random.random() < 0.05:
        base += random.uniform(1.0, 4.0)
    return round(max(0.05, base), 3)


# ── generation ────────────────────────────────────────────────────────────────

def generate() -> tuple[list[dict], dict[str, list]]:
    random.seed(42)

    zone_tags = {
        zone: [f"{random.randint(0,0xFFFFFFFF):08x}{random.randint(0,0xFFFF):04x}"
               for _ in range(TAGS_PER_ZONE)]
        for zone in ZONES
    }

    flat_rows      = []
    fact_telemetry = []
    dim_tag_rows   = []
    reading_id     = 0
    total_tx       = 0

    # Build Dim_Tag
    seen_tags = set()
    for zone, tags in zone_tags.items():
        for tag_id in tags:
            if tag_id not in seen_tags:
                dim_tag_rows.append({
                    "tag_id":            tag_id,
                    "zone_id":           zone,
                    "asset_type":        "Wiliot Gen3 Pixel (simulated)",
                    "harvest_threshold": HARVEST_THRESHOLD,
                })
                seen_tags.add(tag_id)

    start_dt     = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)
    total_mins   = DAYS * 24 * 60

    for offset in range(0, total_mins, POLL_INTERVAL_MINS):
        dt      = start_dt + timedelta(minutes=offset)
        day_num = offset // (24 * 60) + 1
        hour    = dt.hour
        spike   = _anomaly(day_num, hour)

        for zone, cfg in ZONES.items():
            for tag_id in zone_tags[zone]:

                transmitted = random.random() > HARVEST_THRESHOLD

                if not transmitted:
                    flat_rows.append({
                        "timestamp": dt.isoformat(), "day_of_week": dt.strftime("%A"),
                        "hour": hour, "zone": zone, "tag_id": tag_id,
                        "metric": "temperature_c", "value": "",
                        "classification": "NO_TRANSMISSION", "alert": False,
                        "pipeline_latency_ms": "", "packet_transmitted": 0,
                        "battery_co2_saved_g": round(
                            total_tx * (BATTERY_CO2_PER_READING_G - AMBIENT_CO2_PER_READING_G), 4),
                        "ambient_co2_overhead_g": round(
                            total_tx * AMBIENT_CO2_PER_READING_G, 4),
                    })
                    continue

                total_tx  += 1
                reading_id += 1

                if random.random() < 0.75:
                    metric = "temperature_c"
                    value  = _temp(hour, cfg["base_temp"], spike)
                    classification, alert = _classify_temp(value)
                else:
                    metric = "rssi_dbm"
                    value  = _rssi(hour, cfg["rssi_base"])
                    classification, alert = _classify_rssi(value)

                lat        = _latency()
                co2_saved  = round(total_tx * (BATTERY_CO2_PER_READING_G - AMBIENT_CO2_PER_READING_G), 4)
                co2_oh     = round(total_tx * AMBIENT_CO2_PER_READING_G, 4)

                flat_rows.append({
                    "timestamp": dt.isoformat(), "day_of_week": dt.strftime("%A"),
                    "hour": hour, "zone": zone, "tag_id": tag_id,
                    "metric": metric, "value": value,
                    "classification": classification, "alert": alert,
                    "pipeline_latency_ms": lat, "packet_transmitted": 1,
                    "battery_co2_saved_g": co2_saved,
                    "ambient_co2_overhead_g": co2_oh,
                })

                fact_telemetry.append({
                    "reading_id": reading_id,
                    "timestamp": dt.isoformat(),
                    "hour": hour,
                    "day_of_week": dt.strftime("%A"),
                    "zone": zone,
                    "tag_id": tag_id,
                    "metric": metric,
                    "value": value,
                    "classification": classification,
                    "alert": alert,
                    "pipeline_latency_ms": lat,
                    "battery_co2_saved_g": co2_saved,
                })

    # Dim_Zone
    dim_zone_rows = [
        {
            "zone_id":           zone,
            "location":          cfg["location"],
            "optimal_temp_range": cfg["optimal_temp_range"],
            "base_temp_c":       cfg["base_temp"],
            "rssi_base_dbm":     cfg["rssi_base"],
            "asset_type":        "Wiliot Gen3 Pixel (simulated)",
        }
        for zone, cfg in ZONES.items()
    ]

    # Fact_Gateway_Metrics — load from saved run or use defaults
    if METRICS_PATH.exists():
        m = json.loads(METRICS_PATH.read_text())
        gw  = m.get("gateway_stats", {})
        pub = m.get("publisher_stats", {})
        fact_gateway = [{
            "run_id":               1,
            "run_at":               m.get("run_at", ""),
            "zone_count":           len(ZONES),
            "tags_per_zone":        m.get("config", {}).get("tags_per_zone", TAGS_PER_ZONE),
            "poll_cycles":          m.get("config", {}).get("poll_cycles", 10),
            "total_seen":           gw.get("total_seen", 0),
            "accepted":             gw.get("accepted", 0),
            "rejected_unknown_tag": gw.get("rejected_unknown_tag", 0),
            "rejected_bad_auth":    gw.get("rejected_bad_auth", 0),
            "rejected_malformed":   gw.get("rejected_malformed", 0),
            "total_published":      pub.get("total_published", 0),
            "avg_latency_ms":       pub.get("avg_latency_ms", 0),
            "min_latency_ms":       pub.get("min_latency_ms", 0),
            "max_latency_ms":       pub.get("max_latency_ms", 0),
            "throughput_msgs_per_s": m.get("throughput_msgs_per_s", 0),
            "run_duration_s":       m.get("run_duration_s", 0),
        }]
    else:
        fact_gateway = [{
            "run_id": 1, "run_at": datetime.now(timezone.utc).isoformat(),
            "zone_count": 2, "tags_per_zone": 5, "poll_cycles": 10,
            "total_seen": 40, "accepted": 37, "rejected_unknown_tag": 3,
            "rejected_bad_auth": 0, "rejected_malformed": 0,
            "total_published": 37, "avg_latency_ms": 0.381,
            "min_latency_ms": 0.107, "max_latency_ms": 0.821,
            "throughput_msgs_per_s": 7.31, "run_duration_s": 5.06,
        }]

    return flat_rows, {
        "Fact_Telemetry":       (FACT_TELEMETRY_HEADERS, fact_telemetry),
        "Fact_Gateway_Metrics": (FACT_GATEWAY_HEADERS,   fact_gateway),
        "Dim_Zone":             (DIM_ZONE_HEADERS,        dim_zone_rows),
        "Dim_Tag":              (DIM_TAG_HEADERS,          dim_tag_rows),
    }


def write_csv(path: Path, headers: list, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=headers)
        writer.writeheader()
        writer.writerows(rows)


def print_summary(flat_rows: list[dict], star: dict) -> None:
    tx      = [r for r in flat_rows if r["packet_transmitted"] == 1]
    alerts  = [r for r in tx if r["alert"] is True]
    crits   = [r for r in tx if r["classification"] == "CRITICAL"]
    lats    = [r["pipeline_latency_ms"] for r in tx if r["pipeline_latency_ms"] != ""]
    co2     = tx[-1]["battery_co2_saved_g"] if tx else 0

    print("\n" + "=" * 60)
    print("  BI MOCK DATASET SUMMARY")
    print("=" * 60)
    print(f"  Total rows (flat)       : {len(flat_rows):,}")
    print(f"  Packets transmitted     : {len(tx):,}")
    print(f"  Transmission rate       : {len(tx)/len(flat_rows)*100:.1f}%")
    print(f"  Alert events            : {len(alerts):,}")
    print(f"  Critical events         : {len(crits):,}")
    print(f"  Alert rate              : {len(alerts)/len(tx)*100:.1f}%")
    print(f"  Avg pipeline latency    : {sum(lats)/len(lats):.3f} ms")
    print(f"  CO2 saved vs battery    : {co2:,.1f} g")
    print("")
    print("  Star Schema outputs:")
    for name, (_, rows) in star.items():
        print(f"    {name:<25} {len(rows):>6} rows")
    print("=" * 60)
    print("\n  Power BI import order:")
    print("  1. Dim_Zone.csv")
    print("  2. Dim_Tag.csv")
    print("  3. Fact_Telemetry.csv")
    print("  4. Fact_Gateway_Metrics.csv")
    print("\n  Suggested DAX measures:")
    print("  Avg_Ingestion_Latency    = AVERAGE(Fact_Telemetry[pipeline_latency_ms])")
    print("  Alert_Rate_Pct           = DIVIDE(COUNTROWS(FILTER(Fact_Telemetry,")
    print("                               Fact_Telemetry[alert]=TRUE())),")
    print("                               COUNTROWS(Fact_Telemetry),0)*100")
    print("  Rogue_Rejection_Rate_Pct = DIVIDE(SUM(Fact_Gateway_Metrics[rejected_unknown_tag]),")
    print("                               SUM(Fact_Gateway_Metrics[total_seen]),0)")
    print("  CO2_Saved_g              = MAX(Fact_Telemetry[battery_co2_saved_g])")


if __name__ == "__main__":
    print("Generating dataset...")
    flat_rows, star = generate()

    # Write flat file
    write_csv(OUTPUT_FLAT, FLAT_HEADERS, flat_rows)

    # Write Star Schema files
    for name, (headers, rows) in star.items():
        write_csv(OUTPUT_STAR / f"{name}.csv", headers, rows)

    print_summary(flat_rows, star)
    print(f"\n  Flat CSV  : {OUTPUT_FLAT}")
    print(f"  Star CSVs : {OUTPUT_STAR}/")