from __future__ import annotations

from dataclasses import dataclass

import pytest

from permitmycar_app.client import PermitResult
from permitmycar_app.config import (
    CarConfig,
    LoginConfig,
    ResidentConfig,
    ServiceConfig,
)
from permitmycar_app.web import create_app


@dataclass
class FakePermitClient:
    result: PermitResult | Exception
    calls: list[tuple[CarConfig, tuple]]

    def submit(self, car: CarConfig, dates: tuple) -> PermitResult:
        self.calls.append((car, dates))
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


@pytest.fixture
def service_config() -> ServiceConfig:
    return ServiceConfig(
        login=LoginConfig("1 Test Street", "", "1234"),
        resident=ResidentConfig(
            "Test", "Resident", "resident@example.com", "555-555-0100"
        ),
        cars=(
            CarConfig(
                id="1",
                name="Family sedan",
                make="Honda",
                model="Accord",
                color="Blue",
                license_plate="TEST123",
            ),
            CarConfig(
                id="2",
                name="Family SUV",
                make="Toyota",
                model="RAV4",
                color="White",
                license_plate="TEST456",
            ),
        ),
    )


@pytest.fixture
def fake_client() -> FakePermitClient:
    return FakePermitClient(
        result=PermitResult(True, "The vehicle was permitted successfully."),
        calls=[],
    )


@pytest.fixture
def app(service_config: ServiceConfig, fake_client: FakePermitClient):
    app = create_app(
        {
            "TESTING": True,
            "SECRET_KEY": "test-secret",
            "PERMIT_APP_PASSWORD": "house-password",
            "SERVICE_CONFIG": service_config,
            "PERMIT_CLIENT_FACTORY": lambda: fake_client,
        }
    )
    return app


@pytest.fixture
def client(app):
    return app.test_client()


def csrf(client) -> str:
    with client.session_transaction() as current_session:
        return current_session["csrf_token"]


def log_in(client) -> None:
    client.get("/login")
    client.post(
        "/login",
        data={"password": "house-password", "csrf_token": csrf(client)},
    )
