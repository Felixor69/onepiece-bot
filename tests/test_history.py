"""Pamiec rynku miedzy skanami: czy w ogole widzimy ruch."""
from fixwatch.detector import MarketSnapshot
from fixwatch.history import History


def snap(matched, over, under, market_id="1"):
    return MarketSnapshot(market_id=market_id, market_name="First Half Goals 1.5",
                          event_name="A v B", competition="Panama Liga", line=1.5,
                          first_half=True, total_matched=matched,
                          over_price=over, under_price=under,
                          minute=9, home_goals=0, away_goals=0)


def test_first_measurement_gives_nothing():
    h = History()
    assert h.update(snap(18662, 2.10, 2.10), now=0) is None


def test_too_short_span_gives_nothing():
    """Dwa pomiary kilka sekund po sobie to szum, nie naply."""
    h = History()
    h.update(snap(18662, 2.10, 2.10), now=0)
    assert h.update(snap(31062, 1.70, 2.42), now=10) is None


def test_inflow_and_direction_are_measured():
    h = History()
    h.update(snap(18662, 2.10, 2.10), now=0)
    d = h.update(snap(31062, 1.70, 2.42), now=118)
    assert d is not None
    assert d.span == 118
    assert d.money_in == 31062 - 18662
    assert d.matched_before == 18662
    assert round(d.inflow_ratio, 2) == round((31062 - 18662) / 18662, 2)
    assert d.side == "over", "kurs Over zjechal, wiec kupowano Over"
    assert d.prob_move > 0
    assert d.price_before == 2.10 and d.price_now == 1.70
    assert round(d.money_per_minute) == round((31062 - 18662) / (118 / 60))


def test_direction_under_when_over_price_drifts_out():
    h = History()
    h.update(snap(10000, 2.00, 2.00), now=0)
    d = h.update(snap(20000, 6.00, 1.20), now=60)
    assert d.side == "under"
    assert d.price_before == 2.00 and d.price_now == 1.20


def test_turnover_going_backwards_resets():
    """Gdy gielda przeliczy obrot w dol, nie robimy z tego ujemnego naplywu."""
    h = History()
    h.update(snap(50000, 2.00, 2.00), now=0)
    assert h.update(snap(10000, 2.00, 2.00), now=60) is None
    # Po resecie znow potrzebujemy dwoch pomiarow.
    assert h.update(snap(20000, 1.70, 2.42), now=120) is not None


def test_window_slides_so_old_money_stops_counting():
    h = History(window=180)
    h.update(snap(1000, 2.00, 2.00), now=0)
    h.update(snap(20000, 1.70, 2.42), now=60)
    # Dawno temu wpadlo 19 000; 400 s pozniej spokojny rynek nie moze tego liczyc.
    h.update(snap(20100, 1.70, 2.42), now=300)
    d = h.update(snap(20200, 1.70, 2.42), now=400)
    assert d.money_in < 1000, "stary naply musi wypasc z okna"


def test_forget_prunes_dead_markets():
    h = History()
    h.update(snap(1000, 2.0, 2.0, market_id="a"), now=0)
    h.update(snap(1000, 2.0, 2.0, market_id="b"), now=0)
    assert len(h) == 2
    h.forget(["a"])
    assert len(h) == 1
