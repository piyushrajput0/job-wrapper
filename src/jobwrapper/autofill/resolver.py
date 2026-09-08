"""The resolution cascade: a form control in, a value out, with the reason recorded.

Stages, cheapest and most certain first:
  1. ATS map        - `name="job_application[first_name]"` is not ambiguous
  2. Strong token   - the label contains a catalog term exactly
  3. Fuzzy score    - weighted token overlap, type compatibility, negative evidence
  4. Dynamic rules  - "how many years of X" needs the X pulled out first
  5. Answer bank    - has a human already answered this exact question?
  6. Unresolved     - handed to the LLM batch pass, then to the human

The identical algorithm is implemented in extension/shared/resolver.js for V2, driven by the
same JSON. Keep the two in step when you change scoring.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from difflib import SequenceMatcher
from typing import Any

from ..logging_setup import get
from ..models import Profile
from ..models.application import FieldDescriptor, FilledField, FillPlan
from ..store.repo import AnswerRepo
from .catalog import Catalog, ResolveContext, ValueProvider, match_option

log = get("autofill")

FILL_THRESHOLD = 0.85          # fill silently
REVIEW_THRESHOLD = 0.60        # fill but flag
ABBREVIATIONS = {
    r"\be[- ]?mail\b": "email", r"\bdob\b": "date of birth", r"\bph\b": "phone",
    r"\btel\b": "phone", r"\bmob\b": "mobile", r"\bzip\b": "zip", r"\baddr\b": "address",
    r"\bexp\b": "experience", r"\byrs\b": "years", r"#": " number ", r"\buni\b": "university",
    r"\bgrad\b": "graduation", r"\bcomp\b": "compensation", r"\bpref\b": "preferred",
}
TYPE_AFFINITY = {
    "email": {"email"}, "tel": {"tel", "phone"}, "url": {"url"}, "date": {"date"},
    "number": {"number"}, "file": {"file"}, "password": {"password"},
    "checkbox": {"checkbox"}, "radio": {"radio", "select"}, "select-one": {"select", "radio"},
    "select": {"select", "radio"}, "textarea": {"textarea"},
}


@dataclass
class Resolution:
    field_key: str = ""
    value: str = ""
    confidence: float = 0.0
    method: str = "token"
    action: str = "fill"
    needs_review: bool = False
    reason: str = ""
    blocked: str = ""


def normalize_label(text: str) -> str:
    text = (text or "").lower()
    text = re.sub(r"\((?:optional|required)\)", " ", text)
    text = text.replace("*", " ").replace("✱", " ")
    text = re.sub(r"\brequired\b|\boptional\b", " ", text)
    for pattern, replacement in ABBREVIATIONS.items():
        text = re.sub(pattern, replacement, text)
    text = re.sub(r"[_\-/\\]+", " ", text)
    text = re.sub(r"[^a-z0-9+#.,' ]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _tokens(text: str) -> list[str]:
    return [t for t in re.findall(r"[a-z0-9+#]+", text) if t]


class FieldResolver:
    def __init__(self, profile: Profile, context: ResolveContext | None = None,
                 answers: AnswerRepo | None = None, catalog: Catalog | None = None) -> None:
        self.profile = profile
        self.context = context or ResolveContext()
        self.catalog = catalog or Catalog()
        self.values = ValueProvider(profile, self.context)
        self.answers = answers

    # ------------------------------------------------------------------ scoring
    def _ats_lookup(self, descriptor: FieldDescriptor) -> str | None:
        spec = self.catalog.ats(self.context.ats)
        for map_name, attribute in (("name_map", descriptor.name),
                                    ("id_map", descriptor.element_id),
                                    ("automation_id_map", descriptor.name),
                                    ("automation_id_map", descriptor.element_id)):
            mapping = spec.get(map_name) or {}
            if attribute and attribute in mapping and mapping[attribute]:
                return mapping[attribute]
        attribute_map = spec.get("attribute_map") or {}
        for attribute, mapping in attribute_map.items():
            observed = (descriptor.autocomplete if attribute == "autocomplete"
                        else descriptor.name or descriptor.element_id)
            if observed in mapping:
                return mapping[observed]
        # partial match for Workday's suffixed automation ids
        automation = spec.get("automation_id_map") or {}
        haystack = f"{descriptor.name} {descriptor.element_id} {descriptor.selector}"
        for token, key in automation.items():
            if token and token in haystack:
                return key
        return None

    def _score(self, descriptor: FieldDescriptor, spec: dict[str, Any]) -> tuple[float, str]:
        label = normalize_label(descriptor.question_text())
        if not label:
            return 0.0, ""
        label_tokens = set(_tokens(label))
        best, reason = 0.0, ""

        for term in spec.get("strong", []):
            normalized = normalize_label(term)
            if not normalized:
                continue
            if label == normalized:
                return 1.0, f"label equals '{term}'"
            if re.search(rf"(?<![a-z0-9]){re.escape(normalized)}(?![a-z0-9])", label):
                ratio = len(normalized) / max(len(label), 1)
                score = 0.80 + 0.15 * min(1.0, ratio)
                if score > best:
                    best, reason = score, f"label contains '{term}'"

        for term in spec.get("synonyms", []):
            normalized = normalize_label(term)
            if not normalized:
                continue
            if label == normalized:
                score = 0.95
            elif re.search(rf"(?<![a-z0-9]){re.escape(normalized)}(?![a-z0-9])", label):
                score = 0.72 + 0.15 * min(1.0, len(normalized) / max(len(label), 1))
            else:
                term_tokens = set(_tokens(normalized))
                if not term_tokens:
                    continue
                overlap = len(term_tokens & label_tokens) / len(term_tokens)
                sequence = SequenceMatcher(None, normalized, label).ratio()
                score = max(overlap * 0.62, sequence * 0.58)
            if score > best:
                best, reason = score, f"matches '{term}'"

        # negative evidence: the field is about somebody or something else
        for term in spec.get("negative", []):
            if re.search(rf"(?<![a-z0-9]){re.escape(normalize_label(term))}(?![a-z0-9])", label):
                best -= 0.45
                reason += f" (penalised: '{term}')"

        # type compatibility
        expected = spec.get("type", "text")
        observed = (descriptor.input_type or descriptor.tag or "text").lower()
        affinity = TYPE_AFFINITY.get(observed, set())
        if affinity:
            if expected in affinity:
                best += 0.06
            elif expected in {"text", "textarea"} and observed in {"text", "textarea"}:
                best += 0.02
            elif expected not in {"text"} and observed in {"email", "tel", "url", "file",
                                                           "password", "date", "number"}:
                best -= 0.30
        if descriptor.options and expected in {"select", "radio", "checkbox"}:
            best += 0.05
        best += spec.get("priority", 50) / 10000  # deterministic tie-break
        return max(0.0, min(1.0, best)), reason

    def _best_catalog_match(self, descriptor: FieldDescriptor) -> tuple[str, float, str]:
        best_key, best_score, best_reason = "", 0.0, ""
        for spec in self.catalog.fields:
            score, reason = self._score(descriptor, spec)
            if score > best_score:
                best_key, best_score, best_reason = spec["key"], score, reason
        return best_key, best_score, best_reason

    # ------------------------------------------------------------------ dynamic rules
    def _dynamic(self, descriptor: FieldDescriptor) -> Resolution | None:
        question = normalize_label(descriptor.question_text())
        for rule in self.catalog.patterns["dynamic"]:
            match = re.search(rule["pattern"], question)
            if not match:
                continue
            captured = match.group(1).strip() if rule.get("capture") and match.groups() else ""
            handler = getattr(self, f"_dyn_{rule['handler']}", None)
            if handler is None:
                continue
            resolved = handler(captured, descriptor)
            if resolved:
                resolved.method = "token"
                resolved.reason = f"pattern '{rule['id']}'" + (f" -> {captured}" if captured else "")
                return resolved
            if captured and rule.get("terminal"):
                # The question is specifically about `captured` and the profile cannot answer it.
                # Falling through would answer "years with COBOL" using total years of
                # experience, which is worse than not answering - so stop here and let the
                # question reach the model or the human.
                return Resolution(
                    confidence=0.0, method="human",
                    reason=f"pattern '{rule['id']}' matched '{captured}' but the profile has "
                           f"nothing to say about it")
        return None

    def _skill_years(self, skill: str) -> float:
        wanted = skill.lower().strip()
        for entry in self.profile.skills:
            if entry.name.lower() == wanted and entry.years:
                return entry.years
        from ..pipeline.match import canonical_skill

        canonical = (canonical_skill(wanted) or wanted).lower()
        months = 0
        for exp in self.profile.experience:
            haystack = " ".join([*exp.technologies, exp.summary, *exp.bullets]).lower()
            if canonical in haystack or wanted in haystack:
                months += exp.duration_months
        if months:
            return round(months / 12, 1)
        return 0.0

    def _dyn_years_with_skill(self, skill: str, descriptor: FieldDescriptor) -> Resolution | None:
        if not skill:
            return None
        years = self._skill_years(skill)
        if not years:
            if skill.lower() not in {s.lower() for s in self.profile.skill_names()}:
                return None
            years = max(1.0, round(self.profile.computed_years_of_experience() / 2, 1))
        value = f"{years:g}"
        if descriptor.options:
            picked = match_option(value, descriptor.options, self.catalog) or \
                self._closest_numeric_option(years, descriptor.options)
            if not picked:
                return None
            return Resolution(field_key="years_with_skill", value=picked, confidence=0.86,
                              action="select")
        return Resolution(field_key="years_with_skill", value=value, confidence=0.88)

    @staticmethod
    def _closest_numeric_option(years: float, options: list[str]) -> str | None:
        scored: list[tuple[float, str]] = []
        for option in options:
            numbers = [float(n) for n in re.findall(r"\d+(?:\.\d+)?", option)]
            if not numbers:
                continue
            low = numbers[0]
            high = numbers[1] if len(numbers) > 1 else (
                low + 99 if "+" in option or "more" in option.lower() else low)
            if low <= years <= high:
                return option
            scored.append((min(abs(years - low), abs(years - high)), option))
        return min(scored)[1] if scored else None

    def _dyn_proficiency_with_skill(self, skill: str,
                                    descriptor: FieldDescriptor) -> Resolution | None:
        if not skill:
            return None
        level = "intermediate"
        for entry in self.profile.skills:
            if entry.name.lower() == skill.lower():
                level = entry.level
                break
        else:
            if skill.lower() not in {s.lower() for s in self.profile.skill_names()}:
                return None
            years = self._skill_years(skill)
            level = "expert" if years >= 6 else "advanced" if years >= 3 else "intermediate"
        levels = self.catalog.patterns["proficiency_scales"]["level_map"][level]
        for option in descriptor.options:
            if option.lower().strip() in levels:
                return Resolution(field_key="proficiency", value=option, confidence=0.84,
                                  action="select")
        return Resolution(field_key="proficiency", value=level.title(), confidence=0.7)

    def _dyn_has_skill(self, skill: str, descriptor: FieldDescriptor) -> Resolution | None:
        if not skill:
            return None
        has = skill.lower() in {s.lower() for s in self.profile.skill_names()} \
            or self._skill_years(skill) > 0
        value = "Yes" if has else "No"
        if descriptor.options:
            picked = match_option(value, descriptor.options, self.catalog)
            if picked:
                return Resolution(field_key="has_skill", value=picked, confidence=0.85,
                                  action="select")
        return Resolution(field_key="has_skill", value=value, confidence=0.82)

    def _dyn_work_authorized_in(self, country: str, descriptor: FieldDescriptor) -> Resolution | None:
        codes = {"united states": "US", "us": "US", "usa": "US", "u.s.": "US", "america": "US",
                 "united kingdom": "GB", "uk": "GB", "canada": "CA", "germany": "DE",
                 "india": "IN", "australia": "AU", "eu": "EU", "european union": "EU"}
        code = codes.get((country or "").strip().lower())
        if not code:
            return None
        auth = self.profile.work_authorization.for_country(code)
        value = {"yes": "Yes", "no": "No", "prefer_not_to_say": "Prefer not to say"}[
            auth.authorized_to_work]
        picked = match_option(value, descriptor.options, self.catalog) if descriptor.options else value
        if not picked:
            return None
        return Resolution(field_key="work_authorized", value=picked, confidence=0.9,
                          action="select" if descriptor.options else "fill")

    def _dyn_located_in(self, place: str, descriptor: FieldDescriptor) -> Resolution | None:
        if not place:
            return None
        home = f"{self.profile.address.city} {self.profile.address.state} " \
               f"{self.profile.address.state_code} {self.profile.address.country}".lower()
        value = "Yes" if any(part.strip() and part.strip() in home
                             for part in re.split(r"[,/]| or ", place.lower())) else "No"
        picked = match_option(value, descriptor.options, self.catalog) if descriptor.options else value
        return Resolution(field_key="located_in", value=picked or value, confidence=0.78,
                          action="select" if descriptor.options else "fill", needs_review=True)

    def _dyn_commute_to(self, place: str, descriptor: FieldDescriptor) -> Resolution | None:
        value = self.values.value_for("commute_ok")
        picked = match_option(value, descriptor.options, self.catalog) if descriptor.options else value
        return Resolution(field_key="commute_ok", value=picked or value, confidence=0.75,
                          action="select" if descriptor.options else "fill", needs_review=True)

    def _dyn_language_proficiency(self, language: str,
                                  descriptor: FieldDescriptor) -> Resolution | None:
        for entry in self.profile.languages:
            if entry.name.lower() == (language or "").lower():
                picked = (match_option(entry.proficiency, descriptor.options, self.catalog)
                          if descriptor.options else entry.proficiency)
                if picked:
                    return Resolution(field_key="language", value=picked, confidence=0.85,
                                      action="select" if descriptor.options else "fill")
        return None

    def _dyn_notice_period(self, _captured: str, descriptor: FieldDescriptor) -> Resolution | None:
        value = self.values.value_for("notice_period")
        picked = match_option(value, descriptor.options, self.catalog) if descriptor.options else value
        return Resolution(field_key="notice_period", value=picked or value, confidence=0.82,
                          action="select" if descriptor.options else "fill")

    def _dyn_essay_why_company(self, _company: str,
                               descriptor: FieldDescriptor) -> Resolution | None:
        return None  # essays are produced by the answer engine, not resolved here

    # ------------------------------------------------------------------ single field
    def resolve_field(self, descriptor: FieldDescriptor) -> Resolution:
        question = descriptor.question_text()

        signal = self.catalog.needs_human(f"{question} {' '.join(descriptor.options)}")
        if signal:
            return Resolution(confidence=0.0, blocked=f"needs a human: '{signal}'",
                              reason="escalation rule", method="human")
        if self.catalog.is_sensitive(question):
            return Resolution(confidence=0.0, blocked=f"sensitive field: '{question[:60]}'",
                              reason="sensitive-never-fill list", method="human")

        key = self._ats_lookup(descriptor)
        if key:
            value = self._value_for_descriptor(key, descriptor)
            if value is not None:
                return Resolution(field_key=key, value=value, confidence=0.98, method="ats_map",
                                  action=self._action_for(descriptor, key),
                                  reason=f"{self.context.ats} field map")

        dynamic = self._dynamic(descriptor)
        if dynamic:
            return dynamic

        if self.answers:
            remembered = self.answers.recall(question, self.context.company)
            if remembered:
                value = remembered.answer
                if descriptor.options:
                    value = match_option(value, descriptor.options, self.catalog) or value
                return Resolution(field_key=remembered.field_key or "answer_bank", value=value,
                                  confidence=min(0.97, remembered.confidence), method="answer_bank",
                                  action=self._action_for(descriptor, remembered.field_key),
                                  reason=f"answered before ({remembered.source})")

        key, score, reason = self._best_catalog_match(descriptor)
        if key and score >= REVIEW_THRESHOLD:
            value = self._value_for_descriptor(key, descriptor)
            if value:
                spec = self.catalog.by_key[key]
                if spec.get("escalate"):
                    return Resolution(field_key=key, confidence=score,
                                      blocked=f"policy: '{question[:60]}' is always escalated",
                                      method="human", reason=reason)
                return Resolution(
                    field_key=key, value=value, confidence=score,
                    method="token" if score >= FILL_THRESHOLD else "fuzzy",
                    action=self._action_for(descriptor, key),
                    needs_review=score < FILL_THRESHOLD, reason=reason)
            return Resolution(field_key=key, confidence=score, reason=f"{reason}; no value in profile")
        return Resolution(confidence=score, reason="no catalog match")

    @staticmethod
    def _match_date_format(value: str, descriptor: FieldDescriptor) -> str:
        """A text box asking for MM/DD/YYYY should not be handed 2019-05-01."""
        match = re.fullmatch(r"(\d{4})-(\d{2})(?:-(\d{2}))?", value.strip())
        if not match:
            return value
        year, month, day = match.group(1), match.group(2), match.group(3) or "01"
        hint = " ".join([descriptor.placeholder, descriptor.label, descriptor.aria_label,
                         descriptor.name]).lower()
        if descriptor.input_type in {"date", "month"}:
            return value                      # native pickers want ISO
        if "dd/mm" in hint or "dd-mm" in hint:
            return f"{day}/{month}/{year}"
        if "mm/dd" in hint or "mm-dd" in hint:
            return f"{month}/{day}/{year}"
        if "mm/yyyy" in hint or "mm/yy" in hint:
            return f"{month}/{year}"
        if "yyyy" in hint and "mm" not in hint:
            return year
        return value

    def _value_for_descriptor(self, key: str, descriptor: FieldDescriptor) -> str | None:
        value = self.values.value_for(key)
        if not value:
            return None
        if self.catalog.by_key.get(key, {}).get("type") in {"date", "month"}:
            value = self._match_date_format(value, descriptor)
        spec = self.catalog.by_key.get(key, {})
        if descriptor.options and spec.get("type") in {"select", "radio", "checkbox"} or \
                (descriptor.options and descriptor.input_type in {"select", "radio", "checkbox"}):
            return match_option(value, descriptor.options, self.catalog)
        if spec.get("type") == "checkbox" and not descriptor.options:
            return value
        return value

    def _action_for(self, descriptor: FieldDescriptor, key: str) -> str:
        spec = self.catalog.by_key.get(key, {})
        kind = spec.get("type") or descriptor.input_type
        observed = (descriptor.input_type or descriptor.tag or "").lower()
        if kind == "file" or observed == "file":
            return "upload"
        if observed == "checkbox":
            return "check"
        if observed in {"radio", "select", "select-one"} or descriptor.options:
            return "select"
        return "fill"

    # ------------------------------------------------------------------ whole form
    def resolve_form(self, descriptors: list[FieldDescriptor], url: str = "",
                     job_id: str = "") -> FillPlan:
        plan = FillPlan(url=url, ats=self.context.ats, job_id=job_id)
        for descriptor in descriptors:
            if not descriptor.visible and descriptor.input_type != "file":
                continue
            resolution = self.resolve_field(descriptor)
            if resolution.blocked:
                plan.blocking.append(f"{descriptor.question_text()[:70]} - {resolution.blocked}")
                plan.unresolved.append(descriptor)
                continue
            if not resolution.value:
                if descriptor.required or descriptor.input_type in {"file"}:
                    plan.unresolved.append(descriptor)
                continue
            plan.fields.append(FilledField(
                selector=descriptor.selector, frame=descriptor.frame,
                field_key=resolution.field_key,
                question=descriptor.question_text(), value=resolution.value,
                method=resolution.method, confidence=round(resolution.confidence, 3),
                action=resolution.action, needs_review=resolution.needs_review))
            if resolution.action == "upload":
                plan.documents[resolution.field_key] = resolution.value
        log.debug("resolved %d/%d fields (%d unresolved, %d blocking)",
                  len(plan.fields), len(descriptors), len(plan.unresolved), len(plan.blocking))
        return plan
