# onepiece-bot

## onepiece_checker.py
Sprawdza dostępność produktów One Piece w hurt.rebel.pl i wysyła maila.

## fixwatch – skaner podejrzanych rynków goli (Betfair Exchange)
Co 30 s pobiera z Betfair rynki goli (First Half Goals 0.5/1.5/2.5, Over/Under 0.5–4.5)
dla meczów trwających i startujących w ciągu godziny, i alarmuje, gdy:

1. **Kurs nie pasuje do wyniku i minuty**: model Poissona liczy, ile goli powinno jeszcze
   paść, i porównuje z tempem, jakie wycenia rynek. Alarm przy >= 1.7x albo <= 0.6x normy.
2. **Obrót jest duży** (domyślnie >= 5000) w lidze spoza topu (topowe ligi są pomijane).
3. **Rynek goli ma większy obrót niż 1X2** tego samego meczu.

Alert = (2) oraz (1) lub (3). Przykład ze screena (Panama, 0-0 w 9', Over 1.5 FH po 1.70):
rynek 59%, model 26% (fair ~3.85), obrót 31k.

```
pip install -r requirements.txt
cp .env.example .env      # uzupełnij BETFAIR_* i TELEGRAM_*
python -m fixwatch --demo # przykład ze screena, bez logowania
python -m fixwatch --once # jeden skan
python -m fixwatch        # 24/7
```

Wymaga konta Betfair i App Key (https://developer.betfair.com). Wynik i minutę bot bierze
z nieoficjalnego endpointu strony Betfair; jak nie odpowiada, liczy minutę z godziny startu
i działa tylko na sygnałach obrotu.
