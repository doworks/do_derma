# Rx cancel, dispense view, field auto-advance, assessment clear

Agreed 2026-10-13. Branches: do_health `feat/pharmacy-open-visit-orders` (lands first), do_derma `feat/prescription-cancel-dispense-flow`.

## Goal

On the derma chart the doctor can take back an Rx order while the visit is open, see what the pharmacy has handed this patient before, enter a prescription from the keyboard, and wipe a bad note or AI output. The pharmacy can dispense an ordered Rx before the visit is completed.

## Decisions

- Cancel applies to **open visits only**. A completed visit's Rx stays untouchable from the chart.
- A cancelled row is **unlocked as a draft** (edit and re-submit, or delete). Its Medication Request is cancelled and stays in healthcare as the audit trail.
- Any row with net dispensed qty > 0 cannot be cancelled. All-or-nothing per call.
- Dispense summary = **one card per previous prescription** (visit). Current-visit dispense shows per row.
- Auto-advance **skips fields that are already filled**.
- Clear note empties **all three formats**. Clear AI empties the scribe's side outputs, never the note text.

## 1. Pharmacy sees open-visit orders (do_health)

Rule: a Drug Prescription row is dispensable when its encounter is submitted with a dispensable status (unchanged), **or** the encounter is a draft (`docstatus 0`) and the row has `medication_request` set to a submitted (`docstatus 1`) Medication Request.

Apply it in `do_health/pharmacy/prescriptions.py` and `do_health/api/pharmacy.py`:

- `prescription_queue`: the draft-encounter branch joins rows with `medication_request` set; draft rows without one never reach the queue. Date/patient/practitioner/company filters apply to both branches.
- `encounter_prescription_lines`: on a draft encounter, return only ordered rows; on a submitted one, unchanged.
- Patient profile `open_encounters`: include draft encounters that have at least one ordered row.
- One helper owns the rule (e.g. `is_dispensable_row(row, encounter_docstatus)`) so the three sites cannot drift.

Cancelling an order clears `medication_request`, so the line leaves the queue without any do_health cancel hook. `dispensed_quantities` already nets returns and is unchanged.

Tests (`do_health/api/test_pharmacy.py`): ordered row on an open encounter is queued; draft row on the same encounter is not; after the link is cleared the row drops out; submitted-encounter behaviour unchanged.

## 2. Ordered rows keep their identity (do_derma, prerequisite)

`set_derma_prescriptions` rebuilds every row from dicts, and `CHILD_INTERNAL_FIELDS` strips `name`, so each save renames all rows. Once the pharmacy can dispense on an open visit, that orphans `Pharmacy Dispense Item.drug_prescription`.

- `_merge_ordered_prescriptions` keeps ordered rows as the **existing child documents** (same `name`), not re-created dicts.
- Test: submit, dispense against a row, save the Rx tab with a new row added; the ordered row's `name` is unchanged and its dispensed qty still reads back.

## 3. Cancel a submitted Rx (do_derma)

Endpoint `cancel_derma_prescriptions(rows=None, encounter=None, appointment=None, patient=None)` in `api.py`, next to `submit_derma_prescriptions`:

1. `_ensure_clinical_access()`, resolve with `ptype="write"`, `_ensure_encounter_open()`.
2. `rows` is a JSON list of Drug Prescription row names; empty/None means every row with `medication_request`.
3. Throw `ValidationError` when: a named row is not on this encounter; a named row has no `medication_request`; nothing is ordered; any target row has dispensed qty > 0 ("{medication} has been dispensed. Return it at the pharmacy first.").
4. For each target: `frappe.get_doc("Medication Request", name).cancel()` (skip if already `docstatus 2`), clear `row.medication_request`. Save the encounter once. One request transaction, so a failure rolls back every cancel.
5. Return `get_derma_prescriptions(encounter=...)`.

UI (`PrescriptionPanel.vue`, `PrescriptionRow.vue`):

- Ordered row: the lock becomes a **Cancel order** icon button (`data-test="prescription-cancel"`), hidden when the row is dispensed.
- Panel header: **Cancel all orders** (`data-test="prescription-cancel-all"`) beside Submit Rx, shown when any row is ordered and the visit is open.
- Both `frappe.confirm` first, then reload rows from the response.

Tests: cancel one leaves others ordered; cancel all; refused when dispensed (seed a submitted Pharmacy Dispense Item pointing at the row), on a submitted encounter, and for a foreign row; cancelled Medication Request has `docstatus 2`; re-submit after cancel creates a new request.

## 4. Dispense data (do_derma)

New module `do_derma/prescriptions/dispense.py`. Reuses `do_health.pharmacy.prescriptions.dispensed_quantities` and `prescription_quantity`; no quantity logic of its own.

- `get_derma_prescriptions` adds `prescribed_qty` and `dispensed_qty` to each row (keyed by row `name`, which `_drug_prescription_rows` must now include).
- Row status: `Pending` (0), `Partial` (0 < d < p), `Dispensed` (d >= p), shown only on ordered rows or on a submitted visit.
- New endpoint `get_previous_prescriptions(encounter, start=0, limit=5)`: the patient's other encounters (`docstatus < 2`, status not Cancelled) with at least one medication row, newest first (`encounter_date desc, creation desc`). Each card:
  `{encounter, encounter_date, practitioner_name, status, lines: [{medication, drug_code, drug_name, dosage, period, comment, prescribed_qty, dispensed_qty}]}` plus top-level `has_more`.
  Card status: `Dispensed` when every line is, `Not dispensed` when none is, else `Partially dispensed`.
- `previous` is removed from `get_derma_prescriptions`; `_get_previous_prescriptions` is deleted.

Tests: paging (6 visits → 5 then 1, `has_more`); quantities net of a return; current encounter excluded; cancelled encounter excluded.

## 5. Previous-prescription strip (frontend)

New `prescription/PreviousPrescriptions.vue`, above the Rx table, replacing the `repeat-strip` block in `PrescriptionPanel.vue`.

- Horizontal scroll of cards, newest first. Card: date, practitioner, status pill, one line per medication with `dispensed/prescribed`, **Repeat** button.
- Repeat emits the card's lines; the panel runs the existing `repeatRow` for each, which skips medications already on today's Rx and re-checks item and stock. Disabled when all are present or the visit is not editable.
- Loads 5 on mount; a trailing **Load more** card fetches the next 5 and disappears when `has_more` is false.
- Hidden when the patient has no previous prescription. Still shown on a completed visit, with Repeat disabled.

## 6. Field auto-advance (frontend)

- `openNextField(row)` in `PrescriptionPanel.vue`: walks `medication → dosage → period → comment`, opens the first empty picker, or focuses Notes when all are filled.
- Called after the item is chosen (after the dosage/duration auto-fill resolves) and after a dosage or duration pick commits.
- Enter in Notes adds a row and opens its medication search.
- Never runs on a read-only (ordered) row.

## 7. Clear note / clear AI

Endpoint `clear_derma_assessment(scope, encounter=None, appointment=None, patient=None)` in `api.py`, gated like `set_derma_assessment` plus `_ensure_encounter_open()`:

- `scope="note"`: empty every `SOAP_FIELDS`, `HP_FIELDS` and Structured layout field (tables included, so the `diagnosis` rows go too). `MODE_FIELD` kept. Clearing diagnosis rows stops seeding a new Rx diagnosis; a saved Rx diagnosis is untouched.
- `scope="ai"`: empty `AI_DIAGNOSIS_FIELD`, `ICD10_FIELD`, `NOTE_AR_FIELD`, `PATIENT_ADVICE_FIELD`, `PATIENT_ADVICE_AR_FIELD`, `VOICE_TRANSCRIPT_FIELD`; set `PRINT_PATIENT_ADVICE_FIELD` to 0. The recording File is kept.
- Any other scope throws. Returns `get_derma_assessment(...)`.

UI:

- **Clear note** ghost button in the Assessment header actions (`data-test="assessment-clear"`), edit mode, when the note has content.
- **Clear AI** ghost button in the VoiceScribe result head (`data-test="voice-clear"`), when any AI output exists.
- Both `frappe.confirm(... "This cannot be undone.")`, then apply the response through `applyAssessmentResponse`.

Tests: each scope clears exactly its fields and leaves the other set intact; refused on a submitted encounter; bad scope throws.

## Testing and checks

- Python tests per section above; frontend source tests for the strip, auto-advance order, and the new buttons.
- `bench build --app do_derma`, then a live browser pass: submit → cancel one → cancel all → re-submit; pharmacy workbench shows the open-visit order; dispense one, confirm the row pill and that cancel is refused; Repeat and Load more; Clear note and Clear AI.
- Compare test failures against the known failing set on main.

## Out of scope

- Cancelling Rx on a completed visit.
- Counter-sale history in the strip.
- Deleting the voice recording file.
