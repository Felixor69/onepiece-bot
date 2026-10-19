"""Log badawczy: zapisuje KAŻDY napływ powyżej niskiego progu, niezależnie od alertów.

Po co osobno od Discorda: progi, które chronią przed stratą (wysoka kwota, jedna strona,
minimalny kurs), jednocześnie zabijają próbkę — przy nich wpada zero zdarzeń na dzień,
czyli nie ma z czego policzyć, który próg się opłaca. Tu więc łapiemy szeroko i nie
wysyłamy nic; Discord dalej dostaje tylko to, co przeszło pełne filtry.

Jeden wiersz JSONL na napływ, z `event_id` i kursem OBU stron – to minimum, żeby po
meczu dało się rozliczyć i zagranie z kasą, i zagranie przeciw niej.
"""
import json
import os
import time

# Poniżej tej kwoty nie zapisujemy nawet do badań – to już czysty szum cienkiej książki.
DEFAULT_MIN_MONEY = 2000.0
DEFAULT_PATH = "/var/lib/fixwatch/spikes.jsonl"


def wiersz(snapshot, delta, now_wall=None):
    """Płaski rekord: wszystko, co potrzebne do policzenia progów i rozliczenia typu."""
    s, d = snapshot, delta
    return {
        "ts": now_wall if now_wall is not None else time.time(),
        "event_id": s.event_id,
        "event": s.event_name,
        "competition": s.competition,
        "market_id": s.market_id,
        "market": s.market_name,
        "line": s.line,
        "first_half": s.first_half,
        "minute": s.minute,
        "home_goals": s.home_goals,
        "away_goals": s.away_goals,
        # Kursy obu stron, żeby dało się policzyć też wariant przeciwny (fade).
        "over_price": s.over_price,
        "under_price": s.under_price,
        "total_matched": s.total_matched,
        "match_odds_matched": s.match_odds_matched,
        # Co się zmieniło w oknie – to są kandydaci na progi.
        "side": d.side,
        "money_in": round(d.money_in, 2),
        "inflow_ratio": round(d.inflow_ratio, 4),
        "prob_move": round(d.prob_move, 4),
        "prob_before": round(d.prob_before, 4),
        "prob_now": round(d.prob_now, 4),
        "span": round(d.span, 1),
    }


class ResearchLog:
    """Dopisuje napływy do pliku JSONL. Awaria pliku nie może zatrzymać skanu."""

    def __init__(self, path=None, min_money=None):
        self.path = path if path is not None else os.getenv("RESEARCH_LOG", DEFAULT_PATH)
        if min_money is not None:
            self.min_money = min_money
        else:
            raw = os.getenv("RESEARCH_MIN_MONEY")
            self.min_money = float(raw) if raw else DEFAULT_MIN_MONEY
        self.zapisanych = 0
        self._ostrzegal = False

    def enabled(self):
        return bool(self.path)

    def record(self, snapshot, delta, now_wall=None):
        """Zwraca True, gdy wiersz poszedł do pliku."""
        if not self.enabled() or delta is None or delta.money_in < self.min_money:
            return False
        try:
            os.makedirs(os.path.dirname(self.path) or ".", exist_ok=True)
            with open(self.path, "a", encoding="utf-8") as f:
                f.write(json.dumps(wiersz(snapshot, delta, now_wall),
                                   ensure_ascii=False) + "\n")
        except OSError as e:
            # Log badawczy jest wazny, ale nie wazniejszy od dzialania bota.
            if not self._ostrzegal:
                print(f"[WARN] Log badawczy {self.path} niedostępny ({e}); "
                      f"skanuję dalej, ostrzegam raz")
                self._ostrzegal = True
            return False
        self.zapisanych += 1
        return True
