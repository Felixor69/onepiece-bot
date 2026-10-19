"""Wykrywanie podejrzanych rynków goli (np. ustawiane mecze w egzotycznych ligach).

Sygnały:
  1. RATE  – kurs nie pasuje do wyniku i minuty: rynek wycenia tempo goli
             wielokrotnie wyższe (albo niższe) niż normalny mecz.
  2. VOLUME – obrót na rynku goli jest duży jak na ligę spoza topu.
  3. RATIO – rynek goli ma większy obrót niż 1X2 tego meczu (normalnie
             to 1X2 ma najwięcej pieniędzy).
Alert leci, gdy jest VOLUME i do tego RATE albo RATIO.

Strategia w alercie: jedziemy Z podejrzanymi pieniędzmi, czyli obstawiamy (BACK)
tę stronę, którą kupuje rynek – nie przeciw niej. Sygnał RATE mówi, która to
strona: tempo wyższe niż normalne = kasa na Over, niższe = kasa na Under.
"""
from dataclasses import dataclass, field

from . import model


# Poniżej tylu minut do końca okresu nie oceniamy kursu (model zbyt niedokładny).
MIN_REMAINING = 15
# Po tej minucie niskie tempo goli jest normalne (gra na wynik), więc Under nie alarmuje.
UNDER_MAX_MINUTE = 60
# Nie wchodzimy, jeśli kurs spadł tak, że zostało mniej niż tyle z pierwotnego zysku.
# Liczone od zysku (kurs - 1), nie od samego kursu: przy kursie 1.2 ułamek kursu dałby
# próg poniżej 1.0, czyli liczbę, której na giełdzie nie ma.
PROFIT_FLOOR_FRACTION = 0.8


def money(value):
    """1234567 -> "1 234 567" (spacje, bo przecinki w kwotach mylą się z interpunkcją)."""
    return f"{value:,.0f}".replace(",", " ")


def goals_word(n):
    """Polska odmiana: 1 gol, 2 gole, 5 goli."""
    if n == 1:
        return "1 gol"
    return f"{n} gole" if 2 <= n <= 4 else f"{n} goli"


def must_fall(n):
    """"musi paść 1 gol" / "muszą paść 3 gole" – zgodnie z liczbą."""
    return f"musi paść {goals_word(n)}" if n == 1 else f"muszą paść {goals_word(n)}"


@dataclass
class MarketSnapshot:
    market_id: str
    market_name: str          # np. "First Half Goals 1.5"
    event_name: str           # np. "Union Cocle v Herrera FC"
    competition: str          # np. "Panamanian Liga Panamena"
    line: float               # 1.5
    first_half: bool
    total_matched: float      # obrót na rynku (EUR/GBP – waluta konta)
    over_price: float
    under_price: float
    minute: int | None = None
    home_goals: int | None = None
    away_goals: int | None = None
    match_odds_matched: float | None = None   # obrót na 1X2 tego meczu
    url: str = ""


@dataclass
class Config:
    min_volume: float = 5000.0          # minimalny obrót na rynku goli
    rate_ratio_high: float = 1.7        # rynek wycenia >= 1.7x normalne tempo goli
    rate_ratio_low: float = 0.6         # albo <= 0.6x (ustawione "under")
    volume_vs_match_odds: float = 2.0   # rynek goli >= 2x obrotu 1X2
    goals_per_90: float = model.DEFAULT_GOALS_PER_90
    excluded_competitions: list[str] = field(default_factory=list)


@dataclass
class Alert:
    snapshot: MarketSnapshot
    reasons: list[str]
    score: float
    model_over_prob: float | None = None
    market_over_prob: float | None = None
    rate_ratio: float | None = None
    # Strona, na którą idzie podejrzana kasa ("over"/"under"); None = nie wiemy.
    direction: str | None = None
    goals_needed: int | None = None     # ile goli jeszcze musi paść, żeby Over wszedł
    remaining: int | None = None        # minut do końca okresu (z doliczonym)

    def fair_over_price(self):
        if self.model_over_prob:
            return 1 / self.model_over_prob
        return None

    def runner_label(self):
        """Nazwa zakładu z kuponu Betfair, np. "Over 4.5 Goals"."""
        if not self.direction:
            return None
        side = "Over" if self.direction == "over" else "Under"
        return f"{side} {self.snapshot.line:g} Goals"

    def play_price(self):
        """Kurs po stronie, na którą idzie kasa."""
        if not self.direction:
            return None
        s = self.snapshot
        return s.over_price if self.direction == "over" else s.under_price

    def exit_minute(self):
        """Do której minuty trzymamy pozycję, jeśli nic się nie dzieje."""
        s = self.snapshot
        if s.minute is None or self.remaining is None:
            return None
        end = 45 if s.first_half else 90
        return min(s.minute + max(self.remaining // 2, 5), end)

    def play_lines(self):
        """Konkret: co kliknąć, co musi się stać i kiedy uciekać."""
        s = self.snapshot
        if not self.direction:
            powod = ("brak wyniku i minuty z serwisu Betfair"
                     if s.minute is None or s.home_goals is None
                     else "za mało czasu do końca okresu, model nie liczy")
            return [
                "NIE GRAJ NA ŚLEPO – nie wiadomo, na którą stronę idzie kasa",
                f"   Powód: {powod}, zostaje sam sygnał z obrotu.",
                "   Zrób tak: otwórz rynek i zobacz, po której stronie (Over czy Under)",
                "   rośnie obrót i schodzi kurs – dopiero po tej stronie graj BACK.",
            ]

        label, price = self.runner_label(), self.play_price()
        out = [f'ZAGRAJ: BACK (niebieska kolumna) "{label}" @ {price:g}',
               f"   Rynek: {s.market_name} – ten mecz, ten rynek, nie inny"]
        if self.goals_needed is not None and self.remaining is not None:
            koniec = "do przerwy" if s.first_half else "do końca meczu"
            if self.direction == "over":
                warunek = must_fall(self.goals_needed)
            elif self.goals_needed == 1:
                warunek = "nie może paść ANI JEDEN gol"
            else:
                warunek = f"może paść najwyżej {goals_word(self.goals_needed - 1)}"
            out.append(f"   Żeby wygrać: {warunek} w ~{self.remaining} min ({koniec})")
        floor = 1 + (price - 1) * PROFIT_FLOOR_FRACTION
        out.append(f"   Nie bierz kursu poniżej {floor:.2f} – niżej zostaje mniej niż "
                   f"{PROFIT_FLOOR_FRACTION:.0%} pierwotnego zysku, odpuść")
        exit_min = self.exit_minute()
        if exit_min is not None:
            warunek = (f"do {exit_min}' nie padnie gol" if self.direction == "over"
                       else f"gol padnie przed {exit_min}'")
            out.append(f"   Wyjście: jeśli {warunek} – zamknij (LAY \"{label}\") "
                       f"i ratuj część stawki")
        return out

    def format(self):
        s = self.snapshot
        if self.direction:
            strona = "OVER" if self.direction == "over" else "UNDER"
            lines = [f"🚨 PODEJRZANY RYNEK – kasa idzie na {strona}"]
        else:
            lines = ["🚨 PODEJRZANY RYNEK – duży obrót, kierunek nieznany"]
        lines.append(f"{s.competition}: {s.event_name}")

        state = []
        if s.home_goals is not None:
            state.append(f"wynik {s.home_goals}-{s.away_goals}")
        if s.minute == 0:
            state.append("przed meczem")
        elif s.minute is not None:
            state.append(f"{s.minute}'")
        lines.append("Stan: " + (", ".join(state) if state else "nieznany"))

        lines.append("")
        lines += self.play_lines()
        lines.append("")

        lines.append(f"Kursy: Over {s.over_price} / Under {s.under_price}, "
                     f"obrót {money(s.total_matched)}")
        extra = []
        if self.rate_ratio is not None:
            extra.append(f"rynek wycenia {self.rate_ratio:.1f}x normalne tempo goli")
        if s.match_odds_matched:
            extra.append(f"obrót 1X2 {money(s.match_odds_matched)}")
        if extra:
            lines.append(" | ".join(extra))
        lines.append("Powody: " + "; ".join(self.reasons))
        if self.model_over_prob is not None:
            lines.append(f"⚠️ Jedziesz Z PIENIĘDZMI, nie z modelem (model Over "
                         f"{self.model_over_prob:.0%} vs rynek Over "
                         f"{self.market_over_prob:.0%}). Model to goły Poisson – nie zna "
                         f"siły drużyn ani kartek. Przy udowodnionym ustawieniu Betfair "
                         f"może unieważnić rynek.")
        if s.url:
            lines.append(s.url)
        return "\n".join(lines)


def is_excluded(competition, cfg):
    name = (competition or "").lower()
    return any(ex.lower() in name for ex in cfg.excluded_competitions)


def evaluate(s: MarketSnapshot, cfg: Config) -> Alert | None:
    if is_excluded(s.competition, cfg):
        return None
    if not s.over_price or not s.under_price or s.over_price <= 1 or s.under_price <= 1:
        return None

    reasons = []
    score = 0.0
    p_over, _ = model.implied_probs(s.over_price, s.under_price)
    alert = Alert(snapshot=s, reasons=reasons, score=0.0, market_over_prob=p_over)

    volume_ok = s.total_matched >= cfg.min_volume
    if volume_ok:
        reasons.append(f"obrót {money(s.total_matched)} >= {money(cfg.min_volume)}")
        score += s.total_matched / cfg.min_volume

    # Sygnał RATE – tylko gdy znamy wynik i minutę.
    rate_hit = False
    if s.minute is not None and s.home_goals is not None:
        goals = s.home_goals + s.away_goals
        k = model.goals_needed(s.line, goals)
        remaining = model.remaining_minutes(s.minute, s.first_half)
        # Jeśli Over już wszedł albo zostało mało czasu, model jest bez sensu.
        if k > 0 and remaining >= MIN_REMAINING:
            alert.goals_needed = k
            alert.remaining = remaining
            alert.model_over_prob = model.model_over_prob(
                s.line, goals, s.minute, s.first_half, cfg.goals_per_90)
            base = model.baseline_lambda(s.minute, s.first_half, cfg.goals_per_90)
            lam = model.implied_lambda(p_over, k)
            if base > 0 and lam is not None:
                alert.rate_ratio = lam / base
                if alert.rate_ratio >= cfg.rate_ratio_high:
                    rate_hit = True
                    alert.direction = "over"
                    reasons.append(f"kurs na Over za niski: rynek {p_over:.0%} vs model "
                                   f"{alert.model_over_prob:.0%}")
                    score += alert.rate_ratio
                elif alert.rate_ratio <= cfg.rate_ratio_low and s.minute <= UNDER_MAX_MINUTE:
                    rate_hit = True
                    alert.direction = "under"
                    reasons.append(f"kurs na Under za niski: rynek Over {p_over:.0%} vs model "
                                   f"{alert.model_over_prob:.0%}")
                    score += 1 / alert.rate_ratio

    ratio_hit = False
    if s.match_odds_matched is not None and s.match_odds_matched >= 0:
        if s.total_matched > cfg.volume_vs_match_odds * max(s.match_odds_matched, 1):
            ratio_hit = True
            reasons.append("rynek goli ma dużo większy obrót niż 1X2")
            score += 1

    if volume_ok and (rate_hit or ratio_hit):
        alert.score = round(score, 2)
        return alert
    return None
