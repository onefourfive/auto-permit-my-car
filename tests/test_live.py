from __future__ import annotations

import os

import pytest

from permitmycar_app.client import PermitMyCarClient
from permitmycar_app.config import load_service_config


@pytest.mark.live
def test_live_login_and_form_mapping_without_saving():
    if os.environ.get("RUN_LIVE_TESTS") != "1":
        pytest.skip("set RUN_LIVE_TESTS=1 to run the non-saving live check")

    config = load_service_config(
        os.environ.get("PERMIT_CONFIG_PATH", "login_info.yml")
    )
    form = PermitMyCarClient(config)._prepare_form()

    assert form.action.endswith("safelist.php?do=save")
    for car in config.cars:
        assert car.make.casefold() in form.make_ids
        assert car.color.casefold() in form.color_ids
