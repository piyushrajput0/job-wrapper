"""Answering what the resolver could not.

One batched model call handles every unresolved control on a form at once: it maps them onto
catalog keys where possible and writes free-text answers where not. Everything it produces is
written into the answer bank, so the second application that asks the same question costs
nothing and the hundredth is instant.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from ..llm import LLMClient, LLMUnavailable
from ..llm.prompts import ANSWER_SYSTEM, COVER_LETTER_SYSTEM
from ..logging_setup import get
from ..models import Job, Profile
from ..models.application import FieldDescriptor, FilledField
from ..models.resume import MasterResume
from ..store.repo import AnswerRepo
from .catalog import Catalog, ResolveContext, match_option

log = get("autofill.answers")


class AnsweredField(BaseModel):
    index: int
    catalog_key: str = ""
    answer: str = ""
    needs_human: bool = False
    reason: str = ""
    confidence: float = Field(default=0.7, ge=0, le=1)


class AnswerBatch(BaseModel):
    answers: list[AnsweredField] = Field(default_factory=list)


class AnswerEngine:
    def __init__(self, profile: Profile, llm: LLMClient, answers: AnswerRepo | None = None,
                 master: MasterResume | None = None, catalog: Catalog | None = None) -> None:
        self.profile = profile
        self.llm = llm
        self.answers = answers
        self.master = master or MasterResume()
        self.catalog = catalog or Catalog()

    # ------------------------------------------------------------------ context
    def _cached_context(self, job: Job | None) -> str:
        parts = ["=== CANDIDATE PROFILE ===", self.profile.summarize_for_llm()]
        if self.master.experience:
            parts += ["", "=== RESUME EVIDENCE ===", self.master.text_corpus()[:6000]]
        return "\n".join(parts)

    @staticmethod
    def _describe(descriptor: FieldDescriptor, index: int) -> str:
        bits = [f"[{index}] question: {descriptor.question_text()}"]
        if descriptor.input_type:
            bits.append(f"type={descriptor.input_type}")
        if descriptor.options:
            bits.append(f"options={descriptor.options[:25]}")
        if descriptor.maxlength:
            bits.append(f"maxlength={descriptor.maxlength}")
        if descriptor.required:
            bits.append("required")
        return " | ".join(bits)

    # ------------------------------------------------------------------ batch answering
    def answer_batch(self, descriptors: list[FieldDescriptor], job: Job | None,
                     company: str = "", context: ResolveContext | None = None,
                     ) -> tuple[list[FilledField], list[FieldDescriptor]]:
        """Returns (filled, still_unresolved)."""
        if not descriptors:
            return [], []
        if not self.llm.available():
            return self._deterministic(descriptors, job, company)

        listing = "\n".join(self._describe(d, i) for i, d in enumerate(descriptors))
        catalog_keys = ", ".join(sorted(self.catalog.by_key))
        job_block = ""
        if job:
            job_block = (f"\n=== THE JOB ===\nCompany: {job.company}\nTitle: {job.title}\n"
                         f"Location: {job.location}\nDescription:\n{job.description[:9000]}\n")
        prompt = (
            f"{job_block}\n=== FORM CONTROLS TO ANSWER ===\n{listing}\n\n"
            f"=== CATALOG KEYS (use one when the control is a standard field) ===\n{catalog_keys}\n\n"
            "For each control return: its index, a catalog_key if one clearly applies (else empty), "
            "the answer to type or the exact option to pick, needs_human if the profile cannot "
            "support an answer, and your confidence."
        )
        try:
            batch = self.llm.parse(AnswerBatch, system=ANSWER_SYSTEM, prompt=prompt,
                                   cached_context=self._cached_context(job), effort="low",
                                   max_tokens=6000)
        except LLMUnavailable:
            return self._deterministic(descriptors, job, company)
        except Exception as exc:
            log.warning("batch answering failed (%s); falling back", exc)
            return self._deterministic(descriptors, job, company)

        filled: list[FilledField] = []
        unresolved: list[FieldDescriptor] = []
        answered_indexes = set()

        for item in batch.answers:
            if not (0 <= item.index < len(descriptors)):
                continue
            descriptor = descriptors[item.index]
            answered_indexes.add(item.index)
            if item.needs_human or not item.answer.strip():
                unresolved.append(descriptor)
                continue
            value = item.answer.strip()
            if descriptor.options:
                picked = match_option(value, descriptor.options, self.catalog)
                if not picked:
                    unresolved.append(descriptor)
                    continue
                value = picked
            action = ("select" if descriptor.options else
                      "check" if descriptor.input_type == "checkbox" else "fill")
            filled.append(FilledField(
                selector=descriptor.selector, frame=descriptor.frame,
                field_key=item.catalog_key or "llm_answer",
                question=descriptor.question_text(), value=value, method="llm",
                confidence=item.confidence, action=action,
                needs_review=item.confidence < 0.8))
            if self.answers:
                self.answers.remember(
                    descriptor.question_text(), value, field_key=item.catalog_key,
                    company=company if item.catalog_key in ("", "essay") else "",
                    source="llm", confidence=item.confidence)

        unresolved += [d for i, d in enumerate(descriptors) if i not in answered_indexes]
        log.info("model answered %d/%d unresolved control(s)", len(filled), len(descriptors))
        return filled, unresolved

    def _deterministic(self, descriptors: list[FieldDescriptor], job: Job | None,
                       company: str) -> tuple[list[FilledField], list[FieldDescriptor]]:
        """No model: answer only what a template can honestly answer."""
        filled: list[FilledField] = []
        unresolved: list[FieldDescriptor] = []
        for descriptor in descriptors:
            question = descriptor.question_text().lower()
            if descriptor.input_type == "textarea" and job and any(
                    token in question for token in ("why", "interest", "fit", "cover letter",
                                                    "tell us", "motivat")):
                text = self.template_cover_letter(job)
                filled.append(FilledField(
                    selector=descriptor.selector, frame=descriptor.frame,
                    field_key="cover_letter_text",
                    question=descriptor.question_text(), value=text, method="default",
                    confidence=0.55, action="fill", needs_review=True))
            else:
                unresolved.append(descriptor)
        return filled, unresolved

    # ------------------------------------------------------------------ prose
    def template_cover_letter(self, job: Job) -> str:
        """Honest, boring, and derived entirely from the profile. Always flagged for review."""
        latest = self.profile.latest_experience
        skills = sorted(self.profile.skill_names())[:6]
        years = self.profile.computed_years_of_experience()
        opening = (f"I am applying for the {job.title} role at {job.company}. "
                   f"I have {years:g} years of experience")
        if latest:
            opening += f", most recently as {latest.title} at {latest.company}"
        opening += "."
        middle = ""
        if latest and latest.bullets:
            middle = " " + " ".join(latest.bullets[:2])
        closing = (f" The role's focus lines up with my work in "
                   f"{', '.join(skills[:3]) if skills else 'this area'}, and I would welcome the "
                   f"chance to discuss it.")
        return (opening + middle + closing).strip()

    def cover_letter(self, job: Job, extra_context: str = "") -> str:
        if not self.llm.available():
            return self.template_cover_letter(job)
        try:
            return self.llm.text(
                system=COVER_LETTER_SYSTEM,
                prompt=(f"Company: {job.company}\nRole: {job.title}\nLocation: {job.location}\n\n"
                        f"Job description:\n{job.description[:9000]}\n\n{extra_context}"),
                cached_context=self._cached_context(job), effort="low", max_tokens=1200)
        except Exception as exc:
            log.warning("cover letter generation failed (%s); using the template", exc)
            return self.template_cover_letter(job)
