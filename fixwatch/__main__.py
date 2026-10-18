"""Skaner Betfair Exchange: szuka rynków goli, które "świrują" w egzotycznych ligach.

Uruchomienie:
    python -m fixwatch           # pętla 24/7
    python -m fixwatch --once    # jeden skan i koniec
    python -m fixwatch --demo    # przykład ze screena (Panama), bez Betfair
"""
import argparse
import os
import time

import requests
from dotenv import load_dotenv

from . import betfair
from .detector import Config, MarketSnapshot, evaluate
from .notify import notify

# Ligi z dużą płynnością – tam duży obrót jest normalny, więc je pomijamy.
DEFAULT_EXCLUDED = [
    "English Premier League", "English Championship", "Spanish La Liga", "German Bundesliga",
    "Italian Serie A", "French Ligue 1", "Dutch Eredivisie", "Portuguese Primeira Liga",
    "UEFA Champions League", "UEFA Europa League", "UEFA Conference League",
    "FIFA World Cup", "UEFA Euro", "Copa Libertadores", "Brazilian Serie A",
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
        volume_vs_match_odds=env_float("VOLUME_VS_MATCH_ODDS", 1.0),
        goals_per_90=env_float("GOALS_PER_90", 2.6),
        excluded_competitions=DEFAULT_EXCLUDED + extra,
    )


def build_snapshots(client):
    catalogue = client.list_markets(betfair.GOAL_MARKET_TYPES + ["MATCH_ODDS"])
    if not catalogue:
        return []
    by_id = {m["marketId"]: m for m in catalogue}
    books = {b["marketId"]: b for b in client.list_books(list(by_id))}

    match_odds = {}
    goal_markets = []
    for market_id, cat in by_id.items():
        book = books.get(market_id)
        if not book or book.get("status") != "OPEN":
            continue
        if cat.get("description", {}).get("marketType") == "MATCH_ODDS":
            match_odds[cat["event"]["id"]] = book.get("totalMatched", 0.0)
        else:
            goal_markets.append((cat, book))

    in_play_events = {cat["event"]["id"] for cat, book in goal_markets if book.get("inplay")}
    states = client.event_states(in_play_events) if in_play_events else {}

    snapshots = []
    for cat, book in goal_markets:
        line = betfair.parse_line(cat["marketName"])
        over, under = betfair.over_under_prices(book, cat)
        if line is None or not over or not under:
            continue
        event_id = cat["event"]["id"]
        first_half = cat.get("description", {}).get("marketType", "").startswith("FIRST_HALF")
        if book.get("inplay"):
            state = states.get(event_id)
            if state:
                minute, home, away = state["minute"], state["home"], state["away"]
            else:
                minute, home, away = betfair.estimate_minute(cat["marketStartTime"]), None, None
        else:
            minute, home, away = 0, 0, 0
        if first_half and minute is not None and minute >= 45:
            continue
        snapshots.append(MarketSnapshot(
            market_id=cat["marketId"], market_name=cat["marketName"],
            event_name=cat["event"]["name"],
            competition=cat.get("competition", {}).get("name", "?"),
            line=line, first_half=first_half, total_matched=book.get("totalMatched", 0.0),
            over_price=over, under_price=under, minute=minute,
            home_goals=home, away_goals=away,
            match_odds_matched=match_odds.get(event_id),
            url=betfair.MARKET_URL.format(cat["marketId"]),
        ))
    return snapshots


def scan(client, cfg, alerted):
    snapshots = build_snapshots(client)
    alerts = [a for a in (evaluate(s, cfg) for s in snapshots) if a]
    alerts.sort(key=lambda a: a.score, reverse=True)
    for alert in alerts:
        key = alert.snapshot.market_id
        # Ponowny alert dla tego samego rynku dopiero gdy obrót się podwoi.
        if key in alerted and alert.snapshot.total_matched < 2 * alerted[key]:
            continue
        alerted[key] = alert.snapshot.total_matched
        notify(alert)
    print(f"[INFO] Przeskanowano {len(snapshots)} rynków, alertów: {len(alerts)}")


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
    parser.add_argument("--demo", action="store_true", help="przykład ze screena, bez Betfair")
    args = parser.parse_args()
    load_dotenv()

    if args.demo:
        demo()
        return

    cfg = load_config()
    client = betfair.BetfairClient(
        app_key=os.environ["BETFAIR_APP_KEY"],
        username=os.environ["BETFAIR_USERNAME"],
        password=os.environ["BETFAIR_PASSWORD"],
        cert_file=os.getenv("BETFAIR_CERT_FILE"),
        key_file=os.getenv("BETFAIR_KEY_FILE"),
    )
    interval = int(env_float("SCAN_INTERVAL", 30))
    alerted = {}
    client.login()
    print("[INFO] Startuję skaner rynków goli...")
    while True:
        try:
            client.keep_alive()
            scan(client, cfg, alerted)
        except (requests.RequestException, RuntimeError, KeyError) as e:
            print(f"[ERROR] {e}")
        if args.once:
            break
        time.sleep(interval)


if __name__ == "__main__":
    main()
