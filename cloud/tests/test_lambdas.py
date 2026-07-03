"""
Tests for hot-path and cold-path Lambda functions.
Run entirely locally -- no AWS credentials needed.
"""

import importlib.util
import json
import time
from pathlib import Path

LAMBDAS = Path(__file__).resolve().parents[1] / "lambdas"


def _load(name: str, rel: str):
    spec = importlib.util.spec_from_file_location(name, LAMBDAS / rel)
    mod  = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


hot  = _load("hot_index",  "hot-path/index.py")
cold = _load("cold_index", "cold-path/index.py")


def make_payload(metric="temperature_c", value=22.0, zone="greenhouse-A"):
    return {
        "tag_id": "aabbccddeeff",
        "zone":   zone,
        "metric": metric,
        "value":  value,
        "tag_ts": time.time(),
        "pipeline_latency_ms": 0.3,
    }


# Hot path tests

def test_hot_normal_temperature():
    result = hot.process(make_payload(value=22.0))
    assert result["classification"] == "NORMAL"
    assert result["alert"] is False


def test_hot_warning_high_temperature():
    result = hot.process(make_payload(value=30.0))
    assert result["classification"] == "WARNING"
    assert result["alert"] is True


def test_hot_critical_temperature():
    result = hot.process(make_payload(value=36.0))
    assert result["classification"] == "CRITICAL"
    assert result["alert"] is True


def test_hot_frost_risk():
    result = hot.process(make_payload(value=3.5))
    assert result["classification"] == "WARNING"
    assert result["alert"] is True


def test_hot_weak_signal():
    result = hot.process(make_payload(metric="rssi_dbm", value=-82.0))
    assert result["classification"] == "WARNING"
    assert result["alert"] is True


def test_hot_good_signal():
    result = hot.process(make_payload(metric="rssi_dbm", value=-55.0))
    assert result["classification"] == "NORMAL"
    assert result["alert"] is False


def test_hot_latency_fields_present():
    result = hot.process(make_payload())
    assert "pipeline_latency_ms" in result
    assert "lambda_latency_ms"   in result
    assert "total_latency_ms"    in result
    assert result["total_latency_ms"] >= result["pipeline_latency_ms"]


def test_hot_missing_value_returns_error():
    payload = make_payload()
    del payload["value"]
    result = hot.process(payload)
    assert result["status"] == "ERROR"


def test_hot_handler_returns_200():
    response = hot.handler(make_payload())
    assert response["statusCode"] == 200
    body = json.loads(response["body"])
    assert "classification" in body


# Cold path tests

def test_cold_aggregate_basic():
    records = [
        {"zone": "greenhouse-A", "metric": "temperature_c",
         "value": 22.0, "alert": False, "total_latency_ms": 0.4},
        {"zone": "greenhouse-A", "metric": "temperature_c",
         "value": 24.0, "alert": False, "total_latency_ms": 0.5},
        {"zone": "greenhouse-A", "metric": "temperature_c",
         "value": 31.0, "alert": True,  "total_latency_ms": 0.6},
    ]
    summaries = cold.aggregate(records)
    assert len(summaries) == 1
    s = summaries[0]
    assert s["zone"]          == "greenhouse-A"
    assert s["reading_count"] == 3
    assert s["avg_value"]     == round((22.0 + 24.0 + 31.0) / 3, 3)
    assert s["alert_count"]   == 1
    assert s["alert_rate_pct"] == round(1 / 3 * 100, 1)


def test_cold_aggregate_multiple_zones():
    records = [
        {"zone": "greenhouse-A", "metric": "temperature_c",
         "value": 22.0, "alert": False, "total_latency_ms": 0.3},
        {"zone": "greenhouse-B", "metric": "temperature_c",
         "value": 25.0, "alert": False, "total_latency_ms": 0.4},
    ]
    summaries = cold.aggregate(records)
    assert len(summaries) == 2
    zones = {s["zone"] for s in summaries}
    assert zones == {"greenhouse-A", "greenhouse-B"}


def test_cold_aggregate_empty():
    assert cold.aggregate([]) == []


def test_cold_handler_no_records(tmp_path, monkeypatch):
    monkeypatch.setattr(cold, "HOT_PATH_OUTPUT", tmp_path / "nonexistent.jsonl")
    response = cold.handler({})
    assert response["statusCode"] == 200
    assert "no records" in response["body"]