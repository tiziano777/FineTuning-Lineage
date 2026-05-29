from __future__ import annotations

from pathlib import Path

import pandas as pd

import pyarrow as pa
import pyarrow.parquet as pq
# from mds import MDSWriter
from datasets import Dataset, DatasetDict, Features, Value, load_dataset, load_from_disk, concatenate_datasets


_LOADERS: list[tuple[str, object]] = [
    ("*.parquet", lambda p: pd.read_parquet(p)),
    ("*.jsonl.gz", lambda p: pd.read_json(p, lines=True, compression="gzip")),
    ("*.jsonl", lambda p: pd.read_json(p, lines=True)),
]


class DataLoader:
    """Read all data files from a distribution directory into a list of dicts.

    Supported formats (auto-detected, checked in priority order):
    parquet > jsonl.gz > jsonl. All files in the directory must share the
    same format — mixed formats per directory are not supported.
    """

    @staticmethod
    def base_load(dist_uri: str) -> list[dict]:
        path = Path(dist_uri)
        for pattern, reader in _LOADERS:
            files = sorted(path.glob(pattern))
            if files:
                df = pd.concat([reader(f) for f in files], ignore_index=True)
                return df.to_dict("records")
        raise FileNotFoundError(
        f"No supported data files (parquet/jsonl.gz/jsonl) found in: {dist_uri}"
        )


    @staticmethod
    def save_to_cache(data: list[dict], save_path_dir: str) -> None:
        """Save list of dicts a format used for efficient readability and training.

        By default, it saves to arrow format. If save_arrow=False, saves to mds.
        """
        save_path_dir = Path(save_path_dir)
        save_path_dir.mkdir(parents=True, exist_ok=True)
        dataset = Dataset.from_pandas(pd.DataFrame(data=data))
        dataset.save_to_disk(save_path_dir)
        
    
    @staticmethod
    def _load_from_cache(cache_dir: str, is_arrow: bool = True):# -> list[dict]:
        cache_dir = Path(cache_dir)
        return load_from_disk(cache_dir)

    @staticmethod
    def load_cached_dataset(cache_dir: Path, eval_size: float | int = 0, is_arrow: bool = True) -> Dataset | tuple[Dataset, Dataset]:
        """Load a cached `datasets.Dataset` or `datasets.DatasetDict`.

        If `eval_size` is provided (>0), return a tuple `(train_ds, eval_ds)`
        where `eval_ds` is either an existing validation split or a newly
        created split from `train` using `train_test_split`.
        If `eval_size` is 0 (default), preserve previous behavior and return
        a single `Dataset`.
        """
        ds = DataLoader._load_from_cache(str(cache_dir), is_arrow=is_arrow)

        # If it's a DatasetDict (check first — DatasetDict also has column_names)
        if isinstance(ds, DatasetDict):
            if 'train' in ds:
                for val_name in ('validation', 'valid', 'eval', 'test'):
                    if val_name in ds:
                        if eval_size and eval_size > 0:
                            return ds['train'], ds[val_name]
                        return ds['train']
                # No explicit eval split present: either split train or return train
                if eval_size and eval_size > 0:
                    split = ds['train'].train_test_split(test_size=eval_size)
                    return split['train'], split['test']
                return ds['train']
            # Concatenate all splits as fallback
            concatenated = concatenate_datasets([ds[s] for s in ds.keys()])
            if eval_size and eval_size > 0:
                split = concatenated.train_test_split(test_size=eval_size)
                return split['train'], split['test']
            return concatenated

        # Single Dataset
        if hasattr(ds, 'column_names'):
            if eval_size and eval_size > 0:
                split = ds.train_test_split(test_size=eval_size)
                return split['train'], split['test']
            return ds

        # Unknown type
        raise ValueError('Cached dataset is not a Dataset or DatasetDict')



