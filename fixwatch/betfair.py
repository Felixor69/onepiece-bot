"""Minimalny klient Betfair Exchange API-NG (REST) + wynik/minuta z in-play service."""
import re
import time
from datetime import datetime, timedelta, timezone

import requests

LOGIN_URL = "https://identitysso.betfair.com/api/login"
CERT_LOGIN_URL = "https://identitysso-cert.betfair.com/api/certlogin"
KEEPALIVE_URL = "https://identitysso.betfair.com/api/keepAlive"
BETTING_URL = "https://api.betfair.com/exchange/betting/rest/v1.0/"
# Nieoficjalny endpoint, z którego korzysta strona Betfair do pokazywania wyniku i minuty.
TIMELINE_URL = "https://ips.betfair.com/inplayservice/v1/eventTimelines"
MARKET_URL = "https://www.betfair.com/exchange/plus/football/market/{}"

SOCCER = "1"
GOAL_MARKET_TYPES = [
    "FIRST_HALF_GOALS_05", "FIRST_HALF_GOALS_15", "FIRST_HALF_GOALS_25",
    "OVER_UNDER_05", "OVER_UNDER_15", "OVER_UNDER_25", "OVER_UNDER_35", "OVER_UNDER_45",
]
BOOK_CHUNK = 40  # limit wagi zapytania listMarketBook przy EX_BEST_OFFERS


class BetfairClient:
    def __init__(self, app_key, username, password, cert_file=None, key_file=None):
        self.app_key = app_key
        self.username = username
        self.password = password
        self.cert = (cert_file, key_file) if cert_file and key_file else None
        self.session = requests.Session()
        self.token = None
        self.last_login = 0.0

    # --- logowanie ---------------------------------------------------------
    def login(self):
        headers = {"X-Application": self.app_key, "Accept": "application/json",
                   "Content-Type": "application/x-www-form-urlencoded"}
        data = {"username": self.username, "password": self.password}
        if self.cert:
            r = self.session.post(CERT_LOGIN_URL, data=data, headers=headers,
                                  cert=self.cert, timeout=20)
            r.raise_for_status()
            body = r.json()
            ok, token = body.get("loginStatus") == "SUCCESS", body.get("sessionToken")
        else:
            r = self.session.post(LOGIN_URL, data=data, headers=headers, timeout=20)
            r.raise_for_status()
            body = r.json()
            ok, token = body.get("status") == "SUCCESS", body.get("token")
        if not ok:
            raise RuntimeError(f"Logowanie do Betfair nieudane: {body}")
        self.token = token
        self.last_login = time.time()
        print("[INFO] Zalogowano do Betfair.")

    def keep_alive(self):
        # Sesja wygasa po kilku godzinach bez aktywności – odświeżamy co ~3h.
        if self.token and time.time() - self.last_login > 3 * 3600:
            r = self.session.get(KEEPALIVE_URL, headers=self._headers(), timeout=20)
            if r.ok and r.json().get("status") == "SUCCESS":
                self.last_login = time.time()
            else:
                self.login()

    def _headers(self):
        return {"X-Application": self.app_key, "X-Authentication": self.token,
                "Content-Type": "application/json", "Accept": "application/json"}

    def _call(self, method, params):
        if not self.token:
            self.login()
        r = self.session.post(BETTING_URL + method + "/", json=params,
                              headers=self._headers(), timeout=30)
        if r.status_code == 400 and "INVALID_SESSION" in r.text:
            self.login()
            r = self.session.post(BETTING_URL + method + "/", json=params,
                                  headers=self._headers(), timeout=30)
        r.raise_for_status()
        return r.json()

    # --- dane --------------------------------------------------------------
    def list_markets(self, market_types, hours_back=2, hours_ahead=1):
        now = datetime.now(timezone.utc)
        fmt = "%Y-%m-%dT%H:%M:%SZ"
        params = {
            "filter": {
                "eventTypeIds": [SOCCER],
                "marketTypeCodes": market_types,
                "marketStartTime": {"from": (now - timedelta(hours=hours_back)).strftime(fmt),
                                    "to": (now + timedelta(hours=hours_ahead)).strftime(fmt)},
            },
            "marketProjection": ["COMPETITION", "EVENT", "RUNNER_DESCRIPTION",
                                 "MARKET_START_TIME", "MARKET_DESCRIPTION"],
            "maxResults": 1000,
        }
        return self._call("listMarketCatalogue", params)

    def list_books(self, market_ids):
        books = []
        for i in range(0, len(market_ids), BOOK_CHUNK):
            chunk = market_ids[i:i + BOOK_CHUNK]
            books += self._call("listMarketBook", {
                "marketIds": chunk,
                "priceProjection": {"priceData": ["EX_BEST_OFFERS"]},
            })
        return books

    def event_states(self, event_ids):
        """Wynik i minuta per event. Best-effort – przy błędzie zwraca pusty słownik."""
        states = {}
        ids = list(event_ids)
        for i in range(0, len(ids), 50):
            try:
                r = self.session.get(TIMELINE_URL, timeout=15, params={
                    "alt": "json", "eventIds": ",".join(ids[i:i + 50]), "locale": "en_GB",
                    "productType": "EXCHANGE", "regionCode": "UK"})
                r.raise_for_status()
                data = r.json()
            except (requests.RequestException, ValueError) as e:
                print(f"[WARN] Nie udało się pobrać wyników: {e}")
                continue
            for ev in data if isinstance(data, list) else [data]:
                parsed = parse_timeline(ev)
                if parsed:
                    states[str(ev.get("eventId"))] = parsed
        return states

    def fetch(self, market_types):
        """Zwraca (rynki w formacie wspólnym, wynik/minuta per event)."""
        catalogue = self.list_markets(market_types)
        if not catalogue:
            return [], {}
        books = {b["marketId"]: b for b in self.list_books([m["marketId"] for m in catalogue])}
        markets = []
        for cat in catalogue:
            book = books.get(cat["marketId"])
            if not book:
                continue
            names = {r["selectionId"]: r.get("runnerName", "") for r in cat.get("runners", [])}
            markets.append({
                "market_id": cat["marketId"],
                "market_type": cat.get("description", {}).get("marketType", ""),
                "market_name": cat["marketName"],
                "event_id": cat["event"]["id"],
                "event_name": cat["event"]["name"],
                "competition": cat.get("competition", {}).get("name", "?"),
                "start_time": cat.get("marketStartTime", ""),
                "inplay": book.get("inplay", False),
                "status": book.get("status"),
                "total_matched": book.get("totalMatched", 0.0),
                "runners": [{
                    "name": names.get(r["selectionId"], ""),
                    "last": r.get("lastPriceTraded"),
                    "back": [p["price"] for p in r.get("ex", {}).get("availableToBack", [])],
                } for r in book.get("runners", [])],
            })
        in_play = {m["event_id"] for m in markets if m["inplay"]}
        return markets, (self.event_states(in_play) if in_play else {})


def parse_timeline(ev):
    try:
        score = ev["score"]
        home = int(score["home"]["score"])
        away = int(score["away"]["score"])
        minute = ev.get("timeElapsed")
        minute = int(minute) if minute is not None else None
    except (KeyError, TypeError, ValueError):
        return None
    return {"home": home, "away": away, "minute": minute,
            "status": ev.get("inPlayMatchStatus") or ev.get("status")}


def estimate_minute(start_time_iso, now=None):
    """Zapasowe liczenie minuty z godziny startu (z 15 min przerwy)."""
    now = now or datetime.now(timezone.utc)
    start = datetime.strptime(start_time_iso[:19], "%Y-%m-%dT%H:%M:%S").replace(tzinfo=timezone.utc)
    elapsed = (now - start).total_seconds() / 60
    if elapsed < 0:
        return 0
    if elapsed > 60:
        elapsed -= 15
    return int(min(elapsed, 90))


def parse_line(market_name):
    m = re.search(r"(\d+\.5)", market_name or "")
    return float(m.group(1)) if m else None


def over_under(runners):
    """Zwraca (over_price, under_price) – ostatni kurs, a jak go brak to najlepszy back."""
    over = under = None
    for runner in runners:
        price = runner.get("last") or (runner["back"][0] if runner.get("back") else None)
        name = runner.get("name", "").lower()
        if name.startswith("over"):
            over = price
        elif name.startswith("under"):
            under = price
    return over, under
