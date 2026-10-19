"""Log badawczy: lapie szeroko, niezaleznie od filtrow Discorda, i nie wywala skanu."""
import json

from fixwatch import __main__ as main
from fixwatch.detector import Config, MarketSnapshot
from fixwatch.history import Delta, History
from fixwatch.research import ResearchLog, wiersz


def snap(**kw):
    base = dict(market_id="1.X", market_name="First Half Goals 1.5",
                event_name="A v B", competition="Panama Liga", line=1.5,
                first_half=True, total_matched=31062, over_price=1.7, under_price=2.42,
                minute=9, home_goals=0, away_goals=0, match_odds_matched=8000,
                event_id="36191524")
    base.update(kw)
    return MarketSnapshot(**base)


def delta(**kw):
    base = dict(span=118, money_in=12400, matched_before=18662,
                prob_before=0.48, prob_now=0.59, price_before=2.10, price_now=1.70)
    base.update(kw)
    return Delta(**base)


def test_wiersz_ma_event_id_i_oba_kursy():
    """Bez event_id nie da sie rozliczyc typu, bez obu kursow - policzyc wariantu fade."""
    r = wiersz(snap(), delta(), now_wall=1000.0)
    assert r["event_id"] == "36191524"
    assert r["over_price"] == 1.7 and r["under_price"] == 2.42
    assert r["side"] == "over"
    assert r["money_in"] == 12400
    assert round(r["prob_move"], 2) == 0.11
    assert r["ts"] == 1000.0


def test_zapisuje_powyzej_progu(tmp_path):
    log = ResearchLog(path=str(tmp_path / "spikes.jsonl"), min_money=2000)
    assert log.record(snap(), delta()) is True
    assert log.record(snap(), delta(money_in=1999)) is False
    assert log.record(snap(), None) is False
    linie = (tmp_path / "spikes.jsonl").read_text(encoding="utf-8").strip().split("\n")
    assert len(linie) == 1
    assert json.loads(linie[0])["event"] == "A v B"


def test_lapie_szerzej_niz_discord(tmp_path, monkeypatch):
    """Naply na Under po krotkim kursie: Discord go nie dostanie, badania owszem."""
    sent = []
    monkeypatch.setattr(main, "notify", lambda a: sent.append(a))
    log = ResearchLog(path=str(tmp_path / "spikes.jsonl"), min_money=2000)

    def market(over, under, matched):
        return {
            "market_id": "1.FH", "market_type": "FIRST_HALF_GOALS_15",
            "market_name": "First Half Goals 1.5", "event_id": "36191524",
            "event_name": "A v B", "competition": "Panama Liga",
            "start_time": "2026-10-19T12:00:00Z", "inplay": True, "status": "OPEN",
            "total_matched": matched,
            "runners": [{"name": "Over 1.5 Goals", "last": over, "back": [over]},
                        {"name": "Under 1.5 Goals", "last": under, "back": [under]}],
        }

    state = {"36191524": {"minute": 9, "home": 0, "away": 0}}
    history, alerted = History(), {}
    main.scan(lambda: ([market(2.10, 2.10, 18662)], state), Config(), alerted,
              history, now=0, research=log)
    # Kasa idzie na Under, kurs Under 1.30 - ponizej MIN_PRICE i zla strona.
    main.scan(lambda: ([market(4.00, 1.30, 31062)], state), Config(), alerted,
              history, now=118, research=log)
    assert sent == [], "Discord nie dostaje tego napływu"
    zapisy = (tmp_path / "spikes.jsonl").read_text(encoding="utf-8").strip().split("\n")
    assert len(zapisy) == 1, "ale badania go mają"
    assert json.loads(zapisy[0])["side"] == "under"


def test_awaria_pliku_nie_zatrzymuje_skanu(tmp_path, capsys):
    # Sciezka, ktorej nie da sie utworzyc na zadnym systemie: katalogiem mialby byc plik.
    blokada = tmp_path / "to-jest-plik"
    blokada.write_text("x", encoding="utf-8")
    log = ResearchLog(path=str(blokada / "spikes.jsonl"), min_money=2000)
    assert log.record(snap(), delta()) is False
    assert log.record(snap(), delta()) is False
    out = capsys.readouterr().out
    assert out.count("niedostępny") == 1, "ostrzegamy raz, nie w kazdym skanie"


def test_wylaczony_gdy_brak_sciezki():
    log = ResearchLog(path="", min_money=2000)
    assert not log.enabled()
    assert log.record(snap(), delta()) is False
