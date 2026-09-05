"""Application records and the fill plan produced by the autofill engine."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

ApplicationStatus = Literal[
    "planned", "in_progress", "needs_input", "ready_for_review", "submitted",
    "failed", "skipped", "duplicate", "closed",
]

FillMethod = Literal["ats_map", "token", "fuzzy", "answer_bank", "llm", "human", "default"]


class FieldDescriptor(BaseModel):
    """A form control as observed on the page - the shared V1/V2 wire shape."""

    selector: str = ""
    frame: str = ""
    tag: str = "input"
    input_type: str = "text"
    name: str = ""
    element_id: str = ""
    label: str = ""
    aria_label: str = ""
    placeholder: str = ""
    required: bool = False
    options: list[str] = Field(default_factory=list)
    option_values: list[str] = Field(default_factory=list)
    maxlength: int | None = None
    group: str = ""
    section: str = ""
    autocomplete: str = ""
    current_value: str = ""
    visible: bool = True

    def question_text(self) -> str:
        for candidate in (self.label, self.aria_label, self.placeholder, self.name, self.element_id):
            if candidate and not candidate.isdigit():
                return candidate.strip()
        return self.selector


class FilledField(BaseModel):
    selector: str = ""
    field_key: str = ""
    question: str = ""
    value: str = ""
    method: FillMethod = "token"
    confidence: float = 0.0
    action: Literal["fill", "select", "check", "click", "upload", "skip"] = "fill"
    needs_review: bool = False
    error: str = ""


class FillPlan(BaseModel):
    """What the engine intends to do to a form. Reviewable before anything is typed."""

    url: str = ""
    ats: str = ""
    job_id: str = ""
    fields: list[FilledField] = Field(default_factory=list)
    unresolved: list[FieldDescriptor] = Field(default_factory=list)
    blocking: list[str] = Field(default_factory=list)
    documents: dict[str, str] = Field(default_factory=dict)
    created_at: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())

    @property
    def resolved_count(self) -> int:
        return len([f for f in self.fields if f.action != "skip"])

    @property
    def review_count(self) -> int:
        return len([f for f in self.fields if f.needs_review])

    def is_submittable(self) -> bool:
        return not self.blocking and not self.unresolved_required()

    def unresolved_required(self) -> list[FieldDescriptor]:
        return [f for f in self.unresolved if f.required]


class Application(BaseModel):
    id: str = ""
    job_id: str = ""
    company: str = ""
    title: str = ""
    url: str = ""
    ats: str = ""
    status: ApplicationStatus = "planned"
    autonomy: str = "review"
    resume_path: str = ""
    resume_id: str = ""
    cover_letter_path: str = ""
    match_score: int = 0
    fields_filled: int = 0
    fields_flagged: int = 0
    questions_answered: int = 0
    screenshots: list[str] = Field(default_factory=list)
    plan: FillPlan | None = None
    error: str = ""
    notes: str = ""
    confirmation_id: str = ""
    created_at: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())
    submitted_at: str = ""
    events: list[dict[str, Any]] = Field(default_factory=list)

    def log(self, event: str, **data: Any) -> None:
        self.events.append(
            {"at": datetime.now(UTC).isoformat(), "event": event, **data}
        )
