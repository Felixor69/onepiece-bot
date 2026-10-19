# onepiece-bot

## onepiece_checker.py
Sprawdza dostępność produktów One Piece w hurt.rebel.pl i wysyła maila.

## fixwatch – skaner podejrzanych rynków goli (giełda Betfair)
Co minutę pobiera z giełdy Betfair rynki goli (First Half Goals 0.5/1.5/2.5, Over/Under 0.5–4.5)
dla trwających meczów i alarmuje, gdy:

1. **Kurs nie pasuje do wyniku i minuty**: model Poissona liczy, ile goli powinno jeszcze
   paść, i porównuje z tempem, jakie wycenia rynek. Alarm przy >= 1.7x albo <= 0.6x normy.
2. **Obrót jest duży** (domyślnie >= 5000) w lidze spoza topu (topowe ligi są pomijane).
3. **Rynek goli ma co najmniej 2x większy obrót niż 1X2** tego samego meczu.

Sygnał = (2) oraz (1) lub (3). Przykład ze screena (Panama, 0-0 w 9', Over 1.5 FH po 1.70):
rynek 59%, model 26% (fair ~3.85), obrót 31k.

**Na Discorda idzie tylko sygnał z (1)**, bo tylko on mówi, która strona jest kupowana,
czyli co właściwie zagrać. Sam duży obrót (2) i (3) bez anomalii w kursie zostaje w logu
(`journalctl -u fixwatch`) jako `Bez zagrania, nie wysyłam` – w małych ligach rynek goli
rutynowo ma więcej pieniędzy niż 1X2, więc jako powód alertu to był czysty szum.

### Co jest w alercie
Alert podaje gotowe zagranie, a nie same liczby: nazwę zakładu z kuponu Betfair, kurs,
co musi się stać, żeby wszedł, najniższy kurs jaki warto jeszcze wziąć i minutę, po
której pozycję zamykamy.

**Strategia: jedziemy Z podejrzanymi pieniędzmi.** Obstawiamy (BACK) tę stronę, którą
kupuje rynek – założenie jest takie, że ktoś zna wynik. Sygnał (1) mówi, która to strona:
tempo wyższe niż normalne = kasa na Over, niższe = kasa na Under. Gdy znamy tylko obrót
(brak wyniku/minuty), alert nie podaje strony i każe ją najpierw sprawdzić na rynku.

Świadomie **nie** grywamy przeciw rynkowi na podstawie modelu: to goły Poisson ze stałym
`GOALS_PER_90`, bez siły drużyn, kartek i tego, że przegrywający pod koniec się odkrywa.
Gdy model i rynek się nie zgadzają, to częściej model się myli – dlatego `fair` jest w
alercie tylko jako ostrzeżenie, nie jako przewaga. Betfair może też unieważnić rynek,
jeśli ustawienie meczu zostanie udowodnione.

Na serwer (Contabo) jako usługa 24/7, alerty na Discord. Jako root na serwerze:
```
bash <(curl -fsSL https://raw.githubusercontent.com/Felixor69/onepiece-bot/claude/busy-ptolemy-anm020/deploy/install.sh)
journalctl -u fixwatch -f   # logi
```
Skrypt zapyta o token BetsAPI i webhook Discorda i wyśle wiadomość testową.

Lokalnie:
```
pip install -r requirements.txt
cp .env.example .env      # uzupełnij BETSAPI_TOKEN i DISCORD_WEBHOOK_URL
python -m fixwatch --demo # przykład ze screena, bez logowania
python -m fixwatch --once # jeden skan
python -m fixwatch        # 24/7
```

### Skąd dane
- **BetsAPI (domyślnie, działa z Polski):** dane z giełdy Betfair bez konta na Betfair.
  Potrzebny token z https://betsapi.com, pakiet „Betfair API” (100 USD/mies., jest
  1-dniowy trial za 1 USD). W `.env`: `DATA_SOURCE=betsapi`, `BETSAPI_TOKEN=...`.
  Skanuje mecze trwające, co 60 s (limit 3600 zapytań/h).
- **Betfair bezpośrednio:** `DATA_SOURCE=betfair` + `BETFAIR_*`. Wymaga konta Betfair
  i App Key, czyli nie z Polski.
