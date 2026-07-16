"""Tests for BROKE_DISABLED_FEATURES / app.utils.features"""

import os
from unittest.mock import patch

from ward import test

from app.utils.features import FEATURE_UPDATER, get_disabled_features, is_feature_enabled


@test("get_disabled_features is empty when unset")
def _():
    with patch.dict(os.environ, {"BROKE_DISABLED_FEATURES": ""}):
        assert get_disabled_features() == frozenset()


@test("get_disabled_features parses comma-separated lowercase ids")
def _():
    with patch.dict(os.environ, {"BROKE_DISABLED_FEATURES": " updater , other "}):
        assert get_disabled_features() == frozenset({"updater", "other"})


@test("is_feature_enabled is false for disabled updater")
def _():
    with patch.dict(os.environ, {"BROKE_DISABLED_FEATURES": FEATURE_UPDATER}):
        assert is_feature_enabled(FEATURE_UPDATER) is False


@test("is_feature_enabled is true when updater not listed")
def _():
    with patch.dict(os.environ, {"BROKE_DISABLED_FEATURES": "something_else"}):
        assert is_feature_enabled(FEATURE_UPDATER) is True
