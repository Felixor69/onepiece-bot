"""Skaner giełdy Betfair (przez BetsAPI albo bezpośrednio): szuka rynków goli, które "świrują" w egzotycznych ligach.

Uruchomienie:
    python -m fixwatch           # pętla 24/7
    python -m fixwatch --once    # jeden skan i koniec
    python -m fixwatch --demo    # przykład ze screena (Panama), bez pobierania danych
"""
import argparse
import os
import time

import requests
from dotenv import load_dotenv

from . import betfair, betsapi
from .detector import Config, MarketSnapshot, evaluate
from .notify import notify

# Ligi z dużą płynnością – tam duży obrót jest normalny, więc je pomijamy.
DEFAULT_EXCLUDED = [
    "English Premier League", "English Championship", "Spanish La Liga", "German Bundesliga",
    "Italian Serie A", "French Ligue 1", "Dutch Eredivisie", "Portuguese Primeira Liga",
    "UEFA Champions League", "UEFA Europa League", "UEFA Conference League",
    "FIFA World Cup", "UEFA Euro", "Copa Libertadores", "Brazilian Serie A", "Argentinian Primera Division",
]


def env_float(name, default):
    value = os.getenv(name)
    return float(value) if value else default


def load_config():
    extra = [c.strip() for c in os.getenv("EXCLUDED_COMPETITIONS", "").split(",") if c.strip()]
    return Config(
        min_volume=env_float("MIN_VOLUME", 5000),
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


def scan(fetch, cfg, alerted):
    snapshots = build_snapshots(*fetch())
    alerts = [a for a in (evaluate(s, cfg) for s in snapshots) if a]
    alerts.sort(key=lambda a: a.score, reverse=True)
    sent = 0
    for alert in alerts:
        s = alert.snapshot
        # Sam obrót nie mówi, co zagrać (np. rynek goli ma więcej kasy niż 1X2, ale kurs
        # jest normalny). Taki sygnał zostaje w logu – na Discorda nie ma po co iść.
        if not alert.actionable():
            print(f"[INFO] Bez zagrania, nie wysyłam: {s.event_name} | {s.market_name}"
                  f" | {alert.no_direction_reason()}")
            continue
        key = s.market_id
        # Ponowny alert dla tego samego rynku dopiero gdy obrót się podwoi. Zapisujemy
        # tylko wysłane, żeby alert bez kierunku nie zablokował późniejszego zagrania
        # na tym samym rynku.
        if key in alerted and s.total_matched < 2 * alerted[key]:
            continue
        alerted[key] = s.total_matched
        notify(alert)
        sent += 1
    print(f"[INFO] Przeskanowano {len(snapshots)} rynków, "
          f"alertów: {len(alerts)}, wysłanych: {sent}")


def demo():
    """Dane ze screena: Union Cocle - Herrera FC, 0-0, 9'."""
    cfg = load_config()
    snapshots = [
        MarketSnapshot("demo-1", "First Half Goals 1.5", "Union Cocle v Herrera FC",
                       "Panama Liga Panamena de Futbol", 1.5, True, 31062, 1.7, 2.42,
                       minute=9, home_goals=0, away_goals=0, match_odds_matched=8000),
        MarketSnapshot("demo-2", "First Half Goals 2.5", "Union Cocle v Herrera FC",
                       "Panama Liga Panamena de Futbol", 2.5, True, 38498, 2.7, 1.5,
                       minute=9, home_goals=0, away_goals=0, match_odds_matched=8000),
    ]
    for s in snapshots:
        alert = evaluate(s, cfg)
        print(alert.format() if alert else f"[OK] {s.market_name}: brak alertu", "\n")


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--once", action="store_true", help="jeden skan i koniec")
    parser.add_argument("--demo", action="store_true", help="przykład ze screena, bez pobierania danych")
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
        default_interval = 60  # limit BetsAPI: 3600 zapytań/h
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
        default_interval = 30
    interval = int(env_float("SCAN_INTERVAL", default_interval))
    alerted = {}
    print(f"[INFO] Startuję skaner rynków goli (źródło: {source})...")
    while True:
        try:
            scan(fetch, cfg, alerted)
        except (requests.RequestException, RuntimeError, KeyError) as e:
            print(f"[ERROR] {e}")
        if args.once:
            break
        time.sleep(interval)


if __name__ == "__main__":
    main()
