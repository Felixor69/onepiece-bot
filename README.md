# onepiece-bot

## onepiece_checker.py
Sprawdza dostępność produktów One Piece w hurt.rebel.pl i wysyła maila.

## fixwatch – łapie nagły napływ kasy na rynki goli (giełda Betfair)
Co pół minuty mierzy rynki goli (First Half Goals 0.5/1.5/2.5, Over/Under 0.5–4.5) trwających
meczów i alarmuje w momencie, w którym **NAGLE wpada duży hajs na jedną stronę, a kurs po tej
stronie zjeżdża**. To znaczy, że ktoś coś wie – i z tego da się zagrać od razu.

Wyzwalacz to RUCH, nie stan. Liczony między dwoma pomiarami tego samego rynku:

1. **Napływ** – w oknie wpadło co najmniej `SPIKE_MIN_MONEY` (domyślnie 10000).
2. **Skala** – ten napływ to co najmniej `SPIKE_RATIO` (domyślnie 0.3) obrotu, jaki rynek
   miał wcześniej. Mianownik ma podłogę 500, bo na rynku z obrotem 5 każda wpłata to
   tysiące procent.
3. **Ruch kursu** – implikowana szansa przesunęła się o co najmniej `SPIKE_PROB_MOVE`
   (domyślnie 0.05, czyli 5 punktów procentowych).

Do tego **kurs po stronie napływu musi wynosić co najmniej `MIN_PRICE`** (domyślnie 1.5).
Polski podatek od gier to 12% od stawki (`TAX_RATE`), więc realnie wraca `0.88 * kurs`:
kurs 1.20 to netto 1.06 (+6% z wygranej), a przy 1.14 jest się dokładnie na zero nawet
wygrywając za każdym razem. Krótkie kursy nie mają po co zawracać głowy, a alert i tak
podaje kurs netto wprost.

**Kierunek zagrania bierzemy z (3)**: rośnie szansa Over = kasa idzie na Over, więc gramy BACK
Over. To obserwacja rynku, nie wniosek z modelu – dlatego stronę znamy zawsze, także gdy
BetsAPI nie poda wyniku i minuty.

Świadomie **nie** alarmujemy od samego poziomu obrotu. Wcześniej wystarczyło, że rynek goli
ma więcej pieniędzy niż 1X2 – w małych ligach to norma, więc leciały alerty o zupełnie
normalnych rynkach (np. Over 0.5 po 1.04 przy 0-0, tempo 1.1x normy). Czysty szum.

Model Poissona został jako **kontekst** w treści alertu („rynek wycenia 2x normalne tempo
goli"). Nie jest wyzwalaczem i nie służy do grania przeciw rynkowi: to goły Poisson ze stałym
`GOALS_PER_90`, bez siły drużyn, kartek i tego, że przegrywający pod koniec się odkrywa – przy
rozjeździe z rynkiem częściej myli się model.

### Co jest w alercie
Gotowe zagranie, nie liczby: nazwa zakładu z kuponu Betfair, kurs, co musi się stać, najniższy
kurs jaki warto jeszcze wziąć, minuta zamknięcia pozycji, a pod tym „CO SIĘ WŁAŚNIE STAŁO" –
ile kasy wpadło, w ile sekund i z jakiego kursu na jaki zjechało.

Filtry kontekstowe: nie alarmujemy, gdy Over już wszedł, gdy do końca okresu zostało mniej
niż 15 minut (gole nie zdążą paść) ani gdy kurs jest krótszy niż `MIN_PRICE`. Po alercie na danym rynku milczymy `ALERT_COOLDOWN`
sekund (domyślnie 300) – ten sam napływ siedzi jeszcze w oknie historii, więc bez tego jedno
zdarzenie poszłoby kilka razy.

Historia rynków jest **w pamięci procesu**: po restarcie usługi pierwszy skan tylko zapamiętuje
stan i nie wygeneruje sygnału, bo nie ma z czym porównać.

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
python -m fixwatch --once # jeden skan (NIE wykryje ruchu – brak drugiego pomiaru)
python -m fixwatch        # 24/7
```

### Skąd dane
- **BetsAPI (domyślnie, działa z Polski):** dane z giełdy Betfair bez konta na Betfair.
  Potrzebny token z https://betsapi.com, pakiet „Betfair API” (100 USD/mies., jest
  1-dniowy trial za 1 USD). W `.env`: `DATA_SOURCE=betsapi`, `BETSAPI_TOKEN=...`.
  Skanuje mecze trwające, co 30 s (`SCAN_INTERVAL`). Jeden skan to ~1 + 2x ceil(meczów/10)
  zapytań, czyli przy kilkudziesięciu meczach ~11 – co 30 s daje ~1300/h, a limit to
  3600/h. Im częściej patrzymy, tym szybciej widzimy napływ.
- **Betfair bezpośrednio:** `DATA_SOURCE=betfair` + `BETFAIR_*`. Wymaga konta Betfair
  i App Key, czyli nie z Polski.
