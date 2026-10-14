from __future__ import annotations

import frappe
from frappe import _

from do_derma.prescriptions import dispense


def get_rows_to_cancel(encounter_doc, names: list[str]) -> list:
	"""The named ordered rows, or every ordered row when no name is given."""
	rows = encounter_doc.get("drug_prescription") or []
	if not names:
		ordered = [row for row in rows if row.medication_request]
		if not ordered:
			frappe.throw(_("Nothing to cancel: no medication is ordered."), frappe.ValidationError)
		return ordered
	by_name = {row.name: row for row in rows}
	for name in names:
		if name not in by_name:
			frappe.throw(_("Row {0} does not belong to this encounter.").format(name), frappe.ValidationError)
		if not by_name[name].medication_request:
			frappe.throw(_("Row {0} is not ordered.").format(by_name[name].idx), frappe.ValidationError)
	return [by_name[name] for name in names]


def cancel(encounter_doc, names: list[str]) -> None:
	"""Cancel the rows' Medication Requests and unlock the rows; the caller saves the encounter."""
	rows = get_rows_to_cancel(encounter_doc, names)
	# The pharmacy locks the same rows while it validates a dispense.
	frappe.db.get_values("Drug Prescription", {"name": ("in", [row.name for row in rows])}, "name", for_update=True)
	dispense.ensure_not_dispensed(rows)
	for row in rows:
		request = frappe.get_doc("Medication Request", row.medication_request)
		if request.docstatus == 1:
			request.flags.ignore_permissions = True
			request.cancel()
		row.medication_request = None
