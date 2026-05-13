import os
import pandas as pd
from datetime import datetime, timedelta
from pandas.tseries.offsets import MonthEnd
from validators import load_excel_sheets, validate_sheets_and_columns, validate_input_data, parse_bool, parse_string_list, normalize_text
from kpi import compute_kpi


def parse_numeric(value, default=0.0):
    try:
        return float(value)
    except Exception:
        return default


def _parse_date(value):
    if pd.isna(value):
        return None
    try:
        return pd.to_datetime(value, errors="coerce")
    except Exception:
        return None


def _normalize_string(value):
    if pd.isna(value):
        return ""
    return str(value).strip()


def _extract_month_start(plan_df):
    if "miesiac" in plan_df.columns:
        for value in plan_df["miesiac"].dropna().astype(str).unique():
            try:
                parsed = pd.to_datetime(value, errors="coerce")
                if not pd.isna(parsed):
                    return parsed.replace(day=1)
            except Exception:
                continue
    if "data_wymagana" in plan_df.columns:
        valid = plan_df[plan_df["data_wymagana"].notna()]["data_wymagana"].astype(str)
        for value in valid:
            parsed = pd.to_datetime(value, errors="coerce")
            if not pd.isna(parsed):
                return parsed.replace(day=1)
    return None


def _build_date_range(month_start, availability_df, plan_df):
    if month_start is not None:
        start = month_start
        end = month_start + MonthEnd(1)
        dates = pd.date_range(start=start, end=end, freq="B")
        return dates
    if not availability_df.empty:
        dates = pd.to_datetime(availability_df["data"], errors="coerce").dropna().sort_values().unique()
        return pd.DatetimeIndex(dates)
    if not plan_df.empty and plan_df["data_wymagana"].notna().any():
        dates = pd.to_datetime(plan_df["data_wymagana"], errors="coerce").dropna().sort_values().unique()
        return pd.DatetimeIndex(dates)
    return pd.DatetimeIndex([])


def _load_parameters(param_df):
    params = {}
    for _, row in param_df.iterrows():
        key = _normalize_string(row.get("parametr"))
        value = row.get("wartosc")
        params[key] = value
    return params


def _build_capacity_index(workers_df, availability_df, params, dates):
    workers = workers_df.copy()
    workers["id_pracownika"] = workers["id_pracownika"].astype(str).str.strip()
    workers["kompetencje"] = workers["kompetencje"].astype(str)
    workers["status_pracownika"] = workers["status_pracownika"].astype(str)
    active_workers = workers[workers["status_pracownika"].str.lower().isin(["aktywny", "active", "aktywna"])]
    if active_workers.empty:
        return pd.DataFrame(columns=["data", "brygada", "available_hours", "available_workers", "competencje", "capacity"])

    availability = availability_df.copy()
    availability["data"] = pd.to_datetime(availability["data"], errors="coerce")
    availability = availability[availability["czy_dostepny"].apply(lambda x: parse_bool(x, default=False))]
    availability["liczba_dostepnych_godzin"] = availability["liczba_dostepnych_godzin"].apply(parse_numeric)
    availability["id_pracownika"] = availability["id_pracownika"].astype(str).str.strip()
    availability = availability.merge(
        active_workers[["id_pracownika", "brygada", "kompetencje"]], on="id_pracownika", how="left", suffixes=("", "_worker")
    )
    availability = availability[availability["brygada"].notna()]

    daily_hours = parse_numeric(params.get("liczba_godzin_pracy_dziennie", 8))
    max_load = parse_numeric(params.get("maksymalne_obciazenie_proc", 90)) / 100.0
    reserve = parse_numeric(params.get("rezerwa_operacyjna_proc", 10)) / 100.0

    records = []
    for current_date in dates:
        if current_date.weekday() >= 5:
            continue
        date_area = availability[availability["data"] == current_date]
        if date_area.empty:
            continue
        grouped = date_area.groupby("brygada")
        for brygada, group in grouped:
            workers_count = group["id_pracownika"].nunique()
            available_hours = group["liczba_dostepnych_godzin"].sum()
            max_daily = daily_hours * workers_count
            raw_capacity = min(available_hours, max_daily)
            effective_capacity = raw_capacity * max_load * (1 - reserve)
            competencies = set()
            for comps in group["kompetencje"].fillna(""):
                for item in str(comps).split(";"):
                    if item.strip():
                        competencies.add(item.strip().lower())
            records.append(
                {
                    "data": current_date,
                    "brygada": brygada,
                    "available_hours": raw_capacity,
                    "available_workers": workers_count,
                    "competencje": competencies,
                    "capacity": round(effective_capacity, 2),
                    "original_capacity": round(effective_capacity, 2),
                    "used_hours": 0.0,
                }
            )
    return pd.DataFrame(records)


def _normalize_task_row(row, katalog_lookup):
    task = row.copy()
    task["typ_pracy"] = _normalize_string(task.get("typ_pracy"))
    task["nazwa_zadania"] = _normalize_string(task.get("nazwa_zadania"))
    task["ilosc"] = parse_numeric(task.get("ilosc"), default=0.0)
    task["czas_na_jednostke_h"] = parse_numeric(katalog_lookup.get("czas_na_jednostke_h", 0.0), default=0.0)
    task["minimalna_liczba_osob"] = parse_numeric(katalog_lookup.get("minimalna_liczba_osob", 1), default=1)
    task["wymagane_kompetencje"] = [item.lower().strip() for item in parse_string_list(katalog_lookup.get("wymagane_kompetencje", task.get("wymagane_kompetencje")))]
    task["czy_termin_sztywny"] = parse_bool(task.get("czy_termin_sztywny"), default=False)
    task["czy_wymaga_wylaczenia"] = parse_bool(katalog_lookup.get("czy_wymaga_wylaczenia", task.get("czy_wymaga_wylaczenia")), default=False)
    task["czy_moze_byc_dzielone"] = parse_bool(katalog_lookup.get("czy_moze_byc_dzielone", task.get("czy_moze_byc_dzielone")), default=False)
    task["czy_moze_byc_przesuniete"] = parse_bool(katalog_lookup.get("czy_moze_byc_przesuniete", task.get("czy_moze_byc_przesuniete")), default=True)
    task["priorytet"] = parse_numeric(task.get("priorytet"), default=parse_numeric(katalog_lookup.get("domyslny_priorytet", 999)))
    task["data_wymagana"] = _parse_date(task.get("data_wymagana"))
    task["typ_pracy_lower"] = task["typ_pracy"].lower()
    task["external"] = any(word in task["typ_pracy_lower"] for word in ["zewn", "dopusz", "extern"]) or "zewn" in task["nazwa_zadania"].lower()
    task["inwestycyjne"] = "inwest" in task["typ_pracy_lower"] or "inwest" in task["nazwa_zadania"].lower()
    task["eksploatacyjne"] = "eksplo" in task["typ_pracy_lower"] or "eksplo" in task["nazwa_zadania"].lower()
    task["pracochlonnosc_h"] = task["ilosc"] * task["czas_na_jednostke_h"]
    if task["czy_termin_sztywny"] and task["data_wymagana"] is None:
        task["status_potrzeba_decyzji"] = True
    else:
        task["status_potrzeba_decyzji"] = False
    return task


def _build_task_order(task):
    if task["czy_termin_sztywny"]:
        group = 1
    elif task["czy_wymaga_wylaczenia"]:
        group = 2
    elif task["external"]:
        group = 3
    elif task["inwestycyjne"]:
        group = 4
    elif task["eksploatacyjne"]:
        group = 5
    else:
        group = 6
    return (group, task.get("priorytet", 999), task.get("data_wymagana") or datetime.max, -task.get("pracochlonnosc_h", 0.0))


def _safe_ratio(value, denominator):
    if pd.isna(value):
        value = 0.0
    if pd.isna(denominator):
        return 1.0
    if denominator <= 0:
        return 1.0
    return value / denominator


def _find_day_slots(task, capacity_index, dates, target_date=None):
    available_slots = []
    target_date = pd.to_datetime(target_date, errors="coerce") if target_date is not None else None
    for date in dates:
        if date.weekday() >= 5:
            continue
        if task["czy_termin_sztywny"] and task["data_wymagana"] is not None and date != task["data_wymagana"]:
            continue
        day_slots = capacity_index[capacity_index["data"] == date]
        for _, slot in day_slots.iterrows():
            if slot["available_workers"] < task["minimalna_liczba_osob"]:
                continue
            if task["wymagane_kompetencje"]:
                if not set(task["wymagane_kompetencje"]).issubset(slot["competencje"]):
                    continue
            if slot["capacity"] <= 0:
                continue

            day_capacity = capacity_index.loc[capacity_index["data"] == slot["data"], "original_capacity"].sum()
            day_used = capacity_index.loc[capacity_index["data"] == slot["data"], "used_hours"].sum()
            brigade_capacity = capacity_index.loc[capacity_index["brygada"] == slot["brygada"], "original_capacity"].sum()
            brigade_used = capacity_index.loc[capacity_index["brygada"] == slot["brygada"], "used_hours"].sum()
            slot_capacity = slot.get("original_capacity", 0.0)
            slot_used = slot.get("used_hours", 0.0)
            target_distance = 0
            if target_date is not None and not pd.isna(target_date):
                target_distance = abs((pd.to_datetime(slot["data"]) - target_date).days)
            available_slots.append((
                target_distance,
                day_used,
                brigade_used,
                _safe_ratio(day_used, day_capacity),
                _safe_ratio(brigade_used, brigade_capacity),
                _safe_ratio(slot_used, slot_capacity),
                slot["data"],
                str(slot["brygada"]),
                -slot["capacity"],
                slot,
            ))
    available_slots = sorted(available_slots, key=lambda item: item[:-1])
    return [item[-1] for item in available_slots]


def _explanation_for_unplanned(reason):
    text_map = {
        "kompetencje": "Sprawdź dostępność brygady lub kompetencje.",
        "obsada": "Skoryguj obsadę lub dodaj pracowników.",
        "termin_sztywny": "Rozważ przesunięcie terminu lub ręczną interwencję.",
        "pojemnosc": "Zwiększ pojemność brygady lub przenieś zadanie do kolejnego okresu.",
        "brak_danych": "Uzupełnij brakujące dane wejściowe.",
    }
    return text_map.get(reason, "Proszę zweryfikować wymogi planowania.")


def _allocate_task(task, capacity_index, dates, schedule_rows, unplanned_rows, conflict_rows, target_date=None):
    required_hours = task["pracochlonnosc_h"]
    if required_hours <= 0:
        unplanned_rows.loc[len(unplanned_rows)] = {
            "id_zadania": task.get("id_zadania"),
            "typ_pracy": task.get("typ_pracy"),
            "nazwa_zadania": task.get("nazwa_zadania"),
            "pracochlonnosc_h": required_hours,
            "wymagane_kompetencje": "; ".join(task.get("wymagane_kompetencje", [])),
            "powod_niezaplanowania": "Brak pracochłonności do zaplanowania.",
            "rekomendowana_akcja": _explanation_for_unplanned("brak_danych"),
        }
        conflict_rows.loc[len(conflict_rows)] = {
            "id_zadania": task.get("id_zadania"),
            "typ_konfliktu": "Brak pracochłonności",
            "opis_konfliktu": "Zadanie ma zerową lub nieprawidłową wartość pracochłonności.",
            "dane_wejsciowe_powiazane": str(task.get("id_typu_zadania")),
        }
        return

    slots = _find_day_slots(task, capacity_index, dates, target_date=target_date)
    if not slots:
        reason = "termin_sztywny" if task["czy_termin_sztywny"] else "kompetencje"
        unplanned_rows.loc[len(unplanned_rows)] = {
            "id_zadania": task.get("id_zadania"),
            "typ_pracy": task.get("typ_pracy"),
            "nazwa_zadania": task.get("nazwa_zadania"),
            "pracochlonnosc_h": required_hours,
            "wymagane_kompetencje": "; ".join(task.get("wymagane_kompetencje", [])),
            "powod_niezaplanowania": "Brak brygady z wymaganymi kompetencjami lub dostępnej obsady.",
            "rekomendowana_akcja": _explanation_for_unplanned(reason),
        }
        conflict_rows.loc[len(conflict_rows)] = {
            "id_zadania": task.get("id_zadania"),
            "typ_konfliktu": "Brak zdolności planowania",
            "opis_konfliktu": "Nie znaleziono dostępnej brygady z wymaganymi kompetencjami i minimalną obsadą.",
            "dane_wejsciowe_powiazane": str(task.get("id_typu_zadania")),
        }
        return

    if not task["czy_moze_byc_dzielone"]:
        for slot in slots:
            if slot["capacity"] >= required_hours:
                task_hours = required_hours
                slice_quantity = round(task_hours / task["czas_na_jednostke_h"], 3) if task["czas_na_jednostke_h"] else 0
                schedule_rows.loc[len(schedule_rows)] = {
                    "data": slot["data"],
                    "brygada": slot["brygada"],
                    "id_zadania": task.get("id_zadania"),
                    "czesc_zadania": 1,
                    "typ_pracy": task.get("typ_pracy"),
                    "nazwa_zadania": task.get("nazwa_zadania"),
                    "obszar_infrastruktury": task.get("obszar_infrastruktury"),
                    "ulica": task.get("ulica"),
                    "miasto": task.get("miasto"),
                    "ilosc_zaplanowana": slice_quantity,
                    "jednostka": task.get("jednostka"),
                    "zaplanowane_godziny": task_hours,
                    "wymagane_kompetencje": "; ".join(task.get("wymagane_kompetencje", [])),
                    "priorytet": task.get("priorytet"),
                    "czy_termin_sztywny": "Tak" if task.get("czy_termin_sztywny") else "Nie",
                    "data_wymagana": task.get("data_wymagana"),
                    "status": "Rekomendowany",
                }
                capacity_index.loc[slot.name, "capacity"] = slot["capacity"] - task_hours
                capacity_index.loc[slot.name, "used_hours"] = slot.get("used_hours", 0.0) + task_hours
                return
        unplanned_rows.loc[len(unplanned_rows)] = {
            "id_zadania": task.get("id_zadania"),
            "typ_pracy": task.get("typ_pracy"),
            "nazwa_zadania": task.get("nazwa_zadania"),
            "pracochlonnosc_h": required_hours,
            "wymagane_kompetencje": "; ".join(task.get("wymagane_kompetencje", [])),
            "powod_niezaplanowania": "Zadanie niepodzielne przekracza dostępną pojemność dzienną.",
            "rekomendowana_akcja": _explanation_for_unplanned("pojemnosc"),
        }
        conflict_rows.loc[len(conflict_rows)] = {
            "id_zadania": task.get("id_zadania"),
            "typ_konfliktu": "Brak dziennej pojemności",
            "opis_konfliktu": "Nie ma pojedynczego dnia i brygady, która może zrealizować niepodzielne zadanie.",
            "dane_wejsciowe_powiazane": str(task.get("id_typu_zadania")),
        }
        return

    part_number = 1
    remaining = required_hours
    for slot in slots:
        if remaining <= 0:
            break
        available = min(slot["capacity"], remaining)
        if available <= 0:
            continue
        slice_quantity = round(available / task["czas_na_jednostke_h"], 3) if task["czas_na_jednostke_h"] else 0
        schedule_rows.loc[len(schedule_rows)] = {
            "data": slot["data"],
            "brygada": slot["brygada"],
            "id_zadania": task.get("id_zadania"),
            "czesc_zadania": part_number,
            "typ_pracy": task.get("typ_pracy"),
            "nazwa_zadania": task.get("nazwa_zadania"),
            "obszar_infrastruktury": task.get("obszar_infrastruktury"),
            "ulica": task.get("ulica"),
            "miasto": task.get("miasto"),
            "ilosc_zaplanowana": slice_quantity,
            "jednostka": task.get("jednostka"),
            "zaplanowane_godziny": available,
            "wymagane_kompetencje": "; ".join(task.get("wymagane_kompetencje", [])),
            "priorytet": task.get("priorytet"),
            "czy_termin_sztywny": "Tak" if task.get("czy_termin_sztywny") else "Nie",
            "data_wymagana": task.get("data_wymagana"),
            "status": "Rekomendowany",
        }
        capacity_index.loc[slot.name, "capacity"] = slot["capacity"] - available
        capacity_index.loc[slot.name, "used_hours"] = slot.get("used_hours", 0.0) + available
        remaining -= available
        part_number += 1
    if remaining > 0:
        unplanned_rows.loc[len(unplanned_rows)] = {
            "id_zadania": task.get("id_zadania"),
            "typ_pracy": task.get("typ_pracy"),
            "nazwa_zadania": task.get("nazwa_zadania"),
            "pracochlonnosc_h": required_hours,
            "wymagane_kompetencje": "; ".join(task.get("wymagane_kompetencje", [])),
            "powod_niezaplanowania": "Brak wystarczającej pojemności w miesiącu.",
            "rekomendowana_akcja": _explanation_for_unplanned("pojemnosc"),
        }
        conflict_rows.loc[len(conflict_rows)] = {
            "id_zadania": task.get("id_zadania"),
            "typ_konfliktu": "Niewystarczająca pojemność",
            "opis_konfliktu": "Zadanie mogło zostać częściowo zaplanowane, ale pozostały godziny niezaplanowane.",
            "dane_wejsciowe_powiazane": str(task.get("id_typu_zadania")),
        }


def write_output(output_path, schedule_df, unplanned_df, conflicts_df, capacity_df, log_df, kpi_df):
    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
    with pd.ExcelWriter(output_path, engine="openpyxl") as writer:
        schedule_df.to_excel(writer, sheet_name="01_harmonogram", index=False)
        unplanned_df.to_excel(writer, sheet_name="02_niezaplanowane", index=False)
        conflicts_df.to_excel(writer, sheet_name="03_konflikty", index=False)
        capacity_df.to_excel(writer, sheet_name="04_obciazenie_brygad", index=False)
        log_df.to_excel(writer, sheet_name="05_log_decyzji", index=False)
        kpi_df.to_excel(writer, sheet_name="06_kpi", index=False)


def run_scheduler(input_paths: dict, output_path: str) -> dict:
    start_time = datetime.now()
    dfs = load_excel_sheets(input_paths)
    sheet_errors, sheet_warnings = validate_sheets_and_columns(dfs)
    validation = validate_input_data(dfs)
    validation["errors"] = validation["errors"] + sheet_errors
    validation["warnings"] = validation["warnings"] + sheet_warnings
    status = validation.get("status", "OK")

    schedule_df = pd.DataFrame(columns=[
        "data",
        "brygada",
        "id_zadania",
        "czesc_zadania",
        "typ_pracy",
        "nazwa_zadania",
        "obszar_infrastruktury",
        "ulica",
        "miasto",
        "ilosc_zaplanowana",
        "jednostka",
        "zaplanowane_godziny",
        "wymagane_kompetencje",
        "priorytet",
        "czy_termin_sztywny",
        "data_wymagana",
        "status",
    ])
    unplanned_df = pd.DataFrame(columns=[
        "id_zadania",
        "typ_pracy",
        "nazwa_zadania",
        "pracochlonnosc_h",
        "wymagane_kompetencje",
        "powod_niezaplanowania",
        "rekomendowana_akcja",
    ])
    conflicts_df = pd.DataFrame(columns=[
        "id_zadania",
        "typ_konfliktu",
        "opis_konfliktu",
        "dane_wejsciowe_powiazane",
    ])
    obciazenie_df = pd.DataFrame(columns=[
        "brygada",
        "data",
        "dostepne_godziny",
        "zaplanowane_godziny",
        "wykorzystanie_proc",
    ])
    log_rows = []

    if status == "błędy krytyczne":
        log_rows.append({
            "id_zadania": None,
            "etap": "Walidacja",
            "decyzja": "Przerwano planowanie",
            "uzasadnienie": "Wystąpiły błędy krytyczne we wczytanych danych.",
            "data_czas_logu": datetime.now(),
        })
        kpi_df = compute_kpi(validation, schedule_df, unplanned_df, conflicts_df, 0.0)
        write_output(output_path, schedule_df, unplanned_df, conflicts_df, obciazenie_df, pd.DataFrame(log_rows), kpi_df)
        return {
            "plan": schedule_df,
            "unplanned": unplanned_df,
            "conflicts": conflicts_df,
            "obciazenie": obciazenie_df,
            "log": pd.DataFrame(log_rows),
            "kpi": kpi_df,
            "validation": validation,
            "status": status,
        }

    plan_df = dfs["01_plan_miesieczny"].copy()
    katalog_df = dfs["02_katalog_zadan"].copy()
    pracownicy_df = dfs["03_brygady_pracownicy"].copy()
    dostepnosc_df = dfs["04_dostepnosc"].copy()
    parametry_df = dfs["05_parametry"].copy()

    month_start = validation.get("month_start") or _extract_month_start(plan_df)
    dates = _build_date_range(month_start, dostepnosc_df, plan_df)
    params = _load_parameters(parametry_df)
    capacity_index = _build_capacity_index(pracownicy_df, dostepnosc_df, params, dates)

    katalog_df["id_typu_zadania"] = katalog_df["id_typu_zadania"].astype(str).str.strip()
    katalog_lookup = katalog_df.set_index("id_typu_zadania").to_dict(orient="index")
    plan_df["id_typu_zadania"] = plan_df["id_typu_zadania"].astype(str).str.strip()
    plan_df["czy_termin_sztywny"] = plan_df["czy_termin_sztywny"].apply(lambda x: parse_bool(x, default=False))
    plan_df["data_wymagana"] = plan_df["data_wymagana"].apply(_parse_date)
    plan_df["ilosc"] = plan_df["ilosc"].apply(parse_numeric)

    tasks = []
    for _, row in plan_df.iterrows():
        katalog_row = katalog_lookup.get(str(row.get("id_typu_zadania")), {})
        task = _normalize_task_row(row, katalog_row)
        tasks.append(task)
    tasks_sorted = sorted(tasks, key=_build_task_order)

    planning_dates = []
    if not capacity_index.empty and "data" in capacity_index.columns:
        planning_dates = sorted(pd.to_datetime(capacity_index["data"], errors="coerce").dropna().unique())
    flexible_task_count = max(sum(1 for item in tasks_sorted if not item.get("czy_termin_sztywny")), 1)
    flexible_task_index = 0

    for task in tasks_sorted:
        target_date = None
        if planning_dates and not task.get("czy_termin_sztywny"):
            target_position = round(
                flexible_task_index * (len(planning_dates) - 1) / max(flexible_task_count - 1, 1)
            )
            target_date = planning_dates[target_position]
            flexible_task_index += 1
        _allocate_task(task, capacity_index, dates, schedule_df, unplanned_df, conflicts_df, target_date=target_date)
        log_rows.append({
            "id_zadania": task.get("id_zadania"),
            "etap": "Planowanie zadania",
            "decyzja": "Przydzielono" if any(schedule_df["id_zadania"] == task.get("id_zadania")) else "Nie przydzielono",
            "uzasadnienie": "Zadanie zostało ocenione według reguł dostępności i kompetencji.",
            "data_czas_logu": datetime.now(),
        })

    if not schedule_df.empty:
        schedule_df["data"] = pd.to_datetime(schedule_df["data"], errors="coerce")
        schedule_df = schedule_df.sort_values(["data", "brygada", "priorytet"])

    capacity_summary = capacity_index.copy()
    if not capacity_summary.empty:
        allocated = (
            schedule_df.groupby(["brygada", "data"])["zaplanowane_godziny"].sum().reset_index()
        )
        capacity_summary = capacity_summary.rename(columns={"available_hours": "dostepne_godziny"})
        capacity_summary = capacity_summary.merge(allocated, on=["brygada", "data"], how="left")
        capacity_summary["zaplanowane_godziny"] = capacity_summary["zaplanowane_godziny"].fillna(0.0)
        capacity_summary["wykorzystanie_proc"] = capacity_summary.apply(
            lambda row: round((row["zaplanowane_godziny"] / row["dostepne_godziny"] * 100), 1)
            if row["dostepne_godziny"] > 0 else 0.0,
            axis=1,
        )
        obciazenie_df = capacity_summary[["brygada", "data", "dostepne_godziny", "zaplanowane_godziny", "wykorzystanie_proc"]]

    log_rows.append({
        "id_zadania": None,
        "etap": "Planowanie",
        "decyzja": "Wygenerowano harmonogram",
        "uzasadnienie": "Rekomendacja planistyczna została przygotowana według reguł.",
        "data_czas_logu": datetime.now(),
    })

    scheduler_seconds = (datetime.now() - start_time).total_seconds()
    kpi_df = compute_kpi(validation, schedule_df, unplanned_df, conflicts_df, scheduler_seconds)
    write_output(output_path, schedule_df, unplanned_df, conflicts_df, obciazenie_df, pd.DataFrame(log_rows), kpi_df)

    return {
        "plan": schedule_df,
        "unplanned": unplanned_df,
        "conflicts": conflicts_df,
        "obciazenie": obciazenie_df,
        "log": pd.DataFrame(log_rows),
        "kpi": kpi_df,
        "validation": validation,
        "status": status,
    }


def replan_day(result: dict, date, wybor_brygady=None, brak_godzin=0.0, awaria_godziny=0.0):
    if result is None:
        return None
    date = pd.to_datetime(date, errors="coerce")
    if pd.isna(date):
        return None

    plan_df = result.get("plan", pd.DataFrame()).copy()
    obciazenie_df = result.get("obciazenie", pd.DataFrame()).copy()
    conflicts = result.get("conflicts", pd.DataFrame()).copy()
    log = result.get("log", pd.DataFrame()).copy()

    day_schedule = plan_df[plan_df["data"] == date].copy()
    before = day_schedule.copy()
    changed_tasks = []
    if wybor_brygady and brak_godzin > 0:
        mask = day_schedule["brygada"] == wybor_brygady
        affected = day_schedule[mask].sort_values("priorytet", ascending=False)
        if not affected.empty:
            total_hours = affected["zaplanowane_godziny"].sum()
            new_capacity = max(total_hours - brak_godzin, 0.0)
            current = 0.0
            to_keep = []
            to_remove = []
            for _, row in affected.iterrows():
                if current + row["zaplanowane_godziny"] <= new_capacity:
                    to_keep.append(row.name)
                    current += row["zaplanowane_godziny"]
                else:
                    to_remove.append(row.name)
            if to_remove:
                removed = day_schedule.loc[to_remove]
                plan_df = plan_df.drop(index=to_remove)
                for _, row in removed.iterrows():
                    conflicts = pd.concat([
                        conflicts,
                        pd.DataFrame([
                            {
                                "id_zadania": row["id_zadania"],
                                "typ_konfliktu": "Absencja/awaria",
                                "opis_konfliktu": f"Zadanie {row['id_zadania']} utracone z powodu zmniejszonej dostępności brygady.",
                                "dane_wejsciowe_powiazane": row["brygada"],
                            }
                        ])
                    ], ignore_index=True)
                    changed_tasks.append(row)
    if awaria_godziny > 0:
        emergency_id = f"AWARIA_{date.strftime('%Y%m%d')}_{int(awaria_godziny)}"
        emergency_entry = {
            "data": date,
            "brygada": wybor_brygady or "nieprzydzielona",
            "id_zadania": emergency_id,
            "czesc_zadania": 1,
            "typ_pracy": "Awaria",
            "nazwa_zadania": "Zgłoszenie awaryjne",
            "obszar_infrastruktury": "Awaria",
            "ilosc_zaplanowana": round(awaria_godziny, 2),
            "jednostka": "h",
            "zaplanowane_godziny": round(awaria_godziny, 2),
            "wymagane_kompetencje": "awaria",
            "priorytet": 0,
            "czy_termin_sztywny": "Tak",
            "data_wymagana": date,
            "status": "Wymaga decyzji",
            "zrodlo_zadania": "Awaria",
        }
        plan_df = pd.concat([plan_df, pd.DataFrame([emergency_entry])], ignore_index=True)
        conflicts = pd.concat([
            conflicts,
            pd.DataFrame([
                {
                    "id_zadania": emergency_id,
                    "typ_konfliktu": "Awaria",
                    "opis_konfliktu": "Dodano zadanie awaryjne do planu dnia.",
                    "dane_wejsciowe_powiazane": str(wybor_brygady),
                }
            ])
        ], ignore_index=True)
        changed_tasks.append(emergency_entry)

    log_entry = {
        "id_zadania": None,
        "etap": "Przeplanowanie dnia",
        "decyzja": "Rekomendacja wygenerowana",
        "uzasadnienie": f"Przeplanowanie dnia dla {date.date()} z absencją {brak_godzin} h i awarią {awaria_godziny} h.",
        "data_czas_logu": datetime.now(),
    }
    log = pd.concat([log, pd.DataFrame([log_entry])], ignore_index=True)
    summary = {
        "before": before,
        "after": plan_df[plan_df["data"] == date],
        "conflicts": conflicts,
        "log": log,
        "changed_tasks": pd.DataFrame(changed_tasks) if changed_tasks else pd.DataFrame(),
    }
    return summary
