import datetime
from json import JSONEncoder

import numpy as np
import pandas as pd


def convert_numpy_types(obj):
    """Convert numpy types to native Python types"""
    if isinstance(
        obj,
        (
            np.integer,
            np.int8,
            np.int16,
            np.int32,
            np.int64,
            np.uint8,
            np.uint16,
            np.uint32,
            np.uint64,
        ),
    ):
        return int(obj)
    elif isinstance(obj, (np.floating, np.float16, np.float32, np.float64)):
        return float(obj)
    elif isinstance(obj, (np.ndarray,)):
        return obj.tolist()
    elif isinstance(obj, dict):
        return {key: convert_numpy_types(value) for key, value in obj.items()}
    elif isinstance(obj, list):
        return [convert_numpy_types(item) for item in obj]

    # Return the object unchanged if it's not a numpy type
    return obj


class CustomJsonEncoder(JSONEncoder):
    def default(self, obj):
        if isinstance(obj, (pd.Timestamp, datetime.datetime, datetime.date)):
            return obj.isoformat()

        if isinstance(obj, pd.DataFrame):
            return obj.to_dict(orient="split")

        # Only use convert_numpy_types for numpy types; skip native Python types
        if hasattr(obj, '__module__') and obj.__module__ == 'numpy':
            converted = convert_numpy_types(obj)
            if converted is not obj:
                return converted
        elif isinstance(obj, (np.integer, np.floating, np.ndarray)):
            converted = convert_numpy_types(obj)
            if converted is not obj:
                return converted

        return super().default(obj)
