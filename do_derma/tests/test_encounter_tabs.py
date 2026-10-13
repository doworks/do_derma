from __future__ import annotations

import json
from unittest.mock import patch

import frappe
from frappe.tests import IntegrationTestCase
from frappe.utils import nowdate, nowtime

import do_derma.api as api
from do_derma.tests.test_api import DermaTestHelpers


class PrescriptionHelpers(DermaTestHelpers):
	"""Rows the Rx tab would send, with healthcare's two mandatory fields filled."""

	def setUp(self):
		self.addCleanup(frappe.set_user, "Administrator")
		frappe.set_user("Administrator")

	def _row(self, **extra):
		"""The two fields healthcare marks mandatory, plus whatever the test cares about."""
		return {
			"medication": self._get_or_create_medication(),
			"period": self._get_or_create_prescription_duration(),
			**extra,
		}

	def _get_or_create_medication(self):
		existing = frappe.db.get_value("Medication", {}, "name")
		if existing:
			return existing
		token = frappe.generate_hash(length=8)
		return (
			frappe.get_doc(
				{
					"doctype": "Medication",
					"generic_name": f"Derma{token}",
					"dosage_form": frappe.db.get_value("Dosage Form", {}, "name"),
				}
			)
			.insert(ignore_permissions=True)
			.name
		)

	def _get_or_create_prescription_duration(self):
		existing = frappe.db.get_value("Prescription Duration", {}, "name")
		if existing:
			return existing
		return (
			frappe.get_doc({"doctype": "Prescription Duration", "number": 5, "period": "Day"})
			.insert(ignore_permissions=True)
			.name
		)


class TestDermaPrescriptions(PrescriptionHelpers, IntegrationTestCase):
	"""The Rx tab writes and reads Patient Encounter's drug_prescription table."""

	def test_a_saved_row_reads_back(self):
		encounter = self._make_encounter(self._make_patient())
		saved = api.set_derma_prescriptions(
			payload=json.dumps([self._row(drug_name="Hydrocortisone 1%", comment="Thin layer at night")]),
			encounter=encounter.name,
		)
		self.assertEqual(len(saved["drug_prescription"]), 1)
		self.assertEqual(saved["drug_prescription"][0]["drug_name"], "Hydrocortisone 1%")

		reloaded = api.get_derma_prescriptions(encounter=encounter.name)
		self.assertEqual(len(reloaded["drug_prescription"]), 1)
		self.assertEqual(reloaded["drug_prescription"][0]["comment"], "Thin layer at night")

	def _prescribe(self, encounter, drug_name):
		api.set_derma_prescriptions(payload=json.dumps([self._row(drug_name=drug_name)]), encounter=encounter.name)

	def test_the_printout_lists_each_saved_medication(self):
		patient = self._make_patient()
		frappe.db.set_value("Patient", patient, "allergies", "Penicillin")
		encounter = self._make_encounter(patient)
		api.set_derma_prescriptions(
			payload=json.dumps([self._row(dosage="", comment="Thin layer <b>at night</b>")]),
			encounter=encounter.name,
		)
		page = api.get_derma_print_html("prescription", encounter.name)
		medication = self._get_or_create_medication()
		self.assertIn("Prescription", page["title"])
		self.assertEqual(page["html"].count(f">{medication}<"), 1)
		self.assertIn("Thin layer &lt;b&gt;at night&lt;/b&gt;", page["html"])
		self.assertIn("Penicillin", page["html"])
		self.assertIn(patient, page["html"])
		self.assertIn(">Notes<", page["html"])
		self.assertNotIn(">Form<", page["html"])
		self.assertNotIn(">Repeats<", page["html"])
		self.assertNotIn("font-style:italic", page["html"])

	def test_a_visit_without_medications_has_nothing_to_print(self):
		encounter = self._make_encounter(self._make_patient())
		with self.assertRaisesRegex(frappe.ValidationError, "No medications to print"):
			api.get_derma_print_html("prescription", encounter.name)

	def test_an_unknown_printable_is_refused(self):
		with self.assertRaises(frappe.ValidationError):
			api.get_derma_print_html("receipt", "anything")

	def test_rows_replace_the_previous_set(self):
		encounter = self._make_encounter(self._make_patient())
		api.set_derma_prescriptions(
			payload=json.dumps([self._row(drug_name="First"), self._row(drug_name="Second")]),
			encounter=encounter.name,
		)
		saved = api.set_derma_prescriptions(
			payload=json.dumps([self._row(drug_name="Only")]), encounter=encounter.name
		)
		self.assertEqual([row["drug_name"] for row in saved["drug_prescription"]], ["Only"])

	def test_a_resent_row_keeps_fields_the_tab_does_not_show(self):
		"""The tab resends each loaded row whole, so hidden fields survive a comment edit."""
		encounter = self._make_encounter(self._make_patient())
		saved = api.set_derma_prescriptions(
			payload=json.dumps([self._row(interval=2, interval_uom="Day")]), encounter=encounter.name
		)
		resent = {**saved["drug_prescription"][0], "comment": "After meals"}
		saved = api.set_derma_prescriptions(
			payload=json.dumps([resent], default=str), encounter=encounter.name
		)
		row = saved["drug_prescription"][0]
		self.assertEqual((row["interval"], row["interval_uom"], row["comment"]), (2, "Day", "After meals"))

	def test_a_legacy_repeat_count_is_kept_as_sent(self):
		"""The tab no longer shows repeats; a stored count is resent untouched, never judged."""
		encounter = self._make_encounter(self._make_patient())
		saved = api.set_derma_prescriptions(
			payload=json.dumps([self._row(number_of_repeats_allowed=500)]), encounter=encounter.name
		)
		self.assertEqual(saved["drug_prescription"][0]["number_of_repeats_allowed"], 500)

	def _add_assessment_diagnosis(self, encounter, *names):
		doc = frappe.get_doc("Patient Encounter", encounter.name)
		for name in names:
			if not frappe.db.exists("Diagnosis", name):
				frappe.get_doc({"doctype": "Diagnosis", "diagnosis": name}).insert(ignore_permissions=True)
			doc.append("diagnosis", {"diagnosis": name})
		doc.save(ignore_permissions=True)

	def test_the_assessment_diagnosis_is_offered_by_name(self):
		encounter = self._make_encounter(self._make_patient())
		self._add_assessment_diagnosis(encounter, "Derma Acne Test", "Derma Rosacea Test", "Derma Acne Test")
		loaded = api.get_derma_prescriptions(encounter=encounter.name)
		self.assertEqual(loaded["assessment_diagnosis"], "Derma Acne Test, Derma Rosacea Test")
		self.assertEqual(loaded["diagnosis"], "")

	def test_the_rx_diagnosis_saves_without_touching_the_assessment(self):
		encounter = self._make_encounter(self._make_patient())
		self._add_assessment_diagnosis(encounter, "Derma Acne Test")
		saved = api.set_derma_prescriptions(
			payload=json.dumps([self._row()]), encounter=encounter.name, diagnosis="Acne vulgaris, moderate"
		)
		self.assertEqual(saved["diagnosis"], "Acne vulgaris, moderate")
		rows = frappe.get_all("Patient Encounter Diagnosis", {"parent": encounter.name}, pluck="diagnosis")
		self.assertEqual(rows, ["Derma Acne Test"])

	def test_a_save_without_a_diagnosis_keeps_the_stored_one(self):
		encounter = self._make_encounter(self._make_patient())
		api.set_derma_prescriptions(payload=json.dumps([self._row()]), encounter=encounter.name, diagnosis="Eczema")
		saved = api.set_derma_prescriptions(payload=json.dumps([self._row()]), encounter=encounter.name)
		self.assertEqual(saved["diagnosis"], "Eczema")

	def test_the_printout_names_the_rx_diagnosis_only_when_set(self):
		encounter = self._make_encounter(self._make_patient())
		api.set_derma_prescriptions(payload=json.dumps([self._row()]), encounter=encounter.name)
		self.assertNotIn(">Diagnosis:<", api.get_derma_print_html("prescription", encounter.name)["html"])
		api.set_derma_prescriptions(
			payload=json.dumps([self._row()]), encounter=encounter.name, diagnosis="Psoriasis & plaque"
		)
		html = api.get_derma_print_html("prescription", encounter.name)["html"]
		self.assertIn(">Diagnosis:<", html)
		self.assertIn("Psoriasis &amp; plaque", html)
		self.assertLess(html.index(">Allergies:<"), html.index(">Diagnosis:<"))

	def test_is_gated(self):
		frappe.set_user(self._make_limited_user())
		with self.assertRaises(frappe.PermissionError):
			api.get_derma_prescriptions(encounter="does-not-matter")

	def test_the_chart_counts_prescriptions_without_loading_them(self):
		"""The Prescription tab's badge reads this; the rows themselves load on demand."""
		patient = self._make_patient()
		encounter = self._make_encounter(patient)
		chart = api.get_patient_derma_chart(patient_id=patient, encounter=encounter.name)
		self.assertEqual(chart["prescription_count"], 0)

		api.set_derma_prescriptions(
			payload=json.dumps([self._row(drug_name="First"), self._row(drug_name="Second")]),
			encounter=encounter.name,
		)
		chart = api.get_patient_derma_chart(patient_id=patient, encounter=encounter.name)
		self.assertEqual(chart["prescription_count"], 2)

	def test_the_count_is_zero_without_an_encounter(self):
		patient = self._make_patient()
		chart = api.get_patient_derma_chart(patient_id=patient)
		self.assertEqual(chart["prescription_count"], 0)


class TestPreviousPrescriptions(PrescriptionHelpers, IntegrationTestCase):
	"""One card per earlier visit that prescribed, newest first, five at a time."""

	def _visit_with(self, patient, *drug_names):
		encounter = self._make_encounter(patient)
		rows = [self._row(drug_name=name) for name in drug_names]
		api.set_derma_prescriptions(payload=json.dumps(rows), encounter=encounter.name)
		return encounter

	def test_cards_page_newest_first(self):
		patient = self._make_patient()
		visits = [self._visit_with(patient, f"Drug {index}") for index in range(6)]
		current = self._make_encounter(patient)
		first = api.get_previous_prescriptions(encounter=current.name)
		second = api.get_previous_prescriptions(encounter=current.name, start=5)
		self.assertEqual((len(first["cards"]), first["has_more"]), (5, True))
		self.assertEqual((len(second["cards"]), second["has_more"]), (1, False))
		shown = [card["encounter"] for card in first["cards"] + second["cards"]]
		self.assertEqual(shown, [visit.name for visit in reversed(visits)])

	def test_a_visit_with_two_rows_is_one_card(self):
		patient = self._make_patient()
		self._visit_with(patient, "Doxycycline", "Adapalene")
		cards = api.get_previous_prescriptions(encounter=self._make_encounter(patient).name)["cards"]
		self.assertEqual(len(cards), 1)
		self.assertEqual([line["drug_name"] for line in cards[0]["lines"]], ["Doxycycline", "Adapalene"])
		self.assertEqual(cards[0]["status"], "Not dispensed")

	def test_the_current_and_cancelled_visits_are_skipped(self):
		patient = self._make_patient()
		cancelled = self._visit_with(patient, "Isotretinoin")
		frappe.db.set_value("Patient Encounter", cancelled.name, "status", "Cancelled")
		current = self._visit_with(patient, "Hydrocortisone")
		self.assertEqual(api.get_previous_prescriptions(encounter=current.name)["cards"], [])

	def test_the_rx_tab_no_longer_returns_previous(self):
		current = self._make_encounter(self._make_patient())
		self.assertNotIn("previous", api.get_derma_prescriptions(encounter=current.name))

	def test_is_gated(self):
		frappe.set_user(self._make_limited_user())
		with self.assertRaises(frappe.PermissionError):
			api.get_previous_prescriptions(encounter="does-not-matter")


class TestOrderedPrescriptions(PrescriptionHelpers, IntegrationTestCase):
	"""A row turned into a Medication Request is kept verbatim, so resubmitting orders nothing twice."""

	def _ordered_encounter(self):
		encounter = self._make_encounter(self._make_patient())
		api.set_derma_prescriptions(payload=json.dumps([self._row(drug_name="Ordered")]), encounter=encounter.name)
		row = frappe.get_doc("Patient Encounter", encounter.name).drug_prescription[0]
		frappe.db.set_value(row.doctype, row.name, "medication_request", "MR-DERMA-TEST")
		return encounter

	def test_an_ordered_row_survives_a_save_that_omits_it(self):
		encounter = self._ordered_encounter()
		saved = api.set_derma_prescriptions(payload=json.dumps([self._row(drug_name="New")]), encounter=encounter.name)
		self.assertEqual(
			[(row["drug_name"], row.get("medication_request")) for row in saved["drug_prescription"]],
			[("Ordered", "MR-DERMA-TEST"), ("New", None)],
		)

	def test_an_edited_ordered_row_keeps_its_stored_values(self):
		"""A client resending a known request with changed fields does not overwrite what was ordered."""
		encounter = self._ordered_encounter()
		stored = api.get_derma_prescriptions(encounter=encounter.name)["drug_prescription"][0]
		saved = api.set_derma_prescriptions(
			payload=json.dumps(
				[
					self._row(
						drug_name="Edited",
						medication_request=stored["medication_request"],
						comment="Edited after ordering",
					)
				]
			),
			encounter=encounter.name,
		)
		self.assertEqual(len(saved["drug_prescription"]), 1)
		self.assertEqual(saved["drug_prescription"][0]["drug_name"], stored["drug_name"])
		self.assertEqual(saved["drug_prescription"][0]["comment"], stored["comment"])

	def test_an_ordered_row_keeps_its_name_across_saves(self):
		"""The pharmacy links a dispense to the row name; a later save must not rename it."""
		encounter = self._make_encounter(self._make_patient())
		api.set_derma_prescriptions(payload=json.dumps([self._row()]), encounter=encounter.name)
		ordered = api.submit_derma_prescriptions(encounter=encounter.name)["drug_prescription"]
		api.set_derma_prescriptions(payload=json.dumps([*ordered, self._row()], default=str), encounter=encounter.name)
		rows = frappe.get_all(
			"Drug Prescription", {"parent": encounter.name}, ["name", "medication_request", "idx"], order_by="idx"
		)
		self.assertEqual(rows[0].name, ordered[0]["name"])
		self.assertEqual([row.idx for row in rows], [1, 2])
		self.assertIsNone(rows[1].medication_request)

	def test_an_unknown_request_is_refused(self):
		encounter = self._ordered_encounter()
		with self.assertRaises(frappe.ValidationError):
			api.set_derma_prescriptions(
				payload=json.dumps([self._row(drug_name="Forged", medication_request="MR-OTHER")]),
				encounter=encounter.name,
			)


class TestSubmitPrescriptions(PrescriptionHelpers, IntegrationTestCase):
	"""Submit Rx orders the saved rows now; the visit itself stays open."""

	def _requests(self, encounter):
		return frappe.get_all("Medication Request", {"order_group": encounter.name}, pluck="name")

	def test_submit_orders_saved_rows_and_leaves_the_visit_open(self):
		encounter = self._make_encounter(self._make_patient())
		api.set_derma_prescriptions(payload=json.dumps([self._row()]), encounter=encounter.name)
		result = api.submit_derma_prescriptions(encounter=encounter.name)
		self.assertTrue(result["drug_prescription"][0]["medication_request"])
		self.assertEqual(len(self._requests(encounter)), 1)
		self.assertEqual(frappe.db.get_value("Patient Encounter", encounter.name, "docstatus"), 0)

	def test_a_second_submit_orders_only_new_rows(self):
		encounter = self._make_encounter(self._make_patient())
		api.set_derma_prescriptions(payload=json.dumps([self._row()]), encounter=encounter.name)
		ordered = api.submit_derma_prescriptions(encounter=encounter.name)["drug_prescription"]
		api.set_derma_prescriptions(payload=json.dumps([*ordered, self._row()], default=str), encounter=encounter.name)
		api.submit_derma_prescriptions(encounter=encounter.name)
		self.assertEqual(len(self._requests(encounter)), 2)

	def test_a_second_submit_with_nothing_new_is_refused(self):
		encounter = self._make_encounter(self._make_patient())
		api.set_derma_prescriptions(payload=json.dumps([self._row()]), encounter=encounter.name)
		api.submit_derma_prescriptions(encounter=encounter.name)
		with self.assertRaisesRegex(frappe.ValidationError, "Nothing to order"):
			api.submit_derma_prescriptions(encounter=encounter.name)
		self.assertEqual(len(self._requests(encounter)), 1)

	def test_completing_after_submit_orders_nothing_twice(self):
		encounter = self._make_encounter(self._make_patient())
		api.set_derma_prescriptions(payload=json.dumps([self._row()]), encounter=encounter.name)
		api.submit_derma_prescriptions(encounter=encounter.name)
		frappe.get_doc("Patient Encounter", encounter.name).submit()
		self.assertEqual(len(self._requests(encounter)), 1)

	def test_a_completed_visit_cannot_submit(self):
		encounter = self._make_encounter(self._make_patient(), docstatus=1)
		with self.assertRaises(frappe.ValidationError):
			api.submit_derma_prescriptions(encounter=encounter.name)

	def test_is_gated(self):
		frappe.set_user(self._make_limited_user())
		with self.assertRaises(frappe.PermissionError):
			api.submit_derma_prescriptions(encounter="does-not-matter")


class MedicationItemHelpers(PrescriptionHelpers):
	"""Medications, stock items and pharmacy stock for the Rx tab's medication and item pickers."""

	def setUp(self):
		super().setUp()
		self.token = frappe.generate_hash(length=8)
		self.warehouse = frappe.db.get_value("Warehouse", {"is_group": 0}, "name")
		self.medication = self._make_medication(f"DermaMed{self.token}")
		# Some fixtures commit, so the site's own setting is put back explicitly.
		original = frappe.db.get_single_value("Derma Settings", "prescription_warehouse")
		self.addCleanup(self._set_warehouse, original)
		self._set_warehouse(self.warehouse)

	def _make_medication(self, name):
		return (
			frappe.get_doc(
				{
					"doctype": "Medication",
					"generic_name": name,
					"dosage_form": frappe.db.get_value("Dosage Form", {}, "name"),
				}
			)
			.insert(ignore_permissions=True)
			.name
		)

	def _set_warehouse(self, warehouse):
		frappe.db.set_single_value("Derma Settings", "prescription_warehouse", warehouse)
		frappe.clear_document_cache("Derma Settings", "Derma Settings")

	def _make_item(self, item_name=None, actual_qty=None, disabled=0, is_stock_item=1):
		item_name = item_name or f"Derma Rx {frappe.generate_hash(length=8)}"
		item_code = (
			frappe.get_doc(
				{
					"doctype": "Item",
					"item_code": item_name,
					"item_name": item_name,
					"item_group": frappe.db.get_value("Item Group", {"is_group": 0}, "name"),
					"stock_uom": "Nos",
					"is_stock_item": is_stock_item,
					"disabled": disabled,
				}
			)
			.insert(ignore_permissions=True)
			.name
		)
		if actual_qty is not None:
			frappe.get_doc(
				{"doctype": "Bin", "item_code": item_code, "warehouse": self.warehouse, "actual_qty": actual_qty}
			).insert(ignore_permissions=True)
		return item_code

	def _link_item(self, actual_qty=None, disabled=0, item_name=None, medication=None):
		medication = medication or self.medication
		item_code = self._make_item(item_name, actual_qty=actual_qty, disabled=disabled)
		frappe.get_doc(
			{
				"doctype": "Medication Linked Item",
				"parent": medication,
				"parenttype": "Medication",
				"parentfield": "linked_items",
				"idx": len(frappe.get_doc("Medication", medication).linked_items) + 1,
				"item": item_code,
				"item_code": item_code,
			}
		).db_insert()
		return item_code


class TestMedicationItems(MedicationItemHelpers, IntegrationTestCase):
	"""The Rx tab's item chooser: a medication's linked items with stock in the pharmacy warehouse."""

	def test_items_carry_stock_in_the_prescription_warehouse(self):
		self._set_warehouse(self.warehouse)
		stocked = self._link_item(actual_qty=7)
		empty = self._link_item()
		result = api.get_medication_items(self.medication)
		self.assertEqual(result["warehouse"], self.warehouse)
		self.assertEqual(
			[(row["item_code"], row["actual_qty"], row["stock_uom"]) for row in result["items"]],
			[(stocked, 7, "Nos"), (empty, 0, "Nos")],
		)

	def test_no_warehouse_means_unknown_stock(self):
		self._set_warehouse(None)
		self._link_item(actual_qty=7)
		result = api.get_medication_items(self.medication)
		self.assertEqual(result["warehouse"], "")
		self.assertIsNone(result["items"][0]["actual_qty"])

	def test_disabled_items_are_skipped(self):
		self._set_warehouse(self.warehouse)
		self._link_item(disabled=1)
		self.assertEqual(api.get_medication_items(self.medication)["items"], [])

	def test_is_gated(self):
		frappe.set_user(self._make_limited_user())
		with self.assertRaises(frappe.PermissionError):
			api.get_medication_items(self.medication)


class TestSuggestedItems(MedicationItemHelpers, IntegrationTestCase):
	"""Without Linked Items, stock items named like the medication are suggested, never saved."""

	def setUp(self):
		super().setUp()
		self.brand = f"Dermabrand{self.token}"
		self.medication = self._make_medication(f"{self.brand} 20mg Capsules [Oral]")

	def _codes(self, medication=None):
		items = api.get_medication_items(medication or self.medication)["items"]
		return [(row["item_code"], row["is_suggested"]) for row in items]

	def test_items_sharing_the_brand_are_suggested_best_match_first(self):
		medication = self._make_medication(f"{self.brand} Forte 20mg Capsules [Oral]")
		partial = self._make_item(f"{self.brand.upper()} FORTE 10MG", actual_qty=4)
		best = self._make_item(f"{self.brand.upper()} FORTE 20MG CAPS 30")
		self.assertEqual(self._codes(medication), [(best, True), (partial, True)])
		self.assertEqual(frappe.get_doc("Medication", medication).linked_items, [])

	def test_a_brand_only_or_form_only_match_is_noise(self):
		"""A maker's brand spans many products; sharing only it, or only "cream", names another product."""
		self._make_item(f"{self.brand.upper()} NEOTONE EYES")
		self._make_item(f"{self.brand.upper()} NEOTONE CAPSULES")
		self.assertEqual(self._codes(), [])

	def test_a_one_word_medication_matches_on_its_brand(self):
		medication = self._make_medication(f"{self.brand}one")
		item = self._make_item(f"{self.brand.upper()}ONE 100MG TABS")
		self.assertEqual(self._codes(medication), [(item, True)])

	def test_disabled_and_non_stock_items_are_never_suggested(self):
		self._make_item(f"{self.brand} disabled", disabled=1)
		self._make_item(f"{self.brand} service", is_stock_item=0)
		self.assertEqual(self._codes(), [])

	def test_linked_items_replace_suggestions(self):
		self._make_item(f"{self.brand} 20MG CAPS 30")
		linked = self._link_item(medication=self.medication)
		self.assertEqual(self._codes(), [(linked, False)])

	def test_a_short_first_word_suggests_nothing(self):
		medication = self._make_medication(f"Vi {self.token}")
		self._make_item(f"Vi {self.token} drops")
		self.assertEqual(self._codes(medication), [])


class TestMedicationSearch(MedicationItemHelpers, IntegrationTestCase):
	"""The Rx medication picker: this doctor's habits first, then the clinic's, then the name."""

	def setUp(self):
		super().setUp()
		self.doctor = f"DermaDoc{self.token}"
		self.patient = self._make_patient()

	def _prescribe(self, medication, times, practitioner):
		for _ in range(times):
			encounter = self._make_encounter(self.patient)
			api.set_derma_prescriptions(payload=json.dumps([self._row(medication=medication)]), encounter=encounter.name)
			frappe.db.set_value("Patient Encounter", encounter.name, "practitioner", practitioner)

	def _search(self, txt):
		encounter = self._make_encounter(self.patient)
		frappe.db.set_value("Patient Encounter", encounter.name, "practitioner", self.doctor)
		result = api.search_prescription_medications(txt=txt, encounter=encounter.name)
		self.assertEqual(result["warehouse"], self.warehouse)
		return result["results"]

	def test_the_doctor_beats_the_clinic_which_beats_the_name(self):
		name_only = self._make_medication(f"Dermarank{self.token} A")
		clinic = self._make_medication(f"Dermarank{self.token} B")
		doctor = self._make_medication(f"Dermarank{self.token} C")
		self._prescribe(clinic, 3, f"DermaOther{self.token}")
		self._prescribe(doctor, 1, self.doctor)
		results = self._search(f"dermarank{self.token}")
		self.assertEqual([row["medication"] for row in results], [doctor, clinic, name_only])
		self.assertEqual([row["doctor_uses"] for row in results], [1, 0, 0])

	def test_an_empty_search_opens_on_the_doctors_favourites(self):
		favourite = self._make_medication(f"Dermafav{self.token}")
		self._prescribe(favourite, 2, self.doctor)
		results = self._search("")
		self.assertEqual(results[0]["medication"], favourite)
		self.assertLessEqual(len(results), 15)

	def test_results_carry_at_most_three_items_stocked_first(self):
		for _ in range(3):
			self._link_item(actual_qty=0)
		stocked = self._link_item(actual_qty=5)
		results = self._search(self.medication)
		items = results[0]["items"]
		self.assertEqual(len(items), 3)
		self.assertEqual(items[0]["item_code"], stocked)

	def test_disabled_medications_are_not_offered(self):
		frappe.db.set_value("Medication", self.medication, "disabled", 1)
		self.assertEqual(self._search(self.medication), [])

	def test_is_gated(self):
		frappe.set_user(self._make_limited_user())
		with self.assertRaises(frappe.PermissionError):
			api.search_prescription_medications(txt="any")


class TestConsentPreview(DermaTestHelpers, IntegrationTestCase):
	"""A template the health app cannot render must name itself, not explode."""

	def setUp(self):
		self.addCleanup(frappe.set_user, "Administrator")
		frappe.set_user("Administrator")

	def test_a_template_that_cannot_render_returns_an_error_naming_it(self):
		doctype = "Encounter Consent" if api._has_doctype("Encounter Consent") else "Consent Form"
		if not api._has_doctype(doctype):
			self.skipTest("No consent doctype installed.")
		controller = type(frappe.new_doc(doctype))
		if not hasattr(controller, "render_template"):
			self.skipTest("Consent controller has no render_template.")

		blow_up = AttributeError("'ConsentFormTemplate' object has no attribute 'procedure_template'")
		with patch.object(controller, "render_template", side_effect=blow_up):
			result = api.render_derma_consent_preview(
				payload=json.dumps({"consent_form_template": "Broken Template"})
			)
		self.assertFalse(result.get("rendered_html"))
		self.assertIn("Broken Template", result.get("error") or "")

	def test_is_gated(self):
		frappe.set_user(self._make_limited_user())
		with self.assertRaises(frappe.PermissionError):
			api.render_derma_consent_preview(payload="{}")


class TestCompletionMessages(DermaTestHelpers, IntegrationTestCase):
	"""Completion must report on this visit only - the health app's invoice call
	msgprints about apps the clinic does not run."""

	def setUp(self):
		self.addCleanup(frappe.set_user, "Administrator")
		frappe.set_user("Administrator")
		frappe.clear_messages()

	def _make_billable_encounter(self):
		"""An encounter with an appointment - the only shape that reaches the invoice call."""
		patient = self._make_patient()
		appointment = frappe.get_doc(
			{
				"doctype": "Patient Appointment",
				"patient": patient,
				"appointment_type": self._get_or_create_appointment_type(),
				"practitioner": self._get_or_create_practitioner(),
				"appointment_date": nowdate(),
				"appointment_time": nowtime(),
				"company": frappe.db.get_value("Company", {}, "name"),
			}
		).insert(ignore_permissions=True)
		encounter = self._make_encounter(patient)
		encounter.db_set("appointment", appointment.name)
		return encounter

	def test_foreign_invoice_messages_do_not_reach_the_response(self):
		encounter = self._make_billable_encounter()

		def noisy_invoice(**kwargs):
			frappe.msgprint("App do_dental is not installed")
			return {"invoice": "SI-TEST"}

		with patch("do_health.api.methods.create_invoice_for_visit", noisy_invoice):
			api.complete_derma_session(encounter=encounter.name)

		messages = [str(message) for message in (frappe.local.message_log or [])]
		self.assertFalse([message for message in messages if "do_dental" in message], messages)

	def test_a_genuine_invoice_failure_is_still_reported(self):
		encounter = self._make_billable_encounter()

		def failing_invoice(**kwargs):
			raise frappe.ValidationError("No item price found")

		with patch("do_health.api.methods.create_invoice_for_visit", failing_invoice):
			result = api.complete_derma_session(encounter=encounter.name)

		self.assertIsNone(result["invoice"])
		self.assertIn("No item price found", result["invoice_error"] or "")


class TestPrescriptionDispense(PrescriptionHelpers, IntegrationTestCase):
	"""Each row reports what the pharmacy has handed over, net of returns."""

	def _saved_row(self):
		encounter = self._make_encounter(self._make_patient())
		row = api.set_derma_prescriptions(payload=json.dumps([self._row()]), encounter=encounter.name)[
			"drug_prescription"
		][0]
		return encounter, row

	def test_an_undispensed_row_reads_zero(self):
		_, row = self._saved_row()
		self.assertEqual(row["dispensed_qty"], 0)
		self.assertGreater(row["prescribed_qty"], 0)

	def test_each_row_reads_its_dispensed_quantity(self):
		encounter, row = self._saved_row()
		with patch("do_derma.prescriptions.dispense.dispensed_quantities", return_value={row["name"]: 2.0}):
			reloaded = api.get_derma_prescriptions(encounter=encounter.name)["drug_prescription"][0]
		self.assertEqual(reloaded["dispensed_qty"], 2.0)

	def test_a_line_hidden_from_the_pharmacy_reports_no_quantities(self):
		from do_derma.prescriptions import dispense

		row = frappe._dict(name="legacy", custom_hide_from_pharmacy=1)
		self.assertEqual(
			dispense.get_quantities([row])["legacy"], {"prescribed_qty": None, "dispensed_qty": None}
		)

	def test_card_status(self):
		from do_derma.prescriptions import dispense

		def line(prescribed, dispensed):
			return {"prescribed_qty": prescribed, "dispensed_qty": dispensed}

		self.assertEqual(dispense.get_card_status([line(2, 2), line(1, 1)]), dispense.DISPENSED)
		self.assertEqual(dispense.get_card_status([line(2, 1)]), dispense.PARTIAL)
		self.assertEqual(dispense.get_card_status([line(2, 2), line(1, 0)]), dispense.PARTIAL)
		self.assertEqual(dispense.get_card_status([line(2, 0)]), dispense.NOT_DISPENSED)
		self.assertEqual(dispense.get_card_status([line(None, None)]), "")


class TestCancelPrescriptions(PrescriptionHelpers, IntegrationTestCase):
	"""Cancelling an order unlocks the row; anything dispensed blocks the whole call."""

	def _ordered(self, count=2):
		encounter = self._make_encounter(self._make_patient())
		api.set_derma_prescriptions(payload=json.dumps([self._row() for _ in range(count)]), encounter=encounter.name)
		return encounter, api.submit_derma_prescriptions(encounter=encounter.name)["drug_prescription"]

	def _request_status(self, row):
		return frappe.db.get_value("Medication Request", row["medication_request"], "docstatus")

	def test_cancel_one_unlocks_only_that_row(self):
		encounter, rows = self._ordered()
		result = api.cancel_derma_prescriptions(rows=json.dumps([rows[0]["name"]]), encounter=encounter.name)
		requests = {row["name"]: row.get("medication_request") for row in result["drug_prescription"]}
		self.assertIsNone(requests[rows[0]["name"]])
		self.assertEqual(requests[rows[1]["name"]], rows[1]["medication_request"])
		self.assertEqual(self._request_status(rows[0]), 2)
		self.assertEqual(self._request_status(rows[1]), 1)

	def test_cancel_all(self):
		encounter, rows = self._ordered()
		result = api.cancel_derma_prescriptions(encounter=encounter.name)
		self.assertFalse(any(row.get("medication_request") for row in result["drug_prescription"]))
		self.assertEqual([self._request_status(row) for row in rows], [2, 2])

	def test_a_cancelled_row_can_be_ordered_again(self):
		encounter, rows = self._ordered(count=1)
		api.cancel_derma_prescriptions(encounter=encounter.name)
		api.submit_derma_prescriptions(encounter=encounter.name)
		statuses = frappe.get_all("Medication Request", {"order_group": encounter.name}, pluck="docstatus")
		self.assertEqual(sorted(statuses), [1, 2])

	def test_a_dispensed_row_blocks_the_whole_call(self):
		encounter, rows = self._ordered()
		with patch("do_derma.prescriptions.dispense.dispensed_quantities", return_value={rows[1]["name"]: 1.0}):
			with self.assertRaisesRegex(frappe.ValidationError, "has been dispensed"):
				api.cancel_derma_prescriptions(encounter=encounter.name)
		self.assertEqual([self._request_status(row) for row in rows], [1, 1])

	def test_a_foreign_row_is_refused(self):
		encounter, _ = self._ordered(count=1)
		with self.assertRaisesRegex(frappe.ValidationError, "does not belong"):
			api.cancel_derma_prescriptions(rows=json.dumps(["not-a-row"]), encounter=encounter.name)

	def test_an_unordered_row_is_refused(self):
		encounter = self._make_encounter(self._make_patient())
		row = api.set_derma_prescriptions(payload=json.dumps([self._row()]), encounter=encounter.name)[
			"drug_prescription"
		][0]
		with self.assertRaisesRegex(frappe.ValidationError, "is not ordered"):
			api.cancel_derma_prescriptions(rows=json.dumps([row["name"]]), encounter=encounter.name)

	def test_nothing_ordered_is_refused(self):
		encounter = self._make_encounter(self._make_patient())
		with self.assertRaisesRegex(frappe.ValidationError, "Nothing to cancel"):
			api.cancel_derma_prescriptions(encounter=encounter.name)

	def test_a_completed_visit_cannot_cancel(self):
		encounter, _ = self._ordered(count=1)
		frappe.get_doc("Patient Encounter", encounter.name).submit()
		with self.assertRaises(frappe.ValidationError):
			api.cancel_derma_prescriptions(encounter=encounter.name)

	def test_cancel_is_gated(self):
		frappe.set_user(self._make_limited_user())
		with self.assertRaises(frappe.PermissionError):
			api.cancel_derma_prescriptions(encounter="does-not-matter")

	def test_malformed_rows_cancel_nothing(self):
		encounter, rows = self._ordered()
		for bad in ("[bad", '"text"', "{}"):
			with self.assertRaisesRegex(frappe.ValidationError, "Rows must be a list"):
				api.cancel_derma_prescriptions(rows=bad, encounter=encounter.name)
		self.assertEqual([self._request_status(row) for row in rows], [1, 1])
