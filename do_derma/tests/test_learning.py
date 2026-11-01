from __future__ import annotations

import json
from unittest.mock import patch

import frappe
from frappe.tests import IntegrationTestCase

from do_derma import learning, voice
from do_derma.assessment import SOAP_FIELDS
from do_derma.schema import AI_DRAFT_FIELD, ensure_derma_schema
from do_derma.tests.test_api import DermaTestHelpers

SUBJECTIVE = SOAP_FIELDS[0]


class TestLearningRules(IntegrationTestCase):
	def test_changed_sections_ignores_spacing_and_blanks(self):
		self.assertEqual(learning.changed_sections({SUBJECTIVE: "Itchy  hands."}, {SUBJECTIVE: "Itchy hands."}), {})
		self.assertEqual(learning.changed_sections({SUBJECTIVE: "Itchy hands."}, {SUBJECTIVE: ""}), {})
		self.assertEqual(learning.changed_sections({SUBJECTIVE: "A."}, {SUBJECTIVE: "B."})[SUBJECTIVE], {"draft": "A.", "final": "B."})

	def test_patient_name_is_removed(self):
		out = learning.without_name({SUBJECTIVE: {"draft": "Amina Haddad reports itch.", "final": "amina reports itch."}}, "Amina Haddad")
		self.assertNotIn("amina", json.dumps(out).lower())

	def test_usable_rule_checks(self):
		good = {"rule": "Use short sentences.", "visits": 3}
		self.assertEqual(learning.usable_rule(good, set()), "Use short sentences.")
		self.assertIsNone(learning.usable_rule({**good, "visits": 2}, set()))
		self.assertIsNone(learning.usable_rule({"rule": "Write doses as 20 mg.", "visits": 5}, set()))
		self.assertIsNone(learning.usable_rule(good, {"use short sentences."}))
		self.assertIsNone(learning.usable_rule("not an object", set()))

	def test_prompt_carries_rules_only_when_given(self):
		self.assertIn("- Use short sentences.", voice.build_note_prompt("itchy hands", style_rules=["Use short sentences."]))
		self.assertNotIn("WRITING PREFERENCES", voice.build_note_prompt("itchy hands"))


class TestLearnForPractitioner(DermaTestHelpers, IntegrationTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		ensure_derma_schema()

	def setUp(self):
		self.addCleanup(frappe.set_user, "Administrator")
		frappe.set_user("Administrator")

	def _visit(self, draft, final):
		encounter = self._make_encounter(self._make_patient())
		frappe.db.set_value("Patient Encounter", encounter.name, {AI_DRAFT_FIELD: json.dumps({SUBJECTIVE: draft}), SUBJECTIVE: final, "docstatus": 1}, update_modified=False)
		return encounter

	def _draft(self, encounter):
		return frappe.db.get_value("Patient Encounter", encounter.name, AI_DRAFT_FIELD)

	def _learn(self, encounter, reply):
		usage = {"model": "m", "prompt_tokens": 1, "completion_tokens": 1, "duration_ms": 1}
		with patch.object(voice, "chat_complete_with_usage", return_value=(json.dumps(reply), usage)) as chat:
			return learning.learn_for_practitioner(encounter.practitioner), chat

	def test_too_few_edits_keeps_drafts_and_skips_the_ai(self):
		encounter = self._visit("Draft.", "Edited.")
		suggested, chat = self._learn(encounter, {"rules": []})
		self.assertEqual(suggested, 0)
		chat.assert_not_called()
		self.assertTrue(self._draft(encounter))

	def test_unedited_draft_is_forgotten(self):
		encounter = self._visit("Same.", "Same.")
		self._learn(encounter, {"rules": []})
		self.assertFalse(self._draft(encounter))

	def test_learned_rule_is_only_suggested_and_drafts_are_deleted(self):
		visits = [self._visit(f"Draft {i}.", f"Edited {i}.") for i in range(learning.MIN_EDITED_VISITS)]
		rule = f"Prefer bullet points {frappe.generate_hash(length=6).translate(str.maketrans('0123456789', 'abcdefghij'))}."
		suggested, _chat = self._learn(visits[0], {"rules": [{"rule": rule, "visits": 4}, {"rule": rule, "visits": 4}]})
		self.assertEqual(suggested, 1)
		self.assertEqual(frappe.db.get_value("Derma Style Rule", {"rule": rule}, "status"), "Suggested")
		self.assertNotIn(rule, learning.style_rules(visits[0].practitioner))
		self.assertFalse(any(self._draft(visit) for visit in visits))
		frappe.db.set_value("Derma Style Rule", {"rule": rule}, "status", "Active")
		self.assertIn(rule, learning.style_rules(visits[0].practitioner))
