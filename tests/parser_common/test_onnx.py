"""ONNX classify — пропускается без артефакта/deps."""

from __future__ import annotations

import pytest

from parser_common.model_onnx import DEFAULT_ONNX_PATH, predict_importance_onnx


def test_onnx_missing_artifact_returns_none() -> None:
    # Без обученной модели инференс должен тихо деградировать
    if DEFAULT_ONNX_PATH.is_file():
        pytest.skip("ONNX artifact present")
    assert predict_importance_onnx("Отключили воду") is None


def test_onnx_optional_import_safe() -> None:
    # Импорт модуля не требует onnxruntime на этапе import
    import parser_common.model_onnx as mod

    assert hasattr(mod, "predict_importance_onnx")
