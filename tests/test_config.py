from __future__ import annotations

import textwrap

import pytest

from permitmycar_app.config import ConfigError, load_service_config


VALID_CONFIG = """
login:
  your_street_address: 1 Test Street
  unit_number: ""
  pin: "1234"
resident:
  first_name: Test
  last_name: Resident
  email: resident@example.com
  phone: 555-555-0100
cars:
  - name: Family sedan
    make: Honda
    model: Accord
    color: Blue
    license_plate: TEST123
"""


def write_config(tmp_path, contents: str):
    path = tmp_path / "login_info.yml"
    path.write_text(textwrap.dedent(contents), encoding="utf-8")
    return path


def test_loads_valid_config_and_assigns_stable_ids(tmp_path):
    config = load_service_config(write_config(tmp_path, VALID_CONFIG))

    assert config.login.pin == "1234"
    assert config.cars[0].id == "1"
    assert config.cars[0].vin == ""


@pytest.mark.parametrize("pin", ["123", "abcd", "", "12345"])
def test_rejects_invalid_pin(tmp_path, pin):
    raw = VALID_CONFIG.replace('pin: "1234"', f'pin: "{pin}"')

    with pytest.raises(ConfigError, match="four digits"):
        load_service_config(write_config(tmp_path, raw))


def test_rejects_duplicate_car_names_case_insensitively(tmp_path):
    raw = VALID_CONFIG + """
  - name: FAMILY SEDAN
    make: Toyota
    model: Camry
    color: Black
    license_plate: OTHER1
"""

    with pytest.raises(ConfigError, match="unique"):
        load_service_config(write_config(tmp_path, raw))


def test_rejects_missing_car_field_without_exposing_other_values(tmp_path):
    raw = VALID_CONFIG.replace("    color: Blue\n", "")

    with pytest.raises(ConfigError, match=r"cars\[0\]\.color"):
        load_service_config(write_config(tmp_path, raw))
