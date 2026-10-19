"""Czujka: pilnuje, żeby cisza bota nie była nieodróżnialna od jego śmierci.

Alerty są rzadkie z założenia, więc brak wiadomości jest normalnym stanem. To znaczy, że
padnięte API (np. wygasły token BetsAPI) wygląda identycznie jak spokojny wieczór – i może
tak wyglądać tygodniami. Dlatego o awarii trzeba powiadomić wprost.

Dwa rodzaje oślepnięcia, oba tu obsłużone:
  1. krzyk – zapytanie leci wyjątkiem (token odrzucony, timeout, brak sieci),
  2. cisza – zapytania przechodzą, ale nie wracają żadne rynki. To mozliwe, bo pojedyncza
     padnięta paczka nie przerywa skanu, więc gdy padną wszystkie, dostajemy pusty wynik
     bez żadnego błędu.
"""
# Tyle skanów z rzędu musi się nie udać, zanim krzykniemy – jeden timeout to norma.
DEFAULT_FAILS_BEFORE_ALERT = 5
# Jak długo milczeć, zanim przypomnimy o trwającej awarii (żeby nie zasypać kanału).
DEFAULT_REPEAT_AFTER = 6 * 3600.0


class Watchdog:
    def __init__(self, fails_before_alert=DEFAULT_FAILS_BEFORE_ALERT,
                 repeat_after=DEFAULT_REPEAT_AFTER):
        self.fails_before_alert = fails_before_alert
        self.repeat_after = repeat_after
        self.fails = 0
        self.powiadomiono_o = None     # czas ostatniego krzyku, None = nie krzyczeliśmy

    def record(self, ok, detail, now):
        """Zwraca tekst do wysłania na Discorda albo None, gdy nie ma o czym mówić."""
        if ok:
            if self.powiadomiono_o is not None:
                przerwa = (now - self.powiadomiono_o) / 60
                self.fails = 0
                self.powiadomiono_o = None
                return ("✅ fixwatch znowu widzi rynek – dane z BetsAPI wróciły "
                        f"(awaria trwała co najmniej {przerwa:.0f} min). "
                        "Alerty znowu mogą przychodzić.")
            self.fails = 0
            return None

        self.fails += 1
        if self.fails < self.fails_before_alert:
            return None
        if self.powiadomiono_o is None:
            self.powiadomiono_o = now
            return (f"⚠️ fixwatch NIE WIDZI RYNKU – {self.fails} nieudanych skanów z rzędu.\n"
                    f"Powód: {detail}\n"
                    "Dopóki to trwa, brak alertów NIE znaczy, że nic się nie dzieje. "
                    "Sprawdź token BetsAPI (mógł wygasnąć trial) i logi: "
                    "journalctl -u fixwatch -n 50")
        if now - self.powiadomiono_o >= self.repeat_after:
            self.powiadomiono_o = now
            return (f"⚠️ fixwatch nadal nie widzi rynku ({self.fails} nieudanych skanów).\n"
                    f"Powód: {detail}")
        return None
