"""Co trafia na Discorda, a co tylko do logu."""
from fixwatch import __main__ as main
from fixwatch.detector import Config, evaluate


def market(market_type, market_name, over, under, matched, event_id="1",
           status="OPEN", inplay=True):
    return {
        "market_id": f"1.{market_type}", "market_type": market_type,
        "market_name": market_name, "event_id": event_id,
        "event_name": "Santa Clara U23 v Sporting Braga U23",
        "competition": "Portuguese U23", "start_time": "2026-10-19T12:00:00Z",
        "inplay": inplay, "status": status, "total_matched": matched,
        "runners": [{"name": "Over 0.5 Goals", "last": over, "back": [over]},
                    {"name": "Under 0.5 Goals", "last": under, "back": [under]}],
    }


def match_odds(matched, event_id="1"):
    m = market("MATCH_ODDS", "Match Odds", 2.0, 2.0, matched, event_id)
    m["market_id"] = f"1.mo.{event_id}"
    return m


# Prawdziwy przypadek z 19.10.2026 12:04 – normalny rynek, ktory alarmowal tylko
# dlatego, ze 1X2 mialo malo pieniedzy.
SANTA_CLARA = [market("OVER_UNDER_05", "Over/Under 0.5 Goals", 1.04, 21, 8721),
               match_odds(1410)]
SANTA_CLARA_STATE = {"1": {"minute": 2, "home": 0, "away": 0}}


def test_santa_clara_case_alerts_but_is_not_actionable():
    snapshots = main.build_snapshots(SANTA_CLARA, SANTA_CLARA_STATE)
    alert = evaluate(snapshots[0], Config())
    assert alert is not None, "sygnal z obrotu nadal sie liczy"
    assert not alert.actionable()
    assert "kurs jest normalny" in alert.no_direction_reason()
    assert "BEZ ZAGRANIA" in alert.format()


def test_scan_does_not_notify_without_a_side(monkeypatch, capsys):
    sent = []
    monkeypatch.setattr(main, "notify", lambda alert: sent.append(alert))
    main.scan(lambda: (SANTA_CLARA, SANTA_CLARA_STATE), Config(), {})
    assert sent == [], "normalny rynek nie moze iso na Discorda"
    out = capsys.readouterr().out
    assert "Bez zagrania, nie wysyłam" in out
    assert "wysłanych: 0" in out


def _fixy(over, matched):
    """Rynek z anomalia: 0-2 w 78', Over 4.5 wyceniony absurdalnie wysoko."""
    markets = [market("OVER_UNDER_45", "Over/Under 4.5 Goals", over, 1.02, matched),
               match_odds(6896)]
    return markets, {"1": {"minute": 78, "home": 0, "away": 2}}


def test_scan_notifies_when_there_is_a_side(monkeypatch):
    sent = []
    monkeypatch.setattr(main, "notify", lambda alert: sent.append(alert))
    main.scan(lambda: _fixy(21, 5681), Config(), {})
    assert len(sent) == 1
    assert sent[0].direction == "over"
    assert 'BACK (niebieska kolumna) "Over 4.5 Goals" @ 21' in sent[0].format()


def test_silent_alert_does_not_block_a_later_play(monkeypatch):
    """Smieciowy alert nie moze zajac miejsca w dedupie i zablokowac zagrania."""
    sent = []
    monkeypatch.setattr(main, "notify", lambda alert: sent.append(alert))
    alerted = {}
    # Najpierw ten sam rynek bez kierunku, potem z anomalia. Over 4.5 po 7.0 przy 0-0
    # w 2' to tempo 1.03x normy (fair ~7.64), czyli kurs zupelnie normalny.
    normalny = [market("OVER_UNDER_45", "Over/Under 4.5 Goals", 7.0, 1.16, 8721),
                match_odds(1410)]
    main.scan(lambda: (normalny, SANTA_CLARA_STATE), Config(), alerted)
    assert sent == [] and alerted == {}, "nie wyslane = nie zapisane w dedupie"
    main.scan(lambda: _fixy(21, 8721), Config(), alerted)
    assert len(sent) == 1, "zagranie musi przejsc, mimo wczesniejszego smiecia"


def test_dedup_still_holds_for_sent_alerts(monkeypatch):
    sent = []
    monkeypatch.setattr(main, "notify", lambda alert: sent.append(alert))
    alerted = {}
    main.scan(lambda: _fixy(21, 5681), Config(), alerted)
    main.scan(lambda: _fixy(21, 5681), Config(), alerted)
    assert len(sent) == 1, "bez podwojenia obrotu nie powtarzamy alertu"
    main.scan(lambda: _fixy(21, 2 * 5681), Config(), alerted)
    assert len(sent) == 2, "po podwojeniu obrotu alert leci ponownie"
