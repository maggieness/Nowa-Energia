import pandas as pd
from datetime import datetime


def compute_kpi(validation_report, schedule_df, unplanned_df, conflicts_df, scheduler_seconds, replanning_count=0, replanning_seconds=None, approved_without_changes=False):
    tasks_total = validation_report.get("counts", {}).get("tasks_total", 0)
    tasks_planowalne = validation_report.get("counts", {}).get("tasks_planowalne", 0)
    tasks_planned = len(schedule_df) if schedule_df is not None else 0
    tasks_unplanned = len(unplanned_df) if unplanned_df is not None else 0
    conflict_count = len(conflicts_df) if conflicts_df is not None else 0
    if tasks_total > 0:
        completeness = round((tasks_planowalne / tasks_total) * 100, 1)
    else:
        completeness = 0.0
    if tasks_planowalne > 0:
        coverage = round((tasks_planned / tasks_planowalne) * 100, 1)
    else:
        coverage = 0.0
    kpis = [
        {
            "id_kpi": "KPI-01",
            "nazwa_kpi": "Czas przygotowania harmonogramu",
            "wartosc": f"{round(scheduler_seconds, 2)} s",
            "interpretacja": "Czas technicznego wygenerowania rekomendacji.",
            "status": "informacyjny",
        },
        {
            "id_kpi": "KPI-02",
            "nazwa_kpi": "Kompletność danych wejściowych",
            "wartosc": f"{completeness} %",
            "interpretacja": "Procent zadań bez braków danych krytycznych.",
            "status": "informacyjny",
        },
        {
            "id_kpi": "KPI-03",
            "nazwa_kpi": "Pokrycie kompetencji i obsady",
            "wartosc": f"{coverage} %",
            "interpretacja": "Procent zadań planowanych z pełnym pokryciem kompetencji i obsady.",
            "status": "informacyjny",
        },
        {
            "id_kpi": "KPI-04",
            "nazwa_kpi": "Konflikty w harmonogramie",
            "wartosc": str(conflict_count),
            "interpretacja": "Liczba konfliktów i zadań niezaplanowanych.",
            "status": "ostrzeżenie" if conflict_count > 0 else "OK",
        },
        {
            "id_kpi": "KPI-05",
            "nazwa_kpi": "Realizacja/stabilność planu",
            "wartosc": "Do pomiaru po pilotażu",
            "interpretacja": "Nie ma danych wykonania w MVP.",
            "status": "do pomiaru",
        },
        {
            "id_kpi": "KPI-06",
            "nazwa_kpi": "Skala przeplanowania ad hoc",
            "wartosc": str(replanning_count),
            "interpretacja": "Liczba zmian wprowadzonych na ekranie przeplanowania dnia.",
            "status": "informacyjny",
        },
        {
            "id_kpi": "KPI-07",
            "nazwa_kpi": "Czas przeplanowania dnia",
            "wartosc": f"{round(replanning_seconds, 2)} s" if replanning_seconds is not None else "Do pomiaru po pilotażu",
            "interpretacja": "Czas wygenerowania rekomendacji przeplanowania.",
            "status": "informacyjny",
        },
        {
            "id_kpi": "KPI-08",
            "nazwa_kpi": "Jakość rekomendacji",
            "wartosc": "Za mało danych - do pomiaru po pilotażu" if not approved_without_changes else "Za mało danych - do pomiaru po pilotażu",
            "interpretacja": "Udział rekomendacji zaakceptowanych bez ręcznej korekty.",
            "status": "do pomiaru",
        },
    ]
    return pd.DataFrame(kpis)
