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
