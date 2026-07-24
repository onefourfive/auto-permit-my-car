from __future__ import annotations

import hmac
import os
import secrets
import threading
import time
from collections.abc import Callable
from datetime import date, datetime, time as clock_time, timedelta
from functools import wraps
from typing import Any, TypeVar
from zoneinfo import ZoneInfo

from flask import (
    Flask,
    abort,
    flash,
    redirect,
    render_template,
    request,
    session,
    url_for,
)

from .client import PermitMyCarClient, PermitMyCarError, PermitResult
from .config import ServiceConfig, load_service_config

PACIFIC = ZoneInfo("America/Los_Angeles")
REVIEW_TTL_SECONDS = 15 * 60
RESULT_TTL_SECONDS = 15 * 60
F = TypeVar("F", bound=Callable[..., Any])


class SubmissionRegistry:
    """Prevents a confirmation nonce from creating duplicate permits."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._completed: dict[str, tuple[float, PermitResult]] = {}

    def completed(self, nonce: str) -> PermitResult | None:
        with self._lock:
            self._cleanup()
            item = self._completed.get(nonce)
            return item[1] if item else None

    def submit_once(
        self, nonce: str, submitter: Callable[[], PermitResult]
    ) -> tuple[PermitResult, bool]:
        # The service is intentionally single-household. Serializing the
        # external call gives strong double-click protection without a DB.
        with self._lock:
            self._cleanup()
            existing = self._completed.get(nonce)
            if existing:
                return existing[1], True
            result = submitter()
            if result.success:
                self._completed[nonce] = (time.monotonic(), result)
            return result, False

    def _cleanup(self) -> None:
        cutoff = time.monotonic() - RESULT_TTL_SECONDS
        expired = [
            nonce
            for nonce, (created, _) in self._completed.items()
            if created < cutoff
        ]
        for nonce in expired:
            self._completed.pop(nonce, None)


def create_app(test_config: dict[str, Any] | None = None) -> Flask:
    app = Flask(__name__)
    app.config.from_mapping(
        SECRET_KEY=os.environ.get("FLASK_SECRET_KEY", ""),
        PERMIT_APP_PASSWORD=os.environ.get("PERMIT_APP_PASSWORD", ""),
        PERMIT_CONFIG_PATH=os.environ.get(
            "PERMIT_CONFIG_PATH", "login_info.yml"
        ),
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Strict",
        SESSION_COOKIE_SECURE=_environment_bool("COOKIE_SECURE", False),
        PERMANENT_SESSION_LIFETIME=timedelta(days=30),
    )
    if test_config:
        app.config.update(test_config)

    if not app.config.get("TESTING"):
        if not app.config["SECRET_KEY"]:
            raise RuntimeError("FLASK_SECRET_KEY must be set")
        if not app.config["PERMIT_APP_PASSWORD"]:
            raise RuntimeError("PERMIT_APP_PASSWORD must be set")

    service_config: ServiceConfig = app.config.get("SERVICE_CONFIG") or (
        load_service_config(app.config["PERMIT_CONFIG_PATH"])
    )
    app.extensions["service_config"] = service_config
    app.extensions["submission_registry"] = SubmissionRegistry()
    app.extensions["permit_client_factory"] = app.config.get(
        "PERMIT_CLIENT_FACTORY",
        lambda: PermitMyCarClient(service_config),
    )

    @app.before_request
    def validate_csrf() -> None:
        _csrf_token()
        if request.method == "POST":
            submitted = request.form.get("csrf_token", "")
            expected = session.get("csrf_token", "")
            if not submitted or not hmac.compare_digest(submitted, expected):
                abort(400, description="Invalid or missing CSRF token.")

    @app.context_processor
    def common_template_values() -> dict[str, Any]:
        return {"csrf_token": _csrf_token()}

    @app.get("/healthz")
    def healthz() -> tuple[dict[str, str], int]:
        return {"status": "ok"}, 200

    @app.route("/login", methods=["GET", "POST"])
    def login() -> Any:
        if session.get("authenticated"):
            return redirect(url_for("index"))
        if request.method == "POST":
            supplied = request.form.get("password", "")
            expected = str(app.config["PERMIT_APP_PASSWORD"])
            if expected and hmac.compare_digest(supplied, expected):
                session.clear()
                session["authenticated"] = True
                session["csrf_token"] = secrets.token_urlsafe(32)
                session.permanent = True
                return redirect(url_for("index"))
            flash("Incorrect password.", "error")
        return render_template("login.html")

    @app.post("/logout")
    @_login_required
    def logout() -> Any:
        session.clear()
        return redirect(url_for("login"))

    @app.get("/")
    @_login_required
    def index() -> Any:
        return render_template(
            "index.html",
            cars=service_config.cars,
            minimum_date=_minimum_permit_date().isoformat(),
            today=date.today().isoformat(),
        )

    @app.post("/review")
    @_login_required
    def review() -> Any:
        car = service_config.car_by_id(request.form.get("car_id", ""))
        parsed_dates, error = _parse_dates(request.form.getlist("dates"))
        if car is None:
            flash("Choose a configured car.", "error")
        if error:
            flash(error, "error")
        if car is None or error:
            return redirect(url_for("index"))

        nonce = secrets.token_urlsafe(24)
        session["pending_review"] = {
            "nonce": nonce,
            "car_id": car.id,
            "dates": [value.isoformat() for value in parsed_dates],
            "created": int(time.time()),
        }
        return render_template(
            "review.html",
            car=car,
            dates=parsed_dates,
            nonce=nonce,
        )

    @app.post("/permit")
    @_login_required
    def permit() -> Any:
        nonce = request.form.get("nonce", "")
        registry: SubmissionRegistry = app.extensions["submission_registry"]

        cached = registry.completed(nonce)
        if cached:
            return render_template(
                "result.html", result=cached, replayed=True
            )

        pending = session.get("pending_review")
        if not _valid_pending_review(pending, nonce):
            flash(
                "That review expired or was already used. Review the permit again.",
                "error",
            )
            return redirect(url_for("index"))

        car = service_config.car_by_id(str(pending["car_id"]))
        parsed_dates, error = _parse_dates(list(pending["dates"]))
        if car is None or error:
            session.pop("pending_review", None)
            flash("The reviewed permit is no longer valid.", "error")
            return redirect(url_for("index"))

        factory: Callable[[], PermitMyCarClient] = app.extensions[
            "permit_client_factory"
        ]
        try:
            result, replayed = registry.submit_once(
                nonce,
                lambda: factory().submit(car, parsed_dates),
            )
        except PermitMyCarError as exc:
            result = PermitResult(success=False, message=str(exc))
            replayed = False

        if result.success:
            session.pop("pending_review", None)
        return render_template(
            "result.html", result=result, replayed=replayed
        )

    return app


def _login_required(view: F) -> F:
    @wraps(view)
    def wrapped(*args: Any, **kwargs: Any) -> Any:
        if not session.get("authenticated"):
            return redirect(url_for("login"))
        return view(*args, **kwargs)

    return wrapped  # type: ignore[return-value]


def _csrf_token() -> str:
    token = session.get("csrf_token")
    if not token:
        token = secrets.token_urlsafe(32)
        session["csrf_token"] = token
    return token


def _minimum_permit_date(now: datetime | None = None) -> date:
    current = now.astimezone(PACIFIC) if now else datetime.now(PACIFIC)
    if current.time() < clock_time(hour=6):
        return current.date() - timedelta(days=1)
    return current.date()


def _parse_dates(values: list[str]) -> tuple[tuple[date, ...], str | None]:
    if not values:
        return (), "Choose at least one permit date."
    parsed: set[date] = set()
    try:
        for value in values:
            parsed.add(date.fromisoformat(value))
    except (TypeError, ValueError):
        return (), "One or more permit dates are invalid."
    if not parsed:
        return (), "Choose at least one permit date."
    if min(parsed) < _minimum_permit_date():
        return (), "A selected date is too far in the past."
    return tuple(sorted(parsed)), None


def _valid_pending_review(pending: Any, nonce: str) -> bool:
    if not isinstance(pending, dict) or not nonce:
        return False
    if not hmac.compare_digest(str(pending.get("nonce", "")), nonce):
        return False
    try:
        age = int(time.time()) - int(pending["created"])
    except (KeyError, TypeError, ValueError):
        return False
    return 0 <= age <= REVIEW_TTL_SECONDS


def _environment_bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().casefold() in {"1", "true", "yes", "on"}
