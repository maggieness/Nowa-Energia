#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
RDM Hierarchical Classifier – Nowa Energia

Klasyfikator awarii / zdarzeń RDM przygotowany do zaszycia w kodzie aplikacji.
Wersja robocza: 0.2

Założenia:
- klasyfikator jest deterministyczny i regułowy,
- klasyfikacja opiera się na drzewie klasyfikacji zapisanym w kodzie,
- słowniki, katalog awarii i mapowanie na zadania są zapisane w kodzie,
- przyszły plik Excel z awariami nie musi zawierać arkuszy słownikowych ani etykiet testowych,
- Excel wejściowy powinien zawierać przynajmniej arkusz z danymi zgłoszeń, np. 01_Dane_do_klasyfikacji,
- klasyfikator nie podejmuje decyzji operacyjnej; generuje rekomendację do wykorzystania w harmonogramowaniu.

Uruchomienie:
    python rdm_hierarchical_classifier.py --input rdm_awarie.xlsx --output rdm_klasyfikacja_output.xlsx

Wymagane biblioteki:
    pandas
    openpyxl
"""

from __future__ import annotations

import argparse
import re
import unicodedata
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

import pandas as pd


# ============================================================
# 1. Normalizacja i funkcje pomocnicze
# ============================================================

YES = {"tak", "t", "true", "1", "yes", "y"}
NO = {"nie", "n", "false", "0", "no"}
PARTIAL = {"czesciowo", "częściowo", "doraźnie", "doraznie"}
UNKNOWN = {"", "do ustalenia", "do decyzji", "brak danych", "bd", "n/a", "na", "none", "null"}


def strip_accents(value: Any) -> str:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return ""
    text = str(value)
    normalized = unicodedata.normalize("NFKD", text)
    return "".join(ch for ch in normalized if not unicodedata.combining(ch))


def norm(value: Any) -> str:
    text = strip_accents(value).lower().strip()
    text = re.sub(r"\s+", " ", text)
    return text


def norm_key(value: Any) -> str:
    text = norm(value)
    text = re.sub(r"[^a-z0-9]+", "_", text)
    return text.strip("_")


def normalize_columns(df: pd.DataFrame) -> pd.DataFrame:
    copy = df.copy()
    copy.columns = [norm_key(c) for c in copy.columns]
    return copy


def bool_value(value: Any) -> Optional[bool]:
    text = norm(value)
    if text in YES:
        return True
    if text in NO:
        return False
    if text in PARTIAL or text in UNKNOWN:
        return None
    return None


def is_partial(value: Any) -> bool:
    return norm(value) in PARTIAL


def concat_text(*values: Any) -> str:
    return " ".join(norm(v) for v in values if norm(v))


def contains_any(text: str, keywords: Iterable[str]) -> bool:
    t = norm(text)
    return any(norm(k) in t for k in keywords)


def score_keywords(text: str, keywords: Iterable[str]) -> int:
    t = norm(text)
    score = 0
    for kw in keywords:
        if norm(kw) in t:
            score += 1
    return score


def value(row: pd.Series, field: str, default: Any = "") -> Any:
    if field in row.index and not pd.isna(row[field]):
        return row[field]
    return default


# ============================================================
# 2. Drzewo klasyfikacji i katalog typów awarii
# ============================================================

@dataclass(frozen=True)
class IncidentClass:
    code: str
    level_1: str
    level_2: str
    default_priority: str
    normally_for_schedule: bool
    keywords: Tuple[str, ...]
    exclusion_reason: str = ""


# Drzewo klasyfikacji zapisane w kodzie.
# W przyszłym Excelu nie musi być arkusza 03_Katalog_awarii.
CLASSIFICATION_TREE: Dict[str, IncidentClass] = {
    "AW-001": IncidentClass(
        "AW-001", "Bezpieczeństwo i bezpośrednie zagrożenie", "Zerwany lub uszkodzony przewód",
        "P1", False,
        ("zerwany przewod", "urwany przewod", "zwisajacy przewod", "przewod na ziemi", "lezy przewod"),
        "Zdarzenie P1 powinno być obsługiwane poza standardowym harmonogramem."
    ),
    "AW-002": IncidentClass(
        "AW-002", "Bezpieczeństwo i bezpośrednie zagrożenie", "Iskrzenie, łuk, dymienie, podejrzenie pożaru",
        "P1", False,
        ("iskrzenie", "iskry", "luk elektryczny", "dym", "dymienie", "pozar", "spalenizna"),
        "Zdarzenie P1 powinno być obsługiwane poza standardowym harmonogramem."
    ),
    "AW-003": IncidentClass(
        "AW-003", "Ciągłość zasilania", "Brak zasilania większego obszaru",
        "P2", True,
        ("brak zasilania wielu", "wielu odbiorcow", "cale osiedle", "cala ulica", "czesc miejscowosci", "wiekszy obszar")
    ),
    "AW-004": IncidentClass(
        "AW-004", "Ciągłość zasilania", "Brak zasilania pojedynczego odbiorcy",
        "P3", True,
        ("pojedynczy odbiorca", "jeden odbiorca", "jedno gospodarstwo", "jeden budynek", "brak zasilania u odbiorcy", "brak pradu w domu")
    ),
    "AW-005": IncidentClass(
        "AW-005", "Uszkodzenie sieci SN", "Uszkodzenie linii napowietrznej SN",
        "P2", True,
        ("linia napowietrzna sn", "linia sn", "przewod sn", "izolator sn", "slup sn", "osprzet linii sn")
    ),
    "AW-006": IncidentClass(
        "AW-006", "Uszkodzenie sieci nn", "Uszkodzenie linii napowietrznej nn",
        "P3", True,
        ("linia napowietrzna nn", "linia nn", "przewod nn", "slup nn", "przylacze napowietrzne", "osprzet linii nn")
    ),
    "AW-007": IncidentClass(
        "AW-007", "Uszkodzenie sieci SN", "Uszkodzenie linii kablowej SN",
        "P2", True,
        ("linia kablowa sn", "kabel sn", "mufa sn", "glowica sn", "uszkodzenie kabla sn", "diagnostyka kabla sn")
    ),
    "AW-008": IncidentClass(
        "AW-008", "Uszkodzenie sieci nn", "Uszkodzenie linii kablowej nn",
        "P3", True,
        ("linia kablowa nn", "kabel nn", "mufa nn", "uszkodzenie kabla nn", "przylacze kablowe", "obwod kablowy nn")
    ),
    "AW-009": IncidentClass(
        "AW-009", "Stacje i urządzenia", "Awaria stacji SN/nn",
        "P2", True,
        ("stacja sn/nn", "stacja", "transformator", "rozdzielnica", "aparatura stacji", "stacja transformatorowa")
    ),
    "AW-010": IncidentClass(
        "AW-010", "Złącza, szafki i rozdzielnie", "Uszkodzenie złącza, szafki lub rozdzielni",
        "P3", True,
        ("zlacze", "szafka", "rozdzielnia", "otwarta szafka", "drzwiczki", "zamek złącza", "zamek zlacza", "obudowa zlacza")
    ),
    "AW-011": IncidentClass(
        "AW-011", "Automatyka i zabezpieczenia", "Zadziałanie zabezpieczeń / automatyki",
        "P2", True,
        ("zabezpieczenie", "zabezpieczen", "automatyka", "lacznik", "wylacznik", "nie mozna zalaczyc", "zadziałanie zabezpieczen", "zadzialanie zabezpieczen")
    ),
    "AW-012": IncidentClass(
        "AW-012", "Jakość zasilania", "Nieprawidłowe parametry zasilania",
        "P3", True,
        ("niskie napiecie", "wysokie napiecie", "migotanie", "mruganie", "spadki napiecia", "zaniki napiecia", "asymetria")
    ),
    "AW-013": IncidentClass(
        "AW-013", "Roślinność i otoczenie sieci", "Drzewo lub gałęzie na linii",
        "P2", True,
        ("drzewo na linii", "galezie na linii", "galaz", "konar", "wycinka", "drzewo dotyka", "roslinnosc", "krzewy pod linia")
    ),
    "AW-014": IncidentClass(
        "AW-014", "Obce obiekty na sieci", "Obcy przedmiot na sieci",
        "P2", True,
        ("obcy przedmiot", "baner", "folia", "zwierze", "ptak", "przedmiot na przewodach")
    ),
    "AW-015": IncidentClass(
        "AW-015", "Zdarzenia pogodowe", "Uszkodzenie po zdarzeniu pogodowym",
        "P2", True,
        ("burza", "wichura", "wiatr", "oblodzenie", "snieg", "podtopienie", "po wichurze", "po burzy")
    ),
    "AW-016": IncidentClass(
        "AW-016", "Uszkodzenia przez osoby trzecie", "Uszkodzenie mechaniczne przez osoby trzecie",
        "P2", True,
        ("koparka", "roboty ziemne", "samochod uderzyl", "uszkodzenie mechaniczne", "osoba trzecia", "przerwany kabel podczas prac")
    ),
    "AW-017": IncidentClass(
        "AW-017", "Zgłoszenia do weryfikacji", "Podejrzenie zagrożenia bez potwierdzenia awarii",
        "P4", False,
        ("podejrzenie", "nie potwierdzono", "do sprawdzenia", "bez potwierdzenia", "nie stwierdzono awarii")
    ),
    "AW-018": IncidentClass(
        "AW-018", "Zgłoszenia zamykane po interwencji", "Awaria usunięta przez pogotowie bez dalszej naprawy",
        "P4", False,
        ("usunieto na miejscu", "usuniete przez pogotowie", "bez dalszej naprawy", "nie wymaga dalszych prac", "brak dalszej naprawy")
    ),
    "AW-019": IncidentClass(
        "AW-019", "Zgłoszenia wymagające dalszej pracy", "Awaria zabezpieczona tymczasowo",
        "P2", True,
        ("zabezpieczono tymczasowo", "naprawa docelowa", "wymaga dalszej naprawy", "tymczasowo przywrocono", "zabezpieczenie tymczasowe")
    ),
    "AW-020": IncidentClass(
        "AW-020", "Zgłoszenia niewymagające obsługi", "Zdarzenie błędne / duplikat",
        "P4", False,
        ("duplikat", "bledne zgloszenie", "powtorzone", "anulowane", "dotyczy istniejacego zgloszenia")
    ),
}


# Kolejność rozstrzygania remisów. Bardziej specyficzne klasy mają pierwszeństwo.
CLASSIFICATION_ORDER = [
    "AW-020", "AW-018",
    "AW-013", "AW-016", "AW-015", "AW-014",
    "AW-009", "AW-010", "AW-011",
    "AW-007", "AW-008", "AW-005", "AW-006",
    "AW-012", "AW-003", "AW-004",
    "AW-001", "AW-002",
    "AW-019", "AW-017",
]


PRIORITY_DICT = {
    "P1": "Krytyczny – poza standardowym harmonogramem, tryb awaryjny",
    "P2": "Wysoki – pilna naprawa albo zadanie o wysokiej ważności operacyjnej",
    "P3": "Średni – zadanie do zaplanowania w harmonogramie",
    "P4": "Niski – brak dalszej pracy, obserwacja, duplikat albo zamknięcie",
}


# Mapowanie typu awarii na dane wymagane przez harmonogram.
# W przyszłym Excelu nie musi być arkusza z tymi wartościami – są przechowywane w kodzie.
TASK_MAPPING: Dict[str, Dict[str, Any]] = {
    "AW-003": {"tryb": "Pilna naprawa", "typ_zadania": "Naprawa po braku zasilania większego obszaru", "id_typu_zadania": "TZ-ZASIL-OBSZ-001", "jednostka": "szt.", "ilosc": 1, "pracochlonnosc_h": 4, "kompetencje": "SN; nn; diagnostyka", "min_osob": 2, "min_brygad": 1, "dzielone": "Nie", "przesuwalne": "Nie"},
    "AW-004": {"tryb": "Planowa naprawa / kontrola", "typ_zadania": "Naprawa przyłącza / kontrola zasilania", "id_typu_zadania": "TZ-NN-PRZ-001", "jednostka": "szt.", "ilosc": 1, "pracochlonnosc_h": 2, "kompetencje": "nn; przyłącza", "min_osob": 2, "min_brygad": 1, "dzielone": "Nie", "przesuwalne": "Tak"},
    "AW-005": {"tryb": "Pilna naprawa", "typ_zadania": "Naprawa osprzętu linii SN", "id_typu_zadania": "TZ-SN-LN-001", "jednostka": "szt.", "ilosc": 1, "pracochlonnosc_h": 4, "kompetencje": "SN; praca na wysokości", "min_osob": 2, "min_brygad": 1, "dzielone": "Nie", "przesuwalne": "Nie"},
    "AW-006": {"tryb": "Planowa naprawa / kontrola", "typ_zadania": "Naprawa osprzętu linii nn", "id_typu_zadania": "TZ-NN-LN-001", "jednostka": "szt.", "ilosc": 1, "pracochlonnosc_h": 3, "kompetencje": "nn; praca na wysokości", "min_osob": 2, "min_brygad": 1, "dzielone": "Nie", "przesuwalne": "Tak"},
    "AW-007": {"tryb": "Pilna naprawa", "typ_zadania": "Diagnostyka i naprawa kabla SN", "id_typu_zadania": "TZ-SN-KAB-001", "jednostka": "szt.", "ilosc": 1, "pracochlonnosc_h": 6, "kompetencje": "SN; prace kablowe; pomiary", "min_osob": 2, "min_brygad": 1, "dzielone": "Tak", "przesuwalne": "Nie"},
    "AW-008": {"tryb": "Planowa naprawa / kontrola", "typ_zadania": "Naprawa kabla nn", "id_typu_zadania": "TZ-NN-KAB-001", "jednostka": "szt.", "ilosc": 1, "pracochlonnosc_h": 4, "kompetencje": "nn; prace kablowe", "min_osob": 2, "min_brygad": 1, "dzielone": "Tak", "przesuwalne": "Tak"},
    "AW-009": {"tryb": "Pilna naprawa", "typ_zadania": "Kontrola / naprawa stacji SN/nn", "id_typu_zadania": "TZ-ST-CTRL-001", "jednostka": "szt.", "ilosc": 1, "pracochlonnosc_h": 4, "kompetencje": "SN; stacje; pomiary", "min_osob": 2, "min_brygad": 1, "dzielone": "Nie", "przesuwalne": "Nie"},
    "AW-010": {"tryb": "Planowa naprawa / kontrola", "typ_zadania": "Naprawa złącza / szafki", "id_typu_zadania": "TZ-NN-ZK-001", "jednostka": "szt.", "ilosc": 1, "pracochlonnosc_h": 2.5, "kompetencje": "nn; złącza", "min_osob": 2, "min_brygad": 1, "dzielone": "Nie", "przesuwalne": "Tak"},
    "AW-011": {"tryb": "Pilna naprawa", "typ_zadania": "Przegląd automatyki / zabezpieczeń", "id_typu_zadania": "TZ-AUT-001", "jednostka": "szt.", "ilosc": 1, "pracochlonnosc_h": 3, "kompetencje": "SN; automatyka", "min_osob": 2, "min_brygad": 1, "dzielone": "Nie", "przesuwalne": "Tak"},
    "AW-012": {"tryb": "Planowa naprawa / kontrola", "typ_zadania": "Pomiary parametrów zasilania", "id_typu_zadania": "TZ-POM-NN-001", "jednostka": "szt.", "ilosc": 1, "pracochlonnosc_h": 2, "kompetencje": "nn; pomiary", "min_osob": 2, "min_brygad": 1, "dzielone": "Tak", "przesuwalne": "Tak"},
    "AW-013": {"tryb": "Pilna naprawa", "typ_zadania": "Wycinka / usunięcie gałęzi", "id_typu_zadania": "TZ-WYC-001", "jednostka": "szt.", "ilosc": 1, "pracochlonnosc_h": 4, "kompetencje": "wycinka; praca na wysokości", "min_osob": 2, "min_brygad": 1, "dzielone": "Tak", "przesuwalne": "Nie"},
    "AW-014": {"tryb": "Pilna naprawa", "typ_zadania": "Usunięcie obcego przedmiotu", "id_typu_zadania": "TZ-OBCE-001", "jednostka": "szt.", "ilosc": 1, "pracochlonnosc_h": 2, "kompetencje": "SN; praca na wysokości", "min_osob": 2, "min_brygad": 1, "dzielone": "Nie", "przesuwalne": "Tak"},
    "AW-015": {"tryb": "Pilna naprawa", "typ_zadania": "Oględziny po zdarzeniu pogodowym", "id_typu_zadania": "TZ-OGL-001", "jednostka": "km", "ilosc": 2, "pracochlonnosc_h": 3, "kompetencje": "SN; oględziny", "min_osob": 2, "min_brygad": 1, "dzielone": "Tak", "przesuwalne": "Tak"},
    "AW-016": {"tryb": "Pilna naprawa", "typ_zadania": "Naprawa uszkodzenia po ingerencji zewnętrznej", "id_typu_zadania": "TZ-MECH-001", "jednostka": "szt.", "ilosc": 1, "pracochlonnosc_h": 5, "kompetencje": "prace kablowe; nn", "min_osob": 2, "min_brygad": 1, "dzielone": "Tak", "przesuwalne": "Nie"},
    "AW-019": {"tryb": "Pilna naprawa", "typ_zadania": "Naprawa docelowa po zabezpieczeniu tymczasowym", "id_typu_zadania": "TZ-NAPR-DOC-001", "jednostka": "szt.", "ilosc": 1, "pracochlonnosc_h": 5, "kompetencje": "SN; stacje; pomiary", "min_osob": 2, "min_brygad": 1, "dzielone": "Nie", "przesuwalne": "Nie"},
}


# ============================================================
# 3. Klasyfikacja typu awarii
# ============================================================

def build_text(row: pd.Series) -> str:
    return concat_text(
        row.get("rodzaj_obiektu", ""),
        row.get("poziom_napiecia", ""),
        row.get("obszar_infrastruktury", ""),
        row.get("opis_zgloszenia_pierwotny", ""),
        row.get("opis_objawow", ""),
        row.get("zakres_oddzialywania", ""),
        row.get("wynik_interwencji_pogotowia", ""),
        row.get("rekomendacja_dyzurnego_rdm", ""),
    )


def classify_incident_type(row: pd.Series) -> Tuple[IncidentClass, str, str]:
    text = build_text(row)

    # Reguły wynikowe – duplikat i awaria usunięta bez naprawy powinny być stabilnie rozpoznane.
    awaria_usunieta = norm(row.get("czy_awaria_usunieta", ""))
    wymaga_naprawy = bool_value(row.get("czy_wymaga_dalszej_naprawy", ""))
    wynik = norm(row.get("wynik_interwencji_pogotowia", ""))

    if contains_any(text, ("duplikat", "powtorzone", "bledne zgloszenie", "anulowane")):
        return CLASSIFICATION_TREE["AW-020"], "wysoka", "W opisie lub rekomendacji wskazano duplikat, błąd albo anulowanie."

    if contains_any(text, ("obcy przedmiot", "baner", "folia", "przedmiot na przewodach", "przedmiot na linii")):
        return CLASSIFICATION_TREE["AW-014"], "wysoka", "W opisie wskazano obcy przedmiot na sieci."

    if awaria_usunieta == "tak" and wymaga_naprawy is False:
        return CLASSIFICATION_TREE["AW-018"], "wysoka", "Awaria została usunięta i nie wymaga dalszej naprawy."

    # P1 – jeśli jednak trafi do pliku, klasyfikujemy, ale wyłączamy z harmonogramu.
    if bool_value(row.get("czy_zagrozenie_zycia_lub_zdrowia", "")) is True:
        if contains_any(text, CLASSIFICATION_TREE["AW-002"].keywords):
            return CLASSIFICATION_TREE["AW-002"], "wysoka", "Wskazano zagrożenie życia oraz symptomy iskrzenia/pożaru."
        if contains_any(text, CLASSIFICATION_TREE["AW-001"].keywords):
            return CLASSIFICATION_TREE["AW-001"], "wysoka", "Wskazano zagrożenie życia oraz zerwany/uszkodzony przewód."
        return CLASSIFICATION_TREE["AW-001"], "średnia", "Wskazano zagrożenie życia; zdarzenie wyłączone ze standardowego harmonogramu."

    obszar = norm(row.get("obszar_infrastruktury", ""))
    rodzaj = norm(row.get("rodzaj_obiektu", ""))
    napiecie = norm(row.get("poziom_napiecia", ""))

    if contains_any(text, ("naprawa docelowa", "wymaga naprawy docelowej", "tymczasowo przywrocono", "pozostawilo informacje o uszkodzeniu")):
        return CLASSIFICATION_TREE["AW-019"], "wysoka", "Zdarzenie opisano jako zabezpieczone tymczasowo z potrzebą naprawy docelowej."

    if contains_any(text, ("automatyka", "telemechanika", "zdalnego sterowania", "brak potwierdzenia stanu", "lacznik")):
        return CLASSIFICATION_TREE["AW-011"], "wysoka", "Opis wskazuje na automatykę, telemechanikę albo zadziałanie zabezpieczeń."

    if contains_any(text, ("galaz", "galezie", "drzewo", "konar", "wycinka")):
        return CLASSIFICATION_TREE["AW-013"], "wysoka", "Opis wskazuje na roślinność w pobliżu linii."

    if ("sn" in napiecie or "sn" in obszar or "sn" in rodzaj) and contains_any(text, ("ogranicznik przepiec", "osprzet linii sn")):
        return CLASSIFICATION_TREE["AW-005"], "wysoka", "Opis wskazuje na uszkodzenie osprzętu linii SN."

    if contains_any(text, ("burza", "wichura", "wiatr", "oblodzenie", "po wichurze", "po burzy")):
        return CLASSIFICATION_TREE["AW-015"], "wysoka", "Opis wskazuje na zdarzenie pogodowe."

    if contains_any(text, ("roboty drogowe", "roboty ziemne", "koparka", "naruszyly oslone kabla", "osoba trzecia", "przez osoby trzecie", "uszkodzenie mechaniczne")) and "kabl" in text:
        return CLASSIFICATION_TREE["AW-016"], "wysoka", "Opis wskazuje na uszkodzenie mechaniczne przez osoby trzecie."

    if ("nn" in napiecie or "nn" in obszar or "nn" in rodzaj) and contains_any(text, ("kabel nn", "kabla nn", "linia kablowa nn", "przylacze kablowe", "pracach ziemnych")):
        return CLASSIFICATION_TREE["AW-008"], "wysoka", "Opis wskazuje na uszkodzenie kabla nn lub przyłącza kablowego."

    if contains_any(text, ("pojedynczy odbiorca", "jeden odbiorca", "brak zasilania w domu", "zasilanie u sasiadow", "przylacze")):
        return CLASSIFICATION_TREE["AW-004"], "wysoka", "Opis wskazuje na brak zasilania pojedynczego odbiorcy lub przyłącza."

    if contains_any(text, ("roboty drogowe", "roboty ziemne", "koparka", "naruszyly oslone kabla", "osoba trzecia", "uszkodzenie mechaniczne")) and "kabl" in text:
        return CLASSIFICATION_TREE["AW-016"], "wysoka", "Opis wskazuje na uszkodzenie mechaniczne przez osoby trzecie."

    if ("nn" in napiecie or "nn" in obszar or "nn" in rodzaj) and contains_any(text, ("slup", "uchwyt", "linia napowietrzna nn", "przewod obnizony", "osprzet linii nn")):
        return CLASSIFICATION_TREE["AW-006"], "wysoka", "Opis wskazuje na uszkodzenie linii napowietrznej nn."

    if ("sn" in napiecie or "sn" in obszar or "sn" in rodzaj) and contains_any(text, ("kabel sn", "kablu sn", "linia kablowa sn", "diagnostyka kabla sn", "lokalizacja i naprawa kabla sn")):
        return CLASSIFICATION_TREE["AW-007"], "wysoka", "Opis wskazuje na uszkodzenie lub diagnostykę kabla SN."

    # Scoring po drzewie klasyfikacji.
    scored: List[Tuple[int, int, str]] = []
    order_index = {code: idx for idx, code in enumerate(CLASSIFICATION_ORDER)}

    for code, incident in CLASSIFICATION_TREE.items():
        score = score_keywords(text, incident.keywords)

        # Dodatkowe wagi z pól strukturalnych.
        obszar = norm(row.get("obszar_infrastruktury", ""))
        rodzaj = norm(row.get("rodzaj_obiektu", ""))
        napiecie = norm(row.get("poziom_napiecia", ""))

        if code == "AW-009" and ("stacje" in obszar or "stacja" in rodzaj):
            score += 2
        if code in {"AW-005", "AW-007"} and "sn" in napiecie:
            score += 1
        if code in {"AW-006", "AW-008", "AW-010", "AW-012"} and "nn" in napiecie:
            score += 1
        if code == "AW-013" and contains_any(text, ("galaz", "galezie", "drzewo", "konar", "wycinka")):
            score += 3
        if code == "AW-015" and contains_any(text, ("burza", "wichura", "wiatr", "oblodzenie", "po wichurze")):
            score += 2
        if code == "AW-016" and contains_any(text, ("koparka", "samochod", "roboty ziemne", "mechaniczne")):
            score += 3

        if score > 0:
            scored.append((score, order_index.get(code, 999), code))

    if scored:
        scored.sort(key=lambda x: (-x[0], x[1]))
        best_code = scored[0][2]
        confidence = "wysoka" if scored[0][0] >= 3 else "średnia"
        return CLASSIFICATION_TREE[best_code], confidence, f"Najwyższe dopasowanie regułowe dla {best_code}; wynik punktowy {scored[0][0]}."

    # Fallback po wyniku interwencji.
    if "zabezpiecz" in wynik and wymaga_naprawy is True:
        return CLASSIFICATION_TREE["AW-019"], "średnia", "Brak specyficznego typu; wynik wskazuje zabezpieczenie tymczasowe i dalszą naprawę."

    return CLASSIFICATION_TREE["AW-017"], "niska", "Brak jednoznacznego dopasowania; zgłoszenie wymaga weryfikacji."


# ============================================================
# 4. Priorytet, kwalifikacja i mapowanie do harmonogramu
# ============================================================

def recommend_priority(row: pd.Series, incident: IncidentClass) -> Tuple[str, str]:
    if bool_value(row.get("czy_zagrozenie_zycia_lub_zdrowia", "")) is True:
        return "P1", "Zdarzenie oznaczone jako zagrożenie życia lub zdrowia."

    if incident.code in {"AW-001", "AW-002"}:
        return "P1", "Typ awarii należy do zdarzeń bezpośredniego zagrożenia."

    if incident.code in {"AW-018", "AW-020"}:
        return "P4", "Zdarzenie nie wymaga dalszej pracy planistycznej."

    wymaga_naprawy = bool_value(row.get("czy_wymaga_dalszej_naprawy", ""))
    if incident.code == "AW-014" and wymaga_naprawy is False:
        return "P4", "Obcy przedmiot został usunięty albo nie wymaga dalszej pracy."

    return incident.default_priority, f"Priorytet domyślny dla typu {incident.code}."


def qualify_for_schedule(row: pd.Series, incident: IncidentClass, priority: str) -> Tuple[str, str, str, str]:
    """
    Zwraca:
    status_kwalifikacji, powod_kwalifikacji, czy_utworzyc_zadanie_planistyczne, status_raportu
    """
    if priority == "P1" or bool_value(row.get("czy_zagrozenie_zycia_lub_zdrowia", "")) is True:
        return (
            "Nie kwalifikuje się do standardowego harmonogramu",
            "Zdarzenie P1 lub zagrożenie życia/zdrowia powinno być obsługiwane poza standardowym harmonogramem.",
            "Nie",
            "Odrzucone z importu",
        )

    wymaga_naprawy = bool_value(row.get("czy_wymaga_dalszej_naprawy", ""))
    awaria_usunieta_text = norm(row.get("czy_awaria_usunieta", ""))
    wynik = norm(row.get("wynik_interwencji_pogotowia", ""))

    if incident.code in {"AW-018", "AW-020"}:
        return (
            "Nie kwalifikuje się do harmonogramu",
            "Awaria usunięta albo zgłoszenie nie wymaga dalszej pracy.",
            "Nie",
            "Odrzucone z importu",
        )

    if wymaga_naprawy is True:
        return (
            "Do harmonogramu",
            "Zdarzenie wymaga dalszej naprawy, kontroli lub pracy docelowej.",
            "Tak",
            "Gotowe do importu",
        )

    if "zabezpiecz" in wynik or awaria_usunieta_text == "czesciowo":
        return (
            "Do harmonogramu",
            "Zdarzenie zostało zabezpieczone albo usunięte częściowo i wymaga oceny pracy docelowej.",
            "Tak",
            "Gotowe do importu",
        )

    if wymaga_naprawy is None:
        return (
            "Do decyzji",
            "Brak jednoznacznej informacji, czy wymagana jest dalsza naprawa.",
            "Nie",
            "Do decyzji",
        )

    return (
        "Nie kwalifikuje się do harmonogramu",
        "Brak potrzeby dalszej naprawy.",
        "Nie",
        "Odrzucone z importu",
    )


def requires_manager_decision(row: pd.Series, priority: str, status_kwalifikacji: str) -> str:
    if priority == "P1":
        return "Tak"
    if bool_value(row.get("czy_wymaga_wylaczenia", "")) is True:
        return "Tak"
    if bool_value(row.get("czy_termin_sztywny", "")) is True:
        return "Tak"
    if status_kwalifikacji == "Do decyzji":
        return "Tak"
    return "Nie"


def planning_fields(row: pd.Series, incident: IncidentClass, create_task: str) -> Dict[str, Any]:
    if create_task != "Tak":
        return {
            "rekomendowany_tryb_obslugi": "Brak dalszej pracy",
            "rekomendowany_typ_zadania": "Brak zadania",
            "id_typu_zadania": None,
            "jednostka": None,
            "ilosc": 0,
            "szacowana_pracochlonnosc_h": None,
            "wymagane_kompetencje": None,
            "minimalna_liczba_osob": None,
            "minimalna_liczba_brygad": None,
            "czy_moze_byc_dzielone": None,
            "czy_moze_byc_przesuniete": None,
        }

    mapping = TASK_MAPPING.get(incident.code, TASK_MAPPING.get("AW-019"))
    return {
        "rekomendowany_tryb_obslugi": mapping["tryb"],
        "rekomendowany_typ_zadania": mapping["typ_zadania"],
        "id_typu_zadania": mapping["id_typu_zadania"],
        "jednostka": mapping["jednostka"],
        "ilosc": mapping["ilosc"],
        "szacowana_pracochlonnosc_h": mapping["pracochlonnosc_h"],
        "wymagane_kompetencje": mapping["kompetencje"],
        "minimalna_liczba_osob": mapping["min_osob"],
        "minimalna_liczba_brygad": mapping["min_brygad"],
        "czy_moze_byc_dzielone": mapping["dzielone"],
        "czy_moze_byc_przesuniete": "Nie" if bool_value(row.get("czy_wymaga_wylaczenia", "")) is True else mapping["przesuwalne"],
    }


def validate_row(row: pd.Series, create_task: str, priority: str) -> Tuple[str, str]:
    warnings: List[str] = []
    errors: List[str] = []

    required_for_classification = [
        "id_zgloszenia_rdm",
        "miasto",
        "ulica",
        "rodzaj_obiektu",
        "poziom_napiecia",
        "opis_zgloszenia_pierwotny",
        "opis_objawow",
        "wynik_interwencji_pogotowia",
        "czy_wymaga_dalszej_naprawy",
        "czy_zagrozenie_zycia_lub_zdrowia",
    ]

    for col in required_for_classification:
        if col not in row.index or pd.isna(row[col]) or str(row[col]).strip() == "":
            errors.append(f"Brak pola wymaganego do klasyfikacji: {col}")

    if create_task == "Tak":
        for col in ["czy_wymaga_wylaczenia", "czy_termin_sztywny"]:
            if col not in row.index or pd.isna(row[col]) or str(row[col]).strip() == "":
                warnings.append(f"Brak pola wymaganego do harmonogramowania: {col}")

        if bool_value(row.get("czy_termin_sztywny", "")) is True:
            if "data_wymagana" not in row.index or pd.isna(row["data_wymagana"]) or str(row["data_wymagana"]).strip() == "":
                errors.append("Termin sztywny = Tak, ale brak data_wymagana.")

    if priority == "P1":
        warnings.append("Rekord P1 nie powinien trafiać do standardowego harmonogramu prac.")

    return " | ".join(warnings), " | ".join(errors)


# ============================================================
# 5. Klasyfikacja rekordu i pliku
# ============================================================

def classify_row(row: pd.Series) -> Dict[str, Any]:
    incident, confidence, reason_type = classify_incident_type(row)
    priority, reason_priority = recommend_priority(row, incident)
    status_kwalifikacji, powod_kwalifikacji, create_task, status_raportu = qualify_for_schedule(row, incident, priority)
    manager_decision = requires_manager_decision(row, priority, status_kwalifikacji)
    plan = planning_fields(row, incident, create_task)
    warnings, errors = validate_row(row, create_task, priority)

    czy_p1_wykluczone = "Tak" if priority == "P1" else "Nie"

    result = {
        "id_zgloszenia_rdm": row.get("id_zgloszenia_rdm", None),
        "kod_typu_awarii": incident.code,
        "nazwa_typu_awarii": incident.level_2,
        "kategoria_awarii": incident.level_1,
        "priorytet_operacyjny": priority,
        "opis_priorytetu": PRIORITY_DICT.get(priority, ""),
        "status_kwalifikacji": status_kwalifikacji,
        "powod_kwalifikacji": powod_kwalifikacji,
        "czy_utworzyc_zadanie_planistyczne": create_task,
        "czy_p1_wykluczone_z_harmonogramu": czy_p1_wykluczone,
        "czy_wymaga_decyzji_kierownika": manager_decision,
        "status_raportu": status_raportu,
        "poziom_pewnosci_klasyfikacji": confidence,
        "uzasadnienie_klasyfikacji": f"{reason_type} {reason_priority}",
        "ostrzezenia": warnings,
        "bledy_krytyczne": errors,
    }
    result.update(plan)
    return result


def classify_dataframe(df: pd.DataFrame) -> pd.DataFrame:
    df_norm = normalize_columns(df)
    results = pd.DataFrame([classify_row(row) for _, row in df_norm.iterrows()])

    # Dołączamy oryginalne dane po lewej stronie, ale unikamy duplikatu id.
    left = df_norm.copy()
    combined = pd.concat([left.reset_index(drop=True), results.reset_index(drop=True).add_prefix("wynik_")], axis=1)
    return combined


def read_input(path: Path) -> Tuple[pd.DataFrame, Optional[pd.DataFrame]]:
    if path.suffix.lower() in {".xlsx", ".xlsm", ".xls"}:
        xls = pd.ExcelFile(path)
        if "01_Dane_do_klasyfikacji" in xls.sheet_names:
            df = pd.read_excel(path, sheet_name="01_Dane_do_klasyfikacji")
        else:
            df = pd.read_excel(path, sheet_name=xls.sheet_names[0])

        labels = None
        if "02_Etykiety_testowe" in xls.sheet_names:
            labels = pd.read_excel(path, sheet_name="02_Etykiety_testowe")
        return df, labels

    if path.suffix.lower() == ".csv":
        return pd.read_csv(path, sep=None, engine="python"), None

    raise ValueError("Obsługiwane formaty: .xlsx, .xlsm, .xls, .csv")


def build_tree_sheet() -> pd.DataFrame:
    return pd.DataFrame([
        {
            "kod_typu_awarii": c.code,
            "poziom_1": c.level_1,
            "poziom_2": c.level_2,
            "domyslny_priorytet": c.default_priority,
            "czy_zwykle_do_harmonogramu": "Tak" if c.normally_for_schedule else "Nie",
            "slowa_kluczowe": "; ".join(c.keywords),
            "powod_wykluczenia": c.exclusion_reason,
        }
        for c in CLASSIFICATION_TREE.values()
    ])


def build_task_mapping_sheet() -> pd.DataFrame:
    rows = []
    for code, mapping in TASK_MAPPING.items():
        rows.append({"kod_typu_awarii": code, **mapping})
    return pd.DataFrame(rows)


def compare_with_test_labels(classified: pd.DataFrame, labels: Optional[pd.DataFrame]) -> Optional[pd.DataFrame]:
    if labels is None:
        return None

    labels_norm = normalize_columns(labels)
    base = classified.copy()

    if "id_zgloszenia_rdm" not in labels_norm.columns:
        return None

    merged = base.merge(labels_norm, how="left", left_on="id_zgloszenia_rdm", right_on="id_zgloszenia_rdm", suffixes=("", "_test"))

    checks = [
        ("kod_typu_awarii", "kod_typu_awarii_oczekiwany"),
        ("priorytet_operacyjny", "priorytet_operacyjny_oczekiwany"),
        ("status_kwalifikacji", "status_kwalifikacji_oczekiwany"),
        ("czy_utworzyc_zadanie_planistyczne", "czy_utworzyc_zadanie_planistyczne"),
    ]

    out = []
    for _, row in merged.iterrows():
        record = {"id_zgloszenia_rdm": row.get("id_zgloszenia_rdm")}
        for actual_col, expected_col in checks:
            actual = row.get(f"wynik_{actual_col}") if f"wynik_{actual_col}" in row.index else row.get(actual_col)
            expected = row.get(expected_col)
            record[f"{actual_col}_actual"] = actual
            record[f"{actual_col}_expected"] = expected
            record[f"{actual_col}_ok"] = str(actual) == str(expected)
        out.append(record)

    return pd.DataFrame(out)


def classify_file(input_path: str, output_path: str) -> pd.DataFrame:
    input_path = Path(input_path)
    output_path = Path(output_path)

    df, labels = read_input(input_path)
    classified = classify_dataframe(df)
    eval_df = compare_with_test_labels(classified, labels)

    summary = pd.DataFrame([
        {"metryka": "liczba_rekordow", "wartosc": len(classified)},
        {"metryka": "do_harmonogramu", "wartosc": int((classified["wynik_czy_utworzyc_zadanie_planistyczne"] == "Tak").sum())},
        {"metryka": "odrzucone_z_importu", "wartosc": int((classified["wynik_status_raportu"] == "Odrzucone z importu").sum())},
        {"metryka": "do_decyzji_lub_bledy", "wartosc": int((classified["wynik_status_raportu"] == "Do decyzji").sum())},
        {"metryka": "p1_wylaczone", "wartosc": int((classified["wynik_czy_p1_wykluczone_z_harmonogramu"] == "Tak").sum())},
    ])

    with pd.ExcelWriter(output_path, engine="openpyxl") as writer:
        classified.to_excel(writer, index=False, sheet_name="01_Wynik_klasyfikacji")
        summary.to_excel(writer, index=False, sheet_name="02_Podsumowanie")
        build_tree_sheet().to_excel(writer, index=False, sheet_name="03_Drzewo_klasyfikacji")
        build_task_mapping_sheet().to_excel(writer, index=False, sheet_name="04_Mapowanie_zadan")
        if eval_df is not None:
            eval_df.to_excel(writer, index=False, sheet_name="05_Walidacja_testowa")

    return classified


def main() -> None:
    parser = argparse.ArgumentParser(description="Hierarchiczny klasyfikator zgłoszeń RDM")
    parser.add_argument("--input", required=True, help="Ścieżka do pliku Excel/CSV z awariami")
    parser.add_argument("--output", required=True, help="Ścieżka do pliku wynikowego Excel")
    args = parser.parse_args()

    result = classify_file(args.input, args.output)
    print(f"Zakończono klasyfikację. Liczba rekordów: {len(result)}")
    print(f"Plik wynikowy: {args.output}")


if __name__ == "__main__":
    main()
