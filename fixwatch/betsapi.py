"""Dane z giełdy Betfair przez BetsAPI (https://betsapi.com) – bez konta na Betfair.

Wystarczy token BetsAPI (pakiet "Betfair API"). Limit: 3600 zapytań/h,
max 10 meczów na jedno zapytanie o rynki / wyniki.
"""
import requests

from . import betfair

API_URL = "https://api.b365api.com/v1/betfair/"
SOCCER = 1
BATCH = 10
# Wieczorem jedno zapytanie o 10 meczów zwraca kilkaset rynków i odpowiada ~6 s, więc
# 30 s regularnie kończyło się timeoutem na pełnym livie (47 meczów, 1297 rynków).
REQUEST_TIMEOUT = 60


def _obj(value):
    # BetsAPI zwraca [] zamiast {} gdy np. nie ma kursów.
    return value if isinstance(value, dict) else {}


class BetsApiClient:
    def __init__(self, token):
        self.token = token
        self.session = requests.Session()

    def _get(self, path, **params):
        r = self.session.get(API_URL + path, params={"token": self.token, **params},
                             timeout=REQUEST_TIMEOUT)
        r.raise_for_status()
        body = r.json()
        if not body.get("success"):
            raise RuntimeError(f"BetsAPI {path}: {body.get('error') or body}")
        return body

    def inplay_events(self):
        events, page = [], 1
        while True:
            body = self._get("ex/inplay", sport_id=SOCCER, page=page)
            events += body.get("results", [])
            pager = body.get("pager") or {}
            if page * int(pager.get("per_page", 50)) >= int(pager.get("total", 0)):
                return events
            page += 1

    def _batched(self, path, event_ids):
        """Pobiera po `BATCH` meczów. Padnięta paczka nie przerywa całości.

        Przy pełnym livie jedna paczka to kilkaset rynków i bywa, że API nie zdąży.
        Wywalenie wtedy całego skanu kosztowałoby pomiar WSZYSTKICH rynków, czyli dziurę
        w historii i przegapiony napływ – a te mecze, które się pobrały, są w porządku.
        """
        results = []
        ids = list(event_ids)
        for i in range(0, len(ids), BATCH):
            batch = ids[i:i + BATCH]
            try:
                results += self._get(path, event_id=",".join(batch)).get("results", [])
            except (requests.RequestException, RuntimeError, ValueError) as e:
                print(f"[WARN] BetsAPI {path}: paczka {i // BATCH + 1} nie wyszła "
                      f"({type(e).__name__}), lecę dalej bez tych {len(batch)} meczów")
        return results

    def fetch(self):
        """Zwraca (rynki w formacie wspólnym, wynik/minuta per event)."""
        inplay = self.inplay_events()
        leagues = {str(e["id"]): (e.get("league") or {}).get("name") for e in inplay}
        events = self._batched("ex/event", leagues)
        markets = []
        for ev in events:
            event = ev.get("event", {})
            event_id = str(event.get("eventId"))
            comps = ev.get("competitions") or []
            competition = (leagues.get(event_id) or (comps[0].get("name") if comps else None)
                           or event.get("countryCode") or "?")
            for m in ev.get("markets", []):
                desc, state = _obj(m.get("description")), _obj(m.get("state"))
                markets.append({
                    "market_id": m.get("marketId"),
                    "market_type": desc.get("marketType", ""),
                    "market_name": desc.get("marketName", ""),
                    "event_id": event_id,
                    "event_name": event.get("name", "?"),
                    "competition": competition,
                    "start_time": event.get("openDate", ""),
                    "inplay": state.get("inplay", False),
                    "status": state.get("status"),
                    "total_matched": state.get("totalMatched", 0.0),
                    "runners": [{
                        "name": _obj(r.get("description")).get("runnerName", ""),
                        "last": _obj(r.get("state")).get("lastPriceTraded"),
                        "back": [p["price"] for p in
                                 _obj(r.get("exchange")).get("availableToBack", [])],
                    } for r in m.get("runners", [])],
                })
        states = {}
        for tl in self._batched("timeline", leagues):
            parsed = betfair.parse_timeline(tl)
            if parsed:
                states[str(tl.get("eventId"))] = parsed
        return markets, states
