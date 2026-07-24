from __future__ import annotations

from datetime import date

import pytest
import requests

from permitmycar_app.client import (
    AuthenticationError,
    ConfigurationMismatchError,
    PermitMyCarClient,
    UpstreamUnavailableError,
)


class FakeResponse:
    def __init__(self, *, text="", json_data=None, status_code=200):
        self.text = text
        self._json_data = json_data
        self.status_code = status_code

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"status {self.status_code}")

    def json(self):
        if isinstance(self._json_data, Exception):
            raise self._json_data
        return self._json_data


class FakeSession:
    def __init__(self, responses):
        self.responses = iter(responses)
        self.headers = {}
        self.calls = []

    def get(self, url, **kwargs):
        self.calls.append(("GET", url, kwargs))
        return next(self.responses)

    def post(self, url, **kwargs):
        self.calls.append(("POST", url, kwargs))
        return next(self.responses)


def form_html():
    return """
    <form action="safelist.php?do=save" method="post">
      <input type="hidden" name="account" value="account-id">
      <input type="hidden" name="location" value="street-id">
      <select name="vmake">
        <option value="0">Choose</option>
        <option value="10">Honda</option>
      </select>
      <select name="vcolor">
        <option value="0">Choose</option>
        <option value="20">Blue</option>
      </select>
    </form>
    """


def prepared_responses(final_html: str):
    return [
        FakeResponse(text="<html>home</html>"),
        FakeResponse(
            json_data={
                "status": "OK",
                "streets": [
                    {
                        "street": "street-id",
                        "account": "account-id",
                        "unitnum": "",
                    }
                ],
            }
        ),
        FakeResponse(json_data={"status": "OK", "changepw": False}),
        FakeResponse(text=form_html()),
        FakeResponse(text=final_html),
    ]


def test_submits_resolved_ids_and_formatted_dates(service_config):
    session = FakeSession(
        prepared_responses(
            '<div class="alert-success">Vehicle has been safelisted.</div>'
        )
    )
    client = PermitMyCarClient(service_config, session=session)

    result = client.submit(
        service_config.cars[0],
        (date(2030, 1, 2), date(2030, 1, 3)),
    )

    assert result.success
    method, url, kwargs = session.calls[-1]
    assert method == "POST"
    assert "do=save" in url
    assert kwargs["data"]["vmake"] == "10"
    assert kwargs["data"]["vcolor"] == "20"
    assert kwargs["data"]["dates"] == "01/02/2030,01/03/2030"
    assert kwargs["data"]["uaaccepted"] == "1"
    assert kwargs["allow_redirects"] is True


def test_rejects_bad_pin_before_requesting_form(service_config):
    session = FakeSession(
        [
            FakeResponse(text="home"),
            prepared_responses("unused")[1],
            FakeResponse(json_data={"status": "ERROR"}),
        ]
    )

    with pytest.raises(AuthenticationError, match="PIN"):
        PermitMyCarClient(service_config, session=session).submit(
            service_config.cars[0], (date(2030, 1, 2),)
        )

    assert len(session.calls) == 3


def test_stops_when_configured_option_no_longer_exists(service_config):
    session = FakeSession(prepared_responses("unused")[:-1])
    changed_car = service_config.cars[1]

    with pytest.raises(ConfigurationMismatchError, match="make"):
        PermitMyCarClient(service_config, session=session).submit(
            changed_car, (date(2030, 1, 2),)
        )

    assert all("do=save" not in call[1] for call in session.calls)


def test_form_rerender_is_a_rejection(service_config):
    html = form_html().replace(
        "<form ",
        '<div class="alert-danger">Dates are not available.</div><form ',
    )
    session = FakeSession(prepared_responses(html))

    result = PermitMyCarClient(service_config, session=session).submit(
        service_config.cars[0], (date(2030, 1, 2),)
    )

    assert not result.success
    assert result.message == "Dates are not available."


def test_unknown_final_response_fails_closed(service_config):
    session = FakeSession(prepared_responses("<html><p>Welcome</p></html>"))

    with pytest.raises(UpstreamUnavailableError, match="unfamiliar"):
        PermitMyCarClient(service_config, session=session).submit(
            service_config.cars[0], (date(2030, 1, 2),)
        )


@pytest.mark.parametrize(
    ("message", "expected"),
    [
        ("Vehicle has been denied.", "rejected"),
        ("Permit has been rejected.", "rejected"),
        ("Confirmation is pending.", "unfamiliar"),
        ("Vehicle has been inspected.", "unfamiliar"),
    ],
)
def test_ambiguous_or_negative_wording_is_never_success(
    service_config, message, expected
):
    session = FakeSession(prepared_responses(f"<html><p>{message}</p></html>"))
    client = PermitMyCarClient(service_config, session=session)

    if expected == "rejected":
        result = client.submit(
            service_config.cars[0], (date(2030, 1, 2),)
        )
        assert not result.success
    else:
        with pytest.raises(UpstreamUnavailableError, match=expected):
            client.submit(service_config.cars[0], (date(2030, 1, 2),))


def test_explicit_success_phrase_without_success_element_is_accepted(
    service_config,
):
    session = FakeSession(
        prepared_responses("<html><p>Vehicle has been safelisted.</p></html>")
    )

    result = PermitMyCarClient(service_config, session=session).submit(
        service_config.cars[0], (date(2030, 1, 2),)
    )

    assert result.success
