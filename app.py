import os
import tempfile
import calendar
import streamlit as st
import pandas as pd
from html import escape
from datetime import datetime
from scheduler_engine import run_scheduler, replan_day, write_output
from rdm_hierarchical_classifier import classify_file
from ui_components import section_title, render_status_badge, render_summary_cards, show_dataframe, show_day_plan, show_plan_grid

st.set_page_config(page_title="Nowa Energia - Harmonogram pracy", layout="wide")

DATA_DIR = os.path.join(os.getcwd(), "02_Baza danych")
DEFAULT_STALE_PATH = os.path.join(DATA_DIR, "planowanie_brygad_Stale.xlsx")
PLAN_STATUS_OPTIONS = ["Rekomendowany", "Wymaga decyzji", "Zatwierdzony", "Odrzucony"]
EXECUTION_STATUS_OPTIONS = ["Do wykonania", "W trakcie", "Wykonane", "Nie wykonane", "Przeniesione"]

TRAINING_STEPS = [
    {
        "title": "1. Wgraj dane wejściowe",
        "body": (
            "W panelu bocznym, w sekcji Dane, wgraj dwa przykładowe pliki: "
            "`planowanie_brygad_Dzial_planowania.xlsx` przy pozycji Dział planowania oraz "
            "`planowanie_brygad_HR.xlsx` przy pozycji Brygady. "
            "Po wgraniu obu plików aplikacja pokaże, że dane są gotowe do planowania."
        ),
    },
    {
        "title": "2. Uruchom planowanie",
        "body": (
            "Przejdź do zakładki Zarządzanie Harmonogramem i kliknij przycisk Uruchom planowanie. "
            "Aplikacja przygotuje propozycję harmonogramu."
        ),
    },
    {
        "title": "3. Sprawdź propozycję AI",
        "body": (
            "Otrzymasz propozycję AI. W tym miejscu możesz ją zweryfikować, zmodyfikować w tabeli, "
            "a następnie kliknąć Zapisz zmiany w harmonogramie."
        ),
    },
    {
        "title": "4. Zatwierdź harmonogram",
        "body": (
            "Po sprawdzeniu harmonogramu kliknij Zatwierdź harmonogram. "
            "Dopiero zatwierdzony harmonogram pojawi się jako finalny podgląd w zakładce Harmonogram."
        ),
    },
    {
        "title": "5. Wgraj rejestr awarii",
        "body": (
            "Przejdź do zakładki Rejestr Awarii i wgraj przykładowy plik "
            "`rdm_awarie_do_klasyfikacji_harmonogramu.xlsx`. "
            "Aplikacja sklasyfikuje awarie i pokaże wynik do weryfikacji."
        ),
    },
    {
        "title": "6. Dodaj i zaakceptuj awarie",
        "body": (
            "Po sprawdzeniu klasyfikacji kliknij Importuj zakwalifikowane awarie do harmonogramu. "
            "Następnie wróć do Zarządzanie Harmonogramem, zaakceptuj awarie RDM pojedynczo lub wszystkie naraz, "
            "a potem zatwierdź harmonogram ponownie."
        ),
    },
    {
        "title": "7. Przejdź do Dashboardu",
        "body": (
            "Na końcu otwórz zakładkę Dashboard. Zobaczysz tam podsumowanie statusów prac, obciążenie brygad, "
            "miesięczny widok harmonogramu, czas pracy w wybranym miesiącu, godziny awarii oraz zadania niezaplanowane."
        ),
    },
]


def load_workbook_tables(path):
    xls = pd.ExcelFile(path, engine="openpyxl")
    return {
        sheet_name: pd.read_excel(xls, sheet_name=sheet_name, engine="openpyxl")
        for sheet_name in xls.sheet_names
    }


def save_workbook_tables(path, tables):
    with pd.ExcelWriter(path, engine="openpyxl") as writer:
        for sheet_name, df in tables.items():
            df.to_excel(writer, sheet_name=sheet_name, index=False)


def save_uploaded_file(uploaded_file, filename):
    path = os.path.join(tempfile.gettempdir(), filename)
    with open(path, "wb") as output:
        output.write(uploaded_file.getbuffer())
    return path


def render_data_upload(file_key, label, target_filename, file_types, on_upload=None):
    upload_modes = st.session_state["upload_modes"]
    upload_versions = st.session_state["upload_versions"]
    session_files = st.session_state["uploaded_session_files"]
    session_meta = st.session_state["uploaded_session_meta"]

    is_uploaded = file_key in session_files and file_key in session_meta
    is_reuploading = upload_modes.get(file_key, False)
    safe_label = escape(label)

    with st.container(border=True):
        if is_uploaded and not is_reuploading:
            safe_file_name = escape(session_meta[file_key][0])
            st.markdown(
                f"<div class='data-upload-card'><span>{safe_label} - wgrano</span><strong>{safe_file_name}</strong></div>",
                unsafe_allow_html=True,
            )
            if st.button("Zmień plik", key=f"reupload_{file_key}", help="Wgraj ponownie", use_container_width=True):
                upload_modes[file_key] = True
                upload_versions[file_key] = upload_versions.get(file_key, 0) + 1
                st.rerun()
            return

        status_label = "Zmień plik" if is_reuploading else "Do wgrania"
        st.markdown(
            f"<div class='data-upload-card data-upload-card--pending'><span>{safe_label}</span><strong>{status_label}</strong></div>",
            unsafe_allow_html=True,
        )

        uploaded_file = st.file_uploader(
            "Wgraj plik",
            type=file_types,
            key=f"{file_key}_upload_{upload_versions.get(file_key, 0)}",
            help=f"Wgraj plik: {label}",
            label_visibility="collapsed",
        )
    if uploaded_file is None:
        return

    file_path = os.path.join(tempfile.gettempdir(), target_filename)
    with open(file_path, "wb") as output:
        output.write(uploaded_file.getbuffer())

    session_files[file_key] = file_path
    session_meta[file_key] = (uploaded_file.name, uploaded_file.size)
    upload_modes[file_key] = False

    if file_key in ["planowanie", "hr"]:
        st.session_state["schedule_results"] = None
        st.session_state["approved"] = False
        st.session_state["rdm_changes_pending_approval"] = False
        st.session_state["pending_nav_page"] = "Zarządzanie Harmonogramem"

    if on_upload is not None:
        try:
            on_upload(uploaded_file)
        except Exception as exc:
            upload_modes[file_key] = True
            st.error(f"Nie udało się przetworzyć pliku: {exc}")
            return

    st.rerun()


def save_current_results_to_excel():
    results = st.session_state.get("schedule_results")
    if results is None:
        return
    output_path = os.path.join(os.getcwd(), "harmonogram_brygad_output.xlsx")
    write_output(
        output_path,
        results.get("plan", pd.DataFrame()),
        results.get("unplanned", pd.DataFrame()),
        results.get("conflicts", pd.DataFrame()),
        results.get("obciazenie", pd.DataFrame()),
        results.get("log", pd.DataFrame()),
        results.get("kpi", pd.DataFrame()),
    )


def run_current_planning():
    output_path = os.path.join(os.getcwd(), "harmonogram_brygad_output.xlsx")
    try:
        st.session_state["schedule_results"] = run_scheduler(st.session_state["input_paths"], output_path)
        st.session_state["schedule_results"]["plan"] = enrich_plan_addresses_from_input(
            st.session_state["schedule_results"].get("plan", pd.DataFrame())
        )
        st.session_state["approved"] = False
        st.session_state["rdm_changes_pending_approval"] = False
        st.success(f"Planowanie zakończone. Plik wyjściowy zapisano jako {output_path}")
    except Exception as exc:
        st.error(f"Błąd podczas planowania: {exc}")


def render_run_planning_button(key):
    input_ready = st.session_state.get("input_paths") is not None
    button_label = "Uruchom planowanie ponownie" if st.session_state.get("schedule_results") is not None else "Uruchom planowanie"
    if st.button(
        button_label,
        key=key,
        help=PLAN_BUTTON_HELP,
        disabled=not input_ready,
        use_container_width=True,
    ):
        run_current_planning()
    if not input_ready:
        st.caption("Wgraj pliki w sekcji Dane, aby uruchomić planowanie.")


def render_loaded_input_summary():
    session_meta = st.session_state.get("uploaded_session_meta", {})
    plan_name = session_meta.get("planowanie", ("brak pliku", 0))[0]
    hr_name = session_meta.get("hr", ("brak pliku", 0))[0]
    st.markdown(
        f"""
        <div class="loaded-input-panel">
            <span>Dane wejściowe załadowane</span>
            <strong>Dział planowania:</strong> {escape(str(plan_name))}<br>
            <strong>Brygady:</strong> {escape(str(hr_name))}
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_schedule_excel_download():
    output_path = os.path.join(os.getcwd(), "harmonogram_brygad_output.xlsx")
    if not os.path.exists(output_path):
        return
    with open(output_path, "rb") as output_file:
        st.download_button(
            "Pobierz Excel",
            data=output_file.read(),
            file_name="harmonogram_brygad_output.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            use_container_width=True,
        )


def render_management_summary_cards(stats):
    cols = st.columns(3)
    cards = [
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


def get_query_nav_page():
    value = st.query_params.get("nav")
    if isinstance(value, list):
        return value[0] if value else None
    return value


def render_sidebar_navigation(current_page):
    st.sidebar.markdown("<div class='nav-menu-title'>Menu</div>", unsafe_allow_html=True)
    with st.sidebar.container(key="nav_menu"):
        for page_name in PAGES:
            is_active = page_name == current_page
            if st.button(
                page_name,
                key=f"nav_btn_{page_name}",
                type="primary" if is_active else "secondary",
                width="stretch",
            ):
                st.session_state["nav_page"] = page_name
                st.query_params["nav"] = page_name
                st.rerun()


@st.dialog("Jak zacząć")
def render_training_dialog():
    step = st.session_state.get("training_step", 0)

    if step <= 0:
        st.write("Czy chcesz przejść krótkie szkolenie, żeby umiejętnie używać aplikacji?")
        st.write("Pomocnik poprowadzi Cię przez podstawowy scenariusz od wgrania danych do zatwierdzenia harmonogramu.")
        action_cols = st.columns(2)
        if action_cols[0].button("Rozpocznij szkolenie", use_container_width=True):
            st.session_state["training_step"] = 1
            st.rerun()
        if action_cols[1].button("Nie teraz", use_container_width=True):
            st.session_state["show_training_dialog"] = False
            st.session_state["training_prompt_seen"] = True
            st.rerun()
        return

    step_index = min(max(step, 1), len(TRAINING_STEPS)) - 1
    training_step = TRAINING_STEPS[step_index]
    st.markdown(f"**{training_step['title']}**")
    st.write(training_step["body"])
    st.caption(f"Krok {step_index + 1} z {len(TRAINING_STEPS)}")

    nav_cols = st.columns(3)
    if nav_cols[0].button("Wstecz", disabled=step_index == 0, use_container_width=True):
        st.session_state["training_step"] = max(1, step - 1)
        st.rerun()
    if step_index < len(TRAINING_STEPS) - 1:
        if nav_cols[1].button("Dalej", use_container_width=True):
            st.session_state["training_step"] = step + 1
            st.rerun()
    else:
        if nav_cols[1].button("Zakończ", use_container_width=True):
            st.session_state["show_training_dialog"] = False
            st.session_state["training_prompt_seen"] = True
            st.session_state["training_step"] = 0
            st.rerun()
    if nav_cols[2].button("Zamknij", use_container_width=True):
        st.session_state["show_training_dialog"] = False
        st.session_state["training_prompt_seen"] = True
        st.rerun()


def render_monthly_schedule_view(plan_df):
    if plan_df is None or plan_df.empty or "data" not in plan_df.columns:
        st.subheader("Miesięczny widok harmonogramu")
        st.write("Brak dat w harmonogramie.")
        return

    monthly_df = plan_df.copy()
    monthly_df["data"] = pd.to_datetime(monthly_df["data"], errors="coerce")
    monthly_df = monthly_df.dropna(subset=["data"])
    if monthly_df.empty:
        st.subheader("Miesięczny widok harmonogramu")
        st.write("Brak poprawnych dat w harmonogramie.")
        return

    monthly_df["zaplanowane_godziny"] = pd.to_numeric(
        monthly_df.get("zaplanowane_godziny", pd.Series(dtype=float)),
        errors="coerce",
    ).fillna(0)
    monthly_df["miesiac"] = monthly_df["data"].dt.to_period("M").astype(str)

    months = sorted(monthly_df["miesiac"].dropna().unique())
    current_month = pd.Timestamp.today().strftime("%Y-%m")
    default_index = months.index(current_month) if current_month in months else len(months) - 1

    header_cols = st.columns([3, 1])
    with header_cols[0]:
        st.subheader("Miesięczny widok harmonogramu")
    with header_cols[1]:
        selected_month = st.selectbox("Miesiąc", months, index=default_index, key="dashboard_month")

    month_df = monthly_df[monthly_df["miesiac"] == selected_month].copy()
    if month_df.empty:
        st.write("Brak zadań w wybranym miesiącu.")
        return
    if "id_zadania" not in month_df.columns:
        month_df["id_zadania"] = month_df.index.astype(str)
    if "brygada" not in month_df.columns:
        month_df["brygada"] = ""

    emergency_mask = get_emergency_mask(month_df)
    first_day = pd.Period(selected_month, freq="M").to_timestamp()
    days_in_month = calendar.monthrange(first_day.year, first_day.month)[1]
    all_days = pd.date_range(first_day, periods=days_in_month, freq="D")

    daily = (
        month_df.assign(dzien=month_df["data"].dt.normalize())
        .groupby("dzien", dropna=False)
        .agg(
            zadania=("id_zadania", "count"),
            godziny=("zaplanowane_godziny", "sum"),
            brygady=("brygada", lambda values: ", ".join(sorted({str(value) for value in values.dropna()}))),
        )
        .reindex(all_days)
        .reset_index()
        .rename(columns={"index": "Data"})
    )
    daily["Data"] = pd.to_datetime(daily["Data"])
    daily["zadania"] = pd.to_numeric(daily["zadania"], errors="coerce").fillna(0)
    daily["godziny"] = pd.to_numeric(daily["godziny"], errors="coerce").fillna(0)
    daily["brygady"] = daily["brygady"].fillna("").astype(str)

    emergency_daily = (
        month_df[emergency_mask]
        .assign(dzien=month_df.loc[emergency_mask, "data"].dt.normalize())
        .groupby("dzien")["zaplanowane_godziny"]
        .sum()
        .reindex(all_days, fill_value=0)
        .reset_index(drop=True)
    )
    daily["Godziny awarii"] = emergency_daily
    daily["Dzień tygodnia"] = daily["Data"].dt.day_name().map({
        "Monday": "pon.",
        "Tuesday": "wt.",
        "Wednesday": "śr.",
        "Thursday": "czw.",
        "Friday": "pt.",
        "Saturday": "sob.",
        "Sunday": "ndz.",
    })
    daily["Data"] = daily["Data"].dt.strftime("%Y-%m-%d")
    daily["Godziny"] = pd.to_numeric(daily["godziny"], errors="coerce").fillna(0).round(1)
    daily["Zadania"] = pd.to_numeric(daily["zadania"], errors="coerce").fillna(0).astype(int)
    daily["Brygady"] = daily["brygady"].replace("0", "")
    daily["Godziny awarii"] = pd.to_numeric(daily["Godziny awarii"], errors="coerce").fillna(0).round(1)

    total_hours = month_df["zaplanowane_godziny"].sum()
    work_days = int((daily["Godziny"] > 0).sum())
    emergency_hours = float(daily["Godziny awarii"].sum())
    avg_day_hours = total_hours / work_days if work_days else 0

    month_metrics = st.columns(4)
    month_metrics[0].metric("Czas pracy w miesiącu", f"{total_hours:.1f} h")
    month_metrics[1].metric("Dni z pracą", work_days)
    month_metrics[2].metric("Średnio na dzień pracy", f"{avg_day_hours:.1f} h")
    month_metrics[3].metric("Godziny awarii", f"{emergency_hours:.1f} h")

    try:
        import plotly.express as px

        chart_df = daily.copy()
        fig = px.bar(
            chart_df,
            x="Data",
            y="Godziny",
            color="Godziny awarii",
            color_continuous_scale=["#8d6aa5", "#be123c"],
            hover_data=["Zadania", "Godziny awarii", "Brygady"],
        )
        fig.update_layout(
            margin=dict(l=0, r=0, t=12, b=0),
            height=320,
            coloraxis_colorbar=dict(title="Awaria h"),
        )
        st.plotly_chart(fig, use_container_width=True)
    except Exception:
        pass

    st.dataframe(
        daily[["Data", "Dzień tygodnia", "Zadania", "Godziny", "Godziny awarii", "Brygady"]],
        hide_index=True,
        use_container_width=True,
        height=min(520, max(220, 34 * (len(daily) + 1))),
    )


def render_operations_dashboard(results):
    if results is None:
        st.info("Najpierw uruchom planowanie.")
        render_run_planning_button("run_planning_from_dashboard")
        return

    results["plan"] = ensure_execution_status(results.get("plan", pd.DataFrame()))
    plan_df = enrich_plan_addresses_from_input(results["plan"]).copy()
    results["plan"] = plan_df
    unplanned_df = results.get("unplanned", pd.DataFrame()).copy()
    load_df = results.get("obciazenie", pd.DataFrame()).copy()

    if plan_df.empty and unplanned_df.empty and load_df.empty:
        st.warning("Brak danych do dashboardu.")
        return

    if "data" in plan_df.columns:
        plan_df["data"] = pd.to_datetime(plan_df["data"], errors="coerce")
    if "data" in load_df.columns:
        load_df["data"] = pd.to_datetime(load_df["data"], errors="coerce")
    if "wykorzystanie_proc" in load_df.columns:
        load_df["wykorzystanie_proc"] = pd.to_numeric(load_df["wykorzystanie_proc"], errors="coerce")

    total_tasks = len(plan_df)
    done_count = int((plan_df.get("status_wykonania", pd.Series(dtype=str)) == "Wykonane").sum())
    remaining_count = max(total_tasks - done_count, 0)
    unplanned_count = len(unplanned_df)
    planned_hours = pd.to_numeric(plan_df.get("zaplanowane_godziny", pd.Series(dtype=float)), errors="coerce").fillna(0).sum()
    completion_rate = (done_count / total_tasks * 100) if total_tasks else 0
    load_values = load_df["wykorzystanie_proc"].dropna() if "wykorzystanie_proc" in load_df.columns else pd.Series(dtype=float)
    avg_load = load_values.mean() if not load_values.empty else 0
    max_load = load_values.max() if not load_values.empty else 0

    metric_cols = st.columns(4)
    metric_cols[0].metric("Zadania w harmonogramie", total_tasks, f"{planned_hours:.1f} h")
    metric_cols[1].metric("Wykonane", done_count, f"{completion_rate:.0f}%")
    metric_cols[2].metric("Niezaplanowane", unplanned_count)
    metric_cols[3].metric("Średnie obciążenie", f"{avg_load:.0f}%", f"max {max_load:.0f}%")

    attention_items = []
    if not load_df.empty and {"brygada", "wykorzystanie_proc"}.issubset(load_df.columns):
        valid_load_df = load_df.dropna(subset=["wykorzystanie_proc"])
        if not valid_load_df.empty:
            max_load_row = valid_load_df.loc[valid_load_df["wykorzystanie_proc"].idxmax()]
            attention_items.append(
                f"Najwyższe obciążenie: {max_load_row.get('brygada', 'brak danych')} ({max_load:.0f}%)."
            )
            high_load_days = int((valid_load_df["wykorzystanie_proc"] >= 90).sum())
            if high_load_days:
                attention_items.append(f"Dni z obciążeniem co najmniej 90%: {high_load_days}.")
    overdue_count = 0
    if {"data_wymagana", "status_wykonania"}.issubset(plan_df.columns):
        required_dates = pd.to_datetime(plan_df["data_wymagana"], errors="coerce")
        overdue_count = int(((required_dates < pd.Timestamp(datetime.today().date())) & (plan_df["status_wykonania"] != "Wykonane")).sum())
        if overdue_count:
            attention_items.append(f"Zadania po terminie i niewykonane: {overdue_count}.")
    if unplanned_count:
        attention_items.append("Sprawdź listę niezaplanowanych zadań i rekomendowane działania.")
    if remaining_count:
        attention_items.append(f"Pozostało do wykonania: {remaining_count}.")

    if attention_items:
        st.info(" ".join(attention_items))

    render_monthly_schedule_view(plan_df)

    status_summary = (
        plan_df.get("status_wykonania", pd.Series(dtype=str))
        .fillna("Do wykonania")
        .value_counts()
        .reindex(EXECUTION_STATUS_OPTIONS, fill_value=0)
        .reset_index()
    )
    status_summary.columns = ["Status", "Liczba zadań"]

    chart_cols = st.columns(2)
    try:
        import plotly.express as px

        with chart_cols[0]:
            st.subheader("Status prac")
            status_fig = px.bar(
                status_summary,
                x="Status",
                y="Liczba zadań",
                color="Status",
                color_discrete_sequence=["#7c5a9b", "#9a5c7d", "#b58da6", "#6d6078", "#c9a7ba"],
            )
            status_fig.update_layout(showlegend=False, margin=dict(l=0, r=0, t=12, b=0), height=320)
            st.plotly_chart(status_fig, use_container_width=True)

        with chart_cols[1]:
            st.subheader("Obciążenie brygad")
            if load_df.empty or "brygada" not in load_df.columns:
                st.write("Brak danych obciążenia.")
            else:
                load_summary = (
                    load_df.groupby("brygada", dropna=False)["wykorzystanie_proc"]
                    .agg(["mean", "max"])
                    .reset_index()
                    .rename(columns={
                        "brygada": "Brygada",
                        "mean": "Średnie obciążenie (%)",
                        "max": "Maksymalne obciążenie (%)",
                    })
                )
                load_summary["Średnie obciążenie (%)"] = load_summary["Średnie obciążenie (%)"].fillna(0).round(1)
                load_summary["Maksymalne obciążenie (%)"] = load_summary["Maksymalne obciążenie (%)"].fillna(0).round(1)
                load_fig = px.bar(
                    load_summary.sort_values("Średnie obciążenie (%)", ascending=False),
                    x="Brygada",
                    y="Średnie obciążenie (%)",
                    hover_data=["Maksymalne obciążenie (%)"],
                    color_discrete_sequence=["#8d6aa5"],
                )
                load_fig.update_layout(margin=dict(l=0, r=0, t=12, b=0), height=320)
                st.plotly_chart(load_fig, use_container_width=True)
    except Exception:
        with chart_cols[0]:
            st.subheader("Status prac")
            st.dataframe(status_summary, hide_index=True, use_container_width=True)
        with chart_cols[1]:
            st.subheader("Obciążenie brygad")
            show_dataframe(load_df, max_rows=20)

    st.subheader("Zadania niezaplanowane")
    if unplanned_df.empty:
        st.success("Brak zadań niezaplanowanych.")
    else:
        unplanned_columns = [
            "id_zadania",
            "typ_pracy",
            "nazwa_zadania",
            "pracochlonnosc_h",
            "powod_niezaplanowania",
            "rekomendowana_akcja",
        ]
        unplanned_columns = [column for column in unplanned_columns if column in unplanned_df.columns]
        st.dataframe(
            unplanned_df[unplanned_columns].rename(columns={
                "id_zadania": "ID",
                "typ_pracy": "Typ pracy",
                "nazwa_zadania": "Zadanie",
                "pracochlonnosc_h": "Godziny",
                "powod_niezaplanowania": "Powód",
                "rekomendowana_akcja": "Rekomendowana akcja",
            }),
            hide_index=True,
            use_container_width=True,
            height=min(420, max(160, 38 * (len(unplanned_df) + 1))),
        )


def approve_current_schedule():
    results = st.session_state.get("schedule_results")
    if results is None:
        return

    plan_df = ensure_execution_status(results.get("plan", pd.DataFrame()))
    if plan_df.empty:
        return

    plan_df["status"] = "Zatwierdzony"
    results["plan"] = plan_df

    log_entry = pd.DataFrame([{
        "id_zadania": None,
        "etap": "Zatwierdzenie harmonogramu",
        "decyzja": "Zatwierdzono harmonogram",
        "uzasadnienie": "Status wszystkich pozycji harmonogramu ustawiono na Zatwierdzony.",
        "data_czas_logu": datetime.now(),
    }])
    results["log"] = pd.concat(
        [results.get("log", pd.DataFrame()), log_entry],
        ignore_index=True,
    )

    st.session_state["schedule_results"] = results
    st.session_state["approved"] = True
    st.session_state["rdm_changes_pending_approval"] = False
    save_current_results_to_excel()


def sync_approval_from_plan_status(plan_df):
    if plan_df is None or plan_df.empty or "status" not in plan_df.columns:
        st.session_state["approved"] = False
        return
    st.session_state["approved"] = bool((plan_df["status"] == "Zatwierdzony").all())


def update_single_plan_status(row_index, new_status):
    results = st.session_state.get("schedule_results")
    if results is None:
        return

    plan_df = ensure_execution_status(results.get("plan", pd.DataFrame()))
    if row_index not in plan_df.index:
        return

    old_status = plan_df.loc[row_index, "status"]
    plan_df.loc[row_index, "status"] = new_status
    results["plan"] = plan_df

    log_entry = pd.DataFrame([{
        "id_zadania": plan_df.loc[row_index, "id_zadania"] if "id_zadania" in plan_df.columns else None,
        "etap": "Status harmonogramu",
        "decyzja": f"Zmieniono status harmonogramu z {old_status} na {new_status}",
        "data_czas_logu": datetime.now(),
    }])
    results["log"] = pd.concat(
        [results.get("log", pd.DataFrame()), log_entry],
        ignore_index=True,
    )

    st.session_state["schedule_results"] = results
    sync_approval_from_plan_status(plan_df)
    save_current_results_to_excel()


def update_single_task_status(row_index, new_status):
    results = st.session_state.get("schedule_results")
    if results is None:
        return

    plan_df = ensure_execution_status(results.get("plan", pd.DataFrame()))
    if row_index not in plan_df.index:
        return

    old_status = plan_df.loc[row_index, "status_wykonania"]
    plan_df.loc[row_index, "status_wykonania"] = new_status
    results["plan"] = plan_df

    log_entry = pd.DataFrame([{
        "id_zadania": plan_df.loc[row_index, "id_zadania"] if "id_zadania" in plan_df.columns else None,
        "etap": "Status zadania",
        "decyzja": f"Zmieniono status zadania z {old_status} na {new_status}",
        "data_czas_logu": datetime.now(),
    }])
    results["log"] = pd.concat(
        [results.get("log", pd.DataFrame()), log_entry],
        ignore_index=True,
    )

    st.session_state["schedule_results"] = results
    save_current_results_to_excel()


def classify_rdm_report(uploaded_report):
    input_path = save_uploaded_file(uploaded_report, f"rdm_report_{uploaded_report.name}")
    output_path = os.path.join(os.getcwd(), "rdm_klasyfikacja_output.xlsx")
    classified = classify_file(input_path, output_path)
    classified = sort_rdm_classification(classified)
    st.session_state["rdm_classification"] = classified
    st.session_state["rdm_classification_output_path"] = output_path
    st.session_state["rdm_import_summary"] = None
    return classified


def sort_rdm_classification(classified_df):
    if classified_df is None or classified_df.empty:
        return classified_df

    sorted_df = classified_df.copy()
    for column in ["data_wymagana", "data_czas_kwalifikacji"]:
        if column in sorted_df.columns:
            sorted_df[column] = pd.to_datetime(sorted_df[column], errors="coerce")

    sort_columns = [
        column
        for column in ["data_wymagana", "data_czas_kwalifikacji", "wynik_priorytet_operacyjny", "id_zgloszenia_rdm"]
        if column in sorted_df.columns
    ]
    if sort_columns:
        sorted_df = sorted_df.sort_values(sort_columns, kind="stable").reset_index(drop=True)
    return sorted_df


def should_show_rdm_ai_notice():
    classified = st.session_state.get("rdm_classification")
    return (
        classified is not None
        and not classified.empty
        and st.session_state.get("rdm_import_summary") is None
    )


def get_rdm_value(row, column, default=None):
    if column in row.index and not pd.isna(row[column]):
        return row[column]
    return default


def is_yes(value):
    return str(value).strip().lower() == "tak"


def rdm_priority_to_schedule_priority(value):
    return {"P2": 1, "P3": 2, "P4": 3}.get(str(value).strip().upper(), 2)


def build_plan_rows_from_rdm(classified_df):
    rows = []
    rejected = 0
    decision = 0

    for _, row in classified_df.iterrows():
        create_task = get_rdm_value(row, "wynik_czy_utworzyc_zadanie_planistyczne", "Nie")
        report_status = get_rdm_value(row, "wynik_status_raportu", "")
        priority = get_rdm_value(row, "wynik_priorytet_operacyjny", "")
        life_risk = get_rdm_value(row, "czy_zagrozenie_zycia_lub_zdrowia", "")
        task_type_id = get_rdm_value(row, "wynik_id_typu_zadania")
        competencies = get_rdm_value(row, "wynik_wymagane_kompetencje")
        people = get_rdm_value(row, "wynik_minimalna_liczba_osob")

        ready = (
            is_yes(create_task)
            and report_status == "Gotowe do importu"
            and priority != "P1"
            and not is_yes(life_risk)
            and task_type_id not in [None, ""]
            and competencies not in [None, ""]
            and people not in [None, ""]
        )
        if not ready:
            if report_status == "Do decyzji":
                decision += 1
            else:
                rejected += 1
            continue

        required_date = pd.to_datetime(get_rdm_value(row, "data_wymagana"), errors="coerce")
        if pd.isna(required_date):
            required_date = pd.to_datetime(get_rdm_value(row, "data_czas_kwalifikacji"), errors="coerce")
        if pd.isna(required_date):
            required_date = pd.Timestamp(datetime.today().date())

        incident_code = get_rdm_value(row, "wynik_kod_typu_awarii", "")
        incident_name = get_rdm_value(row, "wynik_nazwa_typu_awarii", "")
        task_name = get_rdm_value(row, "wynik_rekomendowany_typ_zadania", incident_name)
        hours = pd.to_numeric(get_rdm_value(row, "wynik_szacowana_pracochlonnosc_h", 0), errors="coerce")
        quantity = pd.to_numeric(get_rdm_value(row, "wynik_ilosc", 1), errors="coerce")

        rows.append({
            "data": required_date,
            "brygada": "Do przydziału",
            "id_zadania": get_rdm_value(row, "id_zgloszenia_rdm"),
            "czesc_zadania": 1,
            "typ_pracy": "Awaria RDM",
            "id_typu_zadania": task_type_id,
            "nazwa_zadania": f"{incident_code} - {task_name}" if incident_code else task_name,
            "obszar_infrastruktury": get_rdm_value(row, "obszar_infrastruktury", ""),
            "ulica": get_rdm_value(row, "ulica", ""),
            "miasto": get_rdm_value(row, "miasto", ""),
            "ilosc_zaplanowana": 0 if pd.isna(quantity) else quantity,
            "jednostka": get_rdm_value(row, "wynik_jednostka", "szt."),
            "zaplanowane_godziny": 0 if pd.isna(hours) else hours,
            "wymagane_kompetencje": competencies,
            "priorytet": rdm_priority_to_schedule_priority(priority),
            "czy_termin_sztywny": get_rdm_value(row, "czy_termin_sztywny", "Nie"),
            "data_wymagana": required_date,
            "status": "Wymaga decyzji",
            "status_wykonania": "Do wykonania",
            "zrodlo_zadania": "Rejestr awarii RDM",
        })

    rows_df = pd.DataFrame(rows)
    if not rows_df.empty:
        rows_df["data_wymagana"] = pd.to_datetime(rows_df["data_wymagana"], errors="coerce")
        rows_df["data"] = pd.to_datetime(rows_df["data"], errors="coerce")
        sort_columns = [column for column in ["data_wymagana", "data", "priorytet", "id_zadania"] if column in rows_df.columns]
        rows_df = rows_df.sort_values(sort_columns, kind="stable").reset_index(drop=True)
    return rows_df, rejected, decision


def import_rdm_classification_to_schedule():
    classified = st.session_state.get("rdm_classification")
    results = st.session_state.get("schedule_results")
    if classified is None or classified.empty or results is None:
        return {"imported": 0, "skipped_duplicates": 0, "rejected": 0, "decision": 0}

    plan_df = ensure_execution_status(results.get("plan", pd.DataFrame()))
    new_rows, rejected, decision = build_plan_rows_from_rdm(classified)
    if new_rows.empty:
        return {"imported": 0, "skipped_duplicates": 0, "rejected": rejected, "decision": decision}

    existing_ids = set(plan_df.get("id_zadania", pd.Series(dtype=str)).astype(str))
    new_rows = new_rows[~new_rows["id_zadania"].astype(str).isin(existing_ids)]
    skipped_duplicates = len(build_plan_rows_from_rdm(classified)[0]) - len(new_rows)

    if not new_rows.empty:
        results["plan"] = pd.concat([plan_df, new_rows], ignore_index=True)
        results["plan"] = ensure_execution_status(results["plan"])
        if "data" in results["plan"].columns:
            results["plan"]["data"] = pd.to_datetime(results["plan"]["data"], errors="coerce")
            sort_columns = [column for column in ["data", "priorytet", "id_zadania"] if column in results["plan"].columns]
            results["plan"] = results["plan"].sort_values(sort_columns, kind="stable").reset_index(drop=True)
        results["log"] = pd.concat([
            results.get("log", pd.DataFrame()),
            pd.DataFrame([{
                "id_zadania": None,
                "etap": "Import RDM",
                "decyzja": "Zaimportowano zakwalifikowane awarie RDM do harmonogramu",
                "uzasadnienie": f"Liczba dodanych pozycji: {len(new_rows)}.",
                "data_czas_logu": datetime.now(),
            }]),
        ], ignore_index=True)
        st.session_state["schedule_results"] = results
        st.session_state["approved"] = False
        st.session_state["rdm_changes_pending_approval"] = True
        save_current_results_to_excel()

    summary = {
        "imported": len(new_rows),
        "skipped_duplicates": skipped_duplicates,
        "rejected": rejected,
        "decision": decision,
    }
    st.session_state["rdm_import_summary"] = summary
    return summary


def ensure_execution_status(plan_df):
    if plan_df is None:
        return pd.DataFrame()
    plan_df = plan_df.copy()
    if "status_wykonania" not in plan_df.columns:
        plan_df["status_wykonania"] = "Do wykonania"
    plan_df["status_wykonania"] = plan_df["status_wykonania"].fillna("Do wykonania")
    if "status" not in plan_df.columns:
        plan_df["status"] = "Rekomendowany"
    plan_df["status"] = plan_df["status"].fillna("Rekomendowany")
    return plan_df


def enrich_plan_addresses_from_input(plan_df):
    if plan_df is None or plan_df.empty or "id_zadania" not in plan_df.columns:
        return plan_df
    if {"ulica", "miasto"}.issubset(plan_df.columns):
        return plan_df

    input_paths = st.session_state.get("input_paths") or {}
    planning_path = input_paths.get("planowanie")
    if not planning_path or not os.path.exists(planning_path):
        return plan_df

    try:
        source_df = pd.read_excel(planning_path, sheet_name="01_plan_miesieczny", engine="openpyxl")
    except Exception:
        return plan_df

    address_columns = [column for column in ["id_zadania", "ulica", "miasto"] if column in source_df.columns]
    if "id_zadania" not in address_columns or len(address_columns) == 1:
        return plan_df

    address_df = source_df[address_columns].drop_duplicates("id_zadania")
    enriched_df = plan_df.merge(address_df, on="id_zadania", how="left", suffixes=("", "_src"))
    for column in ["ulica", "miasto"]:
        source_column = f"{column}_src"
        if source_column in enriched_df.columns:
            if column in enriched_df.columns:
                enriched_df[column] = enriched_df[column].fillna(enriched_df[source_column])
            else:
                enriched_df[column] = enriched_df[source_column]
            enriched_df = enriched_df.drop(columns=[source_column])
    return enriched_df


def filter_plan_table(plan_df, key_prefix):
    if plan_df is None or plan_df.empty:
        return pd.DataFrame()

    filtered = plan_df.copy()
    if "data" in filtered.columns:
        filtered["data"] = pd.to_datetime(filtered["data"], errors="coerce")

    filter_cols = st.columns(4)
    dates = sorted(filtered["data"].dropna().dt.date.astype(str).unique()) if "data" in filtered.columns else []
    types = sorted(filtered["typ_pracy"].dropna().astype(str).unique()) if "typ_pracy" in filtered.columns else []
    brigades = sorted(filtered["brygada"].dropna().astype(str).unique()) if "brygada" in filtered.columns else []
    task_statuses = sorted(filtered["status_wykonania"].dropna().astype(str).unique()) if "status_wykonania" in filtered.columns else []

    selected_date = filter_cols[0].selectbox("Dzień", ["Wszystkie"] + dates, key=f"{key_prefix}_date")
    selected_type = filter_cols[1].selectbox("Typ awarii / pracy", ["Wszystkie"] + types, key=f"{key_prefix}_type")
    selected_brigade = filter_cols[2].selectbox("Brygada", ["Wszystkie"] + brigades, key=f"{key_prefix}_brigade")
    selected_task_status = filter_cols[3].selectbox("Status zadania", ["Wszystkie"] + task_statuses, key=f"{key_prefix}_task_status")

    if selected_date != "Wszystkie" and "data" in filtered.columns:
        filtered = filtered[filtered["data"].dt.date.astype(str) == selected_date]
    if selected_type != "Wszystkie" and "typ_pracy" in filtered.columns:
        filtered = filtered[filtered["typ_pracy"].astype(str) == selected_type]
    if selected_brigade != "Wszystkie" and "brygada" in filtered.columns:
        filtered = filtered[filtered["brygada"].astype(str) == selected_brigade]
    if selected_task_status != "Wszystkie" and "status_wykonania" in filtered.columns:
        filtered = filtered[filtered["status_wykonania"].astype(str) == selected_task_status]

    return filtered


def mark_emergency_source(plan_df):
    if plan_df is None or plan_df.empty:
        return plan_df

    marked_df = plan_df.copy()
    masks = []
    for column in ["typ_pracy", "wymagane_kompetencje", "id_zadania", "nazwa_zadania", "zrodlo_zadania"]:
        if column in marked_df.columns:
            masks.append(marked_df[column].fillna("").astype(str).str.contains("awari|rdm", case=False, regex=True))
    if masks:
        mask = masks[0]
        for item in masks[1:]:
            mask = mask | item
    else:
        mask = pd.Series(False, index=marked_df.index)
    marked_df["Źródło"] = mask.map({True: "Awaria", False: "Plan"})
    return marked_df


def get_emergency_mask(plan_df):
    if plan_df is None or plan_df.empty:
        return pd.Series(False, index=plan_df.index if plan_df is not None else None)
    marked_df = mark_emergency_source(plan_df)
    return marked_df["Źródło"].astype(str).str.lower() == "awaria"


def format_emergency_option(row):
    date_value = pd.to_datetime(row.get("data"), errors="coerce")
    date_label = date_value.strftime("%Y-%m-%d") if not pd.isna(date_value) else "bez daty"
    task_id = row.get("id_zadania", "brak ID")
    task_name = str(row.get("nazwa_zadania", "Awaria")).strip()
    if len(task_name) > 80:
        task_name = f"{task_name[:77]}..."
    return f"{date_label} | {task_id} | {task_name}"


def approve_emergency_rows(row_indices):
    results = st.session_state.get("schedule_results")
    if results is None:
        return 0

    plan_df = ensure_execution_status(results.get("plan", pd.DataFrame()))
    valid_indices = [idx for idx in row_indices if idx in plan_df.index]
    if not valid_indices:
        return 0

    plan_df.loc[valid_indices, "status"] = "Zatwierdzony"
    results["plan"] = plan_df

    emergency_mask = get_emergency_mask(plan_df)
    pending_emergency_mask = emergency_mask & (plan_df["status"].astype(str) != "Zatwierdzony")
    st.session_state["rdm_changes_pending_approval"] = bool(pending_emergency_mask.any())
    sync_approval_from_plan_status(plan_df)

    log_entry = pd.DataFrame([{
        "id_zadania": None,
        "etap": "Akceptacja awarii RDM",
        "decyzja": f"Zatwierdzono awarie RDM: {len(valid_indices)} pozycji",
        "uzasadnienie": "Decyzja kierownika wykonawstwa po weryfikacji zmian z rejestru awarii.",
        "data_czas_logu": datetime.now(),
    }])
    results["log"] = pd.concat(
        [results.get("log", pd.DataFrame()), log_entry],
        ignore_index=True,
    )
    st.session_state["schedule_results"] = results
    save_current_results_to_excel()
    return len(valid_indices)


def get_emergency_tasks(plan_df):
    if plan_df is None or plan_df.empty:
        return pd.DataFrame()
    emergency_df = ensure_execution_status(plan_df)
    masks = []
    for column in ["typ_pracy", "wymagane_kompetencje", "id_zadania", "nazwa_zadania"]:
        if column in emergency_df.columns:
            masks.append(emergency_df[column].fillna("").astype(str).str.contains("awari|rdm", case=False, regex=True, na=False))
    if not masks:
        return pd.DataFrame()
    mask = masks[0]
    for item in masks[1:]:
        mask = mask | item
    emergency_df = emergency_df[mask].copy()
    if "data" in emergency_df.columns:
        emergency_df["data"] = pd.to_datetime(emergency_df["data"], errors="coerce")
        emergency_df = emergency_df.sort_values(["data", "brygada"], na_position="last")
    return emergency_df


def render_emergency_list(plan_df):
    emergency_df = get_emergency_tasks(plan_df)
    if emergency_df.empty:
        st.info("Brak zgłoszonych awarii.")
        return

    display_emergencies = emergency_df.copy()
    if "data" in display_emergencies.columns:
        display_emergencies["data"] = pd.to_datetime(display_emergencies["data"], errors="coerce").dt.strftime("%Y-%m-%d")
    emergency_columns = [
        "data",
        "brygada",
        "id_zadania",
        "nazwa_zadania",
        "obszar_infrastruktury",
        "ulica",
        "miasto",
        "zaplanowane_godziny",
        "priorytet",
        "status",
        "status_wykonania",
    ]
    emergency_columns = [column for column in emergency_columns if column in display_emergencies.columns]
    st.dataframe(
        display_emergencies[emergency_columns].rename(columns={
            "data": "Data",
            "brygada": "Brygada",
            "id_zadania": "ID",
            "nazwa_zadania": "Awaria",
            "obszar_infrastruktury": "Obszar",
            "ulica": "Ulica",
            "miasto": "Miasto",
            "zaplanowane_godziny": "Godz.",
            "priorytet": "Priorytet",
            "status": "Status",
            "status_wykonania": "Status wykonania",
        }),
        hide_index=True,
        use_container_width=True,
    )


st.markdown("""
<style>
    :root {
        --ne-bg: #faf8fc;
        --ne-surface: #ffffff;
        --ne-surface-muted: #f2edf5;
        --ne-border: #ddd2e6;
        --ne-text: #2a2230;
        --ne-muted: #6f6178;
        --ne-primary: #7c5a9b;
        --ne-primary-dark: #64487e;
        --ne-primary-soft: #eee6f4;
        --ne-amber: #a16207;
        --ne-amber-soft: #fef3c7;
        --ne-green: #15803d;
        --ne-green-soft: #dcfce7;
        --ne-red: #be123c;
        --ne-red-soft: #ffe4e6;
        --ne-blue: #9a5c7d;
        --ne-blue-soft: #f5e8ef;
    }

    html, body, [data-testid="stAppViewContainer"] {
        background: var(--ne-bg);
        color: var(--ne-text);
    }

    .block-container {
        max-width: 1480px;
        padding-left: 2rem;
        padding-right: 2rem;
        padding-top: 1.05rem;
        padding-bottom: 2.5rem;
    }

    h1, h2, h3 {
        color: var(--ne-text);
        letter-spacing: 0;
    }

    h1 {
        font-size: 1.75rem;
        font-weight: 700;
        line-height: 1.25;
        padding-top: 0.05rem;
        margin-bottom: 0.75rem;
    }

    .top-safe-spacer {
        height: 0.8rem;
        min-height: 0.8rem;
        visibility: hidden;
    }

    h3 {
        font-size: 1.15rem;
        font-weight: 700;
        padding-bottom: 0.35rem;
        border-bottom: 1px solid var(--ne-border);
    }

    .main-header {
        font-size: 2em;
        color: var(--ne-primary);
        text-align: center;
        margin-bottom: 20px;
    }

    [data-testid="stSidebar"] {
        background:
            radial-gradient(circle at 18% 4%, rgba(214, 184, 220, 0.28) 0, rgba(214, 184, 220, 0) 28%),
            radial-gradient(circle at 92% 34%, rgba(188, 137, 166, 0.24) 0, rgba(188, 137, 166, 0) 34%),
            linear-gradient(180deg, #625071 0%, #725a7c 48%, #806171 100%);
        border-right: 1px solid #a68faf;
        box-shadow: inset -1px 0 0 rgba(255, 255, 255, 0.12);
    }

    [data-testid="stSidebarContent"] {
        padding-top: 0.45rem;
    }

    [data-testid="stSidebar"] * {
        color: #fdf4ff;
    }

    [data-testid="stSidebar"] .stSelectbox label,
    [data-testid="stSidebar"] .stFileUploader label {
        color: #f5edf8;
        font-weight: 650;
    }

    [data-testid="stSidebar"] [data-baseweb="select"] > div {
        background: rgba(59, 45, 70, 0.82);
        border-color: #b49fc0;
        color: #ffffff;
    }

    [data-testid="stSidebar"] [data-testid="stExpander"] {
        background: rgba(255, 255, 255, 0.10);
        border: 1px solid rgba(235, 218, 240, 0.42);
        border-radius: 8px;
        box-shadow: 0 8px 18px rgba(48, 33, 58, 0.12);
    }

    [data-testid="stSidebar"] [data-testid="stExpanderDetails"] {
        padding: 0.7rem 0.75rem 1.25rem 0.75rem;
    }

    [data-testid="stSidebar"] [data-testid="stExpander"] summary {
        background: rgba(88, 67, 103, 0.82) !important;
        color: #ffffff !important;
    }

    [data-testid="stSidebar"] [data-testid="stFileUploaderDropzone"] {
        align-items: center;
        background: transparent;
        border: 0;
        justify-content: center;
        min-height: 2.9rem;
        min-width: 0;
        width: 100%;
        padding: 0.18rem 0 0.08rem 0;
        box-sizing: border-box;
    }

    [data-testid="stSidebar"] [data-testid="stFileUploader"] {
        width: 100%;
        min-width: 0;
        overflow: hidden;
    }

    [data-testid="stSidebar"] [data-testid="stFileUploaderDropzoneInstructions"],
    [data-testid="stSidebar"] [data-testid="stFileUploaderDropzone"] small,
    [data-testid="stSidebar"] [data-testid="stFileUploaderDropzone"] svg {
        display: none;
    }

    [data-testid="stSidebar"] [data-testid="stFileUploaderDropzone"] button {
        display: inline-flex;
        align-items: center;
        justify-content: center;
        width: 100% !important;
        min-width: 0;
        max-width: 100% !important;
        height: auto;
        min-height: 2.55rem;
        background: linear-gradient(180deg, #eadcf0 0%, #dbc7e4 100%) !important;
        border: 1px solid #c9b1d5 !important;
        border-radius: 7px;
        color: #31263d !important;
        font-size: 0;
        font-weight: 800;
        padding: 0.55rem 0.7rem;
        text-align: center;
    }

    [data-testid="stSidebar"] [data-testid="stFileUploaderDropzone"] button:hover {
        background: linear-gradient(180deg, #eadcf0 0%, #dbc7e4 100%) !important;
        border-color: #c9b1d5 !important;
        color: #22192b !important;
    }

    [data-testid="stSidebar"] [data-testid="stFileUploaderDropzone"] button * {
        color: transparent !important;
        font-size: 0 !important;
    }

    [data-testid="stSidebar"] [data-testid="stFileUploaderDropzone"] button > div,
    [data-testid="stSidebar"] [data-testid="stFileUploaderDropzone"] button > span {
        display: none !important;
    }

    [data-testid="stSidebar"] [data-testid="stFileUploaderDropzone"] button svg,
    [data-testid="stSidebar"] [data-testid="stFileUploaderDropzone"] button [class*="icon"],
    [data-testid="stSidebar"] [data-testid="stFileUploaderDropzone"] button [data-testid*="icon"] {
        display: none !important;
        visibility: hidden !important;
    }

    [data-testid="stSidebar"] [data-testid="stFileUploaderDropzone"] button::after {
        content: "Wgraj";
        color: #31263d;
        font-size: 0.86rem;
        font-weight: 800;
        line-height: 1.15;
        margin: 0.08rem auto 0 auto;
        text-align: center;
        width: 100%;
    }

    [data-testid="stSidebar"] [data-testid="stFileUploaderDropzone"] *,
    [data-testid="stSidebar"] [data-testid="stAlert"] * {
        color: #2a2230 !important;
    }

    [data-testid="stSidebar"] .stCaptionContainer,
    [data-testid="stSidebar"] [data-testid="stExpander"] .stMarkdown p,
    [data-testid="stSidebar"] [data-testid="stExpander"] .stMarkdown strong {
        color: #fdf4ff !important;
    }

    [data-testid="stSidebar"] [data-testid="stExpander"] [data-testid="stAlert"] p {
        color: #2a2230 !important;
    }

    [data-testid="stSidebar"] [data-testid="stVerticalBlockBorderWrapper"] {
        background: linear-gradient(180deg, rgba(255, 255, 255, 0.14) 0%, rgba(255, 255, 255, 0.08) 100%);
        border: 1px solid rgba(241, 225, 246, 0.42);
        border-radius: 8px;
        padding: 0.9rem 1.05rem 1rem 1.05rem;
        margin-bottom: 1.05rem;
        box-shadow: 0 6px 16px rgba(56, 40, 65, 0.11);
    }

    [data-testid="stSidebar"] .stButton > button {
        width: 100%;
        min-width: 0;
        max-width: 100%;
        min-height: 2.25rem;
        height: auto;
        padding: 0.45rem 0.55rem;
        border-radius: 7px;
        font-size: 0.8rem;
        line-height: 1.15;
    }

    [data-testid="stSidebar"] [data-testid="stVerticalBlockBorderWrapper"] .stButton > button {
        background: linear-gradient(180deg, #eadcf0 0%, #dbc7e4 100%) !important;
        border: 1px solid #c9b1d5 !important;
        color: #31263d !important;
        font-size: 0.86rem;
        font-weight: 800;
        min-height: 2.55rem;
        padding: 0.55rem 0.7rem;
        text-align: center;
    }

    [data-testid="stSidebar"] [data-testid="stVerticalBlockBorderWrapper"] .stButton > button *,
    [data-testid="stSidebar"] [data-testid="stVerticalBlockBorderWrapper"] .stButton > button p,
    [data-testid="stSidebar"] [data-testid="stVerticalBlockBorderWrapper"] .stButton > button span {
        color: #31263d !important;
        font-size: 0.86rem !important;
        font-weight: 800 !important;
        line-height: 1.15 !important;
    }

    [data-testid="stSidebar"] [data-testid="stVerticalBlockBorderWrapper"] .stButton > button:hover {
        background: linear-gradient(180deg, #eadcf0 0%, #dbc7e4 100%) !important;
        border-color: #c9b1d5 !important;
        color: #22192b !important;
    }

    [data-testid="stSidebar"] [data-testid="stVerticalBlockBorderWrapper"] .stButton > button:hover *,
    [data-testid="stSidebar"] [data-testid="stVerticalBlockBorderWrapper"] .stButton > button:hover p,
    [data-testid="stSidebar"] [data-testid="stVerticalBlockBorderWrapper"] .stButton > button:hover span {
        color: #22192b !important;
    }

    [data-testid="stSidebar"] .st-key-reupload_planowanie button,
    [data-testid="stSidebar"] .st-key-reupload_hr button,
    [data-testid="stSidebar"] [class*="st-key-planowanie_upload_"] button,
    [data-testid="stSidebar"] [class*="st-key-hr_upload_"] button,
    [data-testid="stSidebar"] .st-key-planowanie_upload_0 button,
    [data-testid="stSidebar"] .st-key-planowanie_upload_1 button,
    [data-testid="stSidebar"] .st-key-planowanie_upload_2 button,
    [data-testid="stSidebar"] .st-key-hr_upload_0 button,
    [data-testid="stSidebar"] .st-key-hr_upload_1 button,
    [data-testid="stSidebar"] .st-key-hr_upload_2 button {
        align-items: center !important;
        background: linear-gradient(180deg, #eadcf0 0%, #dbc7e4 100%) !important;
        border: 1px solid #c9b1d5 !important;
        border-radius: 7px !important;
        color: #31263d !important;
        display: flex !important;
        font-size: 0.86rem !important;
        font-weight: 800 !important;
        justify-content: center !important;
        line-height: 1.15 !important;
        min-height: 2.55rem !important;
        width: 100% !important;
    }

    [data-testid="stSidebar"] .st-key-reupload_planowanie button *,
    [data-testid="stSidebar"] .st-key-reupload_planowanie button p,
    [data-testid="stSidebar"] .st-key-reupload_hr button *,
    [data-testid="stSidebar"] .st-key-reupload_hr button p,
    [data-testid="stSidebar"] [class*="st-key-planowanie_upload_"] button::after,
    [data-testid="stSidebar"] [class*="st-key-hr_upload_"] button::after,
    [data-testid="stSidebar"] .st-key-planowanie_upload_0 button::after,
    [data-testid="stSidebar"] .st-key-planowanie_upload_1 button::after,
    [data-testid="stSidebar"] .st-key-planowanie_upload_2 button::after,
    [data-testid="stSidebar"] .st-key-hr_upload_0 button::after,
    [data-testid="stSidebar"] .st-key-hr_upload_1 button::after,
    [data-testid="stSidebar"] .st-key-hr_upload_2 button::after {
        color: #31263d !important;
        font-size: 0.86rem !important;
        font-weight: 800 !important;
        line-height: 1.15 !important;
    }

    [data-testid="stSidebar"] .st-key-reupload_planowanie button:hover,
    [data-testid="stSidebar"] .st-key-reupload_hr button:hover,
    [data-testid="stSidebar"] [class*="st-key-planowanie_upload_"] button:hover,
    [data-testid="stSidebar"] [class*="st-key-hr_upload_"] button:hover,
    [data-testid="stSidebar"] .st-key-planowanie_upload_0 button:hover,
    [data-testid="stSidebar"] .st-key-planowanie_upload_1 button:hover,
    [data-testid="stSidebar"] .st-key-planowanie_upload_2 button:hover,
    [data-testid="stSidebar"] .st-key-hr_upload_0 button:hover,
    [data-testid="stSidebar"] .st-key-hr_upload_1 button:hover,
    [data-testid="stSidebar"] .st-key-hr_upload_2 button:hover {
        background: linear-gradient(180deg, #eadcf0 0%, #dbc7e4 100%) !important;
        border-color: #c9b1d5 !important;
        color: #31263d !important;
    }

    .st-key-nav_menu {
        display: flex;
        flex-direction: column;
        gap: 0.34rem;
        margin: 0.1rem 0 0.8rem 0;
    }

    .st-key-nav_menu .stButton > button {
        width: 100%;
        min-width: 100%;
        max-width: 100%;
        min-height: 2.34rem;
        height: auto;
        padding: 0.58rem 0.68rem;
        border: 1px solid rgba(239, 222, 245, 0.30);
        border-radius: 8px;
        background: linear-gradient(180deg, rgba(255, 255, 255, 0.13) 0%, rgba(255, 255, 255, 0.07) 100%);
        color: #fdf4ff !important;
        font-size: 0.9rem;
        font-weight: 750;
        line-height: 1.15;
        text-align: left;
        justify-content: flex-start;
        transition: background 120ms ease, border-color 120ms ease, color 120ms ease;
    }

    .st-key-nav_menu .stButton > button:hover {
        background: linear-gradient(180deg, rgba(255, 255, 255, 0.20) 0%, rgba(255, 255, 255, 0.11) 100%);
        border-color: rgba(246, 231, 249, 0.55);
        color: #ffffff !important;
    }

    .st-key-nav_menu .stButton > button[kind="primary"] {
        background: linear-gradient(180deg, #9a74a8 0%, #7f5d90 100%);
        border-color: rgba(253, 244, 255, 0.78);
        color: #ffffff !important;
        box-shadow: 0 8px 18px rgba(49, 31, 61, 0.20);
    }

    .st-key-nav_menu .stButton > button[kind="primary"]:hover {
        background: linear-gradient(180deg, #a27bad 0%, #866296 100%);
        border-color: rgba(255, 255, 255, 0.86);
        color: #ffffff !important;
    }

    .nav-menu {
        display: flex;
        flex-direction: column;
        gap: 0.34rem;
        margin: 0.1rem 0 0.8rem 0;
    }

    .nav-menu-title {
        color: #f5edf8;
        font-size: 0.78rem;
        font-weight: 800;
        letter-spacing: 0;
        margin: 0 0 0.12rem 0.1rem;
        text-transform: uppercase;
    }

    .nav-button {
        display: block;
        width: 100%;
        min-height: 2.34rem;
        padding: 0.58rem 0.68rem;
        border: 1px solid rgba(239, 222, 245, 0.30);
        border-radius: 8px;
        background: linear-gradient(180deg, rgba(255, 255, 255, 0.13) 0%, rgba(255, 255, 255, 0.07) 100%);
        color: #fdf4ff !important;
        font-size: 0.9rem;
        font-weight: 750;
        line-height: 1.15;
        text-decoration: none !important;
        transition: background 120ms ease, border-color 120ms ease, color 120ms ease;
    }

    .nav-button:hover {
        background: linear-gradient(180deg, rgba(255, 255, 255, 0.20) 0%, rgba(255, 255, 255, 0.11) 100%);
        border-color: rgba(246, 231, 249, 0.55);
        color: #ffffff !important;
        text-decoration: none !important;
    }

    .nav-button.active {
        background: linear-gradient(180deg, #fff8ff 0%, #f1e6f5 100%);
        border-color: #e1cfe7;
        color: #3c2e4a !important;
        box-shadow: 0 8px 18px rgba(49, 31, 61, 0.16);
    }

    .nav-button span {
        color: inherit !important;
    }

    .stAlert {
        border-radius: 8px;
        border: 1px solid var(--ne-border);
    }

    .stButton>button {
        background-color: var(--ne-primary);
        color: white;
        border: 1px solid var(--ne-primary);
        border-radius: 6px;
        font-weight: 650;
        min-height: 2.45rem;
        min-width: 0;
        max-width: 100%;
        white-space: normal;
        line-height: 1.2;
    }

    .stButton>button:hover {
        background-color: var(--ne-primary-dark);
        border-color: var(--ne-primary-dark);
        color: white;
    }

    .stDownloadButton>button {
        background-color: var(--ne-blue);
        color: white;
        border: 1px solid var(--ne-blue);
        border-radius: 6px;
        font-weight: 650;
        min-height: 2.35rem;
    }

    .stDownloadButton>button:hover {
        background-color: #7d4865;
        border-color: #7d4865;
        color: white;
    }

    .data-upload-card {
        background: transparent;
        border: 0;
        border-radius: 0;
        padding: 0;
        margin: 0 0 0.4rem 0;
        min-width: 0;
    }

    .data-upload-card--pending {
        background: transparent;
        border-color: transparent;
    }

    .data-upload-card span {
        display: block;
        color: #fef7ff;
        font-size: 0.74rem;
        font-weight: 750;
        line-height: 1.08;
        margin-bottom: 0.2rem;
        text-transform: uppercase;
        overflow-wrap: anywhere;
    }

    .data-upload-card strong {
        display: block;
        color: #ffffff;
        font-size: 0.8rem;
        font-weight: 650;
        line-height: 1.15;
        overflow: hidden;
        text-overflow: ellipsis;
        white-space: nowrap;
        max-width: 100%;
    }

    .data-upload-session {
        background: rgba(255, 255, 255, 0.12);
        border: 1px solid rgba(231, 214, 240, 0.34);
        border-radius: 7px;
        color: #fdf7ff;
        font-size: 0.78rem;
        font-weight: 700;
        line-height: 1.25;
        margin-top: 0.8rem;
        margin-bottom: 0.45rem;
        padding: 0.55rem 0.62rem 0.65rem 0.62rem;
        overflow-wrap: anywhere;
    }

    .data-upload-session.pending {
        background: rgba(255, 255, 255, 0.08);
        color: #f2e7f5;
    }

    .loaded-input-panel {
        background: var(--ne-surface);
        border: 1px solid var(--ne-border);
        border-left: 4px solid var(--ne-primary);
        border-radius: 8px;
        color: var(--ne-text);
        font-size: 0.92rem;
        line-height: 1.55;
        margin: 0.25rem 0 0.85rem 0;
        padding: 0.75rem 0.9rem;
        box-shadow: 0 1px 2px rgba(16, 32, 43, 0.06);
    }

    .loaded-input-panel span {
        display: block;
        color: var(--ne-primary-dark);
        font-size: 0.82rem;
        font-weight: 800;
        margin-bottom: 0.2rem;
        text-transform: uppercase;
    }

    [data-testid="stExpander"] {
        background: var(--ne-surface);
        border: 1px solid var(--ne-border);
        border-radius: 8px;
        overflow: hidden;
    }

    [data-testid="stExpander"] summary {
        font-weight: 700;
        color: var(--ne-text);
        background: var(--ne-surface-muted);
    }

    [data-testid="stMetric"] {
        background: var(--ne-surface);
        border: 1px solid var(--ne-border);
        border-radius: 8px;
        padding: 0.75rem 0.9rem;
    }

    [data-testid="stMetricLabel"] {
        color: var(--ne-muted);
    }

    [data-testid="stMetricValue"] {
        color: var(--ne-text);
        font-weight: 750;
    }

    [data-testid="stDataFrame"] {
        border: 1px solid var(--ne-border);
        border-radius: 8px;
        overflow: hidden;
        background: var(--ne-surface);
    }

    [data-baseweb="select"] > div,
    [data-baseweb="input"] > div,
    textarea {
        border-color: var(--ne-border);
        border-radius: 6px;
    }

    label {
        color: var(--ne-text);
        font-weight: 650;
    }

    .metric-card {
        background: var(--ne-surface);
        border: 1px solid var(--ne-border);
        border-left: 4px solid var(--ne-primary);
        border-radius: 8px;
        padding: 0.85rem 1rem;
        min-height: 88px;
        box-shadow: 0 1px 2px rgba(16, 32, 43, 0.06);
    }

    .metric-card h3 {
        border: 0;
        color: var(--ne-text);
        font-size: 1.5rem;
        line-height: 1.1;
        margin: 0 0 0.35rem 0;
        padding: 0;
    }

    .metric-card p {
        color: var(--ne-muted);
        font-size: 0.9rem;
        margin: 0;
    }

    .status-badge {
        display: inline-flex;
        align-items: center;
        min-height: 1.65rem;
        padding: 0.2rem 0.65rem;
        border-radius: 999px;
        border: 1px solid var(--ne-border);
        background: var(--ne-surface-muted);
        color: var(--ne-text);
        font-size: 0.85rem;
        font-weight: 750;
        white-space: nowrap;
    }

    .status-badge.ok {
        background: var(--ne-green-soft);
        border-color: #a8dec3;
        color: var(--ne-green);
    }

    .status-badge.warn {
        background: var(--ne-amber-soft);
        border-color: #ecc974;
        color: var(--ne-amber);
    }

    .status-badge.danger {
        background: var(--ne-red-soft);
        border-color: #f5afa7;
        color: var(--ne-red);
    }

    .status-badge.info {
        background: var(--ne-blue-soft);
        border-color: #adc9e8;
        color: var(--ne-blue);
    }
</style>
""", unsafe_allow_html=True)

if "schedule_results" not in st.session_state:
    st.session_state["schedule_results"] = None
if "input_paths" not in st.session_state:
    st.session_state["input_paths"] = None
if "uploaded_session_files" not in st.session_state:
    st.session_state["uploaded_session_files"] = {}
if "uploaded_session_meta" not in st.session_state:
    st.session_state["uploaded_session_meta"] = {}
if "upload_modes" not in st.session_state:
    st.session_state["upload_modes"] = {"planowanie": False, "hr": False, "rdm": False}
if "upload_versions" not in st.session_state:
    st.session_state["upload_versions"] = {"planowanie": 0, "hr": 0, "rdm": 0}
if "approved" not in st.session_state:
    st.session_state["approved"] = False
if "replan_summary" not in st.session_state:
    st.session_state["replan_summary"] = None
if "stale_path" not in st.session_state:
    st.session_state["stale_path"] = DEFAULT_STALE_PATH
if "stale_tables" not in st.session_state:
    st.session_state["stale_tables"] = None
if "stale_editor_version" not in st.session_state:
    st.session_state["stale_editor_version"] = 0
if "uploaded_emergency_report_meta" not in st.session_state:
    st.session_state["uploaded_emergency_report_meta"] = None
if "rdm_classification" not in st.session_state:
    st.session_state["rdm_classification"] = None
if "rdm_classification_output_path" not in st.session_state:
    st.session_state["rdm_classification_output_path"] = None
if "rdm_import_summary" not in st.session_state:
    st.session_state["rdm_import_summary"] = None
if "rdm_changes_pending_approval" not in st.session_state:
    st.session_state["rdm_changes_pending_approval"] = False
if "training_prompt_seen" not in st.session_state:
    st.session_state["training_prompt_seen"] = False
if "show_training_dialog" not in st.session_state:
    st.session_state["show_training_dialog"] = not st.session_state["training_prompt_seen"]
if "training_step" not in st.session_state:
    st.session_state["training_step"] = 0

DATA_BASIC_PAGES = [
    "Dane wejściowe",
    "Dane stałe",
    "Walidacja",
    "Konflikty",
    "KPI i jakość planu",
    "Log decyzji",
    "Eksport",
]
PAGES = [
    "Zarządzanie Harmonogramem",
    "Harmonogram",
    "Przeplanowanie",
    "Rejestr Awarii",
    "Dashboard",
    "Dane podstawowe",
]
DEFAULT_PAGE = "Zarządzanie Harmonogramem"

pending_nav_page = st.session_state.pop("pending_nav_page", None)
if pending_nav_page in PAGES:
    st.session_state["nav_page"] = pending_nav_page
    st.query_params["nav"] = pending_nav_page
elif get_query_nav_page() in PAGES:
    st.session_state["nav_page"] = get_query_nav_page()
elif "default_nav_page_applied" not in st.session_state:
    st.session_state["nav_page"] = DEFAULT_PAGE
    st.session_state["default_nav_page_applied"] = True
elif "nav_page" not in st.session_state or st.session_state["nav_page"] not in PAGES:
    st.session_state["nav_page"] = DEFAULT_PAGE
page = st.session_state["nav_page"]
render_sidebar_navigation(page)
PLAN_BUTTON_HELP = "Aplikacja generuje rekomendację. Decyzję podejmuje kierownik wykonawstwa."

if st.sidebar.button("Jak zacząć?", use_container_width=True):
    st.session_state["show_training_dialog"] = True
    st.session_state["training_step"] = 0
    st.rerun()

if st.session_state.get("show_training_dialog", False):
    render_training_dialog()

with st.sidebar.expander("Dane", expanded=True):
    stale_path = st.session_state["stale_path"]

    render_data_upload(
        "planowanie",
        "Dział planowania",
        "planowanie_brygad_Dzial_planowania.xlsx",
        ["xlsx"],
    )
    render_data_upload(
        "hr",
        "Brygady",
        "planowanie_brygad_HR.xlsx",
        ["xlsx"],
    )
    
    session_files = st.session_state["uploaded_session_files"]
    if "planowanie" in session_files and "hr" in session_files:
        if os.path.exists(stale_path):
            st.session_state["input_paths"] = {
                "planowanie": session_files["planowanie"],
                "hr": session_files["hr"],
                "stale": stale_path
            }
            st.markdown("<div class='data-upload-session'>Gotowe do planowania</div>", unsafe_allow_html=True)
        else:
            st.session_state["input_paths"] = None
            st.error("Brak danych stałych w aplikacji.")
    else:
        st.session_state["input_paths"] = None
        missing = []
        if "planowanie" not in session_files:
            missing.append("Dział planowania")
        if "hr" not in session_files:
            missing.append("Brygady")
        st.markdown(
            f"<div class='data-upload-session pending'>Brakuje: {escape(', '.join(missing))}</div>",
            unsafe_allow_html=True,
        )

st.markdown("<div class='top-safe-spacer'></div>", unsafe_allow_html=True)
st.title("Nowa Energia — Harmonogram pracy")
active_page = page
if page == "Dane podstawowe":
    if st.session_state.get("data_basic_page") not in DATA_BASIC_PAGES:
        st.session_state["data_basic_page"] = DATA_BASIC_PAGES[0]
    active_page = st.selectbox("Sekcja", DATA_BASIC_PAGES, key="data_basic_page")

if active_page == "Dashboard":
    section_title("Dashboard")
    render_operations_dashboard(st.session_state["schedule_results"])

elif active_page == "Dane wejściowe":
    section_title("Dane wejściowe")
    if st.session_state["input_paths"] is None:
        st.info("Wczytaj pliki planowania i HR w sekcji bocznej. Dane stałe ustawiasz w aplikacji.")
    else:
        for key, path in st.session_state["input_paths"].items():
            if key == "stale":
                continue
            st.subheader(f"Plik: {key}")
            try:
                xls = pd.ExcelFile(path, engine="openpyxl")
                for sheet in xls.sheet_names:
                    st.write(f"Arkusz: {sheet}")
                    df = pd.read_excel(xls, sheet_name=sheet, engine="openpyxl")
                    st.write(f"Liczba wierszy: {len(df)}")
                    show_dataframe(df)
            except Exception as exc:
                st.error(f"Nie można wczytać pliku {key}: {exc}")

elif active_page == "Dane stałe":
    section_title("Dane stałe")
    stale_path = st.session_state["stale_path"]
    st.write("Tutaj zmieniasz stałe używane do planowania. Nie trzeba dodawać osobnego pliku.")

    if not os.path.exists(stale_path):
        st.error("Brak danych stałych w aplikacji.")
    else:
        try:
            if st.session_state["stale_tables"] is None:
                st.session_state["stale_tables"] = load_workbook_tables(stale_path)

            tables = st.session_state["stale_tables"]
            selected_sheet = st.selectbox("Arkusz", list(tables.keys()), key="stale_selected_sheet")
            st.write(f"Liczba wierszy: {len(tables[selected_sheet])}")

            if selected_sheet == "05_parametry":
                st.caption("Zmieniaj tylko wartości. Nazwy parametrów są zablokowane.")
                source_df = tables[selected_sheet].copy()
                edited_df = source_df.copy()

                with st.form(f"stale_form_{selected_sheet}_{st.session_state['stale_editor_version']}"):
                    new_values = []
                    for row_index, row in source_df.iterrows():
                        label_col, value_col = st.columns([2, 3])
                        label_col.text(str(row.get("parametr", "")))
                        new_value = value_col.text_input(
                            "wartosc",
                            value="" if pd.isna(row.get("wartosc")) else str(row.get("wartosc")),
                            key=f"param_value_{row_index}_{st.session_state['stale_editor_version']}",
                            label_visibility="collapsed",
                        )
                        new_values.append(new_value)

                    cols = st.columns(2)
                    save_stale = cols[0].form_submit_button("Zapisz zmiany")
                    reload_stale = cols[1].form_submit_button("Cofnij niezapisane zmiany")

                edited_df["wartosc"] = new_values
            else:
                with st.form(f"stale_form_{selected_sheet}"):
                    edited_df = st.data_editor(
                        tables[selected_sheet],
                        hide_index=True,
                        use_container_width=True,
                        num_rows="dynamic",
                        key=f"stale_editor_{selected_sheet}_{st.session_state['stale_editor_version']}",
                    )

                    cols = st.columns(2)
                    save_stale = cols[0].form_submit_button("Zapisz zmiany")
                    reload_stale = cols[1].form_submit_button("Cofnij niezapisane zmiany")

            if save_stale:
                st.session_state["stale_tables"][selected_sheet] = edited_df
                save_workbook_tables(stale_path, st.session_state["stale_tables"])
                st.session_state["schedule_results"] = None
                st.success("Zmiany zapisane w aplikacji. Uruchom planowanie ponownie, aby użyć zmian.")
            if reload_stale:
                st.session_state["stale_tables"] = load_workbook_tables(stale_path)
                st.session_state["stale_editor_version"] += 1
                st.rerun()
        except Exception as exc:
            st.error(f"Nie można edytować danych stałych: {exc}")

elif active_page == "Walidacja":
    section_title("Walidacja")
    if st.session_state["schedule_results"] is None:
        st.info("Uruchom planowanie, aby zobaczyć walidację.")
    else:
        validation = st.session_state["schedule_results"]["validation"]
        render_status_badge(validation.get("status", "Brak danych"))
        st.subheader("Błędy krytyczne")
        if validation.get("errors"):
            st.json(validation.get("errors"))
        else:
            st.write("Brak błędów krytycznych.")
        st.subheader("Ostrzeżenia")
        if validation.get("warnings"):
            st.json(validation.get("warnings"))
        else:
            st.write("Brak ostrzeżeń.")
        st.subheader("Braki danych")
        show_dataframe(validation.get("missing_data", pd.DataFrame()))
        st.subheader("Konflikty wejściowe")
        show_dataframe(validation.get("conflicts", pd.DataFrame()))

elif active_page == "Harmonogram":
    section_title("Harmonogram")

    if st.session_state["schedule_results"] is None:
        st.info(
            "Ta zakładka pokazuje wyłącznie ostateczny, zatwierdzony harmonogram. "
            "Uruchom planowanie i zatwierdź wynik w zakładce „Zarządzanie Harmonogramem”."
        )
    elif not st.session_state["approved"]:
        if st.session_state.get("rdm_changes_pending_approval", False):
            st.warning(
                "Wgrano rejestr awarii RDM i dodano zmiany do harmonogramu. "
                "Zanim harmonogram będzie ostateczny, kierownik wykonawstwa musi zweryfikować i zaakceptować te zmiany "
                "w zakładce „Zarządzanie Harmonogramem”."
            )
        else:
            st.warning("Brak harmonogramu do wyświetlenia.")
            st.info(
                "Zatwierdź wygenerowany harmonogram w zakładce „Zarządzanie harmonogramem”, "
                "aby zobaczyć go tutaj."
            )
    else:
        st.session_state["schedule_results"]["plan"] = ensure_execution_status(st.session_state["schedule_results"]["plan"])
        plan_df = enrich_plan_addresses_from_input(st.session_state["schedule_results"]["plan"])
        st.session_state["schedule_results"]["plan"] = plan_df
        if plan_df.empty:
            st.warning("Brak zaplanowanych zadań.")
        else:
            validation = st.session_state["schedule_results"].get("validation", {})
            stats = {
                "tasks_total": validation.get("counts", {}).get("tasks_total", 0),
                "planned_count": len(plan_df),
                "unplanned_count": len(st.session_state["schedule_results"].get("unplanned", pd.DataFrame())),
                "conflict_count": len(st.session_state["schedule_results"].get("conflicts", pd.DataFrame())),
            }
            render_management_summary_cards(stats)
            metric_cols = st.columns(4)
            metric_cols[0].metric("Wykonane", len(plan_df[plan_df["status_wykonania"] == "Wykonane"]))
            metric_cols[1].metric("Pozostało", len(plan_df[plan_df["status_wykonania"] != "Wykonane"]))
            metric_cols[2].write("**Status danych:**")
            with metric_cols[2]:
                render_status_badge(validation.get("status", "Brak danych"))
            metric_cols[3].write("**Status harmonogramu:**")
            with metric_cols[3]:
                render_status_badge("Zatwierdzony" if st.session_state["approved"] else "Rekomendowany")

            header_cols = st.columns([4, 1])
            with header_cols[0]:
                st.subheader("Pełny harmonogram")
            with header_cols[1]:
                render_schedule_excel_download()
            filtered_plan = filter_plan_table(plan_df, "schedule_full")
            show_plan_grid(filtered_plan)

elif active_page == "Zarządzanie Harmonogramem":
    section_title("Zarządzanie Harmonogramem")
    if st.session_state["input_paths"] is not None:
        render_loaded_input_summary()
        render_run_planning_button("run_planning_from_management_top")

    if st.session_state["schedule_results"] is None:
        st.info("Najpierw uruchom planowanie.")
        if st.session_state["input_paths"] is None:
            render_run_planning_button("run_planning_from_management_empty")
    else:
        st.session_state["schedule_results"]["plan"] = ensure_execution_status(st.session_state["schedule_results"]["plan"])
        plan_df = enrich_plan_addresses_from_input(st.session_state["schedule_results"]["plan"])
        st.session_state["schedule_results"]["plan"] = plan_df
        if plan_df.empty:
            st.warning("Brak zaplanowanych zadań.")
        else:
            validation = st.session_state["schedule_results"].get("validation", {})
            stats = {
                "tasks_total": validation.get("counts", {}).get("tasks_total", 0),
                "planned_count": len(plan_df),
                "unplanned_count": len(st.session_state["schedule_results"].get("unplanned", pd.DataFrame())),
                "conflict_count": len(st.session_state["schedule_results"].get("conflicts", pd.DataFrame())),
            }
            render_management_summary_cards(stats)
            metric_cols = st.columns(4)
            metric_cols[0].metric("Wykonane", len(plan_df[plan_df["status_wykonania"] == "Wykonane"]))
            metric_cols[1].metric("Pozostało", len(plan_df[plan_df["status_wykonania"] != "Wykonane"]))
            metric_cols[2].write("**Status danych:**")
            with metric_cols[2]:
                render_status_badge(validation.get("status", "Brak danych"))
            metric_cols[3].write("**Status harmonogramu:**")
            with metric_cols[3]:
                render_status_badge("Zatwierdzony" if st.session_state["approved"] else "Rekomendowany")

            st.info(
                "Harmonogram został wygenerowany przez AI i wymaga ręcznej weryfikacji. "
                "Po sprawdzeniu danych zatwierdź harmonogram, aby udostępnić jego finalny podgląd w zakładce Harmonogram."
            )
            if should_show_rdm_ai_notice():
                st.warning(
                    "Klasyfikacje awarii dodawane z raportu RDM są rekomendacją AI. "
                    "Przed zaakceptowaniem ich w harmonogramie kierownik wykonawstwa musi zweryfikować poprawność klasyfikacji, "
                    "priorytetu, wymaganych kompetencji i terminu."
                )
            if st.session_state.get("rdm_changes_pending_approval", False):
                st.warning(
                    "Zaimportowano zmiany z rejestru awarii RDM. "
                    "Zweryfikuj dodane awarie i zatwierdź harmonogram ponownie, zanim uznasz go za ostateczny."
                )
            if st.session_state["approved"]:
                st.success("Harmonogram jest zatwierdzony. Wybierz zakładkę Harmonogram w menu, aby zobaczyć finalny podgląd.")

            action_cols = st.columns([1, 1, 5])
            if not st.session_state["approved"]:
                if action_cols[0].button("Zatwierdź harmonogram"):
                    approve_current_schedule()
                    st.success("Zatwierdzenie oznacza decyzję kierownika wykonawstwa. System nie podejmuje decyzji operacyjnej samodzielnie.")
                    st.rerun()

            emergency_mask = get_emergency_mask(plan_df)
            emergency_rows = plan_df[emergency_mask].copy()
            if not emergency_rows.empty:
                if "data" in emergency_rows.columns:
                    emergency_rows["data"] = pd.to_datetime(emergency_rows["data"], errors="coerce")
                    emergency_rows = emergency_rows.sort_values(
                        [column for column in ["data", "priorytet", "id_zadania"] if column in emergency_rows.columns],
                        kind="stable",
                    )

                with st.expander("Awarie RDM do akceptacji", expanded=st.session_state.get("rdm_changes_pending_approval", False)):
                    st.write("Awarie dodane z rejestru RDM są oznaczone na czerwono. Możesz zaakceptować wszystkie naraz albo wybrane pozycje.")
                    show_plan_grid(emergency_rows)

                    pending_emergency_rows = emergency_rows[emergency_rows["status"].astype(str) != "Zatwierdzony"] if "status" in emergency_rows.columns else emergency_rows
                    if pending_emergency_rows.empty:
                        st.success("Wszystkie awarie RDM w harmonogramie są zatwierdzone.")
                    else:
                        option_pairs = [
                            (f"{format_emergency_option(row)} [{idx}]", idx)
                            for idx, row in pending_emergency_rows.iterrows()
                        ]
                        option_labels = [label for label, _ in option_pairs]
                        option_to_index = dict(option_pairs)

                        bulk_cols = st.columns([2, 2, 3])
                        if bulk_cols[0].button("Zatwierdź wszystkie awarie RDM", use_container_width=True):
                            approved_count = approve_emergency_rows(list(pending_emergency_rows.index))
                            st.success(f"Zatwierdzono awarie RDM: {approved_count}.")
                            st.rerun()

                        selected_labels = st.multiselect(
                            "Wybierz jedną lub wiele awarii do zatwierdzenia",
                            option_labels,
                            key="selected_rdm_emergencies_to_approve",
                        )
                        selected_indices = [option_to_index[label] for label in selected_labels]
                        if st.button("Zatwierdź wybrane awarie RDM", disabled=not selected_indices, use_container_width=True):
                            approved_count = approve_emergency_rows(selected_indices)
                            st.success(f"Zatwierdzono wybrane awarie RDM: {approved_count}.")
                            st.rerun()

            with st.expander("Edytuj harmonogram", expanded=True):
                st.write("Zmień wartości w tabeli i kliknij Zapisz zmiany w harmonogramie.")
                editable_plan = filter_plan_table(plan_df, "schedule_edit")
                if "data" in editable_plan.columns:
                    editable_plan["data"] = pd.to_datetime(editable_plan["data"], errors="coerce")
                if "data_wymagana" in editable_plan.columns:
                    editable_plan["data_wymagana"] = pd.to_datetime(editable_plan["data_wymagana"], errors="coerce")
                editable_plan = mark_emergency_source(editable_plan)

                with st.form("schedule_edit_form"):
                    edited_plan = st.data_editor(
                        editable_plan,
                        hide_index=True,
                        use_container_width=True,
                        num_rows="dynamic",
                        key="schedule_editor",
                        disabled=["Źródło"],
                        column_config={
                            "Źródło": st.column_config.TextColumn("Źródło"),
                            "data": st.column_config.DateColumn("data"),
                            "data_wymagana": st.column_config.DateColumn("data_wymagana"),
                            "zaplanowane_godziny": st.column_config.NumberColumn("zaplanowane_godziny", step=0.5),
                            "ilosc_zaplanowana": st.column_config.NumberColumn("ilosc_zaplanowana", step=1.0),
                            "priorytet": st.column_config.NumberColumn("priorytet", step=1.0),
                            "status": st.column_config.SelectboxColumn("status", options=PLAN_STATUS_OPTIONS),
                            "status_wykonania": st.column_config.SelectboxColumn("status_wykonania", options=EXECUTION_STATUS_OPTIONS),
                            "zrodlo_zadania": None,
                        },
                    )
                    save_schedule = st.form_submit_button("Zapisz zmiany w harmonogramie")

                if save_schedule:
                    if "Źródło" in edited_plan.columns:
                        edited_plan = edited_plan.drop(columns=["Źródło"])
                    if "data" in edited_plan.columns:
                        edited_plan["data"] = pd.to_datetime(edited_plan["data"], errors="coerce")
                    if "data_wymagana" in edited_plan.columns:
                        edited_plan["data_wymagana"] = pd.to_datetime(edited_plan["data_wymagana"], errors="coerce")
                    for column in ["zaplanowane_godziny", "ilosc_zaplanowana", "priorytet"]:
                        if column in edited_plan.columns:
                            edited_plan[column] = pd.to_numeric(edited_plan[column], errors="coerce")
                    edited_plan = ensure_execution_status(edited_plan)

                    st.session_state["schedule_results"]["plan"] = edited_plan
                    sync_approval_from_plan_status(edited_plan)
                    emergency_mask = get_emergency_mask(edited_plan)
                    pending_emergency_mask = emergency_mask & (edited_plan["status"].astype(str) != "Zatwierdzony")
                    st.session_state["rdm_changes_pending_approval"] = bool(pending_emergency_mask.any())
                    if "log" in st.session_state["schedule_results"]:
                        log_entry = pd.DataFrame([{
                            "id_zadania": None,
                            "etap": "Edycja harmonogramu",
                            "decyzja": "Zmieniono harmonogram w aplikacji",
                            "data_czas_logu": datetime.now(),
                        }])
                        st.session_state["schedule_results"]["log"] = pd.concat(
                            [st.session_state["schedule_results"]["log"], log_entry],
                            ignore_index=True,
                        )
                    save_current_results_to_excel()
                    st.success("Harmonogram zapisany. Możesz go teraz sprawdzić i zatwierdzić.")
                    st.rerun()

elif active_page == "Rejestr Awarii":
    section_title("Rejestr Awarii")
    if st.session_state["schedule_results"] is None:
        st.info("Najpierw uruchom planowanie.")
    else:
        st.session_state["schedule_results"]["plan"] = ensure_execution_status(st.session_state["schedule_results"]["plan"])
        plan_df = enrich_plan_addresses_from_input(st.session_state["schedule_results"]["plan"])
        st.session_state["schedule_results"]["plan"] = plan_df
        schedule_approved = st.session_state["approved"]
        if not schedule_approved:
            st.warning("Dodawanie awarii jest dostępne dopiero po zatwierdzeniu harmonogramu.")

        with st.expander("Raport awarii", expanded=True):
            uploaded_emergency_report = st.file_uploader(
                "Wczytaj raport z listą awarii",
                type=["xlsx", "xls", "csv"],
                key="emergency_report",
                disabled=not schedule_approved,
            )
            if not schedule_approved:
                st.info("Zatwierdź harmonogram, aby wczytać i dodać nowe awarie.")
            elif uploaded_emergency_report is None:
                st.info("Wczytaj raport awarii RDM do klasyfikacji.")
            else:
                report_meta = (uploaded_emergency_report.name, uploaded_emergency_report.size)
                if st.session_state["uploaded_emergency_report_meta"] != report_meta:
                    try:
                        st.session_state["uploaded_emergency_report_meta"] = report_meta
                        classify_rdm_report(uploaded_emergency_report)
                        st.success(f"Raport awarii sklasyfikowany: {uploaded_emergency_report.name}")
                    except Exception as exc:
                        st.error(f"Nie udało się sklasyfikować raportu RDM: {exc}")

            classified = st.session_state.get("rdm_classification")
            if classified is not None and not classified.empty:
                if should_show_rdm_ai_notice():
                    st.warning(
                        "Klasyfikacja awarii została wykonana przez AI. "
                        "Przed importem do harmonogramu kierownik wykonawstwa powinien zweryfikować wynik klasyfikacji, "
                        "priorytet, wymagane kompetencje oraz decyzję, czy awaria ma zostać dodana do planu."
                    )
                summary_cols = st.columns(4)
                summary_cols[0].metric("RDM rekordy", len(classified))
                summary_cols[1].metric(
                    "Do harmonogramu",
                    int((classified["wynik_czy_utworzyc_zadanie_planistyczne"] == "Tak").sum()),
                )
                summary_cols[2].metric(
                    "Do decyzji",
                    int((classified["wynik_status_raportu"] == "Do decyzji").sum()),
                )
                summary_cols[3].metric(
                    "Odrzucone",
                    int((classified["wynik_status_raportu"] == "Odrzucone z importu").sum()),
                )

                result_columns = [
                    "id_zgloszenia_rdm",
                    "data_wymagana",
                    "data_czas_kwalifikacji",
                    "miasto",
                    "ulica",
                    "wynik_kod_typu_awarii",
                    "wynik_nazwa_typu_awarii",
                    "wynik_priorytet_operacyjny",
                    "wynik_status_kwalifikacji",
                    "wynik_czy_utworzyc_zadanie_planistyczne",
                    "wynik_status_raportu",
                    "wynik_rekomendowany_typ_zadania",
                    "wynik_wymagane_kompetencje",
                    "wynik_ostrzezenia",
                    "wynik_bledy_krytyczne",
                ]
                result_columns = [column for column in result_columns if column in classified.columns]
                st.dataframe(
                    classified[result_columns].rename(columns={
                        "id_zgloszenia_rdm": "ID RDM",
                        "data_wymagana": "Data wymagana",
                        "data_czas_kwalifikacji": "Data kwalifikacji",
                        "miasto": "Miasto",
                        "ulica": "Ulica",
                        "wynik_kod_typu_awarii": "Kod awarii",
                        "wynik_nazwa_typu_awarii": "Typ awarii",
                        "wynik_priorytet_operacyjny": "Priorytet",
                        "wynik_status_kwalifikacji": "Kwalifikacja",
                        "wynik_czy_utworzyc_zadanie_planistyczne": "Zadanie",
                        "wynik_status_raportu": "Status raportu",
                        "wynik_rekomendowany_typ_zadania": "Typ zadania",
                        "wynik_wymagane_kompetencje": "Kompetencje",
                        "wynik_ostrzezenia": "Ostrzeżenia",
                        "wynik_bledy_krytyczne": "Błędy krytyczne",
                    }),
                    hide_index=True,
                    use_container_width=True,
                    height=420,
                )

                output_path = st.session_state.get("rdm_classification_output_path")
                if output_path and os.path.exists(output_path):
                    with open(output_path, "rb") as output_file:
                        st.download_button(
                            "Pobierz wynik klasyfikacji RDM",
                            data=output_file.read(),
                            file_name="rdm_klasyfikacja_output.xlsx",
                            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                        )

                if st.button("Importuj zakwalifikowane awarie do harmonogramu", disabled=not schedule_approved):
                    import_summary = import_rdm_classification_to_schedule()
                    st.success(
                        "Import RDM zakończony. "
                        f"Dodano: {import_summary['imported']}, "
                        f"duplikaty: {import_summary['skipped_duplicates']}, "
                        f"do decyzji: {import_summary['decision']}, "
                        f"odrzucone: {import_summary['rejected']}."
                    )
                    st.rerun()

        with st.expander("Lista zgłoszonych awarii", expanded=False):
            render_emergency_list(plan_df)

elif active_page == "Status prac":
    if st.session_state["schedule_results"] is None:
        st.info("Najpierw uruchom planowanie.")
    else:
        st.session_state["schedule_results"]["plan"] = ensure_execution_status(st.session_state["schedule_results"]["plan"])
        plan_df = st.session_state["schedule_results"]["plan"].copy()
        if plan_df.empty:
            st.warning("Brak zadań w harmonogramie.")
        else:
            plan_df["data"] = pd.to_datetime(plan_df["data"], errors="coerce")
            status_options = EXECUTION_STATUS_OPTIONS
            summary = plan_df["status_wykonania"].value_counts().reindex(status_options, fill_value=0)

            dates = sorted(plan_df["data"].dropna().dt.date.astype(str).unique())
            brygady = sorted(plan_df["brygada"].dropna().unique())
            filter_cols = st.columns([1.1, 1.1, 1.3, 3.4])
            selected_date = filter_cols[0].selectbox("Dzień", ["Wszystkie"] + dates)
            selected_brygada = filter_cols[1].selectbox("Brygada", ["Wszystkie"] + brygady)
            selected_status = filter_cols[2].selectbox("Status", ["Wszystkie"] + status_options)
            filter_cols[3].caption(" | ".join([f"{name}: {int(summary.get(name, 0))}" for name in status_options]))

            filtered_status = plan_df.copy()
            if selected_date != "Wszystkie":
                filtered_status = filtered_status[filtered_status["data"].dt.date.astype(str) == selected_date]
            if selected_brygada != "Wszystkie":
                filtered_status = filtered_status[filtered_status["brygada"] == selected_brygada]
            if selected_status != "Wszystkie":
                filtered_status = filtered_status[filtered_status["status_wykonania"] == selected_status]

            if filtered_status.empty:
                st.info("Brak zadań dla wybranych filtrów.")
            else:
                task_labels = {}
                for idx, row in filtered_status.iterrows():
                    date_text = row["data"].strftime("%Y-%m-%d") if not pd.isna(row.get("data")) else ""
                    task_labels[idx] = f"{date_text} | {row.get('brygada', '')} | {row.get('id_zadania', '')} | {row.get('nazwa_zadania', '')}"

                edit_cols = st.columns([4, 1.4, 0.8])
                selected_label = edit_cols[0].selectbox("Zadanie do aktualizacji", list(task_labels.values()))
                selected_idx = next(idx for idx, label in task_labels.items() if label == selected_label)
                current_status = filtered_status.loc[selected_idx, "status_wykonania"]
                if current_status not in status_options:
                    current_status = "Do wykonania"
                new_status = edit_cols[1].selectbox("Nowy status", status_options, index=status_options.index(current_status))
                if edit_cols[2].button("Zapisz"):
                    updated_plan = plan_df.copy()
                    updated_plan.loc[selected_idx, "status_wykonania"] = new_status
                    st.session_state["schedule_results"]["plan"] = updated_plan
                    st.session_state["approved"] = False
                    log_entry = pd.DataFrame([{
                        "id_zadania": updated_plan.loc[selected_idx, "id_zadania"],
                        "etap": "Status wykonania",
                        "decyzja": f"Zmieniono status wykonania na: {new_status}",
                        "data_czas_logu": datetime.now(),
                    }])
                    st.session_state["schedule_results"]["log"] = pd.concat(
                        [st.session_state["schedule_results"].get("log", pd.DataFrame()), log_entry],
                        ignore_index=True,
                    )
                    save_current_results_to_excel()
                    st.success("Status zapisany.")
                    st.rerun()

                view_df = filtered_status.copy()
                view_df["Data"] = view_df["data"].dt.strftime("%Y-%m-%d")
                view_df["Adres"] = (
                    view_df.get("ulica", "").fillna("").astype(str)
                    + ", "
                    + view_df.get("miasto", "").fillna("").astype(str)
                ).str.strip(", ")
                view_df = view_df.rename(columns={
                    "status_wykonania": "Status",
                    "brygada": "Brygada",
                    "id_zadania": "ID",
                    "nazwa_zadania": "Zadanie",
                    "zaplanowane_godziny": "Godz.",
                })
                view_cols = [column for column in ["Status", "Data", "Brygada", "ID", "Zadanie", "Adres", "Godz."] if column in view_df.columns]
                st.dataframe(view_df[view_cols], hide_index=True, use_container_width=True, height=560)

elif active_page == "Wykonanie prac":
    if st.session_state["schedule_results"] is None:
        st.info("Najpierw uruchom planowanie.")
    else:
        st.session_state["schedule_results"]["plan"] = ensure_execution_status(st.session_state["schedule_results"]["plan"])
        plan_df = st.session_state["schedule_results"]["plan"].copy()
        if plan_df.empty:
            st.warning("Brak zadań w harmonogramie.")
        else:
            plan_df["data"] = pd.to_datetime(plan_df["data"], errors="coerce")
            status_options = EXECUTION_STATUS_OPTIONS
            summary = plan_df["status_wykonania"].value_counts().reindex(status_options, fill_value=0)
            dates = sorted(plan_df["data"].dropna().dt.date.astype(str).unique())
            brygady = sorted(plan_df["brygada"].dropna().unique())
            filter_cols = st.columns([1.2, 1.2, 1.4, 3.2])
            selected_date = filter_cols[0].selectbox("Dzień", ["Wszystkie"] + dates)
            selected_brygada = filter_cols[1].selectbox("Brygada", ["Wszystkie"] + brygady)
            selected_execution = filter_cols[2].selectbox("Status wykonania", ["Wszystkie"] + status_options)
            filter_cols[3].caption(" | ".join([f"{name}: {int(summary.get(name, 0))}" for name in status_options]))

            editable = plan_df.copy()
            if selected_date != "Wszystkie":
                editable = editable[editable["data"].dt.date.astype(str) == selected_date]
            if selected_brygada != "Wszystkie":
                editable = editable[editable["brygada"] == selected_brygada]
            if selected_execution != "Wszystkie":
                editable = editable[editable["status_wykonania"] == selected_execution]

            st.caption("Zmień status w pierwszej kolumnie i kliknij Zapisz.")
            header = st.columns([1.4, 0.9, 0.9, 0.8, 2.4, 1.4, 1.0, 0.6])
            for col, label in zip(header, ["Status", "Data", "Brygada", "ID", "Zadanie", "Ulica", "Miasto", "Godz."]):
                col.markdown(f"**{label}**")

            status_updates = {}
            for idx, row in editable.iterrows():
                row_cols = st.columns([1.4, 0.9, 0.9, 0.8, 2.4, 1.4, 1.0, 0.6])
                current_status = row.get("status_wykonania", "Do wykonania")
                if current_status not in status_options:
                    current_status = "Do wykonania"
                status_updates[idx] = row_cols[0].selectbox(
                    "Status",
                    status_options,
                    index=status_options.index(current_status),
                    key=f"execution_status_{idx}",
                    label_visibility="collapsed",
                )
                row_cols[1].write(row["data"].strftime("%Y-%m-%d") if not pd.isna(row.get("data")) else "")
                row_cols[2].write(row.get("brygada", ""))
                row_cols[3].write(row.get("id_zadania", ""))
                row_cols[4].write(row.get("nazwa_zadania", ""))
                row_cols[5].write(row.get("ulica", ""))
                row_cols[6].write(row.get("miasto", ""))
                row_cols[7].write(row.get("zaplanowane_godziny", ""))

            save_execution = st.button("Zapisz statusy wykonania")

            if save_execution:
                updated_plan = plan_df.copy()
                for idx, status_value in status_updates.items():
                    updated_plan.loc[idx, "status_wykonania"] = status_value
                st.session_state["schedule_results"]["plan"] = updated_plan
                st.session_state["approved"] = False
                if "log" in st.session_state["schedule_results"]:
                    log_entry = pd.DataFrame([{
                        "id_zadania": None,
                        "etap": "Status wykonania",
                        "decyzja": "Zaktualizowano statusy wykonania zadań",
                        "data_czas_logu": datetime.now(),
                    }])
                    st.session_state["schedule_results"]["log"] = pd.concat(
                        [st.session_state["schedule_results"]["log"], log_entry],
                        ignore_index=True,
                    )
                save_current_results_to_excel()
                st.success("Statusy wykonania zapisane.")
                st.rerun()

            remaining = plan_df[plan_df["status_wykonania"] != "Wykonane"]
            with st.expander("Zadania pozostałe do wykonania", expanded=True):
                show_plan_grid(remaining)

elif active_page == "Przeplanowanie":
    section_title("Przeplanowanie")
    if st.session_state["schedule_results"] is None:
        st.info("Najpierw uruchom planowanie.")
    else:
        results = st.session_state["schedule_results"]
        plan_df = results["plan"]
        if plan_df.empty:
            st.warning("Brak harmonogramu do przeplanowania.")
        else:
            plan_df = plan_df.copy()
            plan_df["data"] = pd.to_datetime(plan_df["data"], errors="coerce")
            dates = sorted(plan_df["data"].dropna().dt.date.unique())
            selected_date = st.date_input("Dzień pracy", value=dates[0] if dates else datetime.today())
            selected_date_ts = pd.to_datetime(selected_date)
            day_plan = plan_df[plan_df["data"] == selected_date_ts].copy()

            tasks_count = len(day_plan)
            hours_count = day_plan.get("zaplanowane_godziny", pd.Series(dtype=float)).sum()
            brygady_count = day_plan["brygada"].nunique() if "brygada" in day_plan.columns else 0
            metric_cols = st.columns(3)
            metric_cols[0].metric("Zadania w dniu", tasks_count)
            metric_cols[1].metric("Zaplanowane godziny", f"{hours_count:.1f}")
            metric_cols[2].metric("Brygady", brygady_count)

            with st.expander("Plan wybranego dnia", expanded=True):
                show_day_plan(day_plan, key_prefix="replan_current_day")

            st.subheader("Problem do obsłużenia")
            brygady = sorted(day_plan["brygada"].dropna().unique()) if not day_plan.empty else sorted(plan_df["brygada"].dropna().unique())
            with st.form("replan_form"):
                selected_brygada = st.selectbox("Której brygady dotyczy problem?", ["Dowolna"] + brygady)
                absent_hours = st.number_input("Ile godzin trzeba zdjąć z planu? (np. absencja)", min_value=0.0, step=1.0, value=0.0)
                emergency_hours = st.number_input("Ile godzin awarii trzeba dodać?", min_value=0.0, step=1.0, value=0.0)
                run_replan = st.form_submit_button("Przelicz plan dnia")

            if run_replan:
                results["plan"] = ensure_execution_status(results.get("plan", pd.DataFrame()))
                brygada = None if selected_brygada == "Dowolna" else selected_brygada
                summary = replan_day(results, selected_date, wybor_brygady=brygada, brak_godzin=absent_hours, awaria_godziny=emergency_hours)
                if summary is not None:
                    summary["date"] = selected_date_ts
                    st.session_state["replan_summary"] = summary
                    st.session_state["approved"] = False

            if st.session_state["replan_summary"] is not None:
                summary = st.session_state["replan_summary"]
                st.subheader("Proponowana zmiana")
                changed = summary.get("changed_tasks", pd.DataFrame())
                if changed is None or changed.empty:
                    st.info("Nie ma zmian do zastosowania dla podanych danych.")
                else:
                    show_plan_grid(changed)

                with st.expander("Plan po zmianie", expanded=True):
                    show_plan_grid(summary.get("after"))
                with st.expander("Plan przed zmianą", expanded=False):
                    show_plan_grid(summary.get("before"))
                with st.expander("Konflikty i uwagi", expanded=False):
                    show_dataframe(summary.get("conflicts"), max_rows=50)

                action_cols = st.columns(2)
                if action_cols[0].button("Zastosuj zmiany w harmonogramie"):
                    change_date = summary.get("date", selected_date_ts)
                    current_plan = st.session_state["schedule_results"]["plan"].copy()
                    current_plan["data"] = pd.to_datetime(current_plan["data"], errors="coerce")
                    updated_day = summary.get("after", pd.DataFrame()).copy()
                    updated_plan = pd.concat(
                        [current_plan[current_plan["data"] != change_date], updated_day],
                        ignore_index=True,
                    )
                    updated_plan = ensure_execution_status(updated_plan)
                    if not updated_plan.empty:
                        updated_plan = updated_plan.sort_values(["data", "brygada", "priorytet"])
                    st.session_state["schedule_results"]["plan"] = updated_plan
                    st.session_state["schedule_results"]["conflicts"] = summary.get("conflicts", st.session_state["schedule_results"].get("conflicts", pd.DataFrame()))
                    st.session_state["schedule_results"]["log"] = summary.get("log", st.session_state["schedule_results"].get("log", pd.DataFrame()))
                    st.session_state["approved"] = False
                    st.session_state["replan_summary"] = None
                    save_current_results_to_excel()
                    st.success("Zmiany zastosowane w harmonogramie. Sprawdź plan i zatwierdź, gdy będzie gotowy.")
                    st.rerun()
                if action_cols[1].button("Odrzuć propozycję"):
                    st.session_state["replan_summary"] = None
                    st.rerun()

elif active_page == "Zadania niezaplanowane":
    section_title("Zadania niezaplanowane")
    if st.session_state["schedule_results"] is None:
        st.info("Najpierw uruchom planowanie.")
    else:
        show_dataframe(st.session_state["schedule_results"]["unplanned"])

elif active_page == "Konflikty":
    section_title("Konflikty")
    if st.session_state["schedule_results"] is None:
        st.info("Najpierw uruchom planowanie.")
    else:
        show_dataframe(st.session_state["schedule_results"]["conflicts"])

elif active_page == "Obciążenie brygad":
    section_title("Obciążenie brygad")
    if st.session_state["schedule_results"] is None:
        st.info("Najpierw uruchom planowanie.")
    else:
        obciazenie = st.session_state["schedule_results"]["obciazenie"]
        if obciazenie.empty:
            st.warning("Brak danych obciążenia.")
        else:
            st.dataframe(obciazenie)
            try:
                import plotly.express as px
                fig = px.bar(obciazenie, x="data", y="wykorzystanie_proc", color="brygada", title="Wykorzystanie brygad")
                st.plotly_chart(fig, use_container_width=True)
            except Exception:
                st.write("Wykres obciążenia nie jest dostępny.")

elif active_page == "Przeplanowanie dnia":
    section_title("Przeplanowanie dnia")
    if st.session_state["schedule_results"] is None:
        st.info("Najpierw uruchom planowanie.")
    else:
        results = st.session_state["schedule_results"]
        plan_df = results["plan"]
        dates = sorted(plan_df["data"].dt.date.unique())
        selected_date = st.date_input("Data do przeplanowania", value=dates[0] if dates else datetime.today())
        brygady = sorted(plan_df["brygada"].dropna().unique())
        selected_brygada = st.selectbox("Brygada", ["Dowolna"] + brygady)
        absent_hours = st.number_input("Brak dostępnych godzin (absencja)", min_value=0.0, step=1.0, value=0.0)
        emergency_hours = st.number_input("Godziny awarii", min_value=0.0, step=1.0, value=0.0)
        if st.button("Uruchom rekomendację przeplanowania"):
            brygada = None if selected_brygada == "Dowolna" else selected_brygada
            summary = replan_day(results, selected_date, wybor_brygady=brygada, brak_godzin=absent_hours, awaria_godziny=emergency_hours)
            st.session_state["replan_summary"] = summary
        if st.session_state["replan_summary"] is not None:
            summary = st.session_state["replan_summary"]
            st.subheader("Zmiany przed / po")
            st.write("Przed:")
            show_dataframe(summary.get("before"))
            st.write("Po:")
            show_dataframe(summary.get("after"))
            st.subheader("Konflikty po przeplanowaniu")
            show_dataframe(summary.get("conflicts"))
            st.subheader("Decyzje do zatwierdzenia")
            show_dataframe(summary.get("changed_tasks"))

elif active_page == "KPI i jakość planu":
    section_title("KPI i jakość planu")
    if st.session_state["schedule_results"] is None:
        st.info("Najpierw uruchom planowanie.")
    else:
        show_dataframe(st.session_state["schedule_results"]["kpi"], max_rows=50)

elif active_page == "Log decyzji":
    section_title("Log decyzji")
    if st.session_state["schedule_results"] is None:
        st.info("Najpierw uruchom planowanie.")
    else:
        show_dataframe(st.session_state["schedule_results"]["log"], max_rows=50)

elif active_page == "Eksport":
    section_title("Eksport")
    if st.session_state["schedule_results"] is None:
        st.info("Najpierw uruchom planowanie.")
    else:
        output_path = os.path.join(os.getcwd(), "harmonogram_brygad_output.xlsx")
        if os.path.exists(output_path):
            with open(output_path, "rb") as f:
                data = f.read()
            st.download_button("Pobierz plik wynikowy Excel", data=data, file_name="harmonogram_brygad_output.xlsx", mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
        else:
            st.warning("Plik wynikowy nie jest jeszcze zapisany.")
        st.write("Można również pobrać dane tabelaryczne jako CSV:")
        if st.session_state["schedule_results"]["plan"] is not None:
            st.download_button("Pobierz harmonogram CSV", st.session_state["schedule_results"]["plan"].to_csv(index=False).encode("utf-8"), "harmonogram.csv", "text/csv")
        if st.session_state["schedule_results"]["unplanned"] is not None:
            st.download_button("Pobierz niezaplanowane CSV", st.session_state["schedule_results"]["unplanned"].to_csv(index=False).encode("utf-8"), "niezaplanowane.csv", "text/csv")
        if st.session_state["schedule_results"]["conflicts"] is not None:
            st.download_button("Pobierz konflikty CSV", st.session_state["schedule_results"]["conflicts"].to_csv(index=False).encode("utf-8"), "konflikty.csv", "text/csv")
