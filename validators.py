import pandas as pd
from datetime import datetime

REQUIRED_SHEETS = {
    "01_plan_miesieczny": [
        "id_zadania",
        "miesiac",
        "typ_pracy",
        "id_typu_zadania",
        "nazwa_zadania",
        "obszar_infrastruktury",
        "jednostka",
        "ilosc",
        "data_wymagana",
        "czy_termin_sztywny",
        "priorytet",
        "uwagi_planistyczne",
    ],
    "02_katalog_zadan": [
        "id_typu_zadania",
        "typ_pracy",
        "nazwa_zadania",
        "obszar_infrastruktury",
        "jednostka",
        "czas_na_jednostke_h",
        "minimalna_liczba_osob",
        "minimalna_liczba_brygad",
        "wymagane_kompetencje",
        "czy_wymaga_wylaczenia",
        "czy_moze_byc_dzielone",
        "czy_moze_byc_przesuniete",
        "domyslny_priorytet",
    ],
    "03_brygady_pracownicy": [
        "id_pracownika",
        "kod_pracownika",
        "brygada",
        "kompetencje",
        "status_pracownika",
    ],
    "04_dostepnosc": [
        "data",
        "brygada",
        "id_pracownika",
        "czy_dostepny",
        "liczba_dostepnych_godzin",
        "powod_niedostepnosci",
    ],
    "05_parametry": [
        "parametr",
        "wartosc",
    ],
}

TRUE_VALUES = {"tak", "yes", "true", "1", "t", "y"}
FALSE_VALUES = {"nie", "no", "false", "0", "f", "n"}


def parse_bool(value, default=False):
    if pd.isna(value):
        return default
    if isinstance(value, bool):
        return value
    text = str(value).strip().lower()
    if not text:
        return default
    if text in TRUE_VALUES:
        return True
    if text in FALSE_VALUES:
        return False
    try:
        return bool(int(text))
    except Exception:
        return default


def parse_string_list(value):
    if pd.isna(value):
        return []
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    return [item.strip() for item in str(value).split(";") if item.strip()]


def normalize_text(value):
    if pd.isna(value):
        return ""
    return str(value).strip()


def load_excel_sheets(paths):
    data = {}
    for key, path in paths.items():
        xls = pd.ExcelFile(path, engine="openpyxl")
        for sheet_name in xls.sheet_names:
            data[sheet_name] = pd.read_excel(xls, sheet_name=sheet_name, engine="openpyxl")
    return data


def validate_sheets_and_columns(dfs):
    errors = []
    warnings = []
    for sheet, required_cols in REQUIRED_SHEETS.items():
        if sheet not in dfs:
            errors.append({
                "level": "błąd krytyczny",
                "sheet": sheet,
                "message": f"Brak arkusza: {sheet}",
            })
            continue
        missing = [col for col in required_cols if col not in dfs[sheet].columns]
        if missing:
            errors.append({
                "level": "błąd krytyczny",
                "sheet": sheet,
                "message": f"Brakujące kolumny w arkuszu {sheet}: {', '.join(missing)}",
            })
    return errors, warnings


def _parse_month(value):
    if pd.isna(value):
        return None
    try:
        parsed = pd.to_datetime(value, errors="coerce")
        if pd.isna(parsed):
            return None
        return parsed.replace(day=1)
    except Exception:
        return None


def validate_input_data(dfs):
    plan = dfs.get("01_plan_miesieczny", pd.DataFrame())
    katalog = dfs.get("02_katalog_zadan", pd.DataFrame())
    pracownicy = dfs.get("03_brygady_pracownicy", pd.DataFrame())
    dostepnosc = dfs.get("04_dostepnosc", pd.DataFrame())
    parametry = dfs.get("05_parametry", pd.DataFrame())

    errors = []
    warnings = []
    missing_rows = []
    conflicts = []

    if plan.empty or katalog.empty or pracownicy.empty or dostepnosc.empty or parametry.empty:
        errors.append({
            "level": "błąd krytyczny",
            "sheet": "ogólne",
            "message": "Co najmniej jeden wymagany arkusz jest pusty lub nie został wczytany.",
        })
        return {
            "status": "błędy krytyczne",
            "errors": errors,
            "warnings": warnings,
            "missing_data": pd.DataFrame(missing_rows),
            "conflicts": pd.DataFrame(conflicts),
            "counts": {
                "tasks_total": len(plan),
                "tasks_planowalne": 0,
                "tasks_do_decyzji": 0,
            },
        }

    plan = plan.copy()
    katalog = katalog.copy()
    pracownicy = pracownicy.copy()
    dostepnosc = dostepnosc.copy()
    parametry = parametry.copy()

    plan["id_typu_zadania"] = plan["id_typu_zadania"].astype(str).str.strip()
    katalog["id_typu_zadania"] = katalog["id_typu_zadania"].astype(str).str.strip()
    plan["ilosc"] = pd.to_numeric(plan["ilosc"], errors="coerce")
    katalog["czas_na_jednostke_h"] = pd.to_numeric(katalog["czas_na_jednostke_h"], errors="coerce")
    katalog["minimalna_liczba_osob"] = pd.to_numeric(katalog["minimalna_liczba_osob"], errors="coerce")

    merged = plan.merge(katalog[["id_typu_zadania", "czas_na_jednostke_h", "wymagane_kompetencje"]], on="id_typu_zadania", how="left", suffixes=("", "_katalog"))
    unmatched = merged[merged["czas_na_jednostke_h"].isna()]
    for _, row in unmatched.iterrows():
        errors.append({
            "level": "błąd krytyczny",
            "sheet": "01_plan_miesieczny",
            "column": "id_typu_zadania",
            "message": f"Brak katalogu zadania dla id_typu_zadania {row['id_typu_zadania']} (zadanie {row.get('id_zadania')}).",
            "task_id": row.get("id_zadania"),
        })

    tasks_invalid_amount = plan[plan["ilosc"].isna() | (plan["ilosc"] <= 0)]
    for _, row in tasks_invalid_amount.iterrows():
        errors.append({
            "level": "błąd krytyczny",
            "sheet": "01_plan_miesieczny",
            "column": "ilosc",
            "message": f"Nieprawidłowa wartość ilości dla zadania {row.get('id_zadania')}.", 
            "task_id": row.get("id_zadania"),
        })

    required_competence = katalog[~katalog["wymagane_kompetencje"].astype(str).str.strip().astype(bool)]
    for _, row in required_competence.iterrows():
        warnings.append({
            "level": "ostrzeżenie",
            "sheet": "02_katalog_zadan",
            "column": "wymagane_kompetencje",
            "message": f"Brak wymaganych kompetencji dla typu zadania {row.get('id_typu_zadania')}.", 
        })

    termin_tasks = plan[plan["czy_termin_sztywny"].apply(lambda x: parse_bool(x)) & plan["data_wymagana"].isna()]
    for _, row in termin_tasks.iterrows():
        errors.append({
            "level": "błąd krytyczny",
            "sheet": "01_plan_miesieczny",
            "column": "data_wymagana",
            "message": f"Zadanie z terminem sztywnym nie ma uzupełnionej daty wymaganej (zadanie {row.get('id_zadania')}).",
            "task_id": row.get("id_zadania"),
        })

    aktywni = pracownicy[pracownicy["status_pracownika"].astype(str).str.lower().isin(["aktywny", "active", "aktywna"])]
    if aktywni.empty:
        errors.append({
            "level": "błąd krytyczny",
            "sheet": "03_brygady_pracownicy",
            "message": "Brak aktywnych pracowników przypisanych do brygad.",
        })

    availability_dates = dostepnosc[~dostepnosc["data"].isna()]["data"].drop_duplicates()
    if availability_dates.empty:
        errors.append({
            "level": "błąd krytyczny",
            "sheet": "04_dostepnosc",
            "message": "Brak informacji o dostępności pracowników.",
        })

    months = plan["miesiac"].dropna().unique()
    month_start = None
    for value in months:
        parsed = _parse_month(value)
        if parsed is not None:
            month_start = parsed
            break
    if month_start is None:
        if not plan[plan["data_wymagana"].notna()].empty:
            month_start = _parse_month(plan[plan["data_wymagana"].dropna().iloc[0]])
    if month_start is None:
        warnings.append({
            "level": "ostrzeżenie",
            "sheet": "01_plan_miesieczny",
            "message": "Nie udało się określić miesiąca z pól planu miesięcznego.",
        })

    counts = {
        "tasks_total": len(plan),
        "tasks_planowalne": len(plan) - len(tasks_invalid_amount) - len(unmatched),
        "tasks_do_decyzji": len(termin_tasks),
    }

    status = "OK" if not errors else "błędy krytyczne"
    if not errors and warnings:
        status = "ostrzeżenia"

    missing_rows.extend([
        {
            "id_zadania": row.get("id_zadania"),
            "opis": row.get("message"),
            "arkusz": row.get("sheet"),
            "kolumna": row.get("column"),
        }
        for row in errors
    ])

    if not month_start and not availability_dates.empty:
        try:
            inferred = pd.to_datetime(availability_dates.iloc[0], errors="coerce")
            month_start = inferred.replace(day=1) if not pd.isna(inferred) else None
        except Exception:
            month_start = None

    return {
        "status": status,
        "errors": errors,
        "warnings": warnings,
        "missing_data": pd.DataFrame(missing_rows),
        "conflicts": pd.DataFrame(conflicts),
        "counts": counts,
        "month_start": month_start,
    }
