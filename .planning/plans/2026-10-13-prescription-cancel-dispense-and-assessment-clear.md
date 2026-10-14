# Rx cancel, dispense cards, Rx auto-advance, assessment clear — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** On an open visit the doctor can cancel ordered Rx rows, sees previous prescriptions with what the pharmacy dispensed, enters an Rx from the keyboard, and can clear the note or the AI output; the pharmacy can dispense ordered rows before the visit is completed.

**Architecture:** do_health owns the "what is dispensable" rule (`pharmacy/prescriptions.py`) and lands first on its own branch. do_derma adds two small modules in `do_derma/prescriptions/` (`dispense.py` reads do_health's dispense totals, `orders.py` cancels Medication Requests), thin gated endpoints in `api.py`, and assessment/voice clear helpers next to the fields they own. The Vue panel owns draft state and confirmations; `DermaChart.vue` owns the server calls; the new previous-prescription strip loads its own pages.

**Tech Stack:** Frappe v16, healthcare (Patient Encounter, Drug Prescription, Medication Request), do_health pharmacy (Pharmacy Dispense), Vue 3 SFCs built by `bench build --app do_derma`.

**Spec:** `.planning/specs/2026-10-13-prescription-cancel-dispense-and-assessment-clear.md`

## Global Constraints

- do_health branch `feat/pharmacy-open-visit-orders` (from do_health `main`), lands first. do_derma branch `feat/prescription-cancel-dispense-flow` (exists, spec committed).
- Cancel applies to open visits only (`docstatus 0`). A row with net dispensed qty > 0 is never cancelled; one call is all-or-nothing.
- A cancelled row is unlocked as a draft; its Medication Request is cancelled (`docstatus 2`), not deleted.
- Previous cards: one per earlier visit with a medication, newest first, 5 per page, Load more.
- Auto-advance skips filled fields.
- Clear note empties SOAP, H&P and Structured fields (diagnosis rows included), keeps the format. Clear AI empties AI diagnosis, ICD-10, Arabic note, advice EN/AR, transcript, and unticks print-advice. The recording File stays.
- Whitelisted endpoints call `_ensure_clinical_access()` first and reuse `_resolve_patient_encounter_doc` / `_ensure_encounter_open`.
- Code taste (CLAUDE.md): short functions, terse comments, no file-top comments, `is_`/`has_` booleans, no abbreviations, no hex colours in component styles.

## Running things

All commands from `/Users/hameed/Developer/bench-v16`.

- One test: `bench --site dermaone.localhost run-tests --module <module> --test <bare_method_name>` — a class name or `Class.method` silently runs **zero** tests; check the `Ran N tests` line.
- Filter output: `... 2>&1 | grep -E "^(Ran |OK|FAILED)|^\s*(FAIL|ERROR)\s"`
- Modules: `do_health.api.test_pharmacy`, `do_derma.tests.test_encounter_tabs`, `do_derma.tests.test_assessment`, `do_derma.tests.test_chart_theme`.
- Lint changed Python only: `pipx run ruff check <files>` and `pipx run ruff format --check <files>` (run from the app directory).
- The do_derma suite has a standing red baseline on `main`; judge by diffing failing names against `main`.

## Review Focus

1. **A doctor cancels an order while another row has unsaved typing** → the reload after cancel would wipe the typing; cancel buttons are disabled while the panel is dirty. Pinned by `test_cancel_waits_for_a_save` (Task 8).
2. **The pharmacy dispenses an open-visit row, then the doctor adds a row and saves** → the ordered row keeps its name, so the dispense still counts. Pinned by `test_an_ordered_row_keeps_its_name_across_saves` (Task 3).
3. **A Medication Request is cancelled in desk while the row still links it** → the pharmacy must not see the row. Pinned by `test_a_cancelled_request_is_not_dispensable` (Task 1).
4. **A migrated legacy line the old pharmacy handled shows in a previous card** → it must not claim "Not dispensed"; quantities are `None` and the card status ignores it. Pinned by `test_a_line_hidden_from_the_pharmacy_reports_no_quantities` (Task 4).
5. **The doctor clicks another cell while a medication's defaults are still loading** → auto-advance must not steal focus. Pinned by `test_advance_after_defaults_respects_an_open_picker` (Task 10).

---

## File map

| File | Change |
|---|---|
| do_health `do_health/pharmacy/prescriptions.py` | `ordered_rows`, `dispensable_rows`, `dispensable_encounters`; queue and per-visit lines include open-visit orders |
| do_health `do_health/api/pharmacy.py` | patient profile `open_encounters` via `dispensable_encounters` |
| do_health `do_health/api/test_pharmacy.py` | `TestOpenVisitOrders` |
| `do_derma/api.py` | row identity in merge, `name` + quantities on rows, `cancel_derma_prescriptions`, `get_previous_prescriptions`, `clear_derma_assessment`; delete `previous` |
| `do_derma/prescriptions/dispense.py` (new) | quantities, card status, previous cards, dispensed guard |
| `do_derma/prescriptions/orders.py` (new) | pick rows to cancel, cancel their requests |
| `do_derma/assessment.py` | `clear_notes` |
| `do_derma/voice.py` | `AI_OUTPUT_FIELDS`, `clear_ai_output` |
| `components/prescription/dispense.js` (new) | row dispense pill helpers |
| `components/prescription/PreviousPrescriptions.vue` (new) | card strip |
| `components/prescription/PrescriptionPanel.vue` | dispense pill, cancel buttons, strip, auto-advance; old repeat strip removed |
| `components/prescription/PrescriptionRow.vue` | `advance` / `notes-enter` emits, `focusNotes` |
| `components/assessment/AssessmentPanel.vue` | Clear note |
| `components/assessment/VoiceScribe.vue` | Clear AI |
| `DermaChart.vue` | cancel + clear calls; `previous` removed |
| `do_derma/tests/test_encounter_tabs.py`, `test_assessment.py`, `test_chart_theme.py` | tests |

---

## Part A — do_health

### Task 1: The dispensable-row rule, and per-visit lines

**Files:**
- Modify: do_health `do_health/pharmacy/prescriptions.py` (after `drug_row_filters`, and `encounter_prescription_lines`)
- Test: do_health `do_health/api/test_pharmacy.py`

**Interfaces:**
- Produces: `ordered_rows(rows) -> list`, `dispensable_rows(rows, open_encounters: set[str]) -> list`, `dispensable_encounters(encounters: list) -> list` (each encounter needs `name`, `docstatus`).

- [ ] **Step 1: Branch**

```bash
cd /Users/hameed/Developer/bench-v16/apps/do_health && git status --short && git switch main && git switch -c feat/pharmacy-open-visit-orders
```
Only `.claude/` and `.serena/` may be untracked.

- [ ] **Step 2: Write the failing tests**

Append to `do_health/api/test_pharmacy.py`:

```python
def _make_open_encounter(patient: str, medication: str):
	"""A draft visit with one ordered row and one draft row, ordered the way the derma chart does."""
	period = frappe.db.get_value("Prescription Duration", {}, "name")
	encounter = frappe.get_doc(
		{
			"doctype": "Patient Encounter",
			"patient": patient,
			"practitioner": frappe.db.get_value("Healthcare Practitioner", {"status": "Active"}, "name"),
			"appointment_type": frappe.db.get_value("Appointment Type", {}, "name"),
			"company": _company(),
			"encounter_date": nowdate(),
			"drug_prescription": [{"medication": medication, "period": period}],
		}
	).insert(ignore_permissions=True)
	encounter.make_medication_request()
	encounter.append("drug_prescription", {"medication": medication, "period": period})
	encounter.save(ignore_permissions=True)
	return encounter


class TestOpenVisitOrders(IntegrationTestCase):
	"""An open visit's ordered rows reach the pharmacy; its draft rows do not."""

	def setUp(self):
		frappe.set_user("Administrator")
		self.patient = _create_patient(TEST_PATIENT).name
		self.encounter = _make_open_encounter(self.patient, _ensure_medication(_ensure_item(TEST_ITEM)))
		self.ordered, self.draft = self.encounter.drug_prescription

	def _queued_rows(self):
		cards = prescriptions.prescription_queue({"patient": self.patient, "fulfilment": "all"}, limit=200)
		return {line["prescription_row"] for card in cards for line in card["lines"]}

	def test_an_ordered_row_on_an_open_visit_is_queued(self):
		self.assertIn(self.ordered.name, self._queued_rows())

	def test_a_draft_row_on_an_open_visit_is_not_queued(self):
		self.assertNotIn(self.draft.name, self._queued_rows())

	def test_a_cancelled_request_is_not_dispensable(self):
		frappe.get_doc("Medication Request", self.ordered.medication_request).cancel()
		self.assertNotIn(self.ordered.name, self._queued_rows())

	def test_an_unlinked_row_drops_out(self):
		frappe.db.set_value("Drug Prescription", self.ordered.name, "medication_request", None)
		self.assertNotIn(self.ordered.name, self._queued_rows())

	def test_the_visit_lists_only_its_ordered_rows(self):
		rows = [line["prescription_row"] for line in prescriptions.encounter_prescription_lines(self.encounter.name)]
		self.assertEqual(rows, [self.ordered.name])

	def test_an_open_visit_with_an_order_is_dispensable(self):
		encounters = [frappe._dict(name=self.encounter.name, docstatus=0)]
		self.assertEqual(prescriptions.dispensable_encounters(encounters), encounters)
		frappe.db.set_value("Drug Prescription", self.ordered.name, "medication_request", None)
		self.assertEqual(prescriptions.dispensable_encounters(encounters), [])
```

Before running, open `prescription_queue` and confirm the value of `filters["fulfilment"]` that skips the pending-only filter (the code shows `fulfilment == "pending"` filters; any other value such as `"all"` keeps every card). If it differs, use the value that keeps every card.

- [ ] **Step 3: Run them, expect FAIL**

`bench --site dermaone.localhost run-tests --module do_health.api.test_pharmacy --test test_an_ordered_row_on_an_open_visit_is_queued` → FAIL (row not queued). `test_an_open_visit_with_an_order_is_dispensable` → `AttributeError: dispensable_encounters`.

- [ ] **Step 4: Implement the rule**

In `do_health/pharmacy/prescriptions.py`, after `drug_row_filters`:

```python
def ordered_rows(rows) -> list:
	"""Rows whose Medication Request is submitted: what an open visit has handed to the pharmacy."""
	requests = [row.get("medication_request") for row in rows if row.get("medication_request")]
	if not requests:
		return []
	submitted = set(
		frappe.get_all("Medication Request", filters={"name": ("in", requests), "docstatus": 1}, pluck="name")
	)
	return [row for row in rows if row.get("medication_request") in submitted]


def dispensable_rows(rows, open_encounters: set[str]) -> list:
	"""A completed visit's rows, and only the ordered rows of a visit still open."""
	ordered = {row.get("name") for row in ordered_rows([row for row in rows if row.get("parent") in open_encounters])}
	return [row for row in rows if row.get("parent") not in open_encounters or row.get("name") in ordered]


def dispensable_encounters(encounters: list) -> list:
	"""Completed visits, and open visits with at least one ordered row."""
	open_names = [encounter.name for encounter in encounters if encounter.docstatus == 0]
	rows = (
		frappe.get_all(
			"Drug Prescription",
			filters={"parent": ("in", open_names), "parenttype": "Patient Encounter", "medication_request": ("is", "set")},
			fields=["name", "parent", "medication_request"],
			limit_page_length=0,
		)
		if open_names
		else []
	)
	ordered = {row.parent for row in ordered_rows(rows)}
	return [encounter for encounter in encounters if encounter.docstatus == 1 or encounter.name in ordered]
```

In `encounter_prescription_lines`, replace

```python
	rows = pharmacy_rows(doc.get("drug_prescription"))
```

with

```python
	open_encounters = {doc.name} if doc.docstatus == 0 else set()
	rows = dispensable_rows(pharmacy_rows(doc.get("drug_prescription")), open_encounters)
```

Update the module docstring's "Only encounters a doctor has actually issued" comment above `DISPENSABLE_ENCOUNTER_STATUSES` to: `# Statuses a visit can be dispensed from; an open visit only for its ordered rows.`

- [ ] **Step 5: Run `test_the_visit_lists_only_its_ordered_rows` and `test_an_open_visit_with_an_order_is_dispensable`, expect PASS.** The queue tests still fail until Task 2.

- [ ] **Step 6: Commit**

```bash
git add do_health/pharmacy/prescriptions.py do_health/api/test_pharmacy.py
git commit -m "feat(pharmacy): an open visit's ordered rows are dispensable"
```

---

### Task 2: Queue and patient profile include open-visit orders

**Files:**
- Modify: do_health `do_health/pharmacy/prescriptions.py` (`_encounter_filters`, `prescription_queue`)
- Modify: do_health `do_health/api/pharmacy.py` (`get_patient_profile`, `open_encounters`)
- Test: do_health `do_health/api/test_pharmacy.py`

**Interfaces:**
- Consumes: `dispensable_rows`, `dispensable_encounters` (Task 1).

- [ ] **Step 1: Add the profile test** to `TestOpenVisitOrders`:

```python
	def test_the_profile_lists_an_open_visit_with_an_order(self):
		profile = pharmacy_api.get_patient_profile(self.patient)
		self.assertIn(self.encounter.name, [row.name for row in profile["open_encounters"]])
```

- [ ] **Step 2: Run the three queue tests and this one, expect FAIL.**

- [ ] **Step 3: Implement**

`_encounter_filters`: change `conditions = {"docstatus": 1}` to `conditions = {"docstatus": ("<", 2)}`.

`prescription_queue`: replace the `encounter_names = frappe.get_all(... pluck="name" ...)` call with

```python
	encounters = frappe.get_all(
		"Patient Encounter",
		filters=_encounter_filters(filters),
		fields=["name", "docstatus"],
		order_by="encounter_date desc, encounter_time desc, creation desc",
		limit_page_length=0,
	)
	if not encounters:
		return []
	encounter_names = [encounter.name for encounter in encounters]
	open_encounters = {encounter.name for encounter in encounters if encounter.docstatus == 0}
```

(the existing `if not encounter_names: return []` goes). Add `"medication_request"` to the `Drug Prescription` `fields` list, and right after that query:

```python
	drug_rows = dispensable_rows(drug_rows, open_encounters)
```

before the existing `if not drug_rows: return []`.

`api/pharmacy.py` `get_patient_profile`: replace the `profile["open_encounters"] = frappe.get_all(...)` block with

```python
	encounters = frappe.get_all(
		"Patient Encounter",
		filters={"patient": patient, "docstatus": ("<", 2), "status": ("in", prescriptions.DISPENSABLE_ENCOUNTER_STATUSES)},
		fields=["name", "encounter_date", "practitioner_name", "status", "docstatus"],
		order_by="encounter_date desc",
		limit_page_length=20,
	)
	profile["open_encounters"] = prescriptions.dispensable_encounters(encounters)[:5]
```

- [ ] **Step 4: Run all of `TestOpenVisitOrders` (each bare name) plus the existing `test_queue_is_readable`, `test_queue_filter_excludes_hidden_rows_only_when_the_field_exists`, expect PASS. Then the whole module:**

`bench --site dermaone.localhost run-tests --module do_health.api.test_pharmacy 2>&1 | grep -E "^(Ran |OK|FAILED)|^\s*(FAIL|ERROR)\s"` — compare against `git stash; <same run>; git stash pop` if anything fails, and fix only what this branch broke.

- [ ] **Step 5: Lint and commit**

```bash
pipx run ruff check do_health/pharmacy/prescriptions.py do_health/api/pharmacy.py do_health/api/test_pharmacy.py
git add do_health/pharmacy/prescriptions.py do_health/api/pharmacy.py do_health/api/test_pharmacy.py
git commit -m "feat(pharmacy): queue and patient profile show an open visit's ordered rows"
```

---

## Part B — do_derma backend

All remaining tasks run in `/Users/hameed/Developer/bench-v16/apps/do_derma` on `feat/prescription-cancel-dispense-flow`.

### Task 3: Ordered rows keep their identity; rows carry their name

**Files:**
- Modify: `do_derma/api.py` (`_merge_ordered_prescriptions`, `_drug_prescription_rows`, `set_derma_prescriptions`)
- Test: `do_derma/tests/test_encounter_tabs.py` (`TestOrderedPrescriptions`)

**Interfaces:**
- Produces: every row from `get_derma_prescriptions` has `name` (Drug Prescription row name). `_merge_ordered_prescriptions(existing: list[Document], incoming: list[dict]) -> list` returns ordered child documents followed by fresh dicts.

- [ ] **Step 1: Write the failing test** in `TestOrderedPrescriptions`:

```python
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
```

- [ ] **Step 2: Run, expect FAIL** (`KeyError: 'name'`).

- [ ] **Step 3: Implement**

```python
def _merge_ordered_prescriptions(existing: list, incoming: list[dict[str, Any]]) -> list:
	"""Rows already ordered keep their stored child document (and name), ahead of the new ones."""
	ordered = [row for row in existing if row.get("medication_request")]
	known = {row.medication_request for row in ordered}
	fresh = []
	for row in incoming:
		request = row.get("medication_request")
		if request and request not in known:
			frappe.throw(
				_("Medication Request {0} does not belong to this encounter.").format(request),
				frappe.ValidationError,
			)
		if not request:
			fresh.append(row)
	return [*ordered, *fresh]
```

```python
def _drug_prescription_rows(encounter_doc) -> list[dict[str, Any]]:
	if not _has_field("Patient Encounter", "drug_prescription"):
		return []
	allowed = _drug_prescription_fields()
	return [{**_drug_prescription_row(row, allowed), "name": row.name} for row in encounter_doc.get("drug_prescription") or []]
```

In `set_derma_prescriptions`, replace the merge and set lines with:

```python
	prescriptions = _merge_ordered_prescriptions(encounter_doc.get("drug_prescription") or [], prescriptions)
	encounter_doc.set("drug_prescription", prescriptions)
	for index, row in enumerate(encounter_doc.drug_prescription, start=1):
		row.idx = index
```

- [ ] **Step 4: Run every test in `TestOrderedPrescriptions` and `TestSubmitPrescriptions` (bare names), expect PASS.**

- [ ] **Step 5: Commit**

```bash
git add do_derma/api.py do_derma/tests/test_encounter_tabs.py
git commit -m "fix(prescriptions): ordered rows keep their name across saves so dispenses stay linked"
```

---

### Task 4: Dispense quantities on each row

**Files:**
- Create: `do_derma/prescriptions/dispense.py`
- Modify: `do_derma/api.py` (import; `_drug_prescription_rows`)
- Test: `do_derma/tests/test_encounter_tabs.py` (new `TestPrescriptionDispense`)

**Interfaces:**
- Produces: `dispense.get_quantities(rows) -> dict[str, dict]` keyed by row name with `prescribed_qty`, `dispensed_qty` (floats, or `None` for lines hidden from the pharmacy); `dispense.ensure_not_dispensed(rows) -> None`; constants `DISPENSED`, `PARTIAL`, `NOT_DISPENSED`; `dispense.get_card_status(lines) -> str`. Rows from `get_derma_prescriptions` gain `prescribed_qty` and `dispensed_qty`.

- [ ] **Step 1: Write the failing tests**

```python
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
		self.assertEqual(dispense.get_quantities([row])["legacy"], {"prescribed_qty": None, "dispensed_qty": None})

	def test_card_status(self):
		from do_derma.prescriptions import dispense

		def line(prescribed, dispensed):
			return {"prescribed_qty": prescribed, "dispensed_qty": dispensed}

		self.assertEqual(dispense.get_card_status([line(2, 2), line(1, 1)]), dispense.DISPENSED)
		self.assertEqual(dispense.get_card_status([line(2, 1)]), dispense.PARTIAL)
		self.assertEqual(dispense.get_card_status([line(2, 2), line(1, 0)]), dispense.PARTIAL)
		self.assertEqual(dispense.get_card_status([line(2, 0)]), dispense.NOT_DISPENSED)
		self.assertEqual(dispense.get_card_status([line(None, None)]), "")
```

- [ ] **Step 2: Run, expect FAIL** (`KeyError: 'dispensed_qty'` / `ImportError`).

- [ ] **Step 3: Create `do_derma/prescriptions/dispense.py`**

```python
from __future__ import annotations

from typing import Any

import frappe
from do_health.pharmacy.prescriptions import HIDE_FROM_PHARMACY_FIELD, dispensed_quantities, prescription_quantity
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
```

- [ ] **Step 4: Wire it into the rows**

`api.py`: change `from do_derma.prescriptions import medications` to `from do_derma.prescriptions import dispense, medications`. `_drug_prescription_rows` becomes:

```python
def _drug_prescription_rows(encounter_doc) -> list[dict[str, Any]]:
	if not _has_field("Patient Encounter", "drug_prescription"):
		return []
	allowed = _drug_prescription_fields()
	rows = encounter_doc.get("drug_prescription") or []
	quantities = dispense.get_quantities(rows)
	return [{**_drug_prescription_row(row, allowed), "name": row.name, **quantities[row.name]} for row in rows]
```

- [ ] **Step 5: Run the four new tests and `TestDermaPrescriptions` (bare names), expect PASS.** `_drug_prescription_row` filters incoming payloads by `allowed`, so the extra keys a client resends are dropped — `test_a_saved_row_reads_back` proves it.

- [ ] **Step 6: Commit**

```bash
git add do_derma/prescriptions/dispense.py do_derma/api.py do_derma/tests/test_encounter_tabs.py
git commit -m "feat(prescriptions): each Rx row reports its prescribed and dispensed quantity"
```

---

### Task 5: Cancel ordered rows

**Files:**
- Create: `do_derma/prescriptions/orders.py`
- Modify: `do_derma/api.py` (import; new endpoint after `submit_derma_prescriptions`)
- Test: `do_derma/tests/test_encounter_tabs.py` (new `TestCancelPrescriptions`)

**Interfaces:**
- Consumes: `dispense.ensure_not_dispensed` (Task 4).
- Produces: `cancel_derma_prescriptions(rows=None, encounter=None, appointment=None, patient=None)` — `rows` is a JSON list of row names, empty for all ordered rows; returns the `get_derma_prescriptions` shape. `orders.cancel(encounter_doc, names: list[str]) -> None`.

- [ ] **Step 1: Write the failing tests**

```python
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
```

- [ ] **Step 2: Run, expect FAIL** (`AttributeError: cancel_derma_prescriptions`).

- [ ] **Step 3: Create `do_derma/prescriptions/orders.py`**

```python
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
	dispense.ensure_not_dispensed(rows)
	for row in rows:
		request = frappe.get_doc("Medication Request", row.medication_request)
		if request.docstatus == 1:
			request.flags.ignore_permissions = True
			request.cancel()
		row.medication_request = None
```

- [ ] **Step 4: Add the endpoint** in `api.py` after `submit_derma_prescriptions`, and change the import to `from do_derma.prescriptions import dispense, medications, orders`:

```python
@frappe.whitelist()
def cancel_derma_prescriptions(rows=None, encounter=None, appointment=None, patient=None):
	"""Cancel ordered rows (all when `rows` is empty) and unlock them; refused once anything is dispensed."""
	_ensure_clinical_access()
	encounter_doc = _resolve_patient_encounter_doc(
		encounter=encounter, appointment=appointment, patient=patient, ptype="write"
	)
	if not encounter_doc:
		frappe.throw(_("No encounter found for this session."), frappe.ValidationError)
	_ensure_encounter_open(encounter_doc.name)
	names = _parse_payload(rows) or []
	if not isinstance(names, list):
		frappe.throw(_("Rows must be a list."), frappe.ValidationError)
	orders.cancel(encounter_doc, names)
	encounter_doc.save(ignore_permissions=True)
	return get_derma_prescriptions(encounter=encounter_doc.name)
```

- [ ] **Step 5: Run every `TestCancelPrescriptions` test (bare names), expect PASS.** If `request.cancel()` fails on a missing permission flag, read the traceback before changing anything; the encounter gate above is the permission check.

- [ ] **Step 6: Commit**

```bash
git add do_derma/prescriptions/orders.py do_derma/api.py do_derma/tests/test_encounter_tabs.py
git commit -m "feat(prescriptions): cancel one or all Rx orders on an open visit"
```

---

### Task 6: Previous prescriptions as paged cards

**Files:**
- Modify: `do_derma/prescriptions/dispense.py` (cards)
- Modify: `do_derma/api.py` (new endpoint; delete `_get_previous_prescriptions` and `previous` from `get_derma_prescriptions`)
- Test: `do_derma/tests/test_encounter_tabs.py` (replace the three `previous` tests in `TestDermaPrescriptions`)

**Interfaces:**
- Consumes: `get_quantities`, `get_card_status` (Task 4).
- Produces: `get_previous_prescriptions(encounter=None, appointment=None, patient=None, start=0, limit=5)` → `{"cards": [{"encounter", "encounter_date", "practitioner_name", "status", "lines": [{"medication", "drug_code", "drug_name", "dosage", "period", "dosage_form", "comment", "prescribed_qty", "dispensed_qty"}]}], "has_more": bool}`. `get_derma_prescriptions` no longer returns `previous`.

- [ ] **Step 1: Replace the tests**

Delete `test_previous_comes_from_the_last_visit_with_medications`, `test_previous_skips_the_current_and_cancelled_visits` and `test_a_first_visit_has_no_previous` from `TestDermaPrescriptions`, and add:

```python
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
```

- [ ] **Step 2: Run, expect FAIL** (`AttributeError: get_previous_prescriptions`).

- [ ] **Step 3: Add the cards to `dispense.py`**

```python
CARD_ROW_FIELDS = ["name", "parent", "medication", "drug_code", "drug_name", "dosage", "period", "interval", "interval_uom", "dosage_form", "comment"]
LINE_FIELDS = ("medication", "drug_code", "drug_name", "dosage", "period", "dosage_form", "comment")


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
	return {"cards": [get_card(encounter, rows, quantities) for encounter in page], "has_more": len(encounters) > limit}


def get_card_rows(encounters: list[str]) -> list:
	if not encounters:
		return []
	fields = list(CARD_ROW_FIELDS)
	if frappe.get_meta("Drug Prescription").has_field(HIDE_FROM_PHARMACY_FIELD):
		fields.append(HIDE_FROM_PHARMACY_FIELD)
	return frappe.get_all(
		"Drug Prescription",
		filters={"parent": ("in", encounters), "parenttype": "Patient Encounter", "medication": ("is", "set")},
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
```

- [ ] **Step 4: Endpoint and removal in `api.py`**

After `get_derma_prescriptions`:

```python
@frappe.whitelist()
def get_previous_prescriptions(encounter=None, appointment=None, patient=None, start=0, limit=5):
	"""Earlier visits' prescriptions with what the pharmacy dispensed, a page of cards at a time."""
	_ensure_clinical_access()
	encounter_doc = _resolve_patient_encounter_doc(encounter=encounter, appointment=appointment, patient=patient)
	if not encounter_doc or not _has_field("Patient Encounter", "drug_prescription"):
		return {"cards": [], "has_more": False}
	return dispense.get_previous_cards(encounter_doc, max(cint(start), 0), min(max(cint(limit), 1), 20))
```

Delete the `"previous": ...` entry from `get_derma_prescriptions`'s return dict and delete `_get_previous_prescriptions`. `grep -n "_get_previous_prescriptions" -r do_derma` must print nothing.

- [ ] **Step 5: Run the new class and `TestDermaPrescriptions` (bare names), expect PASS.**

- [ ] **Step 6: Commit**

```bash
git add do_derma/prescriptions/dispense.py do_derma/api.py do_derma/tests/test_encounter_tabs.py
git commit -m "feat(prescriptions): previous prescriptions as paged cards with dispense status"
```

---

### Task 7: Clear note / clear AI endpoint

**Files:**
- Modify: `do_derma/assessment.py` (`clear_notes`, after `apply_assessment`)
- Modify: `do_derma/voice.py` (`AI_OUTPUT_FIELDS`, `clear_ai_output`; import `PRINT_PATIENT_ADVICE_FIELD`)
- Modify: `do_derma/api.py` (`clear_derma_assessment` after `set_derma_assessment_mode`)
- Test: `do_derma/tests/test_assessment.py` (new `TestClearAssessment`)

**Interfaces:**
- Produces: `clear_derma_assessment(scope, encounter=None, appointment=None, patient=None)` with `scope` `"note"` or `"ai"`; returns the `get_derma_assessment` shape.

- [ ] **Step 1: Write the failing tests** (add imports at the top of the file: `from do_derma import assessment`, `from do_derma.schema import AI_DIAGNOSIS_FIELD, ICD10_FIELD, PRINT_PATIENT_ADVICE_FIELD, VOICE_TRANSCRIPT_FIELD` — skip any already imported):

```python
class TestClearAssessment(AssessmentTestBase):
	"""Clear note empties every format; Clear AI empties only the scribe's side outputs."""

	def _filled(self):
		encounter = self._make_encounter(self._make_patient())
		structured = next(
			row["fieldname"]
			for row in assessment.get_structured_layout()
			if row.get("is_value_field") and row.get("fieldtype") in ("Small Text", "Text", "Long Text", "Data")
		)
		frappe.db.set_value(
			"Patient Encounter",
			encounter.name,
			{
				structured: "Worse at night",
				"custom_derma_soap_subjective": "Itchy rash",
				"custom_derma_hp_history": "Two weeks",
				AI_DIAGNOSIS_FIELD: "Eczema",
				ICD10_FIELD: "L30.9",
				VOICE_TRANSCRIPT_FIELD: "The patient says it itches.",
				PRINT_PATIENT_ADVICE_FIELD: 1,
			},
		)
		return encounter

	def test_clear_note_empties_every_format_and_keeps_ai(self):
		encounter = self._filled()
		result = api.clear_derma_assessment(scope="note", encounter=encounter.name)
		self.assertFalse(any(result["values"].values()))
		self.assertFalse(any(result["soap_values"].values()))
		self.assertFalse(any(result["hp_values"].values()))
		self.assertEqual(result["ai_diagnosis"], "Eczema")

	def test_clear_ai_keeps_the_note(self):
		encounter = self._filled()
		result = api.clear_derma_assessment(scope="ai", encounter=encounter.name)
		self.assertEqual((result["ai_diagnosis"], result["icd10"]), ("", ""))
		self.assertFalse(result["print_patient_advice"])
		self.assertFalse(frappe.db.get_value("Patient Encounter", encounter.name, VOICE_TRANSCRIPT_FIELD))
		self.assertEqual(result["soap_values"]["custom_derma_soap_subjective"], "Itchy rash")

	def test_an_unknown_scope_is_refused(self):
		encounter = self._filled()
		with self.assertRaises(frappe.ValidationError):
			api.clear_derma_assessment(scope="everything", encounter=encounter.name)

	def test_a_completed_visit_cannot_be_cleared(self):
		encounter = self._make_encounter(self._make_patient(), docstatus=1)
		with self.assertRaises(frappe.ValidationError):
			api.clear_derma_assessment(scope="note", encounter=encounter.name)

	def test_clear_is_gated(self):
		frappe.set_user(self._make_limited_user())
		with self.assertRaises(frappe.PermissionError):
			api.clear_derma_assessment(scope="note", encounter="does-not-matter")
```

Check `AssessmentTestBase` imports `api` and has `_make_limited_user` (from `DermaTestHelpers`); add `import do_derma.api as api` if missing. `read_assessment` returns `""` for empty AI fields (see `empty_assessment`); if it returns `None`, assert with `assertFalse` instead.

- [ ] **Step 2: Run, expect FAIL** (`AttributeError: clear_derma_assessment`).

- [ ] **Step 3: Implement**

`assessment.py`:

```python
def clear_notes(encounter_doc) -> None:
	"""Empty every format's fields; the documented format is kept."""
	for mode in ASSESSMENT_MODES:
		if not mode_is_supported(mode):
			continue
		for row in get_layout(mode):
			if row.get("is_value_field"):
				encounter_doc.set(row["fieldname"], [] if row.get("fieldtype") in TABLE_FIELD_TYPES else None)
```

`voice.py`: extend the schema import with `PRINT_PATIENT_ADVICE_FIELD`, then add near the other field constants:

```python
AI_OUTPUT_FIELDS = (AI_DIAGNOSIS_FIELD, ICD10_FIELD, NOTE_AR_FIELD, PATIENT_ADVICE_FIELD, PATIENT_ADVICE_AR_FIELD, TRANSCRIPT_FIELD)


def clear_ai_output(encounter_doc) -> None:
	"""Drop what the scribe produced beside the note; the recording File stays."""
	meta = frappe.get_meta("Patient Encounter")
	for fieldname in AI_OUTPUT_FIELDS:
		if meta.has_field(fieldname):
			encounter_doc.set(fieldname, None)
	if meta.has_field(PRINT_PATIENT_ADVICE_FIELD):
		encounter_doc.set(PRINT_PATIENT_ADVICE_FIELD, 0)
```

`api.py` (`voice` and `assessment` are already imported):

```python
ASSESSMENT_CLEARERS = {"note": assessment.clear_notes, "ai": voice.clear_ai_output}


@frappe.whitelist()
def clear_derma_assessment(scope, encounter=None, appointment=None, patient=None):
	"""Empty the note in every format, or the voice scribe's side outputs."""
	_ensure_clinical_access()
	clear = ASSESSMENT_CLEARERS.get(scope)
	if not clear:
		frappe.throw(_("Unknown clear scope {0}.").format(scope), frappe.ValidationError)
	encounter_doc = _resolve_patient_encounter_doc(
		encounter=encounter, appointment=appointment, patient=patient, ptype="write"
	)
	if not encounter_doc:
		frappe.throw(_("No encounter found for this session."), frappe.DoesNotExistError)
	_ensure_encounter_open(encounter_doc.name)
	clear(encounter_doc)
	encounter_doc.save(ignore_permissions=True)
	return get_derma_assessment(encounter=encounter_doc.name)
```

Put `ASSESSMENT_CLEARERS` with the other module constants at the top of `api.py`.

- [ ] **Step 4: Run the five tests (bare names), expect PASS.** If `test_clear_is_gated` hits `ValidationError` instead, the gate is not first — move `_ensure_clinical_access()` above the scope check (it already is in the code above).

- [ ] **Step 5: Lint backend files and commit**

```bash
pipx run ruff check do_derma/api.py do_derma/assessment.py do_derma/voice.py do_derma/prescriptions/ do_derma/tests/test_encounter_tabs.py do_derma/tests/test_assessment.py
git add do_derma/assessment.py do_derma/voice.py do_derma/api.py do_derma/tests/test_assessment.py
git commit -m "feat(assessment): clear the note in every format, or the AI output"
```

(Ignore pre-existing RUF005/space-indent findings in files you did not otherwise touch.)

---

## Part C — do_derma frontend

Source tests live in `do_derma/tests/test_chart_theme.py` and use `get_component_parts(path) -> (template, script, style)` and `get_element(markup, opening)`. Add new constants next to `PRESCRIPTION_STOCK`:

```python
PRESCRIPTION_DISPENSE = PRESCRIPTION_DIR / "dispense.js"
PREVIOUS_PRESCRIPTIONS = PRESCRIPTION_DIR / "PreviousPrescriptions.vue"
```

### Task 8: Row dispense pill and cancel buttons

**Files:**
- Create: `do_derma/public/js/chart/components/prescription/dispense.js`
- Modify: `PrescriptionPanel.vue` (ordered row cell, header, script, style), `DermaChart.vue` (`@cancel`, `cancelPrescriptionOrders`)
- Test: `do_derma/tests/test_chart_theme.py` (new `TestPrescriptionOrders`)

**Interfaces:**
- Consumes: row `name`, `prescribed_qty`, `dispensed_qty` (Tasks 3–4); `cancel_derma_prescriptions` (Task 5).
- Produces: `getDispenseStatus(row) -> {label, tone} | null`, `isDispensed(row) -> boolean`; panel emits `cancel(names: string[])`.

- [ ] **Step 1: Write the failing source tests**

```python
class TestPrescriptionOrders(TestCase):
	"""Ordered rows show the pharmacy's progress and can be cancelled while nothing is dispensed."""

	def test_ordered_rows_show_their_dispense_status(self):
		template, script, _ = get_component_parts(PRESCRIPTION_PANEL)
		self.assertIn('import { getDispenseStatus, isDispensed } from "./dispense.js"', script)
		cell = get_element(template, '<td class="ordered-cell">')
		self.assertIn('data-test="prescription-dispense-status"', cell)
		helpers = PRESCRIPTION_DISPENSE.read_text()
		for label in ('__("Not dispensed")', '__("Partial")', '__("Dispensed")'):
			self.assertIn(label, helpers)

	def test_a_dispensed_row_offers_no_cancel(self):
		template, _, _ = get_component_parts(PRESCRIPTION_PANEL)
		button = get_element(template, '<button\n              v-if="canEdit && !isDispensed(row)"')
		self.assertIn('data-test="prescription-cancel"', button)

	def test_cancel_all_skips_dispensed_rows(self):
		template, script, _ = get_component_parts(PRESCRIPTION_PANEL)
		self.assertIn('data-test="prescription-cancel-all"', template)
		self.assertIn("orderedRows.value.filter((row) => !isDispensed(row))", script)

	def test_cancel_waits_for_a_save(self):
		template, script, _ = get_component_parts(PRESCRIPTION_PANEL)
		for hook in ('data-test="prescription-cancel"', 'data-test="prescription-cancel-all"'):
			start = template.index(hook)
			button = template[template.rindex("<button", 0, start) : template.index(">", start)]
			self.assertIn("isDirty", button)
		cancel = script.split("function cancelOrders(rows)", 1)[1].split("\n}", 1)[0]
		self.assertIn("frappe.confirm(", cancel)
		self.assertIn('emit("cancel", rows.map((row) => row.name))', cancel)

	def test_the_chart_cancels_through_the_endpoint(self):
		chart = (CHART_DIR / "DermaChart.vue").read_text()
		self.assertIn('@cancel="cancelPrescriptionOrders"', chart)
		self.assertIn('method: "do_derma.api.cancel_derma_prescriptions"', chart)
```

Adjust the `get_element` opening in `test_a_dispensed_row_offers_no_cancel` to the exact indentation you write in Step 3 — the opening must match the source text.

- [ ] **Step 2: Run the module, expect these five to FAIL:**
`bench --site dermaone.localhost run-tests --module do_derma.tests.test_chart_theme 2>&1 | grep -E "^(Ran |OK|FAILED)|^\s*(FAIL|ERROR)\s"`

- [ ] **Step 3: Implement**

`dispense.js`:

```js
const __ = window.__ || ((text) => text)

// The pharmacy's progress on one line, or null for a line it does not track.
export function getDispenseStatus(row) {
  if (row.dispensed_qty == null) return null
  const given = Number(row.dispensed_qty) || 0
  const prescribed = Number(row.prescribed_qty) || 0
  if (!given) return { label: __("Not dispensed"), tone: "neutral" }
  if (given + 0.0001 < prescribed) return { label: `${__("Partial")} ${given}/${prescribed}`, tone: "caution" }
  return { label: __("Dispensed"), tone: "ok" }
}

export function isDispensed(row) {
  return Number(row.dispensed_qty) > 0
}
```

`PrescriptionPanel.vue` ordered-row cell:

```html
          <td class="ordered-cell">
            <span class="chart-pill" data-tone="ok" :title="row.medication_request">{{ __("Ordered") }}</span>
            <span
              v-if="getDispenseStatus(row)"
              class="chart-pill"
              :data-tone="getDispenseStatus(row).tone"
              data-test="prescription-dispense-status"
            >{{ getDispenseStatus(row).label }}</span>
            <button
              v-if="canEdit && !isDispensed(row)"
              type="button"
              class="ghost small"
              data-test="prescription-cancel"
              :disabled="loading || saving || isDirty"
              :title="isDirty ? __('Save first, then cancel') : __('Cancel order')"
              :aria-label="__('Cancel order')"
              @click="cancelOrders([row])"
            >
              <i class="fa-solid fa-ban" aria-hidden="true"></i>
            </button>
          </td>
```

Header, inside `<template v-if="canEdit">` before Submit Rx:

```html
        <button
          v-if="cancellableRows.length"
          type="button"
          class="ghost small"
          data-test="prescription-cancel-all"
          :disabled="loading || saving || isDirty"
          :title="isDirty ? __('Save first, then cancel') : ''"
          @click="cancelOrders(cancellableRows)"
        >
          {{ __("Cancel all orders") }}
        </button>
```

Script: import the helpers, add `"cancel"` to `defineEmits`, and:

```js
const cancellableRows = computed(() => orderedRows.value.filter((row) => !isDispensed(row)))

function cancelOrders(rows) {
  const message =
    rows.length === 1
      ? __("Cancel the order for {0}? The row becomes editable again.").replace("{0}", rows[0].medication || rows[0].drug_name)
      : __("Cancel {0} orders? The rows become editable again.").replace("{0}", rows.length)
  frappe.confirm(message, () => emit("cancel", rows.map((row) => row.name)))
}
```

Style: `.ordered-cell { display: flex; align-items: center; gap: 6px; flex-wrap: wrap; }` — if `.ordered-cell` already has a rule, extend it instead of adding a second one (`test_scoped_rules_never_repeat_a_selector`).

`DermaChart.vue`: add `@cancel="cancelPrescriptionOrders"` on `<PrescriptionPanel`, and after `submitPrescriptionPanel`:

```js
async function cancelPrescriptionOrders(rows) {
  prescriptionPanel.saving = true
  prescriptionPanel.error = ""
  try {
    const response = await frappe.call({
      method: "do_derma.api.cancel_derma_prescriptions",
      args: { ...contextArgs(), rows },
    })
    applyPrescriptionResponse(response.message)
    frappe.show_alert({ message: __("Order cancelled"), indicator: "green" })
  } catch (error) {
    prescriptionPanel.error = serverErrorText(error, __("The order could not be cancelled."))
    frappe.show_alert({ message: prescriptionPanel.error, indicator: "red" })
  } finally {
    prescriptionPanel.saving = false
  }
}
```

- [ ] **Step 4: Run the module, expect the five PASS and no new failures.**

- [ ] **Step 5: Commit**

```bash
git add do_derma/public/js/chart/components/prescription/ do_derma/public/js/chart/DermaChart.vue do_derma/tests/test_chart_theme.py
git commit -m "feat(prescriptions): dispense status and cancel on ordered Rx rows"
```

---

### Task 9: Previous-prescription card strip

**Files:**
- Create: `do_derma/public/js/chart/components/prescription/PreviousPrescriptions.vue`
- Modify: `PrescriptionPanel.vue` (replace `repeat-strip`, drop `previous` prop), `DermaChart.vue` (drop `previous`)
- Test: `do_derma/tests/test_chart_theme.py` (delete `test_last_visit_medications_repeat_into_the_blank_row`, `test_the_chart_keeps_the_previous_visit_across_saves`; add `TestPreviousPrescriptions`)

**Interfaces:**
- Consumes: `get_previous_prescriptions` (Task 6); panel `repeatRow(row)` (existing).
- Produces: `<PreviousPrescriptions :encounter :can-repeat :prescribed @repeat="(lines) => ...">`.

- [ ] **Step 1: Write the failing source tests**

```python
class TestPreviousPrescriptions(TestCase):
	"""Earlier prescriptions as a scrolling strip of cards, five at a time, each repeatable."""

	def test_cards_load_five_at_a_time(self):
		template, script, _ = get_component_parts(PREVIOUS_PRESCRIPTIONS)
		self.assertIn("const PAGE_SIZE = 5", script)
		self.assertIn('method: "do_derma.api.get_previous_prescriptions"', script)
		self.assertIn('data-test="prescription-previous-more"', template)
		self.assertIn('v-if="hasMore"', template)

	def test_a_stale_page_is_dropped(self):
		_, script, _ = get_component_parts(PREVIOUS_PRESCRIPTIONS)
		self.assertIn("if (token !== requestId) return", script)

	def test_each_card_repeats_its_lines(self):
		template, _, _ = get_component_parts(PREVIOUS_PRESCRIPTIONS)
		button = get_element(template, '<button\n        v-if="canRepeat"')
		self.assertIn('data-test="prescription-previous-repeat"', button)
		self.assertIn("emit('repeat', card.lines)", button)
		self.assertIn("prescribed.includes(line.medication)", button)

	def test_the_strip_scrolls_sideways(self):
		_, _, style = get_component_parts(PREVIOUS_PRESCRIPTIONS)
		self.assertIn("overflow-x: auto", get_rule_body(style, ".previous-prescriptions {"))

	def test_the_panel_hosts_the_strip_instead_of_the_old_chips(self):
		template, script, _ = get_component_parts(PRESCRIPTION_PANEL)
		self.assertIn("<PreviousPrescriptions", template)
		self.assertIn('@repeat="(lines) => lines.forEach(repeatRow)"', template)
		self.assertNotIn("repeat-strip", template)
		self.assertNotIn("previous:", script)
		chart = (CHART_DIR / "DermaChart.vue").read_text()
		self.assertNotIn("prescriptionPanel.previous", chart)
```

- [ ] **Step 2: Run the module, expect these to FAIL.**

- [ ] **Step 3: Create `PreviousPrescriptions.vue`**

```vue
<template>
  <section v-if="cards.length" class="previous-prescriptions" data-test="prescription-previous">
    <article v-for="card in cards" :key="card.encounter" class="previous-card" data-test="prescription-previous-card">
      <header class="previous-card-head">
        <span class="previous-date">{{ formatDate(card.encounter_date) }}</span>
        <span v-if="card.status" class="chart-pill" :data-tone="STATUS_TONES[card.status]">{{ __(card.status) }}</span>
      </header>
      <small class="previous-practitioner">{{ card.practitioner_name }}</small>
      <ul class="previous-lines">
        <li v-for="(line, index) in card.lines" :key="index">
          <span class="previous-medication">{{ line.medication || line.drug_name }}</span>
          <small>{{ [line.dosage, line.period].filter(Boolean).join(" · ") }}</small>
          <small v-if="line.dispensed_qty != null" class="previous-quantity">
            {{ line.dispensed_qty }}/{{ line.prescribed_qty }}
          </small>
        </li>
      </ul>
      <button
        v-if="canRepeat"
        type="button"
        class="ghost small"
        data-test="prescription-previous-repeat"
        :disabled="card.lines.every((line) => prescribed.includes(line.medication))"
        @click="emit('repeat', card.lines)"
      >
        {{ __("Repeat") }}
      </button>
    </article>
    <button
      v-if="hasMore"
      type="button"
      class="previous-card previous-more"
      data-test="prescription-previous-more"
      :disabled="loading"
      @click="load(cards.length)"
    >
      {{ loading ? __("Loading...") : __("Load more") }}
    </button>
  </section>
</template>

<script setup>
import { ref, watch } from "vue"

const __ = window.__ || ((text) => text)

const PAGE_SIZE = 5
const STATUS_TONES = { Dispensed: "ok", "Partially dispensed": "caution", "Not dispensed": "neutral" }

const props = defineProps({
  encounter: { type: String, default: "" },
  canRepeat: { type: Boolean, default: false },
  prescribed: { type: Array, default: () => [] },
})

const emit = defineEmits(["repeat"])

const cards = ref([])
const hasMore = ref(false)
const loading = ref(false)
let requestId = 0

watch(() => props.encounter, () => load(0), { immediate: true })

async function load(start) {
  const token = ++requestId
  if (!start) cards.value = []
  if (!props.encounter) return
  loading.value = true
  try {
    const response = await frappe.call({
      method: "do_derma.api.get_previous_prescriptions",
      args: { encounter: props.encounter, start, limit: PAGE_SIZE },
    })
    if (token !== requestId) return
    const page = response?.message || { cards: [], has_more: false }
    cards.value = [...cards.value, ...page.cards]
    hasMore.value = page.has_more
  } catch (error) {
    // eslint-disable-next-line no-console
    console.warn("Failed to load previous prescriptions", error)
  } finally {
    if (token === requestId) loading.value = false
  }
}

function formatDate(value) {
  return frappe.datetime.str_to_user(value)
}
</script>

<style scoped>
.previous-prescriptions {
  display: flex;
  gap: 8px;
  overflow-x: auto;
  margin-bottom: 12px;
  padding-bottom: 4px;
}

.previous-card {
  display: flex;
  flex: 0 0 240px;
  flex-direction: column;
  gap: 4px;
  padding: 10px;
  border: 1px solid var(--chart-border);
  border-radius: 8px;
  background: var(--chart-surface);
  color: var(--chart-text);
}

.previous-card-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 6px;
}

.previous-date,
.previous-medication {
  font-weight: 600;
}

.previous-practitioner,
.previous-lines small {
  color: var(--chart-muted);
}

.previous-lines {
  display: flex;
  flex: 1;
  flex-direction: column;
  gap: 4px;
  margin: 0;
  padding: 0;
  list-style: none;
}

.previous-lines li {
  display: flex;
  flex-direction: column;
}

.previous-more {
  align-items: center;
  justify-content: center;
  border-style: dashed;
  color: var(--chart-text-soft);
  cursor: pointer;
}
</style>
```

- [ ] **Step 4: Wire the panel**

In `PrescriptionPanel.vue`: delete the whole `<div v-if="canEdit && !loading && previousRows.length" class="repeat-strip" ...>` block and its `.repeat-strip` styles; delete the `previous` prop and the `previousRows` / `previousDate` computeds. Directly after the `<p v-if="errorText" ...>` line add:

```html
    <PreviousPrescriptions
      v-if="hasEncounter && !loading"
      :encounter="encounterName"
      :can-repeat="canEdit"
      :prescribed="prescribedMedications"
      @repeat="(lines) => lines.forEach(repeatRow)"
    />
```

Import it next to `PrescriptionRow`. Replace `isPrescribed` with a shared list:

```js
const prescribedMedications = computed(() =>
  [...orderedRows.value.map((row) => row.medication), ...drafts.value.map((draft) => draft.values.medication)].filter(Boolean)
)

function isPrescribed(medication) {
  return prescribedMedications.value.includes(medication)
}
```

In `DermaChart.vue`: delete `:previous="prescriptionPanel.previous"`, the `prescriptionPanel.previous = response.message?.previous || null` line, and `previous: null,` from the `prescriptionPanel` reactive.

Delete the two obsolete source tests named above.

- [ ] **Step 5: Run the module, expect the new tests PASS and no new failures.**

- [ ] **Step 6: Commit**

```bash
git add do_derma/public/js/chart/components/prescription/ do_derma/public/js/chart/DermaChart.vue do_derma/tests/test_chart_theme.py
git commit -m "feat(prescriptions): previous prescriptions strip with dispense status, Repeat and Load more"
```

---

### Task 10: Field auto-advance

**Files:**
- Modify: `PrescriptionRow.vue` (Link `change`, `chooseItem`, Notes keydown, `focusNotes`, emits, expose)
- Modify: `PrescriptionPanel.vue` (`openNextField`, `startNextRow`, call sites, row listeners)
- Test: `do_derma/tests/test_chart_theme.py` (new `TestPrescriptionAutoAdvance`; update the `defineExpose({ commitPicker })` assertion in `test_save_commits_a_typed_picker_value_first` to `defineExpose({ commitPicker, focusNotes })`)

**Interfaces:**
- Produces: row emits `advance` after a pick and `notes-enter` on Enter in Notes; row exposes `focusNotes()`; panel `openNextField(draft)`, `startNextRow()`.

- [ ] **Step 1: Write the failing source tests**

```python
class TestPrescriptionAutoAdvance(TestCase):
	"""After each pick the next empty field opens; Enter in Notes starts the next medication."""

	def test_the_next_empty_field_opens(self):
		_, script, _ = get_component_parts(PRESCRIPTION_PANEL)
		self.assertIn('const ADVANCE_FIELDS = ["dosage", "period"]', script)
		advance = script.split("function openNextField(draft)", 1)[1].split("\n}", 1)[0]
		self.assertIn("ADVANCE_FIELDS.find((field) => !draft.values[field])", advance)
		self.assertIn("focusNotes()", advance)

	def test_a_pick_advances_instead_of_closing(self):
		_, script, _ = get_component_parts(PRESCRIPTION_ROW)
		change = script.split("change: () => {", 1)[1].split("},", 1)[0]
		self.assertIn('emit("advance")', change)
		choose = script.split("function chooseItem(itemCode)", 1)[1].split("\n}", 1)[0]
		self.assertIn('emit("advance")', choose)
		self.assertIn("defineExpose({ commitPicker, focusNotes })", script)

	def test_advance_after_defaults_respects_an_open_picker(self):
		_, script, _ = get_component_parts(PRESCRIPTION_PANEL)
		apply = script.split("async function applyMedication", 1)[1].split("} catch", 1)[0]
		self.assertIn("else if (!openPicker.value) openNextField(draft)", apply)

	def test_enter_in_notes_starts_the_next_row(self):
		template, _, _ = get_component_parts(PRESCRIPTION_ROW)
		notes = get_element(template, "<input")
		self.assertIn("@keydown.enter.prevent=\"emit('notes-enter')\"", notes)
		panel, script, _ = get_component_parts(PRESCRIPTION_PANEL)
		self.assertIn('@notes-enter="startNextRow"', panel)
		self.assertIn('@advance="openNextField(draft)"', panel)
		start = script.split("function startNextRow()", 1)[1].split("\n}", 1)[0]
		self.assertIn('field: "medication"', start)
```

`get_element(template, "<input")` must return the Notes input — it is the only `<input` in the row template; confirm with `grep -c "<input" PrescriptionRow.vue`.

- [ ] **Step 2: Run the module, expect these to FAIL.**

- [ ] **Step 3: Implement the row**

- `defineEmits` gains `"advance"` and `"notes-enter"`.
- Link control `change`:

```js
      change: () => {
        const value = control.get_value() || ""
        emit("update", field, value)
        if (value) emit("advance")
        else closePicker(field)
      },
```

- `chooseItem`:

```js
function chooseItem(itemCode) {
  emit("update", "drug_code", itemCode)
  emit("advance")
}
```

- Notes input gains `@keydown.enter.prevent="emit('notes-enter')"`.
- Add and expose:

```js
function focusNotes() {
  rowElement.value?.querySelector('[data-test="prescription-notes"]')?.focus()
}

defineExpose({ commitPicker, focusNotes })
```

(replace the existing `defineExpose({ commitPicker })`).

- [ ] **Step 4: Implement the panel**

```js
const ADVANCE_FIELDS = ["dosage", "period"]

// Opens the first empty picker after the medication, or moves to Notes once every pick is made.
function openNextField(draft) {
  if (!canEdit.value) return
  const field = ADVANCE_FIELDS.find((field) => !draft.values[field])
  openPicker.value = field ? { key: draft.key, field } : null
  if (!field) nextTick(() => rowComponents[draft.key]?.focusNotes())
}

function startNextRow() {
  ensureTrailingDraft()
  openPicker.value = { key: drafts.value.at(-1).key, field: "medication" }
}
```

Import `nextTick` from `vue`. On `<PrescriptionRow` add `@advance="openNextField(draft)"` and `@notes-enter="startNextRow"`.

In `applyMedication`, replace

```js
    if (!drugCode && draft.linkedItems.length) openPicker.value = { key: draft.key, field: "drug_code" }
```

with

```js
    if (!drugCode && draft.linkedItems.length) openPicker.value = { key: draft.key, field: "drug_code" }
    else if (!openPicker.value) openNextField(draft)
```

In `pickMedication`'s same-medication branch, after `draft.values.drug_code = picked.drugCode` add `openNextField(draft)`.

- [ ] **Step 5: Run the module, expect PASS with no new failures.**

- [ ] **Step 6: Commit**

```bash
git add do_derma/public/js/chart/components/prescription/ do_derma/tests/test_chart_theme.py
git commit -m "feat(prescriptions): each pick opens the next empty Rx field; Enter in Notes starts the next row"
```

---

### Task 11: Clear note and Clear AI buttons

**Files:**
- Modify: `components/assessment/AssessmentPanel.vue`, `components/assessment/VoiceScribe.vue`, `DermaChart.vue`
- Test: `do_derma/tests/test_chart_theme.py` (new `TestAssessmentClear`; `ASSESSMENT_DIR` already exists)

**Interfaces:**
- Consumes: `clear_derma_assessment` (Task 7).
- Produces: AssessmentPanel and VoiceScribe each emit `clear`; chart `clearAssessment(scope)`.

- [ ] **Step 1: Write the failing source tests**

```python
class TestAssessmentClear(TestCase):
	"""Clear note and Clear AI confirm, then go through one chart call."""

	def test_clear_note_sits_in_the_header_while_editing(self):
		template, script, _ = get_component_parts(ASSESSMENT_DIR / "AssessmentPanel.vue")
		button = get_element(template, '<button\n          v-if="editMode && isFilled"')
		self.assertIn('data-test="assessment-clear"', button)
		self.assertIn('"clear"', script.split("defineEmits(", 1)[1].split(")", 1)[0])
		clear = script.split("function clearNote()", 1)[1].split("\n}", 1)[0]
		self.assertIn("frappe.confirm(", clear)

	def test_clear_ai_sits_in_the_scribe_result(self):
		template, script, _ = get_component_parts(ASSESSMENT_DIR / "VoiceScribe.vue")
		head = get_element(template, '<div class="voice-result-head">')
		self.assertIn('data-test="voice-clear"', head)
		clear = script.split("function clearAi()", 1)[1].split("\n}", 1)[0]
		self.assertIn("frappe.confirm(", clear)
		self.assertIn("result.value = null", clear)

	def test_the_chart_clears_through_one_endpoint(self):
		chart = (CHART_DIR / "DermaChart.vue").read_text()
		self.assertIn("@clear=\"clearAssessment('note')\"", chart)
		self.assertIn("@clear=\"clearAssessment('ai')\"", chart)
		self.assertIn('method: "do_derma.api.clear_derma_assessment"', chart)
```

- [ ] **Step 2: Run the module, expect these to FAIL.**

- [ ] **Step 3: Implement**

`AssessmentPanel.vue` — in the Teleport, before the `v-if="!editMode && canEdit"` Edit button:

```html
        <button
          v-if="editMode && isFilled"
          type="button"
          class="ghost small"
          data-test="assessment-clear"
          :disabled="saving"
          @click="clearNote"
        >
          {{ __("Clear note") }}
        </button>
```

Add `"clear"` to `defineEmits` and:

```js
function clearNote() {
  frappe.confirm(__("Clear the note in every format? This cannot be undone."), () => emit("clear"))
}
```

(Edit mode is only offered on a draft or for allow-on-submit fields; the server refuses a completed visit, so no extra docstatus check is needed in the template.)

`VoiceScribe.vue` — last child of `<div class="voice-result-head">`:

```html
        <button
          type="button"
          class="ghost small"
          data-test="voice-clear"
          :title="__('Remove the AI diagnosis, Arabic note, patient advice and transcript')"
          @click="clearAi"
        >
          {{ __("Clear AI") }}
        </button>
```

`defineEmits(["fill", "refined", "clear"])` and:

```js
function clearAi() {
  frappe.confirm(
    __("Clear the AI diagnosis, Arabic note, patient advice and transcript? The note itself stays. This cannot be undone."),
    () => {
      result.value = null
      emit("clear")
    }
  )
}
```

`DermaChart.vue` — `@clear="clearAssessment('ai')"` on `<VoiceScribe`, `@clear="clearAssessment('note')"` on `<AssessmentPanel`, and after `saveAssessment`:

```js
async function clearAssessment(scope) {
  assessmentPanel.saving = true
  assessmentPanel.error = ""
  try {
    const response = await frappe.call({
      method: "do_derma.api.clear_derma_assessment",
      args: { ...contextArgs(), scope },
    })
    applyAssessmentResponse(response.message || {})
    assessmentPanel.editing = scope === "note"
    if (loadedTabs.prescriptions) loadPrescriptionPanel(true)
    frappe.show_alert({ message: scope === "ai" ? __("AI output cleared") : __("Note cleared"), indicator: "green" })
  } catch (error) {
    assessmentPanel.error = serverErrorText(error, __("The assessment could not be cleared."))
    frappe.show_alert({ message: assessmentPanel.error, indicator: "red" })
  } finally {
    assessmentPanel.saving = false
  }
}
```

- [ ] **Step 4: Run the module, expect PASS with no new failures.**

- [ ] **Step 5: Commit**

```bash
git add do_derma/public/js/chart/components/assessment/ do_derma/public/js/chart/DermaChart.vue do_derma/tests/test_chart_theme.py
git commit -m "feat(assessment): Clear note and Clear AI buttons"
```

---

### Task 12: Build, regression diff, live check

**Files:** none new.

- [ ] **Step 1: Build and restart the web server**

```bash
cd /Users/hameed/Developer/bench-v16 && bench build --app do_derma
```
Then restart the port-8002 web process (assets 404 after a build until it restarts — see memory).

- [ ] **Step 2: Full module runs, diff against main**

For each of `do_derma.tests.test_encounter_tabs`, `do_derma.tests.test_assessment`, `do_derma.tests.test_chart_theme`, `do_derma.tests.test_voice`, `do_derma.tests.test_voice_all_formats`, `do_health.api.test_pharmacy`: run filtered on the branch, then on `main` (`git switch main` in the relevant app, run, switch back). Every name failing on the branch must also fail on `main`.

- [ ] **Step 3: Live pass** (`bench --site dermaone.localhost browse --user Administrator`, open a patient's derma chart, Pin Patient Only if asked):

1. Rx tab: pick a medication → item chooser (if several items) → dosage opens only if empty → duration only if empty → Notes focused → Enter opens the next row's search.
2. Save two rows → Submit Rx → each ordered row shows "Not dispensed" and a cancel icon; "Cancel all orders" shows.
3. Type in the blank row: both cancel controls disable. Save, then cancel one row → it becomes an editable draft; cancel all → none ordered; Submit again works.
4. Pharmacy workbench: the open visit's ordered rows are queued, its draft rows are not. Dispense one row (stock receipt in `bench console` if needed) → back on the chart it reads "Dispensed" and has no cancel icon; adding and saving a new row keeps it "Dispensed".
5. Strip: cards newest first, 5 then Load more; Repeat fills today's rows, disabled when all present.
6. Assessment: Edit → Clear note → every format empty, format kept. Dictate or seed AI fields → Clear AI removes the result bar; the note stays.

Record anything off in the PR description; fix bugs found with a test first.

- [ ] **Step 4: Lint changed Python**

```bash
cd /Users/hameed/Developer/bench-v16/apps/do_derma && git diff --name-only main -- '*.py' | xargs pipx run ruff check
cd ../do_health && git diff --name-only main -- '*.py' | xargs pipx run ruff check
```
Only pre-existing findings may remain.

- [ ] **Step 5: Hand off** via superpowers:finishing-a-development-branch — do_health PR first (`--head doworks:feat/pharmacy-open-visit-orders` if do_health also pushes through the fork; check `git remote -v`), then the do_derma PR noting the dependency.
