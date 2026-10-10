from __future__ import annotations

import re
from collections import Counter
from typing import Any

import frappe
from frappe.utils import add_months, flt, today

SEARCH_LIMIT = 50
FAVOURITES_LIMIT = 15
CANDIDATE_LIMIT = 200
ITEMS_PER_RESULT = 3
SUGGESTION_LIMIT = 3
USAGE_MONTHS = 12
MIN_BRAND_LENGTH = 3
# Dosage-form words name no product, so a shared one proves nothing.
FORM_WORDS = frozenset(
	"cap caps capsule capsules tab tabs tablet tablets cream gel lotion ointment solution drops spray foam"
	" oral external use soft gelatin".split()
)


def get_items(medication: str, warehouse: str | None) -> list[dict[str, Any]]:
	"""The medication's Linked Items, or stock Items named like it when none are linked."""
	linked = frappe.get_all(
		"Medication Linked Item",
		filters={"parent": medication, "parenttype": "Medication"},
		pluck="item",
		order_by="idx asc",
	)
	linked = [code for code in linked if code]
	if not linked:
		return get_suggested_items(medication, warehouse)
	items = frappe.get_all(
		"Item",
		filters={"name": ["in", linked], "disabled": 0},
		fields=["name", "item_name", "stock_uom"],
	)
	by_code = {item.name: item for item in items}
	return get_item_rows([by_code[code] for code in linked if code in by_code], warehouse, is_suggested=False)


def get_suggested_items(medication: str, warehouse: str | None) -> list[dict[str, Any]]:
	"""Stock Items sharing the first word of the medication's generic name, the most shared words first.
	The name itself can lead with the dosage form, so it never supplies the brand."""
	words = get_words(frappe.db.get_value("Medication", medication, "generic_name") or medication)
	if not words or len(words[0]) < MIN_BRAND_LENGTH:
		return []
	candidates = frappe.get_all(
		"Item",
		filters={"item_name": ["like", f"%{words[0]}%"], "disabled": 0, "is_stock_item": 1},
		fields=["name", "item_name", "stock_uom"],
	)
	others = set(words[1:]) - FORM_WORDS
	shared = {item.name: len(others & set(get_words(item.item_name))) for item in candidates}
	# Beyond the brand, a medication that names more must share some of it.
	matches = [item for item in candidates if shared[item.name] or not others]
	ranked = sorted(matches, key=lambda item: (-shared[item.name], item.item_name))
	return get_item_rows(ranked[:SUGGESTION_LIMIT], warehouse, is_suggested=True)


def get_words(name: str) -> list[str]:
	"""Lower-case words of a name, without its bracketed route such as "[Oral]"."""
	return re.findall(r"[a-z0-9.]+", re.sub(r"\[[^\]]*\]", " ", (name or "").lower()))


def get_item_rows(items: list, warehouse: str | None, is_suggested: bool) -> list[dict[str, Any]]:
	stock = get_stock([item.name for item in items], warehouse)
	return [
		{
			"item_code": item.name,
			"item_name": item.item_name,
			"stock_uom": item.stock_uom,
			"actual_qty": stock.get(item.name, 0.0) if warehouse else None,
			"is_suggested": is_suggested,
		}
		for item in items
	]


def get_stock(item_codes: list[str], warehouse: str | None) -> dict[str, float]:
	if not warehouse or not item_codes:
		return {}
	bins = frappe.get_all(
		"Bin",
		filters={"item_code": ["in", item_codes], "warehouse": warehouse},
		fields=["item_code", "actual_qty"],
	)
	return {row.item_code: flt(row.actual_qty) for row in bins}


def search(txt: str, practitioner: str | None, warehouse: str | None) -> list[dict[str, Any]]:
	"""Medications matching `txt`, the doctor's habits first, then the clinic's, then by name.
	An empty search returns the doctor's favourites."""
	doctor_uses, clinic_uses = get_usage(practitioner)
	txt = txt.strip()
	if txt:
		names = get_matching_names(txt, clinic_uses)
		limit = SEARCH_LIMIT
	else:
		names = set(clinic_uses)
		limit = FAVOURITES_LIMIT
	enabled = frappe.get_all("Medication", filters={"name": ["in", list(names)], "disabled": 0}, pluck="name")
	ranked = sorted(enabled, key=lambda name: (-doctor_uses[name], -clinic_uses[name], name.lower()))
	return [
		{"medication": name, "doctor_uses": doctor_uses[name], "items": get_result_items(name, warehouse)}
		for name in ranked[:limit]
	]


def get_matching_names(txt: str, clinic_uses: Counter) -> set[str]:
	"""Name matches, plus every used medication that matches, so a common drug is never cut off."""
	pattern = f"%{txt}%"
	names = frappe.get_all(
		"Medication",
		filters={"disabled": 0},
		or_filters={"name": ["like", pattern], "generic_name": ["like", pattern]},
		pluck="name",
		limit=CANDIDATE_LIMIT,
	)
	lowered = txt.lower()
	return {*names, *(name for name in clinic_uses if lowered in name.lower())}


def get_result_items(medication: str, warehouse: str | None) -> list[dict[str, Any]]:
	items = get_items(medication, warehouse)
	return sorted(items, key=lambda item: not flt(item["actual_qty"]) > 0)[:ITEMS_PER_RESULT]


def get_usage(practitioner: str | None) -> tuple[Counter, Counter]:
	"""How often each medication was prescribed in the last year, by this doctor and by everyone."""
	rows = frappe.db.sql(
		"""
		select prescription.medication, encounter.practitioner, count(*) as uses
		from `tabDrug Prescription` prescription
		join `tabPatient Encounter` encounter on encounter.name = prescription.parent
		where prescription.parenttype = 'Patient Encounter'
			and ifnull(prescription.medication, '') != ''
			and encounter.docstatus < 2
			and encounter.encounter_date >= %(since)s
		group by prescription.medication, encounter.practitioner
		""",
		{"since": add_months(today(), -USAGE_MONTHS)},
		as_dict=True,
	)
	doctor_uses, clinic_uses = Counter(), Counter()
	for row in rows:
		clinic_uses[row.medication] += row.uses
		if practitioner and row.practitioner == practitioner:
			doctor_uses[row.medication] += row.uses
	return doctor_uses, clinic_uses
