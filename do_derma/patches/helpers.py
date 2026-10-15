from __future__ import annotations

import frappe


def sync_sidebar_items() -> None:
	"""Create do_derma's sidebar items (do_derma.sidebar) through do_health's standard-item sync."""
	if not frappe.db.exists("DocType", "Health Sidebar Item"):
		return
	from do_health.setup.sidebar_items import sync_standard_items

	sync_standard_items()


def ensure_standard_page(page_name: str, title: str) -> None:
	"""Converge a source-backed desk Page row on sites without developer mode.

	Field-by-field so an unchanged row is never written and `modified` stays put.
	"""
	values = {
		"page_name": page_name,
		"title": title,
		"module": "Do Derma",
		"standard": "Yes",
		"system_page": 0,
	}

	if frappe.db.exists("Page", page_name):
		doc = frappe.get_doc("Page", page_name)
		changed = False
		for fieldname, value in values.items():
			if doc.get(fieldname) != value:
				doc.set(fieldname, value)
				changed = True
		if changed:
			doc.save(ignore_permissions=True)
	else:
		frappe.get_doc({"doctype": "Page", "name": page_name, **values}).insert(ignore_permissions=True)

	frappe.clear_cache()
