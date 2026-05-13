# Nowa Energia — Prototyp harmonogramowania brygad

## Cel
Aplikacja wspiera kierownika wykonawstwa w przygotowaniu rekomendowanego harmonogramu miesięcznego prac brygad. System waliduje dane, generuje propozycję, wykrywa konflikty oraz zapisuje wynik do pliku Excel. Decyzję podejmuje użytkownik.

## Struktura
- `app.py` — interfejs Streamlit
- `scheduler_engine.py` — silnik planistyczny
- `validators.py` — walidacja danych wejściowych
- `ui_components.py` — pomocnicze komponenty UI
- `kpi.py` — obliczenia KPI
- `models.py` — typy i modele danych
- `requirements.txt` — zależności Python

## Wymagania
- Python 3.11+
- `streamlit`
- `pandas`
- `openpyxl`
- `plotly`

## Instalacja
1. Otwórz terminal w katalogu projektu.
2. Utwórz środowisko wirtualne (opcjonalnie):
   ```bash
   python -m venv .venv
   .venv\Scripts\activate
   ```
3. Zainstaluj zależności:
   ```bash
   pip install -r requirements.txt
   ```

## Uruchomienie
1. Umieść plik `planowanie_brygad_input.xlsx` w katalogu projektu lub załaduj go poprzez interfejs aplikacji.
2. W terminalu uruchom:
   ```bash
   streamlit run app.py
   ```
3. W przeglądarce wybierz plik Excel, kliknij `Uruchom planowanie`, a następnie sprawdź dane i eksport.

## Funkcjonalność
- Wczytywanie pliku Excel z wymaganymi arkuszami
- Walidacja kompletności danych i reguł podstawowych
- Generowanie rekomendowanego harmonogramu brygad
- Widok zadań niezaplanowanych i konfliktów
- Widok obciążenia brygad oraz wykres
- Proste przeplanowanie dnia z absencją i awarią
- Obliczanie KPI procesu
- Eksport wyników do `harmonogram_brygad_output.xlsx`

## Uwagi
- System generuje rekomendację, a zatwierdzenie musi wykonać użytkownik.
- Aplikacja nie korzysta z bazy danych ani zewnętrznych usług.
- Prototyp jest modularny i może być rozbudowany o role, integracje lub bardziej zaawansowany silnik planowania.
