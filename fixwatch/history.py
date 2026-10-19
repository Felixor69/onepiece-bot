"""Pamięć rynku między skanami – żeby widzieć RUCH, nie tylko stan.

Sedno sygnału: nie interesuje nas, że na rynku leży dużo pieniędzy (w jednych ligach
to norma), ale że NAGLE wpadł duży hajs na jedną stronę i kurs po tej stronie zjechał.
Jedno zdjęcie rynku tego nie pokaże – trzeba porównać dwa momenty w czasie.

Obrót z giełdy (`total_matched`) jest narastający, więc różnica dwóch pomiarów to
pieniądze, które wpadły w tym czasie.
"""
from collections import deque
from dataclasses import dataclass

from . import model

# Jak długie okno historii trzymamy na rynek (sekundy).
DEFAULT_WINDOW = 180.0
# Krócej niż tyle nie liczymy nic – przy dwóch pomiarach w odstępie paru sekund
# różnica obrotu to szum, nie napływ.
MIN_SPAN = 40.0


@dataclass
class Delta:
    """Co zmieniło się na rynku w oknie czasowym."""
    span: float              # ile sekund między pomiarami
    money_in: float          # ile kasy wpadło w tym czasie
    matched_before: float    # ile było obrotu na początku okna
    prob_before: float       # implikowane P(Over) na początku okna
    prob_now: float          # implikowane P(Over) teraz
    price_before: float      # kurs na stronę napływu, na początku okna
    price_now: float         # ten sam kurs teraz

    @property
    def inflow_ratio(self):
        """Napływ jako krotność tego, co na rynku leżało wcześniej."""
        return self.money_in / max(self.matched_before, 1.0)

    @property
    def prob_move(self):
        return self.prob_now - self.prob_before

    @property
    def side(self):
        """Strona, która była kupowana: rosnące P(Over) = kasa na Over."""
        return "over" if self.prob_move > 0 else "under"

    @property
    def money_per_minute(self):
        return self.money_in / (self.span / 60.0) if self.span else 0.0


class History:
    """Trzyma ostatnie pomiary każdego rynku i liczy z nich zmianę.

    Trzymane w pamięci procesu: po restarcie usługi historia startuje od zera, więc
    pierwsze ~1-2 skany po restarcie nie wygenerują sygnału (nie ma z czym porównać).
    """

    def __init__(self, window=DEFAULT_WINDOW, min_span=MIN_SPAN):
        self.window = window
        self.min_span = min_span
        self._points = {}      # market_id -> deque[(ts, matched, p_over, over_price, under_price)]

    def update(self, snapshot, now):
        """Zapisuje pomiar i zwraca Deltę, albo None gdy nie ma jeszcze z czym porównać."""
        p_over, _ = model.implied_probs(snapshot.over_price, snapshot.under_price)
        points = self._points.setdefault(snapshot.market_id, deque())
        points.append((now, snapshot.total_matched, p_over,
                       snapshot.over_price, snapshot.under_price))

        # Zostawiamy jeden pomiar sprzed okna, żeby mieć punkt odniesienia dla pełnego okna.
        while len(points) > 2 and points[1][0] < now - self.window:
            points.popleft()

        oldest = points[0]
        span = now - oldest[0]
        if len(points) < 2 or span < self.min_span:
            return None

        money_in = snapshot.total_matched - oldest[1]
        if money_in < 0:
            # Giełda przeliczyła obrót w dół – nie ma z tego napływu, zaczynamy od nowa.
            points.clear()
            points.append((now, snapshot.total_matched, p_over,
                           snapshot.over_price, snapshot.under_price))
            return None

        side_over = p_over - oldest[2] > 0
        return Delta(
            span=span, money_in=money_in, matched_before=oldest[1],
            prob_before=oldest[2], prob_now=p_over,
            price_before=oldest[3] if side_over else oldest[4],
            price_now=snapshot.over_price if side_over else snapshot.under_price,
        )

    def forget(self, live_market_ids):
        """Czyści rynki, których już nie ma w livie, żeby pamięć nie rosła bez końca."""
        for market_id in set(self._points) - set(live_market_ids):
            del self._points[market_id]

    def __len__(self):
        return len(self._points)
