# Prescription tab: submit on its own, diagnosis, notes, linked-item stock

Agreed 2026-10-10. Branch `feat/prescription-submit-and-stock`.

## Goal

Let the doctor finish and hand over a prescription without completing the visit, print it with a
diagnosis, and pick the dispensable item knowing what is on the pharmacy shelf.

## 1. Submit Rx without completing the encounter

- New whitelisted endpoint `submit_derma_prescriptions(encounter=None, appointment=None, patient=None)`.
  Gates with `_ensure_clinical_access()`, resolves the encounter with `_resolve_patient_encounter_doc(..., ptype="write")`,
  then `_ensure_encounter_open()`.
- It orders only rows already saved on the encounter that have a medication and no `medication_request`,
  by calling healthcare's `encounter_doc.make_medication_request()` and saving the encounter.
  It never takes a row payload: what is ordered is exactly what is saved.
- Throws `ValidationError` when there is nothing to order.
- The encounter stays a draft. `complete_derma_session` later submits it; healthcare's
  `make_medication_request` skips rows that already carry a `medication_request`, so nothing is ordered twice.
- Returns the same shape as `get_derma_prescriptions`.

Frontend (`PrescriptionPanel.vue`):

- "Submit Rx" button in the panel header, next to Save and Print.
- Disabled while the panel is dirty (the doctor saves first) or no saved row is unordered.
- Click → `frappe.confirm("Order N medications? Ordered rows can't be edited here.")` → endpoint → refresh rows.
- Ordered rows render as the existing read-only "Ordered" rows. The doctor can add rows, save, and submit again.
- Cancelling an ordered medication stays in desk (Medication Request). Out of scope.

## 2. Prescription diagnosis

- New Patient Encounter custom field `custom_derma_prescription_diagnosis` (Small Text), declared in
  `schema.py` (never only in a patch: fresh installs skip patches).
- `get_derma_prescriptions` returns `diagnosis` and `assessment_diagnosis` (the encounter's `diagnosis`
  table names, comma-joined, de-duplicated, in order).
- Seeding: when the stored field is empty on first load, the panel fills its input from
  `assessment_diagnosis`. It is a draft value until saved. After that it is never overwritten automatically.
- A "Copy from assessment" link replaces the input text with `assessment_diagnosis` on demand.
- Only diagnosis names are copied: no ICD codes, differential diagnosis or diagnosis note.
- `set_derma_prescriptions` accepts the diagnosis alongside the rows and saves it. Editing it marks the
  panel dirty, so the existing tab-switch and reload guard covers it.
- Editable until the encounter is completed, including after rows are ordered.
- Not required for submit or print.
- Editing it never touches the assessment's `diagnosis` table.

## 3. Notes replace Form and Repeats

Chart:

- Remove the Form (`dosage_form`) and Repeats (`number_of_repeats_allowed`) columns from draft and ordered rows.
- Add a Notes column: an always-visible text input bound to `comment`.
- Delete the comment toggle button, hover preview, note dot and expandable comment row, with their state and CSS.
- `dosage_form` is still filled silently from the Medication's default, so the Medication Request keeps it.
- "Repeat from last visit" copies `comment` into Notes, drops `number_of_repeats_allowed`, and re-picks the
  linked item through the chooser flow so stock is current.

Backend:

- Delete `_validate_prescription_rows` and `MAX_PRESCRIPTION_REPEATS`, with their tests.

Print (`printing/pages.py`):

- Columns: #, Medication, Dosage, Duration, Notes. The italic comment line under the medication goes.
- A Diagnosis line right under the Allergies line, omitted when the prescription diagnosis is empty.
- Every saved row prints, ordered or not (unchanged).

## 4. Linked-item chooser with stock

- New Derma Settings field `prescription_warehouse` (Link → Warehouse), read through `settings.py`.
- New whitelisted endpoint `get_medication_items(medication)`, gated by `_ensure_clinical_access()`.
  It returns the medication's linked items, each with `item_code`, `item_name`, `stock_uom` and `actual_qty`
  (`Bin.actual_qty` in the configured warehouse), plus `warehouse`.
  When no warehouse is set, `actual_qty` is `None` and `warehouse` is empty.
- After a Medication is picked:
  - exactly one linked item: auto-picked, with its stock shown on the row;
  - several: a small chooser lists them as "Item name · 12 Nos". Zero-stock items are greyed out with
    "0 in stock" but stay selectable (outside pharmacies are a valid path);
  - the chooser always ends with "Choose another medication", which clears the row's medication and
    reopens the medication search;
  - no warehouse set: stock shows "—" and the chooser shows a hint to set one in Derma Settings.
    Prescribing is never blocked.
- The picked item shows as a chip beside the medication (name + stock). Clicking it reopens the chooser.
  This replaces the hidden `drug_code` Link picker.

## 5. Picker page length

- The Rx tab's Medication, Prescription Dosage and Prescription Duration pickers fetch 50 results.
  Desk's Link control sets `page_length` from `link_field_results_limit` (`link.js:439`), so the Rx control
  instance overrides `get_search_args` to set `page_length: 50`. The site-wide setting is untouched.

## Out of scope

- Cancelling or amending Medication Requests from the chart.
- Dispensing, stock reservation or Stock Entries.
- Projected or multi-warehouse stock.

## Testing

Backend (`tests/test_encounter_tabs.py`):

- Submit orders only saved, unordered rows; the encounter stays draft; a second submit orders only new rows.
- Submit with nothing to order throws; submit on a completed encounter throws.
- Completing the encounter after a submit creates no duplicate Medication Requests.
- Diagnosis round-trips through set/get and never changes the encounter's `diagnosis` table.
- `assessment_diagnosis` joins the diagnosis names.
- `get_medication_items` returns stock from the configured warehouse, and `None` when it is unset.
- Print: Notes column and Diagnosis line present, Form and Repeats absent, Diagnosis omitted when empty.

Source tests (the existing chart source-test pattern):

- Submit button disabled while dirty; no Form or Repeats columns; Notes input present; Rx pickers set `page_length: 50`.

Live check: save → submit → ordered rows lock; chooser shows stock; print shows Diagnosis and Notes.
