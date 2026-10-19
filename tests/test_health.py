"""Czujka: cisza bota nie moze byc nieodroznialna od jego smierci."""
from fixwatch.health import Watchdog


def test_jeden_blad_nie_alarmuje():
    w = Watchdog(fails_before_alert=5)
    assert all(w.record(False, "timeout", now=t) is None for t in range(4))


def test_po_progu_krzyczy_raz():
    w = Watchdog(fails_before_alert=3, repeat_after=1000)
    assert w.record(False, "HTTPError: 403", 0) is None
    assert w.record(False, "HTTPError: 403", 10) is None
    msg = w.record(False, "HTTPError: 403", 20)
    assert "NIE WIDZI RYNKU" in msg and "403" in msg
    assert "token BetsAPI" in msg, "ma podpowiedziec najbardziej prawdopodobna przyczyne"
    assert w.record(False, "HTTPError: 403", 30) is None, "nie powtarzamy od razu"


def test_przypomina_po_czasie():
    w = Watchdog(fails_before_alert=1, repeat_after=100)
    assert w.record(False, "x", 0) is not None
    assert w.record(False, "x", 50) is None
    assert "nadal nie widzi" in w.record(False, "x", 100)


def test_zglasza_powrot():
    w = Watchdog(fails_before_alert=1)
    w.record(False, "x", 0)
    msg = w.record(True, "", 600)
    assert "znowu widzi rynek" in msg and "10 min" in msg
    assert w.record(True, "", 700) is None, "po powrocie milczymy"


def test_zero_rynkow_to_tez_oslepniecie():
    """Padniete wszystkie paczki daja pusty wynik BEZ bledu - to musi alarmowac."""
    w = Watchdog(fails_before_alert=2)
    assert w.record(False, "skan nie zwrócił ani jednego rynku", 0) is None
    assert "NIE WIDZI RYNKU" in w.record(False, "skan nie zwrócił ani jednego rynku", 10)


def test_sukces_zeruje_licznik():
    w = Watchdog(fails_before_alert=3)
    w.record(False, "x", 0)
    w.record(False, "x", 1)
    assert w.record(True, "", 2) is None
    assert w.record(False, "x", 3) is None, "licznik liczy od nowa"
