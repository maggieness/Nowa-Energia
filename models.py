from dataclasses import dataclass, field
from typing import Any, Dict, List

@dataclass
class ValidationIssue:
    level: str
    message: str
    sheet: str = ""
    column: str = ""
    task_id: Any = None
    details: Dict[str, Any] = field(default_factory=dict)

@dataclass
class ScheduleResult:
    plan: Any
    unplanned: Any
    conflicts: Any
    obciazenie: Any
    log: Any
    kpi: Any
    validation: Dict[str, Any]
    status: str = ""
