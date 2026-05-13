import streamlit as st
import pandas as pd


def section_title(title):
    st.markdown(f"### {title}")


def render_status_badge(value):
    normalized = str(value).lower()
    badge_class = "info"
    if value in ["OK", "Zatwierdzony", "Wykonane"]:
        badge_class = "ok"
    elif value in ["Rekomendowany", "Do wykonania", "W trakcie"]:
        badge_class = "info"
    elif value in ["ostrzeżenia", "Wymaga decyzji", "Przeniesione"] or "ostrze" in normalized:
        badge_class = "warn"
    elif value in ["błędy krytyczne", "Odrzucony", "Nie wykonane"] or "błąd" in normalized or "blad" in normalized:
        badge_class = "danger"
    st.markdown(f"<span class='status-badge {badge_class}'>{value}</span>", unsafe_allow_html=True)


def render_summary_cards(stats):
    cols = st.columns(4)
    cards = [
        ("Liczba zadań", stats.get("tasks_total", 0)),
        ("Zaplanowane zadania", stats.get("planned_count", 0)),
        ("Niezaplanowane", stats.get("unplanned_count", 0)),
        ("Konflikty", stats.get("conflict_count", 0)),
    ]
    for col, (label, value) in zip(cols, cards):
        col.markdown(f"""
        <div class="metric-card">
            <h3>{value}</h3>
            <p>{label}</p>
        </div>
        """, unsafe_allow_html=True)


def show_dataframe(df, max_rows=20):
    if df is None or df.empty:
        st.write("Brak danych do wyświetlenia.")
        return
    st.dataframe(df.head(max_rows), hide_index=True, use_container_width=True)


def _emergency_mask(df):
    if df is None or df.empty:
        return pd.Series(False, index=df.index if df is not None else None)

    masks = []
    for column in ["typ_pracy", "wymagane_kompetencje", "id_zadania", "nazwa_zadania", "zrodlo_zadania"]:
        if column in df.columns:
            masks.append(df[column].fillna("").astype(str).str.contains("awari|rdm", case=False, regex=True))
    if not masks:
        return pd.Series(False, index=df.index)

    mask = masks[0]
    for item in masks[1:]:
        mask = mask | item
    return mask


def _highlight_emergency_rows(row):
    if str(row.get("Źródło", "")).lower() != "awaria":
        return [""] * len(row)
    return ["background-color: #ffe4e6; color: #7f1d1d; border-color: #fecdd3; font-weight: 650;" for _ in row]


def prepare_plan_view(df):
    if df is None or df.empty:
        return pd.DataFrame()

    display_df = df.copy()
    display_df["zrodlo_widok"] = _emergency_mask(display_df).map({True: "Awaria", False: "Plan"})
    if "data" in display_df.columns:
        display_df["data"] = pd.to_datetime(display_df["data"], errors="coerce").dt.strftime("%Y-%m-%d")
    if "data_wymagana" in display_df.columns:
        display_df["data_wymagana"] = pd.to_datetime(display_df["data_wymagana"], errors="coerce").dt.strftime("%Y-%m-%d")
    address_columns = [column for column in ["ulica", "miasto"] if column in display_df.columns]
    if address_columns:
        address_df = display_df[address_columns].fillna("").astype(str)
        display_df["adres"] = address_df.apply(
            lambda row: ", ".join([value.strip() for value in row if value.strip()]),
            axis=1,
        )

    columns = [
        "zrodlo_widok",
        "data",
        "brygada",
        "status_wykonania",
        "id_zadania",
        "nazwa_zadania",
        "adres",
        "zaplanowane_godziny",
        "typ_pracy",
        "priorytet",
        "status",
    ]
    columns = [column for column in columns if column in display_df.columns]
    display_df = display_df[columns]

    return display_df.rename(columns={
        "zrodlo_widok": "Źródło",
        "data": "Data",
        "brygada": "Brygada",
        "status_wykonania": "Status zadania",
        "id_zadania": "ID",
        "czesc_zadania": "Część",
        "typ_pracy": "Typ pracy",
        "nazwa_zadania": "Zadanie",
        "obszar_infrastruktury": "Obszar",
        "adres": "Adres",
        "ilosc_zaplanowana": "Ilość",
        "jednostka": "Jedn.",
        "zaplanowane_godziny": "Godziny",
        "priorytet": "Priorytet",
        "status": "Status harmonogramu",
    })


def show_plan_grid(df, max_rows=None):
    display_df = prepare_plan_view(df)
    if display_df.empty:
        st.write("Brak danych do wyświetlenia.")
        return

    if max_rows is not None:
        display_df = display_df.head(max_rows)

    height = min(720, max(180, 38 * (len(display_df) + 1)))
    styled_df = display_df.style.apply(_highlight_emergency_rows, axis=1)
    st.dataframe(
        styled_df,
        hide_index=True,
        use_container_width=True,
        height=height,
        column_config={
            "Źródło": st.column_config.TextColumn(width="small"),
            "Data": st.column_config.TextColumn(width="small"),
            "Brygada": st.column_config.TextColumn(width="small"),
            "Status zadania": st.column_config.TextColumn(width="medium"),
            "ID": st.column_config.TextColumn(width="small"),
            "Część": st.column_config.TextColumn(width="small"),
            "Typ pracy": st.column_config.TextColumn(width="medium"),
            "Zadanie": st.column_config.TextColumn(width="large"),
            "Adres": st.column_config.TextColumn(width="large"),
            "Ilość": st.column_config.NumberColumn(width="small"),
            "Jedn.": st.column_config.TextColumn(width="small"),
            "Godziny": st.column_config.NumberColumn(width="small", format="%.1f"),
            "Priorytet": st.column_config.NumberColumn(width="small"),
            "Status harmonogramu": st.column_config.TextColumn(width="medium"),
        },
    )


def show_day_plan(plan_df, key_prefix="day_plan"):
    if plan_df is None or plan_df.empty:
        st.write("Brak danych do wyświetlenia.")
        return

    plan_df = plan_df.copy()
    plan_df["data"] = pd.to_datetime(plan_df["data"], errors="coerce")
    daty = sorted(plan_df["data"].dropna().dt.date.astype(str).unique())
    if not daty:
        st.write("Brak dat w harmonogramie.")
        return

    selected_date = st.selectbox("Dzień", daty, key=f"{key_prefix}_date")
    day_df = plan_df[plan_df["data"].dt.date.astype(str) == selected_date].copy()
    if day_df.empty:
        st.write("Brak zadań na ten dzień.")
        return

    total_hours = day_df.get("zaplanowane_godziny", pd.Series(dtype=float)).sum()
    st.caption(f"{len(day_df)} zadań, {total_hours:.1f} godz.")

    for brygada, group in day_df.groupby("brygada", dropna=False):
        hours = group.get("zaplanowane_godziny", pd.Series(dtype=float)).sum()
        label = f"Brygada {brygada} - {len(group)} zadań, {hours:.1f} godz."
        with st.expander(label, expanded=False):
            show_plan_grid(group)


def show_day_plan(plan_df, key_prefix="day_plan"):
    if plan_df is None or plan_df.empty:
        st.write("Brak danych do wyświetlenia.")
        return

    plan_df = plan_df.copy()
    plan_df["data"] = pd.to_datetime(plan_df["data"], errors="coerce")
    daty = sorted(plan_df["data"].dropna().dt.date.astype(str).unique())
    if not daty:
        st.write("Brak dat w harmonogramie.")
        return

    selected_date = st.selectbox("Dzień", daty, key=f"{key_prefix}_date")
    day_df = plan_df[plan_df["data"].dt.date.astype(str) == selected_date].copy()
    if day_df.empty:
        st.write("Brak zadań na ten dzień.")
        return

    total_hours = day_df.get("zaplanowane_godziny", pd.Series(dtype=float)).sum()
    brygady_count = day_df["brygada"].nunique() if "brygada" in day_df.columns else 0
    st.caption(f"{len(day_df)} zadań | {total_hours:.1f} godz. | {brygady_count} brygad")
    show_plan_grid(day_df.sort_values(["brygada", "priorytet"]))


def show_download_button(dataframe, filename, label):
    csv = dataframe.to_csv(index=False).encode("utf-8")
    st.download_button(label=label, data=csv, file_name=filename, mime="text/csv")
