"""The scribe learns how each doctor writes.

generate_note keeps the AI draft on the encounter. Once a day, for completed encounters,
the draft is compared with the note the doctor kept, and changes that repeat across visits
become Suggested rows in Derma Style Rule. Only rules a person sets to Active reach the
note prompt. The model itself is never retrained, and each draft is deleted once read.

Off unless Derma Settings.enable_style_learning is ticked.
"""

from __future__ import annotations

import json
import re
from typing import Any

import frappe
from frappe.utils import cint, cstr

from do_derma import voice
from do_derma.assessment import HP_FIELDS, SOAP_FIELDS
from do_derma.schema import AI_DRAFT_FIELD

MIN_EDITED_VISITS = 5
MIN_RULE_VISITS = 3
MAX_VISITS = 20
MAX_ACTIVE_RULES = 15
MAX_RULE_CHARS = 200
MAX_SECTION_CHARS = 1500

LEARNING_PROMPT = """You study how one dermatologist edits AI-drafted clinical notes. You receive a JSON list of visits; each visit maps a note section to its "draft" (AI) and "final" (what the doctor kept).

Find WRITING PREFERENCES the doctor applies repeatedly: section order, wording, terminology, abbreviations, level of detail, sentence style, what they always add or remove as a matter of format.

Rules for your answer:
- A preference must appear in at least 3 different visits. Count them honestly. One-off corrections are not preferences.
- Corrections of content are not preferences: a changed finding, diagnosis, drug, dose, duration or date means the draft was wrong for that visit. Never turn one into a rule.
- A rule must never tell the scribe to state, assume or omit a clinical fact, or to choose a treatment. Style only.
- Text the doctor adds in many visits is still content if it records something said, done, advised, found or prescribed ("Sunscreen advised", "Consent taken", "No allergies"). It was true of those visits and may be false of the next, so never make a rule that adds it. Test: if following the rule could put something in the record that did not happen in that visit, it is not a rule.
- Write each rule as one short general instruction for a scribe, with no numbers, patient details, drug names or diagnoses.
- Few good rules are better than many. An empty list is a good answer.

Respond with ONLY a valid JSON object: {"rules": [{"rule": "...", "visits": 3}]}"""


def _squeezed(value: Any) -> str:
	return " ".join(cstr(value).split())


def changed_sections(draft: dict[str, Any], final: dict[str, Any]) -> dict[str, dict[str, str]]:
	"""Sections the doctor changed, spacing aside. A section left blank is a removal, not a style signal."""
	changes = {}
	for field in (*SOAP_FIELDS, *HP_FIELDS):
		before, after = _squeezed(draft.get(field)), _squeezed(final.get(field))
		if before and after and before != after:
			changes[field] = {"draft": before[:MAX_SECTION_CHARS], "final": after[:MAX_SECTION_CHARS]}
	return changes


def without_name(changes: dict[str, dict[str, str]], patient_name: str | None) -> dict[str, dict[str, str]]:
	"""The learning call has no need for who the patient is."""
	words = [re.escape(word) for word in cstr(patient_name).split() if len(word) > 2]
	if not words:
		return changes
	pattern = re.compile(r"\b(" + "|".join(words) + r")\b", re.IGNORECASE)
	return {field: {key: pattern.sub("the patient", text) for key, text in pair.items()} for field, pair in changes.items()}


def usable_rule(row: Any, known: set[str]) -> str | None:
	"""The model's rule, if it passes the checks that do not depend on trusting the model."""
	if not isinstance(row, dict) or cint(row.get("visits")) < MIN_RULE_VISITS:
		return None
	rule = _squeezed(row.get("rule"))
	# ponytail: any digit rejects the rule, a cheap guard against doses; a drug name still needs the doctor's review
	if not rule or len(rule) > MAX_RULE_CHARS or re.search(r"\d", rule) or rule.casefold() in known:
		return None
	return rule


def style_rules(practitioner: str | None) -> list[str]:
	if not practitioner:
		return []
	return frappe.get_all(
		"Derma Style Rule",
		filters={"practitioner": practitioner, "status": "Active"},
		pluck="rule",
		order_by="modified desc",
		limit=MAX_ACTIVE_RULES,
	)


def learn_for_practitioner(practitioner: str) -> int:
	"""Returns how many rules were suggested. Drafts stay until enough edited visits have built up."""
	fields = ["name", "patient_name", AI_DRAFT_FIELD, *SOAP_FIELDS, *HP_FIELDS]
	rows = frappe.get_all(
		"Patient Encounter",
		filters={"practitioner": practitioner, "docstatus": 1, AI_DRAFT_FIELD: ["is", "set"]},
		fields=fields,
		order_by="creation desc",
		limit=500,
	)
	visits, sent = [], []
	for row in rows:
		changes = changed_sections(voice.safe_parse_json(row.get(AI_DRAFT_FIELD)) or {}, row)
		if not changes:
			_forget_draft(row["name"])  # kept as drafted: nothing to learn
		elif len(visits) < MAX_VISITS:
			visits.append(without_name(changes, row.get("patient_name")))
			sent.append(row["name"])
	if len(visits) < MIN_EDITED_VISITS:
		return 0

	raw, usage = voice.chat_complete_with_usage(LEARNING_PROMPT, json.dumps(visits, ensure_ascii=False), temperature=0.1)
	parsed = voice.safe_parse_json(raw)
	if not parsed:
		voice.record_usage("Learning", status="Failed", error="unparseable reply", **usage)
		return 0
	voice.record_usage("Learning", **usage)

	known = {_squeezed(rule).casefold() for rule in frappe.get_all("Derma Style Rule", filters={"practitioner": practitioner}, pluck="rule")}
	suggested = 0
	rules = parsed.get("rules")
	for row in rules if isinstance(rules, list) else []:
		rule = usable_rule(row, known)
		if rule:
			known.add(rule.casefold())
			frappe.get_doc({"doctype": "Derma Style Rule", "practitioner": practitioner, "rule": rule, "visits": cint(row["visits"])}).insert(ignore_permissions=True)
			suggested += 1
	for name in sent:
		_forget_draft(name)
	return suggested


def _forget_draft(encounter: str) -> None:
	frappe.db.set_value("Patient Encounter", encounter, AI_DRAFT_FIELD, None, update_modified=False)


def learn_style_rules() -> None:
	"""Daily. One doctor's failure must not stop the others."""
	if not voice.is_enabled() or not cint(voice._setting("enable_style_learning", 0)):
		return
	practitioners = frappe.get_all(
		"Patient Encounter",
		filters={"docstatus": 1, AI_DRAFT_FIELD: ["is", "set"]},
		pluck="practitioner",
		distinct=True,
	)
	for practitioner in practitioners:
		if not practitioner:
			continue
		try:
			learn_for_practitioner(practitioner)
			frappe.db.commit()  # nosemgrep: each doctor's rules stand on their own
		except Exception:  # noqa: BLE001
			frappe.db.rollback()
			frappe.log_error(title=f"Style learning failed: {practitioner}")
