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
	"""Migrated lines the old pharmacy handled have no dispense records to read."""
	return not row.get(HIDE_FROM_PHARMACY_FIELD)


def get_quantities(rows) -> dict[str, dict[str, float | None]]:
	"""Prescribed and net dispensed qty per Drug Prescription row name."""
	dispensed = dispensed_quantities([row.name for row in rows])
	return {
		row.name: {
			"prescribed_qty": prescription_quantity(row) if is_tracked(row) else None,
			"dispensed_qty": flt(dispensed.get(row.name)) if is_tracked(row) else None,
		}
		for row in rows
	}


def get_card_status(lines: list[dict[str, Any]]) -> str:
	tracked = [line for line in lines if line["dispensed_qty"] is not None]
	if not tracked:
		return ""
	given = [line["dispensed_qty"] > 0 for line in tracked]
	if not any(given):
		return NOT_DISPENSED
	if all(given) and all(line["dispensed_qty"] + 0.0001 >= line["prescribed_qty"] for line in tracked):
		return DISPENSED
	return PARTIAL


def ensure_not_dispensed(rows) -> None:
	dispensed = dispensed_quantities([row.name for row in rows])
	for row in rows:
		if flt(dispensed.get(row.name)) > 0:
			frappe.throw(
				_("{0} has been dispensed. Return it at the pharmacy first.").format(
					row.medication or row.drug_name or row.drug_code
				),
				frappe.ValidationError,
			)


def get_previous_cards(encounter_doc, start: int, limit: int) -> dict[str, Any]:
	"""The patient's other visits that prescribed a medication, newest first, one card each."""
	encounters = frappe.get_all(
		"Patient Encounter",
		filters=[
			["patient", "=", encounter_doc.patient],
			["name", "!=", encounter_doc.name],
			["docstatus", "<", 2],
			["status", "!=", "Cancelled"],
			["Drug Prescription", "medication", "is", "set"],
		],
		fields=["name", "encounter_date", "practitioner_name", "creation"],
		order_by="encounter_date desc, creation desc",
		limit_start=start,
		limit_page_length=limit + 1,
		distinct=True,
	)
	page = encounters[:limit]
	rows = get_card_rows([encounter.name for encounter in page])
	quantities = get_quantities(rows)
	return {
		"cards": [get_card(encounter, rows, quantities) for encounter in page],
		"has_more": len(encounters) > limit,
	}


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
	lines = [
		{**{key: row.get(key) for key in LINE_FIELDS}, **quantities[row.name]}
		for row in rows
		if row.parent == encounter.name
	]
	return {
		"encounter": encounter.name,
		"encounter_date": encounter.encounter_date,
		"practitioner_name": encounter.practitioner_name,
		"status": get_card_status(lines),
		"lines": lines,
	}
