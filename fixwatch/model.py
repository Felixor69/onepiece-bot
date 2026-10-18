"""Model bramek (Poisson) – ile goli "powinno" paść w pozostałym czasie.

Używany do porównania kursów z rynku z tym, co wynika z wyniku i minuty.
Przykład ze screena: 0-0 w 9', Over 1.5 w 1. połowie po 1.70 (~59%),
a model mówi ~26% – rynek wycenia ~2x wyższe tempo goli niż normalnie.
"""
import math

# Średnia liczba goli na mecz (obie drużyny). Niższe ligi są zwykle w okolicy 2.5-2.8.
DEFAULT_GOALS_PER_90 = 2.6
# Część goli padająca w 1. połowie (statystycznie ~44-45%).
FIRST_HALF_SHARE = 0.45
# Doliczony czas, który dorzucamy do pozostałych minut.
STOPPAGE_FH = 2
STOPPAGE_FT = 4


def poisson_at_least(k, lam):
    """P(N >= k) dla N ~ Poisson(lam)."""
    if k <= 0:
        return 1.0
    if lam <= 0:
        return 0.0
    cdf = 0.0
    term = math.exp(-lam)
    for i in range(k):
        cdf += term
        term *= lam / (i + 1)
    return max(0.0, 1.0 - cdf)


def remaining_minutes(minute, first_half):
    if first_half:
        return max(45 - minute, 0) + STOPPAGE_FH
    return max(90 - minute, 0) + STOPPAGE_FT


def baseline_lambda(minute, first_half, goals_per_90=DEFAULT_GOALS_PER_90):
    """Oczekiwana liczba goli do końca okresu przy normalnym tempie."""
    if first_half:
        per_minute = goals_per_90 * FIRST_HALF_SHARE / 45
    else:
        per_minute = goals_per_90 / 90
    return per_minute * remaining_minutes(minute, first_half)


def goals_needed(line, current_goals):
    """Ile goli jeszcze musi paść, żeby Over `line` wszedł."""
    return math.floor(line) + 1 - current_goals


def model_over_prob(line, current_goals, minute, first_half,
                    goals_per_90=DEFAULT_GOALS_PER_90):
    lam = baseline_lambda(minute, first_half, goals_per_90)
    return poisson_at_least(goals_needed(line, current_goals), lam)


def implied_lambda(p_over, k):
    """Odwrócenie modelu: jakie tempo goli wycenia rynek, skoro P(Over) = p_over."""
    if k <= 0:
        return None
    p_over = min(max(p_over, 1e-6), 1 - 1e-6)
    lo, hi = 0.0, 30.0
    for _ in range(80):
        mid = (lo + hi) / 2
        if poisson_at_least(k, mid) < p_over:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2


def implied_probs(over_price, under_price):
    """Prawdopodobieństwa z kursów, z usuniętą marżą (normalizacja do 1)."""
    io, iu = 1 / over_price, 1 / under_price
    total = io + iu
    return io / total, iu / total
