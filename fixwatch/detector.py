"""Wykrywanie nagłego napływu pieniędzy na rynek goli (podejrzenie ustawionego meczu).

Sedno: nie szukamy rynków, na których LEŻY dużo pieniędzy – w małych ligach to norma
i generuje wyłącznie szum. Szukamy momentu, w którym pieniądze NAGLE WPADAJĄ na jedną
stronę i kurs po tej stronie zjeżdża. To jest sygnał, że ktoś coś wie, i to jest coś,
z czego da się zagrać od razu.

Wyzwalacz (wszystkie trzy warunki, liczone między dwoma pomiarami rynku):
  1. NAPŁYW  – w oknie wpadło co najmniej `spike_min_money`,
  2. SKALA   – ten napływ to co najmniej `spike_ratio` tego, co na rynku leżało wcześniej,
  3. RUCH    – implikowana szansa przesunęła się o co najmniej `spike_prob_move`.

Kierunek zagrania bierzemy z (3): rośnie P(Over) = kasa idzie na Over. To obserwacja
rynku, nie wniosek z modelu – dlatego kierunek znamy zawsze, także gdy BetsAPI nie poda
wyniku i minuty.

Model Poissona został tu wyłącznie jako KONTEKST w treści alertu („rynek wycenia 2x
normalne tempo goli"). Nie jest wyzwalaczem i nie służy do grania przeciw rynkowi: to
goły Poisson bez siły drużyn i kartek, więc przy rozjeździe częściej myli się model.
"""
from dataclasses import dataclass, field

from . import model


# Poniżej tylu minut do końca okresu nie ma sensu grać (za mało czasu na gole).
MIN_REMAINING = 15
# Podatek od gier w PL: 12% od stawki. Stawiasz 1, pracuje 0.88, wraca 0.88 * kurs,
# więc przy kursie 1/0.88 = 1.136 jesteś na zero nawet wygrywając za każdym razem.
DEFAULT_TAX_RATE = 0.12
# Nie wchodzimy, jeśli kurs spadł tak, że zostało mniej niż tyle z pierwotnego zysku.
# Liczone od zysku (kurs - 1), nie od samego kursu: przy kursie 1.2 ułamek kursu dałby
# próg poniżej 1.0, czyli liczbę, której na giełdzie nie ma.
PROFIT_FLOOR_FRACTION = 0.8


def money(value):
    """1234567 -> "1 234 567" (spacje, bo przecinki w kwotach mylą się z interpunkcją)."""
    return f"{value:,.0f}".replace(",", " ")


def net_price(price, tax_rate=DEFAULT_TAX_RATE):
    """Kurs po podatku od stawki – tyle realnie wraca z jednej postawionej jednostki."""
    return price * (1 - tax_rate)


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
    # Klucz do rozliczenia typu po meczu: betfair/timeline?event_id=... daje gole z
    # minutami. Bez tego pola nie da sie policzyc, czy alert mial racje.
    event_id: str = ""


@dataclass
class Config:
    # --- wyzwalacz: nagly naplyw ---
    spike_min_money: float = 10000.0    # ile kasy musi wpasc w oknie
    spike_ratio: float = 0.3            # ...i ile to ma byc wzgledem obrotu sprzed okna
    spike_prob_move: float = 0.05       # ...przy przesunieciu szansy o tyle (5 pkt proc.)
    # --- oplacalnosc po podatku ---
    # Ponizej tego kursu nie gramy: podatek od stawki zjada cala marze (kurs 1.30 to
    # netto 1.14, czyli +14% z wygranej, a przy 1.14 jest sie dokladnie na zero).
    min_price: float = 1.5
    tax_rate: float = DEFAULT_TAX_RATE
    # Ktore strony gramy: "over", "under" albo "both". Detektor jest symetryczny, to
    # jest wybor Felixa - trzymanie Under przy 0-0 to inna gra niz czekanie na gole.
    sides: str = "over"
    # --- kontekst w tresci alertu ---
    rate_ratio_high: float = 1.7        # rynek wycenia >= 1.7x normalne tempo goli
    rate_ratio_low: float = 0.6         # albo <= 0.6x
    volume_vs_match_odds: float = 2.0   # rynek goli >= 2x obrotu 1X2
    goals_per_90: float = model.DEFAULT_GOALS_PER_90
    excluded_competitions: list[str] = field(default_factory=list)


@dataclass
class Alert:
    snapshot: MarketSnapshot
    reasons: list[str]
    score: float
    delta: object = None                # history.Delta – co sie zmienilo w oknie
    direction: str | None = None        # strona, na ktora idzie kasa
    model_over_prob: float | None = None
    market_over_prob: float | None = None
    rate_ratio: float | None = None
    goals_needed: int | None = None     # ile goli jeszcze musi paść, żeby Over wszedł
    remaining: int | None = None        # minut do końca okresu (z doliczonym)
    tax_rate: float = DEFAULT_TAX_RATE  # do przeliczenia kursu na netto
    min_price: float = 1.5              # najnizszy kurs, ktory ma sens po podatku

    def fair_over_price(self):
        if self.model_over_prob:
            return 1 / self.model_over_prob
        return None

    def runner_label(self):
        """Nazwa zakładu z kuponu Betfair, np. "Over 4.5 Goals"."""
        side = "Over" if self.direction == "over" else "Under"
        return f"{side} {self.snapshot.line:g} Goals"

    def play_price(self):
        """Kurs po stronie, na którą idzie kasa."""
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
        label, price = self.runner_label(), self.play_price()
        out = [f'ZAGRAJ TERAZ: BACK (niebieska kolumna) "{label}" @ {price:g}',
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
        netto = net_price(price, self.tax_rate)
        out.append(f"   Po podatku: kurs {price:g} = netto {netto:.2f}, "
                   f"czyli +{(netto - 1) * 100:.0f}% ze stawki")
        # Dwa ograniczenia na kurs: nie oddajemy wiecej niz 20% zysku i nie schodzimy
        # pod prog oplacalnosci po podatku. Obowiazuje wyzszy z nich.
        zysk_floor = 1 + (price - 1) * PROFIT_FLOOR_FRACTION
        floor = max(zysk_floor, self.min_price)
        powod = ("niżej podatek zjada opłacalność" if floor == self.min_price
                 else f"niżej zostaje mniej niż {PROFIT_FLOOR_FRACTION:.0%} pierwotnego zysku")
        out.append(f"   Nie bierz kursu poniżej {floor:.2f} – {powod}, odpuść")
        exit_min = self.exit_minute()
        if exit_min is not None:
            warunek = (f"do {exit_min}' nie padnie gol" if self.direction == "over"
                       else f"gol padnie przed {exit_min}'")
            out.append(f"   Wyjście: jeśli {warunek} – zamknij (LAY \"{label}\") "
                       f"i ratuj część stawki")
        return out

    def movement_lines(self):
        """Co się właśnie stało na rynku – powód, dla którego to w ogóle leci."""
        d = self.delta
        if d is None:
            return []
        return [
            f"CO SIĘ WŁAŚNIE STAŁO: w {d.span:.0f} s wpadło {money(d.money_in)} "
            f"({d.inflow_ratio:.0%} obrotu, jaki rynek miał wcześniej)",
            f"   Kurs {self.runner_label()}: {d.price_before:g} -> {d.price_now:g} "
            f"(szansa Over {d.prob_before:.0%} -> {d.prob_now:.0%})",
            f"   Tempo napływu: {money(d.money_per_minute)} na minutę",
        ]

    def format(self):
        s = self.snapshot
        strona = "OVER" if self.direction == "over" else "UNDER"
        lines = [f"🚨 NAGŁY NAPŁYW KASY na {strona} – ktoś coś wie"]
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
        lines += self.movement_lines()

        kontekst = [f"obrót łącznie {money(s.total_matched)}"]
        if s.match_odds_matched:
            kontekst.append(f"obrót 1X2 {money(s.match_odds_matched)}")
        lines.append(" | ".join(kontekst))
        if self.reasons:
            lines.append("Dodatkowo: " + "; ".join(self.reasons))
        lines.append("⚠️ Kurs leci w dół – licz się z tym, że zanim klikniesz, będzie "
                     "gorszy niż podany. Przy udowodnionym ustawieniu Betfair może "
                     "unieważnić rynek.")
        if s.url:
            lines.append(s.url)
        return "\n".join(lines)


def is_excluded(competition, cfg):
    name = (competition or "").lower()
    return any(ex.lower() in name for ex in cfg.excluded_competitions)


def evaluate(s: MarketSnapshot, cfg: Config, delta=None) -> Alert | None:
    """Alert tylko wtedy, gdy w oknie NAGLE wpadła kasa na jedną stronę.

    `delta` to history.Delta; None oznacza, że nie mamy jeszcze drugiego pomiaru
    tego rynku – wtedy nie ma mowy o ruchu i nie ma sygnału.
    """
    if is_excluded(s.competition, cfg):
        return None
    if not s.over_price or not s.under_price or s.over_price <= 1 or s.under_price <= 1:
        return None
    if delta is None:
        return None

    # --- wyzwalacz ---------------------------------------------------------
    if delta.money_in < cfg.spike_min_money:
        return None
    if delta.inflow_ratio < cfg.spike_ratio:
        return None
    if abs(delta.prob_move) < cfg.spike_prob_move:
        return None

    # Gramy tylko wybrane strony rynku.
    if cfg.sides != "both" and delta.side != cfg.sides:
        return None

    # Kurs po stronie napływu musi się opłacać po podatku od stawki. Przy 1.20 netto
    # wychodzi 1.06, czyli +6% z wygranej – nie ma o co grać, więc nie zawracamy głowy.
    play_price = s.over_price if delta.side == "over" else s.under_price
    if play_price < cfg.min_price:
        return None

    p_over, _ = model.implied_probs(s.over_price, s.under_price)
    reasons = []
    alert = Alert(snapshot=s, reasons=reasons, score=0.0, delta=delta,
                  direction=delta.side, market_over_prob=p_over,
                  tax_rate=cfg.tax_rate, min_price=cfg.min_price)

    # --- kontekst z wyniku i minuty ---------------------------------------
    if s.minute is not None and s.home_goals is not None:
        goals = s.home_goals + s.away_goals
        k = model.goals_needed(s.line, goals)
        remaining = model.remaining_minutes(s.minute, s.first_half)
        if k <= 0:
            return None     # Over już wszedł, nie ma czego grać
        if remaining < MIN_REMAINING:
            return None     # za mało czasu, żeby gole zdążyły paść
        alert.goals_needed = k
        alert.remaining = remaining
        alert.model_over_prob = model.model_over_prob(
            s.line, goals, s.minute, s.first_half, cfg.goals_per_90)
        base = model.baseline_lambda(s.minute, s.first_half, cfg.goals_per_90)
        lam = model.implied_lambda(p_over, k)
        if base > 0 and lam is not None:
            alert.rate_ratio = lam / base
            if alert.rate_ratio >= cfg.rate_ratio_high:
                reasons.append(f"kurs wycenia {alert.rate_ratio:.1f}x normalne tempo goli "
                               f"(rynek Over {p_over:.0%} vs model {alert.model_over_prob:.0%})")
            elif alert.rate_ratio <= cfg.rate_ratio_low:
                reasons.append(f"kurs wycenia {alert.rate_ratio:.1f}x normalnego tempa goli "
                               f"(rynek Over {p_over:.0%} vs model {alert.model_over_prob:.0%})")

    if s.match_odds_matched is not None and s.total_matched > (
            cfg.volume_vs_match_odds * max(s.match_odds_matched, 1)):
        reasons.append("rynek goli ma dużo większy obrót niż 1X2")

    # Im gwałtowniejszy ruch, tym wyżej w kolejce.
    alert.score = round(delta.inflow_ratio + abs(delta.prob_move) * 10
                        + delta.money_in / cfg.spike_min_money, 2)
    return alert
