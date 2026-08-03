"""Metadata transform: connector envelopes → colleague store shapes."""

from .map_dataset import map_dataset, map_datasets
from .map_run import map_run, map_runs, new_pipeline_id

__all__ = [
    "map_run",
    "map_runs",
    "map_dataset",
    "map_datasets",
    "new_pipeline_id",
]
