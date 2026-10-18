"""Wykrywanie podejrzanych rynków goli (np. ustawiane mecze w egzotycznych ligach).

Sygnały:
  1. RATE  – kurs nie pasuje do wyniku i minuty: rynek wycenia tempo goli
             wielokrotnie wyższe (albo niższe) niż normalny mecz.
  2. VOLUME – obrót na rynku goli jest duży jak na ligę spoza topu.
  3. RATIO – rynek goli ma większy obrót niż 1X2 tego meczu (normalnie
             to 1X2 ma najwięcej pieniędzy).
Alert leci, gdy jest VOLUME i do tego RATE albo RATIO.
"""
from dataclasses import dataclass, field

from . import model


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
    volume_vs_match_odds: float = 1.0   # rynek goli > 1X2
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

    def fair_over_price(self):
        if self.model_over_prob:
            return 1 / self.model_over_prob
        return None

    def format(self):
        s = self.snapshot
        lines = [f"🚨 {s.competition}: {s.event_name}"]
        state = []
        if s.home_goals is not None:
            state.append(f"wynik {s.home_goals}-{s.away_goals}")
        if s.minute is not None:
            state.append(f"{s.minute}'")
        if state:
            lines.append(", ".join(state))
        lines.append(f"{s.market_name}: Over {s.over_price} / Under {s.under_price}, "
                     f"obrót {s.total_matched:,.0f}".replace(",", " "))
        if self.model_over_prob is not None:
            lines.append(f"Rynek: Over {self.market_over_prob:.0%} | "
                         f"model: {self.model_over_prob:.0%} (fair ~{self.fair_over_price():.2f})")
        if self.rate_ratio is not None:
            lines.append(f"Rynek wycenia {self.rate_ratio:.1f}x normalne tempo goli")
        if s.match_odds_matched:
            lines.append(f"Obrót 1X2: {s.match_odds_matched:,.0f}".replace(",", " "))
        lines.append("Powody: " + "; ".join(self.reasons))
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
        reasons.append(f"obrót {s.total_matched:,.0f} >= {cfg.min_volume:,.0f}".replace(",", " "))
        score += s.total_matched / cfg.min_volume

    # Sygnał RATE – tylko gdy znamy wynik i minutę.
    rate_hit = False
    if s.minute is not None and s.home_goals is not None:
        goals = s.home_goals + s.away_goals
        k = model.goals_needed(s.line, goals)
        if k > 0:  # jeśli Over już wszedł, rynek nie ma znaczenia
            alert.model_over_prob = model.model_over_prob(
                s.line, goals, s.minute, s.first_half, cfg.goals_per_90)
            base = model.baseline_lambda(s.minute, s.first_half, cfg.goals_per_90)
            lam = model.implied_lambda(p_over, k)
            if base > 0 and lam is not None:
                alert.rate_ratio = lam / base
                if alert.rate_ratio >= cfg.rate_ratio_high:
                    rate_hit = True
                    reasons.append(f"kurs na Over za niski: rynek {p_over:.0%} vs model "
                                   f"{alert.model_over_prob:.0%}")
                    score += alert.rate_ratio
                elif alert.rate_ratio <= cfg.rate_ratio_low:
                    rate_hit = True
                    reasons.append(f"kurs na Under za niski: rynek Over {p_over:.0%} vs model "
                                   f"{alert.model_over_prob:.0%}")
                    score += 1 / alert.rate_ratio

    ratio_hit = False
    if s.match_odds_matched is not None and s.match_odds_matched >= 0:
        if s.total_matched > cfg.volume_vs_match_odds * max(s.match_odds_matched, 1):
            ratio_hit = True
            reasons.append("rynek goli ma większy obrót niż 1X2")
            score += 1

    if volume_ok and (rate_hit or ratio_hit):
        alert.score = round(score, 2)
        return alert
    return None
