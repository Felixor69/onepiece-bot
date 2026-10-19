"""Skaner giełdy Betfair (przez BetsAPI albo bezpośrednio): łapie NAGŁY napływ kasy na rynki goli.

Sygnałem jest ruch, nie stan: alert leci, gdy w ciągu kilkudziesięciu sekund na jedną
stronę rynku goli wpada duży hajs i kurs po tej stronie zjeżdża. Wymaga więc dwóch
pomiarów tego samego rynku – po starcie pierwszy skan tylko zapamiętuje stan.

Uruchomienie:
    python -m fixwatch           # pętla 24/7
    python -m fixwatch --once    # jeden skan (NIE wykryje ruchu – brak drugiego pomiaru)
    python -m fixwatch --demo    # przykład ze screena (Panama), bez pobierania danych
"""
import argparse
import os
import time

import requests
from dotenv import load_dotenv

from . import betfair, betsapi
from .detector import Config, MarketSnapshot, evaluate
from .history import History
from .notify import notify

# Ligi z dużą płynnością – tam duży obrót jest normalny, więc je pomijamy.
DEFAULT_EXCLUDED = [
    "English Premier League", "English Championship", "Spanish La Liga", "German Bundesliga",
    "Italian Serie A", "French Ligue 1", "Dutch Eredivisie", "Portuguese Primeira Liga",
    "UEFA Champions League", "UEFA Europa League", "UEFA Conference League",
    "FIFA World Cup", "UEFA Euro", "Copa Libertadores", "Brazilian Serie A", "Argentinian Primera Division",
]
# Po alercie na danym rynku milczymy tyle sekund. Musi być dłuższe niż okno historii,
# inaczej ten sam napływ byłby raportowany w każdym kolejnym skanie.
DEFAULT_COOLDOWN = 300.0


def env_float(name, default):
    value = os.getenv(name)
    return float(value) if value else default


def load_config():
    extra = [c.strip() for c in os.getenv("EXCLUDED_COMPETITIONS", "").split(",") if c.strip()]
    return Config(
        spike_min_money=env_float("SPIKE_MIN_MONEY", 2000),
        spike_ratio=env_float("SPIKE_RATIO", 0.3),
        spike_prob_move=env_float("SPIKE_PROB_MOVE", 0.05),
        rate_ratio_high=env_float("RATE_RATIO_HIGH", 1.7),
        rate_ratio_low=env_float("RATE_RATIO_LOW", 0.6),
        volume_vs_match_odds=env_float("VOLUME_VS_MATCH_ODDS", 2.0),
        goals_per_90=env_float("GOALS_PER_90", 2.6),
        excluded_competitions=DEFAULT_EXCLUDED + extra,
    )


GOAL_TYPES = set(betfair.GOAL_MARKET_TYPES)


def build_snapshots(markets, states):
    """Z rynków w formacie wspólnym (Betfair albo BetsAPI) robi dane dla detektora."""
    markets = [m for m in markets if m["status"] == "OPEN"]
    match_odds = {m["event_id"]: m["total_matched"] for m in markets
                  if m["market_type"] == "MATCH_ODDS"}

    snapshots = []
    for m in markets:
        if m["market_type"] not in GOAL_TYPES:
            continue
        line = betfair.parse_line(m["market_name"])
        over, under = betfair.over_under(m["runners"])
        if line is None or not over or not under:
            continue
        first_half = m["market_type"].startswith("FIRST_HALF")
        if m["inplay"]:
            state = states.get(m["event_id"])
            if state:
                minute, home, away = state["minute"], state["home"], state["away"]
            else:
                minute, home, away = betfair.estimate_minute(m["start_time"]), None, None
        else:
            minute, home, away = 0, 0, 0
        if first_half and minute is not None and minute >= 45:
            continue
        snapshots.append(MarketSnapshot(
            market_id=m["market_id"], market_name=m["market_name"],
            event_name=m["event_name"], competition=m["competition"],
            line=line, first_half=first_half, total_matched=m["total_matched"],
            over_price=over, under_price=under, minute=minute,
            home_goals=home, away_goals=away,
            match_odds_matched=match_odds.get(m["event_id"]),
            url=betfair.MARKET_URL.format(m["market_id"]),
        ))
    return snapshots


def scan(fetch, cfg, alerted, history, cooldown=DEFAULT_COOLDOWN, now=None):
    now = time.monotonic() if now is None else now
    snapshots = build_snapshots(*fetch())
    history.forget([s.market_id for s in snapshots])

    alerts = []
    for s in snapshots:
        alert = evaluate(s, cfg, history.update(s, now))
        if alert:
            alerts.append(alert)
    alerts.sort(key=lambda a: a.score, reverse=True)

    sent = 0
    for alert in alerts:
        key = alert.snapshot.market_id
        # Ten sam napływ siedzi w oknie historii jeszcze przez chwilę, więc po alercie
        # milczymy na tym rynku, zamiast powtarzać to samo zdarzenie w kolejnych skanach.
        last = alerted.get(key)
        if last is not None and now - last < cooldown:
            continue
        alerted[key] = now
        notify(alert)
        sent += 1
    print(f"[INFO] Przeskanowano {len(snapshots)} rynków (w pamięci {len(history)}), "
          f"napływów: {len(alerts)}, wysłanych: {sent}")


def demo():
    """Dane ze screena: Union Cocle - Herrera FC, 0-0, 9', nagły hajs na Over 1.5."""
    from .history import Delta

    cfg = load_config()
    snapshot = MarketSnapshot(
        "demo-1", "First Half Goals 1.5", "Union Cocle v Herrera FC",
        "Panama Liga Panamena de Futbol", 1.5, True, 31062, 1.7, 2.42,
        minute=9, home_goals=0, away_goals=0, match_odds_matched=8000,
        url=betfair.MARKET_URL.format("1.111111111"))
    # W 118 s wpadlo 12 400 przy 18 662 obrotu wczesniej, kurs Over 2.10 -> 1.70.
    delta = Delta(span=118, money_in=12400, matched_before=18662,
                  prob_before=0.48, prob_now=0.59, price_before=2.10, price_now=1.70)
    alert = evaluate(snapshot, cfg, delta)
    print(alert.format() if alert else "[OK] brak alertu")


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--once", action="store_true",
                        help="jeden skan i koniec (nie wykryje ruchu – brak drugiego pomiaru)")
    parser.add_argument("--demo", action="store_true",
                        help="przykład ze screena, bez pobierania danych")
    args = parser.parse_args()
    load_dotenv()

    if args.demo:
        demo()
        return

    cfg = load_config()
    source = os.getenv("DATA_SOURCE", "betsapi")
    if source == "betsapi":
        client = betsapi.BetsApiClient(os.environ["BETSAPI_TOKEN"])
        fetch = client.fetch
        # Limit BetsAPI to 3600 zapytan/h, a jeden skan to ~1 + 2x ceil(liczba meczow/10)
        # zapytan, czyli przy kilkudziesieciu meczach ~11. Co 30 s mamy ~1300/h - z zapasem,
        # a im czesciej patrzymy, tym szybciej widzimy naply.
        default_interval = 30
    else:
        client = betfair.BetfairClient(
            app_key=os.environ["BETFAIR_APP_KEY"],
            username=os.environ["BETFAIR_USERNAME"],
            password=os.environ["BETFAIR_PASSWORD"],
            cert_file=os.getenv("BETFAIR_CERT_FILE"),
            key_file=os.getenv("BETFAIR_KEY_FILE"),
        )
        client.login()

        def fetch():
            client.keep_alive()
            return client.fetch(betfair.GOAL_MARKET_TYPES + ["MATCH_ODDS"])
        default_interval = 20
    interval = int(env_float("SCAN_INTERVAL", default_interval))
    cooldown = env_float("ALERT_COOLDOWN", DEFAULT_COOLDOWN)
    history = History(window=env_float("SPIKE_WINDOW", 180))
    alerted = {}
    print(f"[INFO] Startuję skaner nagłych napływów (źródło: {source}, "
          f"skan co {interval} s). Pierwszy skan tylko zapamiętuje stan rynków.")
    while True:
        try:
            scan(fetch, cfg, alerted, history, cooldown)
        except (requests.RequestException, RuntimeError, KeyError) as e:
            print(f"[ERROR] {e}")
        if args.once:
            break
        time.sleep(interval)


if __name__ == "__main__":
    main()
