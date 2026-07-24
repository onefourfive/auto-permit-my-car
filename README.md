# Permit a car

A private, mobile-friendly front end for permitting a pre-configured family car
through [PermitMyCar](https://www.permitmycar.com/).

The browser receives only friendly car names and descriptions. The resident
address, PermitMyCar PIN, contact details, and license plates remain in the
server-side `login_info.yml`.

## Run with Docker

1. Copy the environment template and replace both secrets:

   ```sh
   cp .env.example .env
   python3 -c 'import secrets; print(secrets.token_urlsafe(48))'
   ```

2. Confirm `login_info.yml` contains the household and vehicle information.
   A vehicle may optionally include `vin`, containing the last six digits.

3. Start the service:

   ```sh
   docker compose up --build -d
   ```

4. Open `http://<server-address>:8080` from the private network.

The login session lasts 30 days. For encrypted browser traffic, put the service
behind an HTTPS reverse proxy or expose it through a private networking service
such as Tailscale, then set `COOKIE_SECURE=true`.

## Configuration

The existing YAML shape is used directly:

```yaml
login:
  your_street_address: "..."
  unit_number: ""
  pin: "0000"
resident:
  first_name: "..."
  last_name: "..."
  email: "..."
  phone: "..."
cars:
  - name: "Friendly name shown in the app"
    make: "..."
    model: "..."
    color: "..."
    license_plate: "..."
    # vin: "optional last six digits"
```

Make and color must match PermitMyCar's current dropdown labels. The service
looks up their internal IDs from the live form and stops with a clear error if
the site or configured value changes.

## Development and tests

Create an isolated environment, install the development dependencies, and run
the tests:

```sh
python3 -m venv .venv
.venv/bin/pip install -r requirements-dev.txt
.venv/bin/pytest
```

All regular tests mock PermitMyCar and cannot create a permit. The service does
not automatically retry the final external POST because its outcome could be
ambiguous.

## Operational notes

- Review tokens expire after 15 minutes.
- Dates are interpreted in `America/Los_Angeles`. Before 6:00 AM, yesterday is
  also selectable to match PermitMyCar's overnight behavior.
- Successful confirmation nonces are cached for 15 minutes to absorb duplicate
  browser submissions. This cache is intentionally in memory and resets when
  the container restarts.
- No credentials or complete upstream response bodies are logged by the app.
