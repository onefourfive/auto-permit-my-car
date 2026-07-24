from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml


class ConfigError(ValueError):
    """Raised when login_info.yml is incomplete or malformed."""


@dataclass(frozen=True)
class LoginConfig:
    street_address: str
    unit_number: str
    pin: str


@dataclass(frozen=True)
class ResidentConfig:
    first_name: str
    last_name: str
    email: str
    phone: str


@dataclass(frozen=True)
class CarConfig:
    id: str
    name: str
    make: str
    model: str
    color: str
    license_plate: str
    vin: str = ""


@dataclass(frozen=True)
class ServiceConfig:
    login: LoginConfig
    resident: ResidentConfig
    cars: tuple[CarConfig, ...]

    def car_by_id(self, car_id: str) -> CarConfig | None:
        return next((car for car in self.cars if car.id == car_id), None)


def _mapping(value: Any, path: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ConfigError(f"{path} must be a mapping")
    return value


def _required_text(mapping: dict[str, Any], key: str, path: str) -> str:
    value = mapping.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ConfigError(f"{path}.{key} must be a non-empty string")
    return value.strip()


def _optional_text(mapping: dict[str, Any], key: str) -> str:
    value = mapping.get(key, "")
    if value is None:
        return ""
    if not isinstance(value, str):
        raise ConfigError(f"{key} must be a string")
    return value.strip()


def load_service_config(path: str | Path) -> ServiceConfig:
    config_path = Path(path)
    try:
        raw = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ConfigError(f"configuration file not found: {config_path}") from exc
    except yaml.YAMLError as exc:
        raise ConfigError(f"invalid YAML in {config_path}") from exc

    root = _mapping(raw, "root")
    login_raw = _mapping(root.get("login"), "login")
    resident_raw = _mapping(root.get("resident"), "resident")
    cars_raw = root.get("cars")
    if not isinstance(cars_raw, list) or not cars_raw:
        raise ConfigError("cars must be a non-empty list")

    pin = _optional_text(login_raw, "pin")
    if len(pin) != 4 or not pin.isdigit():
        raise ConfigError("login.pin must contain exactly four digits")

    login = LoginConfig(
        street_address=_required_text(
            login_raw, "your_street_address", "login"
        ),
        unit_number=_optional_text(login_raw, "unit_number"),
        pin=pin,
    )
    resident = ResidentConfig(
        first_name=_required_text(resident_raw, "first_name", "resident"),
        last_name=_required_text(resident_raw, "last_name", "resident"),
        email=_required_text(resident_raw, "email", "resident"),
        phone=_required_text(resident_raw, "phone", "resident"),
    )

    cars: list[CarConfig] = []
    names: set[str] = set()
    for index, item in enumerate(cars_raw, start=1):
        car_raw = _mapping(item, f"cars[{index - 1}]")
        name = _required_text(car_raw, "name", f"cars[{index - 1}]")
        normalized_name = name.casefold()
        if normalized_name in names:
            raise ConfigError(f"car names must be unique: {name}")
        names.add(normalized_name)
        cars.append(
            CarConfig(
                id=str(index),
                name=name,
                make=_required_text(car_raw, "make", f"cars[{index - 1}]"),
                model=_required_text(car_raw, "model", f"cars[{index - 1}]"),
                color=_required_text(car_raw, "color", f"cars[{index - 1}]"),
                license_plate=_required_text(
                    car_raw, "license_plate", f"cars[{index - 1}]"
                ),
                vin=_optional_text(car_raw, "vin"),
            )
        )

    return ServiceConfig(login=login, resident=resident, cars=tuple(cars))
