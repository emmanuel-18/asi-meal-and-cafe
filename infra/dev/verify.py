"""Development HTTPS smoke checks; optional normal interactive sign-in/logout."""

import argparse
import getpass
import http.cookiejar
import ipaddress
import json
from pathlib import Path
import ssl
import urllib.error
import urllib.request


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sign-in", action="store_true", help="Prompt privately for an existing account")
    args = parser.parse_args()
    folder = Path(__file__).resolve().parent
    fields = dict(line.split("=", 1) for line in (folder / ".env").read_text().splitlines()
                  if line.strip() and not line.startswith("#"))
    host = fields["DEV_HOST"].strip()
    port = fields["DEV_WEB_PORT"].strip()
    address = ipaddress.ip_address(host)
    if not address.is_private or address.is_loopback or address.version != 4:
        raise SystemExit("DEV_HOST must be this machine's private LAN IPv4 address")
    if not port.isdecimal() or not 1 <= int(port) <= 65535:
        raise SystemExit("DEV_WEB_PORT must be a valid TCP port")
    base = f"https://{host}:{port}"
    context = ssl.create_default_context(cafile=str(folder / "dev-root-ca.crt"))
    jar = http.cookiejar.CookieJar()
    client = urllib.request.build_opener(urllib.request.ProxyHandler({}),
        urllib.request.HTTPSHandler(context=context), urllib.request.HTTPCookieProcessor(jar))

    def request(path, expected, body=None, origin=base, csrf=None):
        headers = {"Origin": origin}
        if body is not None:
            headers.update({"Content-Type": "application/json", "X-ASI-Request": "1"})
        if csrf:
            headers["X-CSRF-Token"] = csrf
        req = urllib.request.Request(base + path, headers=headers,
            data=None if body is None else json.dumps(body).encode())
        try:
            response = client.open(req, timeout=20)
        except urllib.error.HTTPError as error:
            response = error
        with response:
            if response.code != expected:
                raise RuntimeError(f"{path}: expected {expected}, received {response.code}")
            payload = response.read()
        print(f"{path}: HTTP {expected}")
        return json.loads(payload) if payload and expected == 200 and path != "/" else None

    for path, status in [("/", 200), ("/health", 200), ("/auth/me", 401),
                         ("/api/users", 401), ("/docs", 404), ("/openapi.json", 404)]:
        request(path, status)
    request("/auth/login", 403, {}, origin="https://untrusted.invalid")
    if args.sign_in:
        login = input("Existing development login: ").strip()
        password = getpass.getpass("Password (hidden): ")
        try:
            session = request("/auth/login", 200, {"login_name": login, "password": password})
        finally:
            password = None
        cookie = next((c for c in jar if c.name == "__Host-asi_session"), None)
        if not cookie or not cookie.secure or not cookie.has_nonstandard_attr("HttpOnly"):
            raise RuntimeError("Expected secure HttpOnly session cookie")
        request("/auth/me", 200)
        request("/auth/logout", 204, {}, csrf=session["csrf_token"])
        request("/auth/me", 401)
        jar.clear()
        print("Normal sign-in, secure cookie, session and CSRF-protected logout verified.")
    else:
        print("Read-only checks passed. Existing-account sign-in requires --sign-in.")


if __name__ == "__main__":
    main()
