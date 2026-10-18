from fixwatch import model
from fixwatch.betfair import estimate_minute, parse_line, parse_timeline
from fixwatch.detector import Config, MarketSnapshot, evaluate


def snap(**kw):
    base = dict(market_id="1", market_name="First Half Goals 1.5", event_name="A v B",
                competition="Panama Liga", line=1.5, first_half=True, total_matched=31000,
                over_price=1.7, under_price=2.42, minute=9, home_goals=0, away_goals=0,
                match_odds_matched=8000)
    base.update(kw)
    return MarketSnapshot(**base)


def test_poisson():
    assert model.poisson_at_least(0, 1.0) == 1.0
    assert abs(model.poisson_at_least(1, 1.0) - (1 - 2.718281828 ** -1)) < 1e-6


def test_screenshot_case_is_flagged():
    alert = evaluate(snap(), Config())
    assert alert is not None
    assert 0.2 < alert.model_over_prob < 0.3       # normalnie ~26%
    assert alert.market_over_prob > 0.55           # rynek ~59%
    assert alert.rate_ratio > 1.9


def test_implied_lambda_roundtrip():
    lam = model.implied_lambda(model.poisson_at_least(2, 0.9), 2)
    assert abs(lam - 0.9) < 1e-6


def test_normal_market_not_flagged():
    # 0-0 w 9', Over 1.5 FH po uczciwym kursie ~4.3, duży obrót – brak alertu RATE,
    # a 1X2 ma więcej pieniędzy niż rynek goli.
    assert evaluate(snap(over_price=4.3, under_price=1.3, match_odds_matched=200000),
                    Config()) is None


def test_low_volume_not_flagged():
    assert evaluate(snap(total_matched=300), Config()) is None


def test_excluded_competition():
    cfg = Config(excluded_competitions=["English Premier League"])
    assert evaluate(snap(competition="English Premier League"), cfg) is None


def test_under_fix_flagged():
    # 0-0 przed meczem, Over 2.5 FT po 6.0 – rynek mówi, że goli prawie nie będzie.
    s = snap(market_name="Over/Under 2.5 Goals", line=2.5, first_half=False, minute=0,
             over_price=6.0, under_price=1.2)
    alert = evaluate(s, Config())
    assert alert is not None and alert.rate_ratio < 0.6


def test_unknown_score_uses_volume_ratio_only():
    assert evaluate(snap(home_goals=None, away_goals=None), Config()) is not None
    assert evaluate(snap(home_goals=None, away_goals=None, match_odds_matched=10**6),
                    Config()) is None


def test_settled_over_ignored_for_rate():
    alert = evaluate(snap(home_goals=1, away_goals=1, match_odds_matched=10**6), Config())
    assert alert is None


def test_helpers():
    assert parse_line("First Half Goals 1.5") == 1.5
    assert parse_line("Over/Under 2.5 Goals") == 2.5
    assert parse_timeline({"score": {"home": {"score": "0"}, "away": {"score": "1"}},
                           "timeElapsed": 9}) == {"home": 0, "away": 1, "minute": 9,
                                                  "status": None}
    assert estimate_minute("2026-10-18T20:00:00.000Z",
                           now=__import__("datetime").datetime(2026, 10, 18, 20, 9,
                           tzinfo=__import__("datetime").timezone.utc)) == 9


def test_late_game_under_not_flagged():
    # 0-1 w 72', Over 2.5 po 30 – pod koniec meczu niskie tempo jest normalne.
    s = snap(market_name="Over/Under 2.5 Goals", line=2.5, first_half=False, minute=72,
             home_goals=0, away_goals=1, over_price=30, under_price=1.12,
             total_matched=86000, match_odds_matched=84000)
    assert evaluate(s, Config()) is None


def test_discord_message(monkeypatch):
    from fixwatch import notify
    sent = {}

    class Resp:
        ok = True

    def fake_post(url, json, timeout):
        sent["url"], sent["body"] = url, json
        return Resp()

    monkeypatch.setenv("DISCORD_WEBHOOK_URL", "https://discord.test/hook")
    monkeypatch.setattr(notify.requests, "post", fake_post)
    assert notify.send_discord("🚨 A v B\nhttps://www.betfair.com/x")
    assert sent["body"]["content"] == "🚨 A v B\n<https://www.betfair.com/x>"
