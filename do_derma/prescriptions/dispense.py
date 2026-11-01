from __future__ import annotations

from typing import Any

import frappe
from do_health.pharmacy.prescriptions import (
	HIDE_FROM_PHARMACY_FIELD,
	dispensed_quantities,
	prescription_quantity,
)
from frappe import _
from frappe.utils import flt

CARD_ROW_FIELDS = [
	"name",
	"parent",
	"medication",
	"drug_code",
	"drug_name",
	"dosage",
	"period",
	"interval",
	"interval_uom",
	"dosage_form",
	"comment",
]
LINE_FIELDS = ("medication", "drug_code", "drug_name", "dosage", "period", "dosage_form", "comment")
DISPENSED = "Dispensed"
PARTIAL = "Partially dispensed"
NOT_DISPENSED = "Not dispensed"


def is_tracked(row) -> bool:
	"""Migrated lines the old pharmacy handled have no dispense records; they count as handed over."""
	return not row.get(HIDE_FROM_PHARMACY_FIELD)


def get_quantities(rows) -> dict[str, dict[str, float]]:
	"""Prescribed and net dispensed qty per Drug Prescription row name."""
	dispensed = dispensed_quantities([row.name for row in rows if is_tracked(row)])
	quantities = {}
	for row in rows:
		prescribed = prescription_quantity(row)
		given = flt(dispensed.get(row.name)) if is_tracked(row) else prescribed
		quantities[row.name] = {"prescribed_qty": prescribed, "dispensed_qty": given}
	return quantities


def get_line_status(prescribed: float, dispensed: float) -> str:
	if dispensed <= 0:
		return NOT_DISPENSED
	if dispensed + 0.0001 >= prescribed:
		return DISPENSED
	return PARTIAL


def get_summary(statuses: list[str]) -> dict[str, int]:
	return {
		"lines": len(statuses),
		"dispensed": statuses.count(DISPENSED),
		"partial": statuses.count(PARTIAL),
	}


def ensure_not_dispensed(rows) -> None:
	"""Refuse once anything is dispensed, reading past the snapshot so a dispense committed meanwhile counts."""
	dispensed = dispensed_quantities([row.name for row in rows], for_update=True)
	for row in rows:
		if flt(dispensed.get(row.name)) > 0:
			frappe.throw(
				_("{0} has been dispensed. Return it at the pharmacy first.").format(
					row.medication or row.drug_name or row.drug_code
				),
				frappe.ValidationError,
			)


def get_previous_encounters(encounter_doc, start: int = 0, page_length: int = 0) -> list:
	"""The patient's other visits that prescribed a medication, newest first."""
	return frappe.get_all(
		"Patient Encounter",
		filters=[
			["patient", "=", encounter_doc.patient],
			["name", "!=", encounter_doc.name],
			["docstatus", "<", 2],
			["status", "!=", "Cancelled"],
			["Drug Prescription", "medication", "is", "set"],
		],
		# `creation` is selected because DISTINCT needs every ORDER BY column.
		fields=["name", "encounter_date", "practitioner_name", "creation"],
		order_by="encounter_date desc, creation desc",
		limit_start=start,
		limit_page_length=page_length,
		distinct=True,
	)


def get_previous_cards(encounter_doc, start: int, limit: int) -> dict[str, Any]:
	"""One card per earlier visit; the first page also summarises every earlier line."""
	encounters = get_previous_encounters(encounter_doc, start, limit + 1)
	page = encounters[:limit]
	rows = get_card_rows([encounter.name for encounter in page])
	quantities = get_quantities(rows)
	result = {
		"cards": [get_card(encounter, rows, quantities) for encounter in page],
		"has_more": len(encounters) > limit,
	}
	if not start:
		result["summary"] = get_previous_summary(encounter_doc)
	return result


def get_previous_summary(encounter_doc) -> dict[str, int]:
	rows = get_card_rows([encounter.name for encounter in get_previous_encounters(encounter_doc)])
	quantities = get_quantities(rows).values()
	return get_summary(
		[get_line_status(item["prescribed_qty"], item["dispensed_qty"]) for item in quantities]
	)


def get_card_rows(encounters: list[str]) -> list:
	if not encounters:
		return []
	fields = list(CARD_ROW_FIELDS)
	if frappe.get_meta("Drug Prescription").has_field(HIDE_FROM_PHARMACY_FIELD):
		fields.append(HIDE_FROM_PHARMACY_FIELD)
	return frappe.get_all(
		"Drug Prescription",
		filters={
			"parent": ("in", encounters),
			"parenttype": "Patient Encounter",
			"medication": ("is", "set"),
		},
		fields=fields,
		order_by="idx asc",
		limit_page_length=0,
	)


def get_card(encounter, rows: list, quantities: dict) -> dict[str, Any]:
	lines = [get_line(row, quantities[row.name]) for row in rows if row.parent == encounter.name]
	return {
		"encounter": encounter.name,
		"encounter_date": encounter.encounter_date,
		"practitioner_name": encounter.practitioner_name,
		"lines": lines,
	}


def get_line(row, quantity: dict[str, float]) -> dict[str, Any]:
	return {
		**{key: row.get(key) for key in LINE_FIELDS},
		**quantity,
		"status": get_line_status(quantity["prescribed_qty"], quantity["dispensed_qty"]),
	}
