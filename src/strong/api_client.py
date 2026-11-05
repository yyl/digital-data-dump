"""Read Strong's unofficial backend API; credentials and tokens stay in memory.

Endpoint shapes were verified against TheAlexLichter/strong-exporter and a live
account. Pagination links supply cursors only; requests remain on Strong's host.
"""

from urllib.parse import parse_qs, quote, urlsplit

import requests


API_URL = "https://back.strong.app/"


class StrongAPIError(RuntimeError):
    """A safe diagnostic that never includes credentials or response bodies."""


class StrongAPIClient:
    def __init__(self, username, password, *, timeout=30, session=None):
        self._username = username
        self._password = password
        self.timeout = timeout
        self.session = session or requests.Session()
        self.session.headers.update({
            "User-Agent": "Strong Android", "Accept": "application/json",
            "X-Client-Build": "600013", "X-Client-Platform": "android",
        })
        self.user_id = None

    def _request(self, method, path, **kwargs):
        try:
            response = self.session.request(
                method, API_URL + path, timeout=self.timeout,
                allow_redirects=False, **kwargs,
            )
        except requests.RequestException:
            raise StrongAPIError("Strong connection failed or timed out.") from None
        with response:
            if response.status_code != 200:
                detail = {
                    401: "Login or session rejected; check your Strong credentials.",
                    403: "Access forbidden.",
                    429: "Rate limited; wait before syncing again.",
                }.get(response.status_code, "The server rejected the request.")
                raise StrongAPIError(f"Strong HTTP {response.status_code}. {detail}")
            try:
                data = response.json()
            except ValueError:
                raise StrongAPIError("Strong returned an invalid JSON response.") from None
        if not isinstance(data, dict):
            raise StrongAPIError("Strong returned an unexpected response shape.")
        return data

    def login(self):
        self.user_id = None
        self.session.headers.pop("Authorization", None)
        if not self._username or not self._password:
            raise StrongAPIError("Set both STRONG_USER and STRONG_PASS to use the API.")
        data = self._request("POST", "auth/login", json={
            "usernameOrEmail": self._username, "password": self._password,
        })
        if not all(isinstance(data.get(key), str) and data[key]
                   for key in ("accessToken", "userId")):
            raise StrongAPIError("Strong returned an unexpected login response.")
        self.user_id = data["userId"]
        self.session.headers["Authorization"] = "Bearer " + data["accessToken"]

    @staticmethod
    def _items(data, key):
        embedded = data.get("_embedded")
        if not isinstance(embedded, dict) or not isinstance(embedded.get(key), list):
            raise StrongAPIError("Strong returned an invalid paginated response.")
        items = embedded[key]
        if any(not isinstance(item, dict) or not isinstance(item.get("id"), str)
               or not item["id"] for item in items):
            raise StrongAPIError("Strong returned an invalid record ID.")
        return items

    @staticmethod
    def _link(data, relation):
        links = data.get("_links", {})
        if not isinstance(links, dict):
            raise StrongAPIError("Strong returned invalid pagination links.")
        link = links.get(relation)
        if link is None:
            return None
        if not isinstance(link, dict) or not isinstance(link.get("href"), str):
            raise StrongAPIError("Strong returned an invalid pagination link.")
        return link["href"]

    def _require_login(self):
        if self.user_id is None:
            raise StrongAPIError("Log in to Strong before fetching account data.")
        return quote(self.user_id, safe="")

    def get_measurements(self):
        user_id = self._require_login()
        measurements = {}
        for path in ("api/measurements", f"api/users/{user_id}/measurements"):
            page = 0
            while True:
                data = self._request("GET", path, params={"page": page})
                batch = self._items(data, "measurement")
                for item in batch:
                    # Strong's current default pages overlap (page 0 returns
                    # 200 items, but page 1 advances only 100). Definitions are
                    # a lookup, so repeated IDs are expected and deduplicated.
                    measurements[item["id"]] = item
                href = self._link(data, "next")
                if href is None:
                    break
                try:
                    next_page = int(parse_qs(urlsplit(href).query)["page"][0])
                except (KeyError, ValueError, IndexError):
                    raise StrongAPIError("Strong returned an invalid exercise cursor.") from None
                if not batch or next_page <= page:
                    raise StrongAPIError("Strong exercise pagination did not advance.")
                page = next_page
        return measurements

    def get_workout_logs(self):
        user_id = self._require_login()
        logs, record_ids, cursors = [], set(), {""}
        continuation = ""
        while True:
            data = self._request("GET", f"api/users/{user_id}", params={
                "limit": 200, "continuation": continuation, "include": "log",
            })
            batch = self._items(data, "log")
            for log in batch:
                if log["id"] in record_ids:
                    raise StrongAPIError("Strong returned duplicate workout logs.")
                record_ids.add(log["id"])
                logs.append(log)
            href = self._link(data, "continuation")
            if href is None:
                return logs
            continuation = parse_qs(urlsplit(href).query).get("continuation", [""])[0]
            if not batch or not continuation or continuation in cursors:
                raise StrongAPIError("Strong workout pagination did not advance.")
            cursors.add(continuation)

    def close(self):
        self.user_id = None
        self.session.headers.pop("Authorization", None)
        self.session.close()
