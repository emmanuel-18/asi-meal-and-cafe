"""Interactive, loopback-only client for the separately isolated development demo."""
import getpass
import re
import sys
import warnings
from urllib.parse import unquote, urlsplit
from uuid import UUID

import httpx

ORIGIN = "http://127.0.0.1:43871"


class DemoClientError(Exception):
    """Safe error without response bodies, credentials, or session data."""


class DemoClient:
    def __init__(self, client=None):
        self._client = client or httpx.Client(base_url=ORIGIN, timeout=15, follow_redirects=False, trust_env=False)
        self._csrf = None
        self._authorized = False

    def login(self, password):
        self._authorized = False
        self._csrf = None
        response = self._client.post("/auth/login", headers={"Origin": ORIGIN, "X-ASI-Request": "1"},
                                     json={"login_name": "demo_seeder", "password": password})
        if response.status_code != 200:
            raise DemoClientError(f"Authentication failed (HTTP {response.status_code}).")
        data = response.json()
        user = data.get("user", {})
        if user.get("login_name") != "demo_seeder" or user.get("role") != "admin" or user.get("password_change_required"):
            raise DemoClientError("Demo seeder must be an active Admin with its first password change completed.")
        self._csrf = data["csrf_token"]
        self._authorized = True

    def request(self, method, path, body=None):
        if not self._authorized:
            raise DemoClientError("Authentication required.")
        url = urlsplit(path)
        resource = url.path
        roots = ("/api/visitors", "/api/dishes", "/api/menus", "/api/orders", "/api/employees", "/api/reports")
        read_allowed = method == "GET" and (resource == "/api/menu-defaults" or any(resource == root or resource.startswith(root + "/") for root in roots))
        write_allowed = (method == "POST" and resource in {"/api/visitors", "/api/dishes", "/api/menus", "/api/orders"}) or (
            method == "PUT" and re.fullmatch(r"/api/menus/[0-9]+/dates", resource)
        ) or (
            method == "POST" and re.fullmatch(r"/api/orders/[0-9]+/received", resource)
        )
        if (url.scheme or url.netloc or url.fragment or unquote(resource) != resource
                or "\\" in resource or ".." in resource.split("/") or not (read_allowed or write_allowed)):
            raise DemoClientError("Unsupported demo operation.")
        if method == "POST" and resource == "/api/orders":
            try:
                UUID(str(body["request_key"]))
            except (KeyError, TypeError, ValueError):
                raise DemoClientError("A stable order request key is required.") from None
        headers = {"Origin": ORIGIN, "X-CSRF-Token": self._csrf}
        response = self._client.request(method, path, headers=headers, json=body)
        if response.status_code in (401, 403):
            self._authorized = False
            self._csrf = None
            raise DemoClientError(f"Authorization failed (HTTP {response.status_code}); stopped.")
        if not response.is_success:
            raise DemoClientError(f"Request failed (HTTP {response.status_code}); review before retrying.")
        return response.json()

    def create_order(self, payload):
        return self.request("POST", "/api/orders", payload)

    def close(self):
        self._authorized = False
        self._csrf = None
        self._client.close()


def main():
    if not sys.stdin.isatty():
        print("An interactive terminal is required.", file=sys.stderr)
        return 1
    client = DemoClient()
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", getpass.GetPassWarning)
            password = getpass.getpass("Demo seeder password: ")
        client.login(password)
        print("Demo seeder authentication succeeded. No demo records were created.")
        return 0
    except (DemoClientError, httpx.HTTPError, ValueError, KeyError, getpass.GetPassWarning):
        print("Authentication failed or is unavailable; no demo records were created.", file=sys.stderr)
        return 1
    finally:
        client.close()


if __name__ == "__main__":
    raise SystemExit(main())
