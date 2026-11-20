"""Preserve numeric types when serializing NumPy evaluation results."""
import json
from pathlib import Path


def numeric_default(value):
    import numpy as np
    if isinstance(value, np.ndarray):
        return value.tolist()
    if isinstance(value, np.generic):
        return value.item()
    if isinstance(value, Path):
        return str(value)
    raise TypeError(f'Object of type {type(value).__name__} is not JSON serializable')


def dumps(value, **kwargs):
    return json.dumps(value, default=numeric_default, allow_nan=False, **kwargs)
