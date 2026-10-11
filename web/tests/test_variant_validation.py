"""Scoring configuration validation works without a database or imported engine."""
import copy
import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from web.routes_lab import VariantIn

V1 = json.loads((Path(__file__).resolve().parents[2] / "contracts/fixtures/variant_v1.json").read_text())


@pytest.mark.parametrize("field,value", [
    ("enabled", []), ("enabled", ["lag_ms", "lag_ms"]), ("enabled", ["unknown"]),
    ("pass_threshold", 0), ("pass_threshold", -0.1), ("pass_threshold", 1.01),
    ("pass_threshold", True), ("pass_threshold", float("nan")), ("pass_threshold", float("inf")),
    ("features", {}), ("id", " "),
])
def test_invalid_configuration(field, value):
    cfg = copy.deepcopy(V1)
    cfg[field] = value
    with pytest.raises(ValidationError):
        VariantIn.model_validate(cfg)


@pytest.mark.parametrize("band", [[1, 1], [2, 1], [1], [1, 2, 3], [0, float("inf")], [float("nan"), 1]])
def test_disabled_bands_are_validated(band):
    cfg = copy.deepcopy(V1)
    cfg["features"]["power_law_beta"] = band
    with pytest.raises(ValidationError):
        VariantIn.model_validate(cfg)


def test_full_valid_configuration_and_extras_are_preserved():
    cfg = {**V1, "reason": "review me", "enabled": ["lag_ms"], "pass_threshold": 1}
    assert VariantIn.model_validate(cfg).model_dump() == cfg


@pytest.mark.parametrize("version", ["v1", "smooth_v2", "roaming_v3"])
def test_supported_path_version_is_preserved(version):
    cfg = {**V1, "path_version": version}
    assert VariantIn.model_validate(cfg).model_dump() == cfg


@pytest.mark.parametrize("version", ["unknown", None, [], {}, 2])
def test_invalid_path_version_is_rejected(version):
    with pytest.raises(ValidationError):
        VariantIn.model_validate({**V1, "path_version": version})
