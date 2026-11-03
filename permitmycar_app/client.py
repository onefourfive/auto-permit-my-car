from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from typing import Any
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

from .config import CarConfig, ServiceConfig


class PermitMyCarError(RuntimeError):
    """A safe, user-displayable error from the upstream integration."""


class AuthenticationError(PermitMyCarError):
    pass


class ConfigurationMismatchError(PermitMyCarError):
    pass


class UpstreamUnavailableError(PermitMyCarError):
    pass


@dataclass(frozen=True)
class PermitResult:
    success: bool
    message: str
    confirmation: str = ""
    # The safelist confirmation code that must be shown on the windshield.
    confirmation_code: str = ""


@dataclass(frozen=True)
class PreparedForm:
    action: str
    hidden_fields: dict[str, str]
    make_ids: dict[str, str]
    color_ids: dict[str, str]


class PermitMyCarClient:
    BASE_URL = "https://www.permitmycar.com/"
    TIMEOUT = (5, 15)

    def __init__(
        self,
        config: ServiceConfig,
        *,
        session: requests.Session | None = None,
        base_url: str | None = None,
    ) -> None:
        self.config = config
        self.session = session or requests.Session()
        self.base_url = base_url or self.BASE_URL
        self.session.headers.update(
            {
                "User-Agent": (
                    "permitmycar-family-service/1.0 "
                    "(private resident automation)"
                )
            }
        )

    def submit(self, car: CarConfig, dates: tuple[date, ...]) -> PermitResult:
        prepared = self._prepare_form()
        make_id = self._lookup_option(prepared.make_ids, car.make, "make")
        color_id = self._lookup_option(prepared.color_ids, car.color, "color")

        payload = dict(prepared.hidden_fields)
        payload.update(
            {
                "rfname": self.config.resident.first_name,
                "rlname": self.config.resident.last_name,
                "remail": self.config.resident.email,
                "rphone": self.config.resident.phone,
                "vlicense": car.license_plate,
                "vin": car.vin,
                "vmake": make_id,
                "vmodel": car.model,
                "vcolor": color_id,
                "uaaccepted": payload.get("uaaccepted", "1") or "1",
                "dates": ",".join(value.strftime("%m/%d/%Y") for value in dates),
                "do": "save",
            }
        )

        try:
            response = self.session.post(
                prepared.action,
                data=payload,
                timeout=self.TIMEOUT,
                allow_redirects=True,
            )
            response.raise_for_status()
        except requests.RequestException as exc:
            raise UpstreamUnavailableError(
                "PermitMyCar did not respond. No automatic retry was attempted."
            ) from exc

        return self._parse_submission_response(response.text)

    def _prepare_form(self) -> PreparedForm:
        try:
            self.session.get(self.base_url, timeout=self.TIMEOUT).raise_for_status()
            address_response = self.session.get(
                urljoin(self.base_url, "global.php"),
                params={
                    "do": "validate",
                    "module": "address",
                    "value": self.config.login.street_address,
                    "placeID": "",
                },
                timeout=self.TIMEOUT,
            )
            address_response.raise_for_status()
            address_data = address_response.json()
        except (requests.RequestException, ValueError) as exc:
            raise UpstreamUnavailableError(
                "PermitMyCar could not validate the configured address."
            ) from exc

        if address_data.get("status") != "OK":
            raise AuthenticationError(
                "PermitMyCar rejected the configured street address."
            )
        location = self._choose_location(address_data.get("streets"))

        self._validate_pin(location)

        try:
            fill_response = self.session.post(
                urljoin(self.base_url, "safelist.php?do=fill"),
                data={
                    "address": self.config.login.street_address,
                    "location": str(location["street"]),
                    "account": str(location["account"]),
                    "pin": self.config.login.pin,
                    "do": "fill",
                },
                timeout=self.TIMEOUT,
            )
            fill_response.raise_for_status()
        except requests.RequestException as exc:
            raise UpstreamUnavailableError(
                "PermitMyCar did not return the permit form."
            ) from exc

        soup = BeautifulSoup(fill_response.text, "html.parser")
        form = soup.find("form", action=lambda value: value and "do=save" in value)
        if form is None:
            message = self._extract_error(soup)
            raise AuthenticationError(
                message or "PermitMyCar did not accept the configured login."
            )

        hidden_fields = {
            field.get("name"): field.get("value", "")
            for field in form.select('input[type="hidden"][name]')
        }
        hidden_fields.setdefault("account", str(location["account"]))
        hidden_fields.setdefault("location", str(location["street"]))

        return PreparedForm(
            action=urljoin(self.base_url, form.get("action", "")),
            hidden_fields=hidden_fields,
            make_ids=self._options(form, "vmake"),
            color_ids=self._options(form, "vcolor"),
        )

    def _choose_location(self, streets: Any) -> dict[str, Any]:
        if not isinstance(streets, list) or not streets:
            raise AuthenticationError(
                "No PermitMyCar community matched the configured address."
            )

        unit = self.config.login.unit_number
        if unit:
            matches = [
                street
                for street in streets
                if str(street.get("unitnum", "")).strip() == unit
            ]
        else:
            matches = streets if len(streets) == 1 else []

        if len(matches) != 1:
            raise AuthenticationError(
                "The configured unit number did not identify one community."
            )
        location = matches[0]
        if not location.get("street") or not location.get("account"):
            raise UpstreamUnavailableError(
                "PermitMyCar returned an incomplete community record."
            )
        return location

    def _validate_pin(self, location: dict[str, Any]) -> None:
        try:
            response = self.session.get(
                urljoin(self.base_url, "global.php"),
                params={
                    "do": "validate",
                    "module": "location",
                    "id": location["street"],
                    "pw": self.config.login.pin,
                },
                timeout=self.TIMEOUT,
            )
            response.raise_for_status()
            data = response.json()
        except (requests.RequestException, ValueError) as exc:
            raise UpstreamUnavailableError(
                "PermitMyCar could not validate the configured PIN."
            ) from exc

        if data.get("status") != "OK":
            raise AuthenticationError(
                "PermitMyCar rejected the configured PIN."
            )
        if data.get("changepw"):
            raise AuthenticationError(
                "PermitMyCar requires the temporary PIN to be changed manually."
            )

    @staticmethod
    def _options(form: Any, name: str) -> dict[str, str]:
        select = form.find("select", attrs={"name": name})
        if select is None:
            raise UpstreamUnavailableError(
                f"PermitMyCar no longer provides the {name} list."
            )
        return {
            option.get_text(" ", strip=True).casefold(): option.get("value", "")
            for option in select.find_all("option")
            if option.get("value") not in (None, "", "0")
        }

    @staticmethod
    def _lookup_option(options: dict[str, str], value: str, label: str) -> str:
        option_id = options.get(value.strip().casefold())
        if not option_id:
            raise ConfigurationMismatchError(
                f'The configured vehicle {label} "{value}" is not available '
                "on PermitMyCar."
            )
        return option_id

    @classmethod
    def _parse_submission_response(cls, html: str) -> PermitResult:
        soup = BeautifulSoup(html, "html.parser")
        if soup.find("form", action=lambda value: value and "do=save" in value):
            return PermitResult(
                success=False,
                message=cls._extract_error(soup)
                or "PermitMyCar rejected the permit details.",
            )

        text = " ".join(soup.stripped_strings)
        normalized = text.casefold()
        error_markers = (
            "missing information",
            "invalid pin",
            "unable to",
            "could not",
            "error:",
            "not permitted",
            "has been denied",
            "has been rejected",
            "permit denied",
            "permit rejected",
        )
        if any(marker in normalized for marker in error_markers):
            return PermitResult(
                success=False,
                message=cls._extract_error(soup)
                or "PermitMyCar rejected the permit.",
            )

        confirmation = cls._extract_confirmation(soup)
        ambiguous_markers = (
            "denied",
            "rejected",
            "pending",
            "failed",
            "error",
        )
        structured_success = bool(confirmation) and not any(
            marker in confirmation.casefold() for marker in ambiguous_markers
        )
        explicit_success = any(
            re.search(pattern, normalized)
            for pattern in (
                # PermitMyCar's page reads "<plate> has been safelisted for
                # the night(s) of", so no "vehicle" precedes the phrase.
                r"\b(?:has been|was) (?:successfully )?safelisted\b",
                r"\bvehicle (?:has been|was) permitted successfully\b",
                r"\bpermit (?:has been|was) (?:successfully )?"
                r"(?:approved|created|issued|saved|submitted)\b",
                r"\bsuccessfully (?:permitted|safelisted)\b",
            )
        )
        if structured_success or explicit_success:
            return PermitResult(
                success=True,
                message="The vehicle was permitted successfully.",
                confirmation=confirmation,
                confirmation_code=cls._extract_confirmation_code(
                    soup, confirmation, text
                ),
            )

        raise UpstreamUnavailableError(
            "PermitMyCar returned an unfamiliar response. Check PermitMyCar "
            "before trying again; the service did not retry."
        )

    @staticmethod
    def _extract_error(soup: BeautifulSoup) -> str:
        selectors = (
            ".alert-danger",
            "#form-error",
            ".text-danger",
            ".error",
        )
        for selector in selectors:
            node = soup.select_one(selector)
            if node:
                text = node.get_text(" ", strip=True)
                if text:
                    return text[:300]
        return ""

    @staticmethod
    def _extract_confirmation(soup: BeautifulSoup) -> str:
        for selector in (".alert-success", ".confirmation", "#confirmation"):
            node = soup.select_one(selector)
            if node:
                return node.get_text(" ", strip=True)[:300]
        return ""

    @staticmethod
    def _extract_confirmation_code(soup: BeautifulSoup, *texts: str) -> str:
        # PermitMyCar labels the code in one element and shows it alone in
        # the next: <p>This is your confirmation number</p><h2>K8D2</h2>.
        # A code must contain a digit so boilerplate such as "the
        # confirmation code is required" is never mistaken for one.
        code_shape = re.compile(r"[A-Z0-9][A-Z0-9-]{2,31}", re.IGNORECASE)
        label = re.compile(r"\bconfirmation (?:code|number)\s*:?\s*$", re.IGNORECASE)
        for node in soup.find_all(string=label):
            following = node.parent.find_next_sibling() if node.parent else None
            if following is None:
                continue
            code = following.get_text(" ", strip=True)
            if code_shape.fullmatch(code) and any(c.isdigit() for c in code):
                return code

        pattern = re.compile(
            r"\bconfirmation\s*(?:code|number|no\.?|#)?\s*(?:is\b)?\s*[:#]?\s*"
            r"([A-Z0-9][A-Z0-9-]{2,31})\b",
            re.IGNORECASE,
        )
        for text in texts:
            for match in pattern.finditer(text):
                code = match.group(1)
                if any(character.isdigit() for character in code):
                    return code
        return ""
