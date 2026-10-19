"""Co trafia na Discorda przez pelna petle skanu."""
from fixwatch import __main__ as main
from fixwatch.detector import Config
from fixwatch.history import History


def market(market_type, market_name, over, under, matched, event_id="1"):
    return {
        "market_id": f"1.{market_type}", "market_type": market_type,
        "market_name": market_name, "event_id": event_id,
        "event_name": "Union Cocle v Herrera FC",
        "competition": "Panama Liga Panamena de Futbol",
        "start_time": "2026-10-19T12:00:00Z", "inplay": True, "status": "OPEN",
        "total_matched": matched,
        "runners": [{"name": "Over 1.5 Goals", "last": over, "back": [over]},
                    {"name": "Under 1.5 Goals", "last": under, "back": [under]}],
    }


def match_odds(matched, event_id="1"):
    m = market("MATCH_ODDS", "Match Odds", 2.0, 2.0, matched, event_id)
    m["market_id"] = f"1.mo.{event_id}"
    return m


STATE = {"1": {"minute": 9, "home": 0, "away": 0}}


def feed(over, under, matched):
    return lambda: ([market("FIRST_HALF_GOALS_15", "First Half Goals 1.5", over, under,
                            matched), match_odds(8000)], STATE)


# Rynek spokojny, a potem nagly hajs na Over - dokladnie przypadek ze screena.
SPOKOJNY = feed(2.10, 2.10, 18662)
NAPLY = feed(1.70, 2.42, 31062)


def test_first_scan_only_remembers(monkeypatch, capsys):
    sent = []
    monkeypatch.setattr(main, "notify", lambda a: sent.append(a))
    main.scan(SPOKOJNY, Config(), {}, History(), now=0)
    assert sent == [], "pierwszy skan nie ma z czym porownac"
    assert "wysłanych: 0" in capsys.readouterr().out


def test_spike_between_scans_is_sent(monkeypatch):
    sent = []
    monkeypatch.setattr(main, "notify", lambda a: sent.append(a))
    history, alerted = History(), {}
    main.scan(SPOKOJNY, Config(), alerted, history, now=0)
    main.scan(NAPLY, Config(), alerted, history, now=118)
    assert len(sent) == 1
    alert = sent[0]
    assert alert.direction == "over"
    assert "NAGŁY NAPŁYW KASY na OVER" in alert.format()
    assert "w 118 s wpadło 12 400" in alert.format()


def test_quiet_market_sends_nothing(monkeypatch):
    """Duzy obrot bez ruchu - dawniej to wlasnie zasypywalo Discorda."""
    sent = []
    monkeypatch.setattr(main, "notify", lambda a: sent.append(a))
    history, alerted = History(), {}
    main.scan(NAPLY, Config(), alerted, history, now=0)
    main.scan(feed(1.70, 2.42, 31120), Config(), alerted, history, now=60)
    main.scan(feed(1.70, 2.42, 31180), Config(), alerted, history, now=120)
    assert sent == []


def test_cooldown_stops_repeating_the_same_spike(monkeypatch):
    """Ten sam naply siedzi w oknie historii, wiec bez cooldownu poszedlby kilka razy."""
    sent = []
    monkeypatch.setattr(main, "notify", lambda a: sent.append(a))
    history, alerted = History(), {}
    main.scan(SPOKOJNY, Config(), alerted, history, now=0)
    main.scan(NAPLY, Config(), alerted, history, now=118)
    main.scan(feed(1.68, 2.44, 31300), Config(), alerted, history, now=148)
    main.scan(feed(1.68, 2.44, 31400), Config(), alerted, history, now=178)
    assert len(sent) == 1, "jedno zdarzenie = jedna wiadomosc"


def test_new_spike_after_cooldown_is_sent(monkeypatch):
    sent = []
    monkeypatch.setattr(main, "notify", lambda a: sent.append(a))
    history, alerted = History(), {}
    main.scan(SPOKOJNY, Config(), alerted, history, now=0)
    main.scan(NAPLY, Config(), alerted, history, now=118)
    assert len(sent) == 1
    # Po cooldownie kolejny gwaltowny naply to nowe zdarzenie i ma dojsc.
    main.scan(feed(1.70, 2.42, 31500), Config(), alerted, history, now=600)
    main.scan(feed(1.55, 2.80, 60000), Config(), alerted, history, now=700)
    assert len(sent) == 2


def excluded_feed(over, under, matched):
    def fetch():
        m = market("OVER_UNDER_25", "Over/Under 2.5 Goals", over, under, matched)
        m["competition"] = "Italian Serie A"
        mo = match_odds(8000)
        mo["competition"] = "Italian Serie A"
        return [m, mo], STATE
    return fetch


def real_cfg():
    """Config jak w produkcji – z lista wykluczonych lig, ktora dokłada load_config()."""
    return Config(excluded_competitions=main.DEFAULT_EXCLUDED)


def test_excluded_league_stays_out_of_the_calibration_log(capsys):
    """Realny przypadek: Serie A robila 30 tys. naplywu przy ruchu 0% i trafiala do logu,
    mimo ze jest wykluczona - z czego wychodzilo, ze progi sa o rzad za niskie."""
    history, alerted = History(), {}
    main.scan(excluded_feed(2.00, 2.00, 100000), real_cfg(), alerted, history, now=0)
    main.scan(excluded_feed(1.70, 2.42, 130876), real_cfg(), alerted, history, now=90)
    out = capsys.readouterr().out
    assert "Największy napływ" not in out
    assert "wysłanych: 0" in out


def test_excluded_league_never_alerts_either(monkeypatch):
    sent = []
    monkeypatch.setattr(main, "notify", lambda a: sent.append(a))
    history, alerted = History(), {}
    main.scan(excluded_feed(2.00, 2.00, 100000), real_cfg(), alerted, history, now=0)
    main.scan(excluded_feed(1.70, 2.42, 130876), real_cfg(), alerted, history, now=90)
    assert sent == []


def test_eligible_league_does_reach_the_calibration_log(capsys):
    history, alerted = History(), {}
    main.scan(SPOKOJNY, Config(), alerted, history, now=0)
    main.scan(feed(1.90, 2.10, 23000), Config(), alerted, history, now=90)
    out = capsys.readouterr().out
    assert "Największy napływ w oknie: 4 338" in out
