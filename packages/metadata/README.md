# Metadata Layer (Plan 3)

Canonical store for pipelines, datasets, monitors, lineage, incidents, costs, and health scores.

See **[docs/METADATA_LAYER.md](../../docs/METADATA_LAYER.md)** for the full entity catalog and competitor comparison.

## Quick start

```bash
pip install -e ".[dev]"
pip install -e ../normalization
python -m pytest -q
python -m metadata.api
```
