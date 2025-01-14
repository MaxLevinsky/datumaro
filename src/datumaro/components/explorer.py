# Copyright (C) 2023 Intel Corporation
#
# SPDX-License-Identifier: MIT

from typing import Optional, Sequence, Union

import numpy as np

from datumaro.components.annotation import HashKey
from datumaro.components.dataset import Dataset
from datumaro.components.dataset_base import DatasetItem
from datumaro.components.errors import DatumaroError, MediaTypeError
from datumaro.components.media import MediaElement
from datumaro.plugins.explorer import ExplorerLauncher


def calculate_hamming(B1, B2):
    """
    :param B1:  vector [n]
    :param B2:  vector [r*n]
    :return: hamming distance [r]
    """
    return np.count_nonzero(B1 != B2, axis=1)


def select_uninferenced_dataset(dataset):
    uninferenced_dataset = Dataset(media_type=MediaElement)
    for item in dataset:
        if not any(isinstance(annotation, HashKey) for annotation in item.annotations):
            uninferenced_dataset.put(item)
    return uninferenced_dataset


class Explorer:
    def __init__(
        self,
        *datasets: Sequence[Dataset],
        topk: int = 10,
    ) -> None:
        """
        Explorer for Datumaro dataitems

        Parameters
        ----------
        dataset:
            Datumaro dataset to explore similar dataitem.
        topk:
            Number of images.
        """
        self._model = None
        self._text_model = None
        self._topk = topk
        database_keys = []
        item_list = []

        datasets_to_infer = [select_uninferenced_dataset(dataset) for dataset in datasets]
        datasets = self.compute_hash_key(datasets, datasets_to_infer)

        for dataset in datasets:
            for item in dataset:
                for annotation in item.annotations:
                    if isinstance(annotation, HashKey):
                        try:
                            hash_key = annotation.hash_key
                            hash_key = np.unpackbits(hash_key, axis=-1)
                            database_keys.append(hash_key)
                            item_list.append(item)
                        except Exception:
                            continue

        if all(i is None for i in database_keys):
            # media.data is None case
            raise ValueError("Database should have hash_key")

        self._database_keys = np.stack(database_keys, axis=0)
        self._item_list = item_list

    @property
    def model(self):
        if self._model is None:
            self._model = ExplorerLauncher(model_name="clip_visual_ViT-B_32")
        return self._model

    @property
    def text_model(self):
        if self._text_model is None:
            self._text_model = ExplorerLauncher(model_name="clip_text_ViT-B_32")
        return self._text_model

    def compute_hash_key(self, datasets, datasets_to_infer):
        for dataset in datasets_to_infer:
            if len(dataset) > 0:
                dataset.run_model(self.model, append_annotation=True)
        for dataset, dataset_to_infer in zip(datasets, datasets_to_infer):
            dataset.update(dataset_to_infer)
        return datasets

    def explore_topk(
        self,
        query: Union[DatasetItem, str],
        topk: Optional[int] = None,
    ):
        """
        Explore topk similar results based on hamming distance for query DatasetItem
        """
        if not topk:
            topk = self._topk

        database_keys = self._database_keys

        if isinstance(query, DatasetItem):
            query_key = self._get_hash_key_from_item_query(query)
        elif isinstance(query, str):
            query_key = self._get_hash_key_from_text_query(query)
        else:
            raise MediaTypeError(
                "Unexpected media type of query '%s'. "
                "Expected 'DatasetItem' or 'string', actual'%s'" % (query, type(query))
            )

        if not isinstance(query_key, HashKey):
            # media.data is None case
            raise ValueError("Query should have hash_key")

        unpacked_key = np.unpackbits(query_key.hash_key, axis=-1)
        logits = calculate_hamming(unpacked_key, database_keys)
        ind = np.argsort(logits)

        item_list = np.array(self._item_list)[ind]
        result = item_list[:topk].tolist()

        return result

    def _get_hash_key_from_item_query(self, query: DatasetItem) -> HashKey:
        """Get hash key from the `DatasetItem`.

        If not exists, launch the model inference to obtain it.
        """
        query_keys_in_item = [
            annotation for annotation in query.annotations if isinstance(annotation, HashKey)
        ]

        if len(query_keys_in_item) > 1:
            raise DatumaroError(
                f"There are more than two HashKey ({query_keys_in_item}) "
                f"in the query item ({query}). It is ambiguous!"
            )

        if len(query_keys_in_item) == 1:
            return query_keys_in_item[0]

        return self._model.infer_item(query)

    def _get_hash_key_from_text_query(self, query: str) -> HashKey:
        return self.text_model.infer_text(query)
