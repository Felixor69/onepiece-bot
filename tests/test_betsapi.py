from fixwatch import betsapi
from fixwatch.__main__ import build_snapshots
from fixwatch.detector import Config, evaluate


def runner(name, last):
    return {"description": {"runnerName": name}, "state": {"lastPriceTraded": last},
            "exchange": {"availableToBack": [{"price": last, "size": 100}]}}


def market(mid, mtype, name, matched, runners):
    return {"marketId": mid, "description": {"marketType": mtype, "marketName": name},
            "state": {"status": "OPEN", "inplay": True, "totalMatched": matched},
            "runners": runners}


# Odpowiedzi w formacie BetsAPI (struktura jak w ich przykładach z dokumentacji).
RESPONSES = {
    "ex/inplay": {"success": 1, "pager": {"page": 1, "per_page": 50, "total": 1},
                  "results": [{"id": "35000001", "league": {"name": "Panama Liga Panamena"}}]},
    "ex/event": {"success": 1, "results": [{
        "event": {"eventId": 35000001, "name": "Union Cocle v Herrera FC",
                  "openDate": "2026-10-18T22:00:00.000Z"},
        "competitions": [],
        "markets": [
            market("1.1", "MATCH_ODDS", "Match Odds", 8000,
                   [runner("Union Cocle", 2.5), runner("Herrera FC", 3.0),
                    runner("The Draw", 3.2)]),
            market("1.2", "FIRST_HALF_GOALS_15", "First Half Goals 1.5", 31062,
                   [runner("Under 1.5 Goals", 2.42), runner("Over 1.5 Goals", 1.7)]),
        ]}]},
    "timeline": {"success": 1, "results": [{
        "eventId": 35000001, "timeElapsed": 9, "inPlayMatchStatus": "FirstHalf",
        "score": {"home": {"score": "0"}, "away": {"score": "0"}}}]},
}


class FakeResponse:
    def __init__(self, body):
        self.body = body

    def raise_for_status(self):
        pass

    def json(self):
        return self.body


class FakeSession:
    def get(self, url, params, timeout):
        assert params["token"] == "t"
        return FakeResponse(RESPONSES[url.removeprefix(betsapi.API_URL)])


def test_betsapi_screenshot_case():
    client = betsapi.BetsApiClient("t")
    client.session = FakeSession()
    snapshots = build_snapshots(*client.fetch())
    assert len(snapshots) == 1
    s = snapshots[0]
    assert (s.competition, s.minute, s.home_goals, s.over_price, s.under_price) == \
        ("Panama Liga Panamena", 9, 0, 1.7, 2.42)
    assert s.match_odds_matched == 8000
    alert = evaluate(s, Config())
    assert alert is not None and alert.rate_ratio > 1.9
