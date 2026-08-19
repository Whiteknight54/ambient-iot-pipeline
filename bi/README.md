# Business Intelligence Layer

Generates the dimensional model consumed by Tableau.

`generate_dataset.py` produces a 7-day, 20,160-row simulated deployment and
derives a star schema in `star_schema/`:

- `Fact_Telemetry.csv` — readings, alerts, classifications, latencies
- `Fact_Gateway_Metrics.csv` — acceptance and rejection counts per run
- `Dim_Zone.csv`, `Dim_Tag.csv` — conformed dimensions

Gateway metrics are read from `docs/evaluation/aiot_metrics.json`, so the
dashboard reflects whichever pipeline run was last executed. Both rejection
categories are carried through, allowing unknown-tag and MAC-failure rejections
to be reported separately.

Regenerate with `python bi/generate_dataset.py`, then refresh the Tableau extract.
Import order and relationship definitions are documented in the root README.