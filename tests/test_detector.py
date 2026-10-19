from fixwatch import model
from fixwatch.betfair import estimate_minute, parse_line, parse_timeline
from fixwatch.detector import Config, MarketSnapshot, evaluate
from fixwatch.history import Delta


def snap(**kw):
    base = dict(market_id="1", market_name="First Half Goals 1.5", event_name="A v B",
                competition="Panama Liga", line=1.5, first_half=True, total_matched=31062,
                over_price=1.7, under_price=2.42, minute=9, home_goals=0, away_goals=0,
                match_odds_matched=8000)
    base.update(kw)
    return MarketSnapshot(**base)


def spike(**kw):
    """Naply ze screena: w 118 s wpadlo 12 400 przy 18 662 wczesniej, Over 2.10 -> 1.70."""
    base = dict(span=118, money_in=12400, matched_before=18662,
                prob_before=0.48, prob_now=0.59, price_before=2.10, price_now=1.70)
    base.update(kw)
    return Delta(**base)


# --- model ------------------------------------------------------------------

def test_poisson():
    assert model.poisson_at_least(0, 1.0) == 1.0
    assert abs(model.poisson_at_least(1, 1.0) - (1 - 2.718281828 ** -1)) < 1e-6


def test_implied_lambda_roundtrip():
    lam = model.implied_lambda(model.poisson_at_least(2, 0.9), 2)
    assert abs(lam - 0.9) < 1e-6


def test_helpers():
    assert parse_line("First Half Goals 1.5") == 1.5
    assert parse_line("Over/Under 2.5 Goals") == 2.5
    assert parse_timeline({"score": {"home": {"score": "0"}, "away": {"score": "1"}},
                           "timeElapsed": 9}) == {"home": 0, "away": 1, "minute": 9,
                                                  "status": None}
    assert estimate_minute("2026-10-18T20:00:00.000Z",
                           now=__import__("datetime").datetime(2026, 10, 18, 20, 9,
                           tzinfo=__import__("datetime").timezone.utc)) == 9


# --- wyzwalacz: tylko nagly naply ------------------------------------------

def test_screenshot_case_is_flagged():
    alert = evaluate(snap(), Config(), spike())
    assert alert is not None
    assert alert.direction == "over"
    assert alert.runner_label() == "Over 1.5 Goals"
    assert alert.play_price() == 1.7
    assert 0.2 < alert.model_over_prob < 0.3      # model normalnie ~26%
    assert alert.market_over_prob > 0.55          # rynek ~59%
    assert alert.rate_ratio > 1.9


def test_no_history_no_alert():
    """Pierwszy pomiar rynku: nie ma z czym porownac, wiec nie ma sygnalu."""
    assert evaluate(snap(), Config(), None) is None


def test_quiet_market_not_flagged():
    """Duzy obrot, ale nic sie nie dzieje - to byl dawny zrodlo szumu."""
    assert evaluate(snap(), Config(), spike(money_in=120, prob_before=0.58,
                                            prob_now=0.59)) is None


def test_small_inflow_not_flagged():
    assert evaluate(snap(), Config(), spike(money_in=1500)) is None


def test_inflow_small_against_existing_turnover():
    """12 400 to duzo, ale nie na rynku, ktory mial juz 500 tys. obrotu."""
    assert evaluate(snap(), Config(), spike(matched_before=500000)) is None


def test_price_must_move():
    """Kasa wpadla, ale rynek ja wchlonal bez ruchu kursu - nie wiemy, co kupowano."""
    assert evaluate(snap(), Config(), spike(prob_before=0.58, prob_now=0.59)) is None


def under_snap(**kw):
    base = dict(market_name="Over/Under 2.5 Goals", line=2.5, first_half=False,
                over_price=2.6, under_price=1.6)
    base.update(kw)
    return snap(**base)


def under_cfg(**kw):
    """Config dla testow mechaniki Under - domyslnie gramy tylko Over."""
    return Config(sides="under", **kw)


def under_spike(**kw):
    base = dict(prob_before=0.50, prob_now=0.38, price_before=1.90, price_now=1.60)
    base.update(kw)
    return spike(**base)


def test_direction_follows_the_price_move():
    alert = evaluate(under_snap(), under_cfg(), under_spike())
    assert alert.direction == "under"
    assert alert.runner_label() == "Under 2.5 Goals"
    assert alert.play_price() == 1.6


def test_direction_known_without_score():
    """Kluczowa poprawa: kierunek z ruchu kursu, wiec dziala bez wyniku i minuty."""
    alert = evaluate(snap(minute=None, home_goals=None, away_goals=None),
                     Config(), spike())
    assert alert is not None and alert.direction == "over"
    assert alert.goals_needed is None            # bez wyniku nie liczymy warunku
    assert "ZAGRAJ TERAZ" in alert.format()


# --- filtry kontekstowe -----------------------------------------------------

def test_settled_over_ignored():
    """Over juz wszedl - nie ma czego grac, nawet przy napływie."""
    assert evaluate(snap(home_goals=1, away_goals=1), Config(), spike()) is None


def test_too_little_time_ignored():
    s = snap(market_name="Over/Under 2.5 Goals", line=2.5, first_half=False, minute=88,
             home_goals=0, away_goals=0)
    assert evaluate(s, Config(), spike()) is None


def test_excluded_competition():
    cfg = Config(excluded_competitions=["English Premier League"])
    assert evaluate(snap(competition="English Premier League"), cfg, spike()) is None


def test_broken_prices_ignored():
    assert evaluate(snap(over_price=1.0), Config(), spike()) is None
    assert evaluate(snap(under_price=0), Config(), spike()) is None


# --- tresc alertu -----------------------------------------------------------

def test_format_has_concrete_play_and_movement():
    text = evaluate(snap(), Config(), spike()).format()
    assert "NAGŁY NAPŁYW KASY na OVER" in text
    assert 'ZAGRAJ TERAZ: BACK (niebieska kolumna) "Over 1.5 Goals" @ 1.7' in text
    assert "muszą paść 2 gole" in text
    assert "Wyjście: jeśli do 28' nie padnie gol" in text
    assert "w 118 s wpadło 12 400 (66% obrotu, jaki rynek miał wcześniej)" in text
    assert "Kurs Over 1.5 Goals: 2.1 -> 1.7 (szansa Over 48% -> 59%)" in text


def test_under_format_flips_the_condition():
    text = evaluate(under_snap(), under_cfg(), under_spike()).format()
    assert "na UNDER" in text
    assert "może paść najwyżej 2 gole" in text
    assert "gol padnie przed" in text


# --- oplacalnosc po podatku -------------------------------------------------

def test_short_price_is_not_worth_playing():
    """Kurs 1.30 to netto 1.14 - podatek zjada marze, wiec nie zawracamy glowy."""
    assert evaluate(under_snap(under_price=1.3), under_cfg(),
                    under_spike(price_now=1.30)) is None
    assert evaluate(snap(over_price=1.2), Config(), spike(price_now=1.20)) is None


def test_min_price_boundary_passes():
    alert = evaluate(under_snap(under_price=1.5), under_cfg(), under_spike(price_now=1.50))
    assert alert is not None and alert.play_price() == 1.5


def test_min_price_is_configurable():
    cfg = Config(min_price=1.9)
    assert evaluate(snap(), cfg, spike()) is None, "Over po 1.70 nie przechodzi progu 1.90"
    assert evaluate(snap(over_price=2.0), Config(min_price=1.9), spike()) is not None


def test_net_price_after_tax_is_shown():
    text = evaluate(snap(), Config(), spike()).format()
    # 1.70 * 0.88 = 1.496
    assert "Po podatku: kurs 1.7 = netto 1.50, czyli +50% ze stawki" in text


def test_floor_never_goes_under_min_price():
    """Przy kursie 1.55 ulamek zysku dalby 1.44, czyli kurs, ktorego i tak nie zagramy."""
    alert = evaluate(under_snap(under_price=1.55), under_cfg(), under_spike(price_now=1.55))
    floor = [ln for ln in alert.format().split("\n") if "Nie bierz kursu" in ln][0]
    assert "1.50" in floor
    assert "podatek zjada opłacalność" in floor


def test_floor_uses_profit_rule_when_it_is_higher():
    floor = [ln for ln in evaluate(snap(), Config(), spike()).format().split("\n")
             if "Nie bierz kursu" in ln][0]
    assert "1.56" in floor, "przy kursie 1.70 wiazace jest 80% zysku, nie prog podatkowy"


def test_net_price_helper():
    from fixwatch.detector import net_price
    assert round(net_price(1.70), 3) == 1.496
    assert round(net_price(2.00), 2) == 1.76
    # Prog, przy ktorym wygrywajac zawsze wychodzisz na zero.
    assert round(net_price(1 / 0.88), 6) == 1.0


def test_exit_minute_stays_in_period():
    assert evaluate(snap(), Config(), spike()).exit_minute() == 28


def test_goals_word_and_must_fall():
    from fixwatch.detector import goals_word, must_fall
    assert [goals_word(n) for n in (1, 2, 4, 5)] == ["1 gol", "2 gole", "4 gole", "5 goli"]
    assert must_fall(1) == "musi paść 1 gol"
    assert must_fall(3) == "muszą paść 3 gole"


def test_money_uses_spaces_and_keeps_punctuation():
    from fixwatch.detector import money
    assert money(31062) == "31 062"
    assert "obrót łącznie 31 062 | obrót 1X2 8 000" in evaluate(
        snap(), Config(), spike()).format()


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


# --- ktore strony gramy -----------------------------------------------------

def test_only_over_by_default():
    """Domyslnie gramy tylko Over - wybor Felixa, nie wlasciwosc detektora."""
    assert Config().sides == "over"
    assert evaluate(snap(), Config(), spike()) is not None
    # Ten sam naply na Under, domyslnym configiem - nie przechodzi.
    assert evaluate(under_snap(), Config(), under_spike()) is None


def test_sides_under_only():
    cfg = Config(sides="under")
    assert evaluate(under_snap(), cfg, under_spike()) is not None
    assert evaluate(snap(), cfg, spike()) is None


def test_sides_both():
    cfg = Config(sides="both")
    assert evaluate(snap(), cfg, spike()) is not None
    assert evaluate(under_snap(), cfg, under_spike()) is not None


# --- fade: gramy przeciw kasie ----------------------------------------------

def fade_cfg(**kw):
    return Config(strategy="fade", **kw)


def test_fade_odwraca_strone_kurs_i_warunek():
    """Kasa idzie na Over 1.5 po 1.7, wiec fade obstawia Under 1.5 po 2.42."""
    a = evaluate(snap(), fade_cfg(), spike())
    assert a is not None
    assert a.direction == "over", "strona naplywu sie nie zmienia"
    assert a.bet_side() == "under", "ale obstawiamy przeciwna"
    assert a.runner_label() == "Under 1.5 Goals"
    assert a.play_price() == 2.42
    text = a.format()
    assert "GRASZ PRZECIW TEJ KASIE" in text
    assert 'ZAGRAJ TERAZ: BACK (niebieska kolumna) "Under 1.5 Goals" @ 2.42' in text
    # Warunek wygranej odwrocony: Under 1.5 przy 2 brakujacych golach = max 1 gol.
    assert "może paść najwyżej 1 gol" in text
    assert "gol padnie przed 28'" in text, "wyjscie tez odwrocone"


def test_fade_opisuje_ruch_strony_naplywu_nie_obstawianej():
    """Kurs 2.1 -> 1.7 dotyczy Over (naplyw), a nie obstawianego Under - inaczej klamie."""
    text = evaluate(snap(), fade_cfg(), spike()).format()
    assert "Kurs Over 1.5 Goals: 2.1 -> 1.7" in text
    assert "Kurs Under 1.5 Goals: 2.1" not in text


def test_fade_prog_kursu_dotyczy_strony_obstawianej():
    """Kasa na Over po 1.7, ale Under po 1.3 - fade nie ma sensu po podatku."""
    assert evaluate(snap(under_price=1.3), fade_cfg(), spike()) is None
    # A gdy to Over jest drogie, follow odpada, fade przechodzi.
    assert evaluate(snap(over_price=1.3, under_price=3.6), Config(), spike()) is None


def test_fade_na_naplywie_na_under_obstawia_over():
    a = evaluate(under_snap(), fade_cfg(sides="under"), under_spike())
    assert a.direction == "under" and a.bet_side() == "over"
    assert a.runner_label() == "Over 2.5 Goals" and a.play_price() == 2.6
    assert "muszą paść 3 gole" in a.format()


def test_follow_bez_zmian():
    """Domyslna strategia musi dzialac dokladnie jak wczesniej."""
    a = evaluate(snap(), Config(), spike())
    assert a.bet_side() == "over" and a.play_price() == 1.7
    assert "ktoś coś wie" in a.format()
