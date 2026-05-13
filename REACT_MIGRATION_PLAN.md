# Streamlit to React Migration Plan

## Goal

Create a React-based version of the Nowa Energia scheduling app while keeping the existing Python planning engine stable.

The current Streamlit app is a working prototype. The migration should separate the UI from the scheduling logic:

- React frontend for the user interface.
- FastAPI backend for planning, validation, replanning, uploads, and exports.
- Existing Python modules reused where possible:
  - `scheduler_engine.py`
  - `validators.py`
  - `kpi.py`
  - `models.py`

## Why This Is More Than a UI Swap

Streamlit currently handles many things automatically:

- File upload
- Session state
- App reruns after actions
- Dataframe display and editing
- Forms and buttons
- Downloads
- Plotly rendering
- Python logic and UI in one process

In React, these need explicit frontend and backend implementation:

- API endpoints
- JSON serialization of pandas dataframes
- Upload and download handling
- Frontend state management
- Editable table components
- Error and loading states
- Running frontend and backend servers

## Recommended Approach

Work on a copied project folder first, leaving the current Streamlit version untouched.

Suggested copy name:

`Projekt Nowa Energia React`

## Phase 1 - First Working React Version

Estimated time: 1 day

Scope:

- Create FastAPI backend.
- Create React frontend.
- Upload planning and HR Excel files.
- Use existing fixed data file from `02_Baza danych/planowanie_brygad_Stale.xlsx`.
- Run `run_scheduler`.
- Display main outputs:
  - Recommended schedule
  - Unplanned tasks
  - Conflicts
  - KPI
- Download generated Excel result.

Not required in phase 1:

- Full stale-data editor
- Advanced editable schedule grid
- Full execution status workflow
- Polished layout
- User authentication
- Database

## Phase 2 - Functional Parity

Estimated time: 2-3 additional days

Scope:

- Add navigation matching current Streamlit pages.
- Add validation page.
- Add load/preview of uploaded source sheets.
- Add schedule editing.
- Add execution status updates.
- Add emergency task flow.
- Add daily view.
- Add replanning workflow.
- Add CSV exports.
- Add workload chart.
- Add log view.

## Phase 3 - Polished Web App

Estimated time: 3-5 additional days

Scope:

- Improve layout and visual design.
- Add robust loading and error states.
- Add backend response models.
- Add tests for API endpoints and scheduling behavior.
- Add cleaner project structure.
- Add deployment instructions.
- Consider persistent storage if needed.

## Initial Technical Shape

Proposed structure:

```text
backend/
  main.py
  api/
    routes.py
  services/
    scheduler_service.py
frontend/
  package.json
  src/
    App.jsx
    api/
    components/
    pages/
```

Suggested stack:

- Backend: FastAPI, pandas, openpyxl
- Frontend: React, Vite, TanStack Table or AG Grid, Plotly/Recharts
- Styling: simple CSS first, then improve

## Main Risk Areas

- Editable dataframe behavior from Streamlit needs a proper React table solution.
- Session state must be replaced with explicit frontend/backend state.
- Excel upload/download handling must be tested carefully.
- Pandas date/time values need clean JSON serialization.
- The scheduling engine should remain unchanged unless an API boundary exposes hidden assumptions.

## Decision

Start with a project copy at the end of the day, then build Phase 1 first. Keep the Streamlit app as the fallback until the React version is good enough to replace it.
