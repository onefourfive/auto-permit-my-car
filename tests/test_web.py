from __future__ import annotations

from datetime import date, datetime

from permitmycar_app.client import PermitResult, UpstreamUnavailableError
from permitmycar_app.web import PACIFIC, _minimum_permit_date

from .conftest import csrf, log_in


def test_private_pages_require_login(client):
    response = client.get("/")

    assert response.status_code == 302
    assert response.headers["Location"].endswith("/login")


def test_login_rejects_bad_password_and_accepts_good_one(client):
    client.get("/login")
    bad = client.post(
        "/login",
        data={"password": "wrong", "csrf_token": csrf(client)},
    )
    assert b"Incorrect password" in bad.data

    good = client.post(
        "/login",
        data={"password": "house-password", "csrf_token": csrf(client)},
    )
    assert good.status_code == 302
    assert good.headers["Location"].endswith("/")


def test_post_requires_csrf(client):
    response = client.post("/login", data={"password": "house-password"})

    assert response.status_code == 400


def test_index_renders_inline_calendar_without_activation_control(client):
    log_in(client)

    response = client.get("/")

    assert response.status_code == 200
    assert b'id="date-calendar"' in response.data
    assert b'id="calendar-grid"' in response.data
    assert b'id="previous-month"' in response.data
    assert b'id="next-month"' in response.data
    assert b'id="clear-dates"' in response.data
    assert b'id="date-picker"' not in response.data
    assert b'id="add-date"' not in response.data
    assert b'name="dates"' in response.data  # no-JavaScript fallback


def test_review_and_submit_one_car_for_multiple_dates(
    client, fake_client
):
    log_in(client)
    review = client.post(
        "/review",
        data={
            "csrf_token": csrf(client),
            "car_id": "1",
            "dates": ["2030-01-03", "2030-01-02", "2030-01-02"],
        },
    )

    assert review.status_code == 200
    assert b"Family sedan" in review.data
    assert b"January 2, 2030" in review.data
    with client.session_transaction() as current_session:
        nonce = current_session["pending_review"]["nonce"]

    result = client.post(
        "/permit",
        data={"csrf_token": csrf(client), "nonce": nonce},
    )

    assert result.status_code == 200
    assert b"Permit complete" in result.data
    assert len(fake_client.calls) == 1
    _, dates = fake_client.calls[0]
    assert dates == (date(2030, 1, 2), date(2030, 1, 3))


def test_successful_nonce_is_not_submitted_twice(client, fake_client):
    log_in(client)
    client.post(
        "/review",
        data={
            "csrf_token": csrf(client),
            "car_id": "1",
            "dates": "2030-01-02",
        },
    )
    with client.session_transaction() as current_session:
        nonce = current_session["pending_review"]["nonce"]

    for _ in range(2):
        response = client.post(
            "/permit",
            data={"csrf_token": csrf(client), "nonce": nonce},
        )
        assert response.status_code == 200

    assert len(fake_client.calls) == 1
    assert b"already submitted" in response.data


def test_indeterminate_nonce_is_consumed_before_upstream_call(
    client, fake_client
):
    fake_client.result = UpstreamUnavailableError(
        "PermitMyCar timed out after submission. No retry was attempted."
    )
    log_in(client)
    client.post(
        "/review",
        data={
            "csrf_token": csrf(client),
            "car_id": "1",
            "dates": "2030-01-02",
        },
    )
    with client.session_transaction() as current_session:
        nonce = current_session["pending_review"]["nonce"]

    first = client.post(
        "/permit",
        data={"csrf_token": csrf(client), "nonce": nonce},
    )
    second = client.post(
        "/permit",
        data={"csrf_token": csrf(client), "nonce": nonce},
    )

    assert b"timed out after submission" in first.data
    assert b"already started" in second.data
    assert len(fake_client.calls) == 1


def test_rejected_nonce_cannot_be_resubmitted(client, fake_client):
    fake_client.result = PermitResult(
        success=False, message="PermitMyCar rejected the dates."
    )
    log_in(client)
    client.post(
        "/review",
        data={
            "csrf_token": csrf(client),
            "car_id": "1",
            "dates": "2030-01-02",
        },
    )
    with client.session_transaction() as current_session:
        nonce = current_session["pending_review"]["nonce"]

    for _ in range(2):
        response = client.post(
            "/permit",
            data={"csrf_token": csrf(client), "nonce": nonce},
        )
        assert b"rejected the dates" in response.data

    assert len(fake_client.calls) == 1


def test_review_rejects_missing_car_and_date(client):
    log_in(client)
    response = client.post(
        "/review",
        data={"csrf_token": csrf(client)},
        follow_redirects=True,
    )

    assert b"Choose a configured car" in response.data
    assert b"Choose at least one permit date" in response.data


def test_yesterday_allowed_only_before_six_am_pacific():
    early = datetime(2030, 1, 2, 5, 59, tzinfo=PACIFIC)
    later = datetime(2030, 1, 2, 6, 0, tzinfo=PACIFIC)

    assert _minimum_permit_date(early) == date(2030, 1, 1)
    assert _minimum_permit_date(later) == date(2030, 1, 2)


def test_healthcheck_contains_no_private_data(client):
    response = client.get("/healthz")

    assert response.status_code == 200
    assert response.json == {"status": "ok"}


def _submit_reviewed_permit(client):
    log_in(client)
    client.post(
        "/review",
        data={
            "csrf_token": csrf(client),
            "car_id": "1",
            "dates": "2030-01-02",
        },
    )
    with client.session_transaction() as current_session:
        nonce = current_session["pending_review"]["nonce"]
    return client.post(
        "/permit",
        data={"csrf_token": csrf(client), "nonce": nonce},
    )


def test_success_page_shows_confirmation_code(client, fake_client):
    fake_client.result = PermitResult(
        True,
        "The vehicle was permitted successfully.",
        confirmation_code="4827193",
    )

    response = _submit_reviewed_permit(client)

    assert b"Confirmation code" in response.data
    assert b"4827193" in response.data
    assert b"No confirmation code was found" not in response.data


def test_success_page_warns_when_confirmation_code_is_missing(client):
    response = _submit_reviewed_permit(client)

    assert b"Permit complete" in response.data
    assert b"No confirmation code was found" in response.data
