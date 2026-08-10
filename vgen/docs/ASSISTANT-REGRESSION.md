# Assistant regression (etl-observability-assistant)

Run from `vgen/`:

```bash
python scripts/assistant_regression.py
```

Optional subset:

```bash
python scripts/assistant_regression.py --only fleet,last_success,hr_health
```

Requires `vgen.exe`, valid `vgen/.env` API credentials, and FAAS MySQL password on tools.

Results land in `_assistant_test_results/regression/`.
