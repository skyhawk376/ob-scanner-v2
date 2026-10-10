"""Minimal read-only HTTP client for online.aerogest.fr (login + planning JSON)."""
from __future__ import annotations

import re
from datetime import date

import httpx

from .parse import BASE_URL

UA = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
      "Chrome/124.0 Safari/537.36")


class AerogestError(Exception):
    pass


class SessionExpired(AerogestError):
    pass


class AerogestClient:
    def __init__(self, user: str, password: str, timeout: float = 30.0, transport=None):
        self._user, self._password = user, password
        self.http = httpx.Client(base_url=BASE_URL, headers={"User-Agent": UA},
                                 follow_redirects=True, timeout=timeout, transport=transport)
        self.logged_in = False

    def close(self):
        self.http.close()

    def login(self) -> None:
        r = self.http.get("/Connection/logon")
        m = re.search(r'name="__RequestVerificationToken" type="hidden" value="([^"]+)"', r.text)
        if not m:
            raise AerogestError("login form not found (site changed or captcha?)")
        r = self.http.post("/Connection/logon", data={
            "__RequestVerificationToken": m.group(1), "login": self._user,
            "password": self._password, "rememberMe": "false"})
        if "/Connection/logon" in str(r.url).lower() or "Connection/LogOut" not in r.text:
            raise AerogestError(f"login failed (HTTP {r.status_code})")
        self.logged_in = True

    def _post_json(self, path: str) -> dict:
        r = self.http.post(path, data={}, headers={"X-Requested-With": "XMLHttpRequest"})
        if r.status_code in (401, 403) or "/connection/logon" in str(r.url).lower():
            raise SessionExpired(path)
        try:
            data = r.json()
        except ValueError:
            raise SessionExpired(path)
        if not isinstance(data, dict) or "lignes" not in data:
            raise AerogestError(f"unexpected payload for {path}: HTTP {r.status_code}")
        return data

    def post_json(self, path: str) -> dict:
        if not self.logged_in:
            self.login()
        try:
            return self._post_json(path)
        except SessionExpired:
            self.logged_in = False
            self.login()
            return self._post_json(path)

    def daily(self, day: date) -> dict:
        return self.post_json(f"/api/schedule/bookingapi/getplanning/{day:%Y%m%d}")

    def aircraft(self, acft_id: int, start: date) -> dict:
        """≈30 consecutive days for one aircraft starting at `start`."""
        return self.post_json(f"/api/schedule/bookingapi/GetPlanningAircraft/{acft_id}?d={start:%Y%m%d}")
