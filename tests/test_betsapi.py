from dataclasses import replace

from fixwatch import betsapi
from fixwatch.__main__ import build_snapshots
from fixwatch.detector import Config, evaluate
from fixwatch.history import History


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

    # Sygnalem jest ruch, wiec potrzebny drugi pomiar: najpierw spokojny rynek,
    # potem ten sam rynek po naplywie kasy.
    history = History()
    spokojny = replace(s, total_matched=18662, over_price=2.10, under_price=2.10)
    assert history.update(spokojny, now=0) is None
    alert = evaluate(s, Config(), history.update(s, now=118))
    assert alert is not None
    assert alert.direction == "over"
    assert alert.rate_ratio > 1.9
    assert alert.delta.money_in == 31062 - 18662


def test_batched_survives_a_failed_batch(capsys):
    """Padnieta paczka nie moze kosztowac pomiaru pozostalych meczow."""
    import requests

    client = betsapi.BetsApiClient("t")

    class Flaky:
        calls = 0

        def get(self, url, params, timeout):
            Flaky.calls += 1
            if Flaky.calls == 1:
                raise requests.ConnectionError("read timed out")
            return FakeResponse({"success": 1, "results": [{"id": params["event_id"]}]})

    client.session = Flaky()
    out = client._batched("ex/event", [str(i) for i in range(20)])
    assert len(out) == 1, "druga paczka musi przejsc, mimo padnietej pierwszej"
    assert "nie wyszła" in capsys.readouterr().out


def test_request_timeout_is_generous():
    """Przy pelnym livie jedna paczka odpowiada ~6 s, a 30 s konczylo sie timeoutem."""
    seen = {}

    class Timed:
        def get(self, url, params, timeout):
            seen["timeout"] = timeout
            return FakeResponse({"success": 1, "results": []})

    client = betsapi.BetsApiClient("t")
    client.session = Timed()
    client.inplay_events()
    assert seen["timeout"] >= 60


def test_calkowite_padniecie_paczek_to_awaria():
    """Czesc paczek moze paobo, ale gdy padna wszystkie, czujka musi sie dowiedziec."""
    import pytest
    import requests

    client = betsapi.BetsApiClient("t")

    class Martwy:
        def get(self, url, params, timeout):
            raise requests.ConnectionError("read timed out")

    client.session = Martwy()
    with pytest.raises(RuntimeError, match="padly wszystkie"):
        client._batched("ex/event", [str(i) for i in range(20)])


def test_pusta_lista_meczow_to_nie_awaria():
    """Noca nie ma meczow w trakcie - API zwraca pusta liste i to jest poprawne."""
    class Pusty:
        def get(self, url, params, timeout):
            return FakeResponse({"success": 1, "results": [],
                                 "pager": {"page": 1, "per_page": 50, "total": 0}})

    client = betsapi.BetsApiClient("t")
    client.session = Pusty()
    assert client.inplay_events() == []
    assert client._batched("ex/event", []) == [], "brak paczek to tez nie awaria"
