# Prescription submit, diagnosis, notes and linked-item stock — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** The Rx tab can order its medications without completing the visit, prints a doctor-editable diagnosis, shows Notes instead of Form/Repeats, and picks the dispensable item with its pharmacy stock.

**Architecture:** Backend endpoints stay in `do_derma/api.py` next to the existing Rx endpoints, gate first, and reuse the `_resolve_patient_encounter_doc` / `_ensure_encounter_open` / `_has_field` helpers. The diagnosis field lives in `schema.py`, the warehouse setting in Derma Settings read through `settings.py`. The Vue panel (`components/prescription/`) owns draft state; `DermaChart.vue` owns the calls.

**Tech Stack:** Frappe v16, healthcare app (Patient Encounter, Medication, Medication Request), ERPNext `Bin`, Vue 3 SFCs built by `bench build --app do_derma`.

**Spec:** `.planning/specs/2026-10-10-prescription-submit-diagnosis-stock.md`

## Global Constraints

- Branch: `feat/prescription-submit-and-stock` (already created; the spec is committed on it).
- Custom Fields live in `do_derma/schema.py`, never only in a patch (fresh installs skip patches).
- Whitelisted endpoints call `_ensure_clinical_access()` first.
- Diagnosis field: `custom_derma_prescription_diagnosis` (Small Text) on Patient Encounter.
- Settings field: `prescription_warehouse` (Link → Warehouse) on Derma Settings.
- Rx pickers fetch 50 results; the site-wide `link_field_results_limit` is untouched.
- Cancelling Medication Requests, dispensing, stock reservation, projected stock: out of scope.
- Code taste (CLAUDE.md): short functions, terse comments, no file-top comments, `is_`/`has_` booleans, no abbreviations.

## Running things

All commands run from `/Users/hameed/Developer/bench-v16`.

- One backend test: `bench --site dermaone.localhost run-tests --module do_derma.tests.test_encounter_tabs --test <bare_method_name>`
  (a class name or `Class.method` silently runs **zero** tests — always pass the bare method name and check the "Ran N tests" line).
- Source tests: `bench --site dermaone.localhost run-tests --module do_derma.tests.test_chart_theme`
- Filter noisy output: `... 2>&1 | grep -E "^(Ran |OK|FAILED)|^\s*(FAIL|ERROR)\s"`
- Lint changed Python only: `pipx run ruff check <files>` and `pipx run ruff format --check <files>`.
- Schema/settings changes need `bench --site dermaone.localhost migrate`.
- The suite has a standing red baseline on `main` (17 names, see memory). Judge by diffing failing names against `main`, never by "all green".

## Review Focus

1. **A doctor double-clicks Submit Rx** → the second call finds nothing unordered and fails with "Nothing to order", never creating duplicate Medication Requests. Pinned by `test_a_second_submit_with_nothing_new_is_refused` (Task 5).
2. **The visit is completed after an Rx submit** → healthcare's `on_submit` orders nothing twice. Pinned by `test_completing_after_submit_orders_nothing_twice` (Task 5).
3. **The Rx tab is opened just to look on a visit whose assessment has a diagnosis** → the seeded diagnosis must not mark the panel unsaved (no leave-guard nag). Pinned by `test_a_copied_diagnosis_is_not_unsaved_until_something_is_prescribed` (Task 4).
4. **A medication whose linked item is disabled, or a site with no warehouse set** → disabled items are skipped; stock reads `None` and prescribing still works. Pinned by `test_disabled_items_are_skipped` and `test_no_warehouse_means_unknown_stock` (Task 7).
5. **A stored comment with line breaks shown in the single-line Notes input** → the value is untouched unless the doctor types in it (Notes updates only on `@input`). Pinned by `test_notes_update_only_on_input` (Task 2).

---

## File map

| File | Change |
|---|---|
| `do_derma/api.py` | drop repeats validation; diagnosis read/write; `submit_derma_prescriptions`; `get_medication_items` |
| `do_derma/schema.py` | `PRESCRIPTION_DIAGNOSIS_FIELD` constant + Custom Field |
| `do_derma/settings.py` | `get_prescription_warehouse()` |
| `do_derma/do_derma/doctype/derma_settings/derma_settings.json` | Prescriptions section + `prescription_warehouse` |
| `do_derma/printing/pages.py` | Notes column, Diagnosis line |
| `do_derma/public/js/chart/components/prescription/PrescriptionPanel.vue` | Notes column, diagnosis field, Submit Rx, item chooser wiring |
| `do_derma/public/js/chart/components/prescription/PrescriptionRow.vue` | Notes input, chooser + chip, picker page length |
| `do_derma/public/js/chart/DermaChart.vue` | diagnosis props, save payload shape, submit call, refresh after assessment save |
| `do_derma/tests/test_encounter_tabs.py` | backend tests |
| `do_derma/tests/test_chart_theme.py` | source tests |

---

### Task 1: Drop the repeats validation

**Files:**
- Modify: `do_derma/api.py:36` (`MAX_PRESCRIPTION_REPEATS`), `do_derma/api.py:2215-2223` (`_validate_prescription_rows`), `do_derma/api.py:3406` (its call)
- Test: `do_derma/tests/test_encounter_tabs.py:147-154`

**Interfaces:**
- Produces: `set_derma_prescriptions` no longer rejects any `number_of_repeats_allowed`.

- [ ] **Step 1: Replace the refusal test with an acceptance test**

In `TestDermaPrescriptions`, replace `test_an_absurd_repeat_count_is_refused` with:

```python
	def test_a_legacy_repeat_count_is_kept_as_sent(self):
		"""The tab no longer shows repeats; a stored count is resent untouched, never judged."""
		encounter = self._make_encounter(self._make_patient())
		saved = api.set_derma_prescriptions(
			payload=json.dumps([self._row(number_of_repeats_allowed=500)]), encounter=encounter.name
		)
		self.assertEqual(saved["drug_prescription"][0]["number_of_repeats_allowed"], 500)
```

- [ ] **Step 2: Run it, expect FAIL** (`ValidationError: Row 1: repeats must be between 0 and 12.`)

`bench --site dermaone.localhost run-tests --module do_derma.tests.test_encounter_tabs --test test_a_legacy_repeat_count_is_kept_as_sent`

- [ ] **Step 3: Delete the validation**

Delete the `MAX_PRESCRIPTION_REPEATS = 12` line, the whole `_validate_prescription_rows` function, and the `_validate_prescription_rows(prescriptions)` line in `set_derma_prescriptions`. `grep -n "MAX_PRESCRIPTION_REPEATS\|_validate_prescription_rows" -r do_derma` must print nothing.

- [ ] **Step 4: Run it, expect PASS**

- [ ] **Step 5: Commit**

```bash
git add do_derma/api.py do_derma/tests/test_encounter_tabs.py
git commit -m "refactor(prescriptions): stop judging repeat counts the tab no longer shows"
```

---

### Task 2: Notes replace Form and Repeats (chart and print)

**Files:**
- Modify: `do_derma/public/js/chart/components/prescription/PrescriptionRow.vue`
- Modify: `do_derma/public/js/chart/components/prescription/PrescriptionPanel.vue`
- Modify: `do_derma/printing/pages.py:17-22, 152-166`
- Test: `do_derma/tests/test_chart_theme.py` (`TestPrescriptionRow`, `PRESCRIPTION_HOOKS`, `TestPrescriptionPanelRestyle`), `do_derma/tests/test_encounter_tabs.py`

**Interfaces:**
- Produces: row emits `update("comment", text)` from a `data-test="prescription-notes"` input; no `toggle-comment` emit, no `commentOpen` prop. `dosage_form` stays in the panel's `VALUE_FIELDS` (filled silently); `number_of_repeats_allowed` leaves `VALUE_FIELDS`.

- [ ] **Step 1: Update the source tests**

In `test_chart_theme.py`:

1. In `PRESCRIPTION_HOOKS`, replace `"prescription-comment",` with `"prescription-notes",`.
2. Replace `test_comment_and_delete_live_in_the_actions_cluster` with:

```python
	def test_notes_are_an_always_visible_column(self):
		template, script, style = get_component_parts(PRESCRIPTION_ROW)
		start = template.index('class="cell-input notes-input"')
		notes = template[start : template.index("/>", start)]
		self.assertIn('data-test="prescription-notes"', notes)
		self.assertIn(':value="row.values.comment"', notes)
		for gone in ("prescription-comment", "comment-preview", "comment-row", "note-dot", "toggle-comment"):
			self.assertNotIn(gone, template + script + style)
		actions = get_element(template, '<td class="row-actions"')
		self.assertIn('data-test="prescription-delete"', actions)

	def test_notes_update_only_on_input(self):
		"""A stored comment with line breaks is left alone unless the doctor types in it."""
		template, _, _ = get_component_parts(PRESCRIPTION_ROW)
		start = template.index('class="cell-input notes-input"')
		notes = template[start : template.index("/>", start)]
		self.assertIn("@input=\"emit('update', 'comment', $event.target.value)\"", notes)
		self.assertNotIn("v-model", notes)

	def test_form_and_repeats_are_gone(self):
		row_template, row_script, _ = get_component_parts(PRESCRIPTION_ROW)
		panel_template, panel_script, panel_style = get_component_parts(PRESCRIPTION_PANEL)
		for text in ("number_of_repeats_allowed", "repeats-input", '__("Form")', '__("Repeats")'):
			self.assertNotIn(text, row_template + row_script + panel_template + panel_script)
		self.assertNotIn("col-form", panel_template + panel_style)
		self.assertNotIn("row.dosage_form", panel_template)
		self.assertIn('"dosage_form"', panel_script)
		self.assertIn('__("Notes")', panel_template)
```

3. In `test_the_trailing_row_is_muted_without_actions`, delete the line
   `self.assertIn('v-if="!isNext && (!readOnly || row.values.comment)"', template)`.

In `test_encounter_tabs.py`, extend `test_the_printout_lists_each_saved_medication` with:

```python
		self.assertIn(">Notes<", page["html"])
		self.assertNotIn(">Form<", page["html"])
		self.assertNotIn(">Repeats<", page["html"])
		self.assertNotIn("font-style:italic", page["html"])
```

- [ ] **Step 2: Run both modules, expect the new/changed tests to FAIL**

`bench --site dermaone.localhost run-tests --module do_derma.tests.test_chart_theme 2>&1 | grep -E "^(Ran |OK|FAILED)|^\s*(FAIL|ERROR)\s"`
`bench --site dermaone.localhost run-tests --module do_derma.tests.test_encounter_tabs --test test_the_printout_lists_each_saved_medication`

- [ ] **Step 3: Row — swap the repeats cell for Notes, delete the comment UI**

In `PrescriptionRow.vue` template, replace the whole repeats `<td>` (the one holding `class="cell-input repeats-input"`) with:

```html
    <td>
      <input
        type="text"
        class="cell-input notes-input"
        data-test="prescription-notes"
        :value="row.values.comment"
        :disabled="readOnly"
        :placeholder="readOnly ? '' : __('Notes')"
        :aria-label="__('Notes')"
        @input="emit('update', 'comment', $event.target.value)"
      />
    </td>
```

In `<td class="row-actions">` delete the comment `<button data-test="prescription-comment" ...>` and the `<div v-if="preview" class="comment-preview" ...>`. Delete the whole `<tr v-if="commentOpen" class="comment-row">...</tr>`.

In the script:
- `LINK_OPTIONS`: delete `dosage_form: "Dosage Form",`.
- `LINK_COLUMNS`: delete `{ field: "dosage_form", placeholder: __("Form") },`.
- Delete `PREVIEW_DELAY_MS`, `PREVIEW_GAP_PX`, the `commentOpen` prop, `"toggle-comment"` from `defineEmits`, `const preview = ref(null)`, `let previewTimer = null`, `onBeforeUnmount(hidePreview)`, `showPreview`, `hidePreview`, `previewStyle`. Drop `onBeforeUnmount` from the `vue` import.

In the style: delete `.comment-preview`, `.comment-preview p`, `.comment-input`, `.comment-input:focus`, `.note-dot` rules (and any `.repeats-input` rule). Add:

```css
.notes-input {
  cursor: text;
}
```

- [ ] **Step 4: Panel — columns, ordered rows, fields**

In `PrescriptionPanel.vue`:

```html
      <colgroup>
        <col class="col-medication" />
        <col class="col-dosage" />
        <col class="col-duration" />
        <col class="col-notes" />
        <col class="col-actions" />
      </colgroup>
      <thead>
        <tr>
          <th class="chart-label">{{ __("Medication") }}</th>
          <th class="chart-label">{{ __("Dosage") }}</th>
          <th class="chart-label">{{ __("Duration") }} <span class="required-mark">*</span></th>
          <th class="chart-label">{{ __("Notes") }}</th>
          <th class="chart-label"><span class="sr-only">{{ __("Actions") }}</span></th>
        </tr>
      </thead>
```

In the ordered row, replace the `dosage_form` and `number_of_repeats_allowed` cells with `<td>{{ row.comment || "—" }}</td>`.

On `<PrescriptionRow>` delete `:comment-open="openComment === draft.key"` and `@toggle-comment="..."`.

Script:
- `VALUE_FIELDS` becomes `["medication", "drug_code", "dosage", "period", "dosage_form", "comment"]`.
- Delete `const openComment = ref(null)` and every `openComment.value = ...` line (in `resetDrafts` and `removeRow`).
- `isBlank` becomes:

```js
function isBlank(draft) {
  return VALUE_FIELDS.every((field) => !draft.values[field])
}
```

Style: replace the `.col-duration, .col-form` and `.col-repeats` rules with:

```css
.col-duration {
  width: 15%;
}

.col-notes {
  width: 25%;
}
```

- [ ] **Step 5: Print — Notes column, no italic line**

In `do_derma/printing/pages.py`:

```python
PRESCRIPTION_COLUMNS = (
	("dosage", "Dosage"),
	("period", "Duration"),
	("comment", "Notes"),
)
```

and in `get_prescription_table` replace the medication cell lines with:

```python
		cells = [str(index), f"<strong>{escape_html(row.medication)}</strong>"]
```

(delete the `if row.comment:` block).

- [ ] **Step 6: Run both modules, expect the new tests to PASS** (and no new failures vs. the baseline names).

- [ ] **Step 7: Lint and commit**

```bash
pipx run ruff check do_derma/printing/pages.py do_derma/tests/test_encounter_tabs.py do_derma/tests/test_chart_theme.py
git add do_derma/printing/pages.py do_derma/public/js/chart/components/prescription do_derma/tests
git commit -m "feat(prescriptions): notes column replaces form and repeats on screen and on paper"
```

---

### Task 3: Prescription diagnosis — field, read/write, print

**Files:**
- Modify: `do_derma/schema.py` (constants near line 51-58; `DERMA_CUSTOM_FIELDS["Patient Encounter"]` after the `NOTE_AR_FIELD` entry ~line 247)
- Modify: `do_derma/api.py` (`get_derma_prescriptions` ~3378, `set_derma_prescriptions` ~3391; new `_get_assessment_diagnosis` beside `_drug_prescription_rows`)
- Modify: `do_derma/printing/pages.py` (`get_prescription_page`, new `get_diagnosis_line`)
- Test: `do_derma/tests/test_encounter_tabs.py`

**Interfaces:**
- Produces: `schema.PRESCRIPTION_DIAGNOSIS_FIELD = "custom_derma_prescription_diagnosis"`.
- Produces: `get_derma_prescriptions(...)` → `{"encounter", "drug_prescription", "previous", "diagnosis": str, "assessment_diagnosis": str}`.
- Produces: `set_derma_prescriptions(payload=None, encounter=None, appointment=None, patient=None, diagnosis=None)` → same shape as `get_derma_prescriptions`. `diagnosis=None` leaves the stored value alone.

- [ ] **Step 1: Write failing tests**

Add to `TestDermaPrescriptions`:

```python
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
			payload=json.dumps([self._row()]), encounter=encounter.name, diagnosis="Psoriasis <plaque>"
		)
		html = api.get_derma_print_html("prescription", encounter.name)["html"]
		self.assertIn(">Diagnosis:<", html)
		self.assertIn("Psoriasis &lt;plaque&gt;", html)
		self.assertLess(html.index(">Allergies:<"), html.index(">Diagnosis:<"))
```

- [ ] **Step 2: Run them, expect FAIL** (`KeyError: 'assessment_diagnosis'`, unexpected kwarg `diagnosis`).

- [ ] **Step 3: Schema field**

In `do_derma/schema.py`, beside `NOTE_AR_FIELD`:

```python
PRESCRIPTION_DIAGNOSIS_FIELD = "custom_derma_prescription_diagnosis"
```

and append to `DERMA_CUSTOM_FIELDS["Patient Encounter"]`, right after the `NOTE_AR_FIELD` entry:

```python
		{
			"fieldname": PRESCRIPTION_DIAGNOSIS_FIELD,
			"fieldtype": "Small Text",
			"label": "Prescription Diagnosis",
			"insert_after": NOTE_AR_FIELD,
			"no_copy": 1,
			"description": "Printed on the prescription. Starts as a copy of the assessment's diagnosis.",
		},
```

Run `bench --site dermaone.localhost migrate`.

- [ ] **Step 4: API read/write**

In `api.py` add `from do_derma.schema import PRESCRIPTION_DIAGNOSIS_FIELD` to the existing `from do_derma.schema import ...` line. Beside `_drug_prescription_rows`:

```python
def _get_assessment_diagnosis(encounter_doc) -> str:
	return _join_unique(row.diagnosis for row in encounter_doc.get("diagnosis") or [])
```

`get_derma_prescriptions` returns:

```python
	return {
		"encounter": encounter_doc.name if encounter_doc else encounter or "",
		"drug_prescription": _drug_prescription_rows(encounter_doc) if encounter_doc else [],
		"previous": _get_previous_prescriptions(encounter_doc) if encounter_doc else None,
		"diagnosis": cstr(encounter_doc.get(PRESCRIPTION_DIAGNOSIS_FIELD)) if encounter_doc else "",
		"assessment_diagnosis": _get_assessment_diagnosis(encounter_doc) if encounter_doc else "",
	}
```

`set_derma_prescriptions` gains `diagnosis=None`; before `encounter_doc.save(...)`:

```python
	if diagnosis is not None and _has_field("Patient Encounter", PRESCRIPTION_DIAGNOSIS_FIELD):
		encounter_doc.set(PRESCRIPTION_DIAGNOSIS_FIELD, cstr(diagnosis).strip())
```

and its last line becomes `return get_derma_prescriptions(encounter=encounter_doc.name)`.

- [ ] **Step 5: Print line**

In `do_derma/printing/pages.py` import `PRESCRIPTION_DIAGNOSIS_FIELD` from `do_derma.schema`, add after `get_allergy_line`:

```python
def get_diagnosis_line(doc) -> str:
	text = (doc.get(PRESCRIPTION_DIAGNOSIS_FIELD) or "").strip()
	if not text:
		return ""
	label = escape_html(_("Diagnosis"))
	return f'<p style="margin:0 0 16px;font-size:13px;"><strong>{label}:</strong> {escape_html(text)}</p>'
```

and in `get_prescription_page` insert `+ get_diagnosis_line(doc)` right after `+ get_allergy_line(patient)`.

Check the label markup the test expects: `get_allergy_line` renders `<strong>Allergies:</strong>` — so the test's `">Allergies:<"` and `">Diagnosis:<"` match.

- [ ] **Step 6: Run the four tests plus the whole `test_encounter_tabs` module; expect PASS** and no new failures.

- [ ] **Step 7: Lint and commit**

```bash
pipx run ruff check do_derma/api.py do_derma/schema.py do_derma/printing/pages.py do_derma/tests/test_encounter_tabs.py
git add do_derma/api.py do_derma/schema.py do_derma/printing/pages.py do_derma/tests/test_encounter_tabs.py
git commit -m "feat(prescriptions): an editable Rx diagnosis copied from the assessment, printed under allergies"
```

---

### Task 4: Prescription diagnosis — the Rx tab field

**Files:**
- Modify: `do_derma/public/js/chart/components/prescription/PrescriptionPanel.vue`
- Modify: `do_derma/public/js/chart/DermaChart.vue` (panel tag ~296-311, `prescriptionPanel` reactive ~742, `saveSectionBeforeLeaving` ~1109, `saveAssessment` ~2041, `loadPrescriptionPanel` / `savePrescriptionPanel` ~2178-2210)
- Test: `do_derma/tests/test_chart_theme.py`

**Interfaces:**
- Consumes: Task 3's `diagnosis` / `assessment_diagnosis` response keys and `diagnosis` save argument.
- Produces: panel props `savedDiagnosis: String`, `assessmentDiagnosis: String`; `getSavePayload()` and `emit("save", ...)` now carry `{ rows, diagnosis }` (or `null`).

- [ ] **Step 1: Write failing source tests**

Add to `TestPrescriptionPanelRestyle`:

```python
	def test_the_diagnosis_field_copies_from_the_assessment(self):
		template, script, _ = get_component_parts(PRESCRIPTION_PANEL)
		field = get_element(template, '<div v-if="hasEncounter && !loading" class="diagnosis-field"')
		self.assertIn('data-test="prescription-diagnosis"', field)
		self.assertIn('data-test="prescription-copy-diagnosis"', field)
		self.assertIn('__("Copy from assessment")', field)
		self.assertIn("savedDiagnosis: { type: String, default: \"\" }", script)
		self.assertIn("assessmentDiagnosis: { type: String, default: \"\" }", script)
		reset = script.split("function resetDrafts()", 1)[1].split("\n}", 1)[0]
		self.assertIn("props.savedDiagnosis || (canEdit.value ? props.assessmentDiagnosis : \"\")", reset)

	def test_a_copied_diagnosis_is_not_unsaved_until_something_is_prescribed(self):
		_, script, _ = get_component_parts(PRESCRIPTION_PANEL)
		dirty = script.split("const isDiagnosisDirty", 1)[1].split("})", 1)[0]
		self.assertIn("rowCount.value > 0", dirty)
		self.assertIn("diagnosis.value !== seededDiagnosis.value", dirty)
		self.assertIn("|| isDiagnosisDirty.value", script)

	def test_the_save_payload_carries_the_diagnosis(self):
		_, script, _ = get_component_parts(PRESCRIPTION_PANEL)
		self.assertIn("return { rows: getPayload(), diagnosis: diagnosis.value }", script)
		chart = (CHART_DIR / "DermaChart.vue").read_text()
		save = chart.split("async function savePrescriptionPanel", 1)[1].split("\n}", 1)[0]
		self.assertIn("payload: payload.rows, diagnosis: payload.diagnosis", save)
		self.assertIn(':saved-diagnosis="prescriptionPanel.diagnosis"', chart)
		self.assertIn(':assessment-diagnosis="prescriptionPanel.assessmentDiagnosis"', chart)

	def test_an_assessment_save_refreshes_the_offered_diagnosis(self):
		chart = (CHART_DIR / "DermaChart.vue").read_text()
		save = chart.split("async function saveAssessment", 1)[1].split("\n}", 1)[0]
		self.assertIn("if (loadedTabs.prescriptions) loadPrescriptionPanel(true)", save)
```

- [ ] **Step 2: Run `test_chart_theme`, expect these to FAIL.**

- [ ] **Step 3: Panel template**

Insert directly after the `<p v-if="errorText" ...>` line:

```html
    <div v-if="hasEncounter && !loading" class="diagnosis-field">
      <div class="diagnosis-head">
        <label class="chart-label" for="prescription-diagnosis">{{ __("Diagnosis") }}</label>
        <button
          v-if="canEdit && assessmentDiagnosis"
          type="button"
          class="ghost small"
          data-test="prescription-copy-diagnosis"
          @click="diagnosis = assessmentDiagnosis"
        >
          {{ __("Copy from assessment") }}
        </button>
      </div>
      <textarea
        id="prescription-diagnosis"
        v-model="diagnosis"
        rows="2"
        class="diagnosis-input"
        data-test="prescription-diagnosis"
        :disabled="!canEdit"
        :placeholder="__('Printed on the prescription')"
      ></textarea>
    </div>
```

- [ ] **Step 4: Panel script**

Props: add

```js
  savedDiagnosis: { type: String, default: "" },
  assessmentDiagnosis: { type: String, default: "" },
```

State, beside `snapshot`:

```js
const diagnosis = ref("")
const seededDiagnosis = ref("")
```

Replace `isDirty` with:

```js
// A copied diagnosis needs saving only once the visit prescribes something, so a look at the tab stays clean.
const isDiagnosisDirty = computed(() => {
  if (diagnosis.value === props.savedDiagnosis) return false
  return rowCount.value > 0 || Boolean(props.savedDiagnosis) || diagnosis.value !== seededDiagnosis.value
})
const isDirty = computed(() => JSON.stringify(getPayload()) !== snapshot.value || isDiagnosisDirty.value)
```

In `resetDrafts`, before `snapshot.value = ...`:

```js
  seededDiagnosis.value = props.savedDiagnosis || (canEdit.value ? props.assessmentDiagnosis : "")
  diagnosis.value = seededDiagnosis.value
```

`getSavePayload` and `save`:

```js
/** The rows and diagnosis to save, or null when a required field is missing (the gap is shown). */
async function getSavePayload() {
  await rowComponents[openPicker.value?.key]?.commitPicker()
  showMissing.value = true
  if (validationError.value) return null
  showMissing.value = false
  return { rows: getPayload(), diagnosis: diagnosis.value }
}

defineExpose({ getSavePayload })

async function save() {
  if (!canEdit.value || props.saving || props.loading) return
  const payload = await getSavePayload()
  if (payload) emit("save", payload)
}
```

Style:

```css
.diagnosis-field {
  margin-bottom: 12px;
}

.diagnosis-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 4px;
}

.diagnosis-input {
  width: 100%;
  padding: 6px 8px;
  border: 1px solid var(--chart-border);
  border-radius: 6px;
  background: var(--chart-surface);
  color: var(--chart-text);
  font-size: 13px;
  resize: vertical;
}

.diagnosis-input:focus {
  border-color: var(--chart-accent);
  outline: none;
}
```

- [ ] **Step 5: Chart wiring**

`prescriptionPanel` reactive becomes:

```js
const prescriptionPanel = reactive({
  loading: false,
  saving: false,
  error: "",
  encounter: "",
  rows: [],
  previous: null,
  diagnosis: "",
  assessmentDiagnosis: "",
})
```

On the `<PrescriptionPanel>` tag add:

```html
      :saved-diagnosis="prescriptionPanel.diagnosis"
      :assessment-diagnosis="prescriptionPanel.assessmentDiagnosis"
```

Add one helper beside `loadPrescriptionPanel` and use it in both load and save (set the diagnosis fields **before** `rows`, since the panel resets on the `rows` watcher):

```js
function applyPrescriptionResponse(message = {}) {
  prescriptionPanel.encounter = message.encounter || prescriptionPanel.encounter || encounter.value.name || ""
  prescriptionPanel.diagnosis = message.diagnosis || ""
  prescriptionPanel.assessmentDiagnosis = message.assessment_diagnosis || ""
  prescriptionPanel.rows = message.drug_prescription || []
}
```

`loadPrescriptionPanel` try-block body:

```js
    const response = await frappe.call({ method: "do_derma.api.get_derma_prescriptions", args: contextArgs() })
    applyPrescriptionResponse(response.message)
    prescriptionPanel.previous = response.message?.previous || null
    loadedTabs.prescriptions = true
```

(the existing test needs the literal `prescriptionPanel.previous = response.message?.previous || null` — keep it).

`savePrescriptionPanel(payload)`:

```js
async function savePrescriptionPanel(payload) {
  prescriptionPanel.saving = true
  prescriptionPanel.error = ""
  try {
    const response = await frappe.call({
      method: "do_derma.api.set_derma_prescriptions",
      args: { ...contextArgs(), payload: payload.rows, diagnosis: payload.diagnosis },
    })
    applyPrescriptionResponse(response.message)
    frappe.show_alert({ message: __("Prescriptions saved"), indicator: "green" })
  } catch (error) {
    // A refused save must never look like a saved one: the row is not in the record.
    prescriptionPanel.error = serverErrorText(error, __("Prescriptions could not be saved."))
    frappe.show_alert({ message: prescriptionPanel.error, indicator: "red" })
  } finally {
    prescriptionPanel.saving = false
  }
}
```

`saveSectionBeforeLeaving` prescriptions branch:

```js
    const payload = await prescriptionPanelRef.value.getSavePayload()
    if (!payload) return false
    await savePrescriptionPanel(payload)
    return !prescriptionPanel.error
```

`saveAssessment`, right after `frappe.show_alert({ message: __("Assessment saved"), ... })`:

```js
    if (loadedTabs.prescriptions) loadPrescriptionPanel(true)
```

- [ ] **Step 6: Run `test_chart_theme`; expect PASS** (including the pre-existing `test_the_chart_keeps_the_previous_visit_across_saves`, which asserts `savePrescriptionPanel` never mentions `previous`).

- [ ] **Step 7: Commit**

```bash
git add do_derma/public/js/chart do_derma/tests/test_chart_theme.py
git commit -m "feat(prescriptions): Rx tab diagnosis field seeded from the assessment"
```

---

### Task 5: Submit Rx — backend

**Files:**
- Modify: `do_derma/api.py` (new endpoint after `set_derma_prescriptions`)
- Test: `do_derma/tests/test_encounter_tabs.py` (new class `TestSubmitPrescriptions`)

**Interfaces:**
- Produces: `submit_derma_prescriptions(encounter=None, appointment=None, patient=None)` → `get_derma_prescriptions` shape. Throws `ValidationError` with "Nothing to order" when no saved row lacks a `medication_request`.

- [ ] **Step 1: Write failing tests**

```python
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
```

- [ ] **Step 2: Run each by bare name; expect FAIL** (`AttributeError: ... submit_derma_prescriptions`).

- [ ] **Step 3: Implement**

After `set_derma_prescriptions` in `api.py`:

```python
@frappe.whitelist()
def submit_derma_prescriptions(encounter=None, appointment=None, patient=None):
	"""Order the saved, not-yet-ordered rows as Medication Requests; the visit stays open."""
	_ensure_clinical_access()
	encounter_doc = _resolve_patient_encounter_doc(
		encounter=encounter, appointment=appointment, patient=patient, ptype="write"
	)
	if not encounter_doc:
		frappe.throw(_("No encounter found for this session."), frappe.ValidationError)
	_ensure_encounter_open(encounter_doc.name)
	rows = encounter_doc.get("drug_prescription") or []
	if not any((row.medication or row.drug_code) and not row.medication_request for row in rows):
		frappe.throw(_("Nothing to order: save new medications first."), frappe.ValidationError)
	encounter_doc.make_medication_request()
	encounter_doc.save(ignore_permissions=True)
	return get_derma_prescriptions(encounter=encounter_doc.name)
```

The `(row.medication or row.drug_code)` test mirrors healthcare's own `make_medication_request` condition, so the guard and the ordering agree on what is orderable.

If `test_a_completed_visit_cannot_submit` fails because `_resolve_patient_encounter_doc` refuses before `_ensure_encounter_open`, that is still a `ValidationError`/`PermissionError` — read the actual exception and keep the assertion on the type actually raised for a submitted encounter (it must not succeed).

- [ ] **Step 4: Run the class's tests by bare name; expect PASS.** Then run the full `test_encounter_tabs` module.

- [ ] **Step 5: Lint and commit**

```bash
pipx run ruff check do_derma/api.py do_derma/tests/test_encounter_tabs.py
git add do_derma/api.py do_derma/tests/test_encounter_tabs.py
git commit -m "feat(prescriptions): order the saved Rx without completing the visit"
```

---

### Task 6: Submit Rx — button

**Files:**
- Modify: `PrescriptionPanel.vue`, `DermaChart.vue`
- Test: `do_derma/tests/test_chart_theme.py`

**Interfaces:**
- Consumes: Task 5's `do_derma.api.submit_derma_prescriptions`.
- Produces: panel emits `submit` (no payload) after the user confirms.

- [ ] **Step 1: Write failing source tests; update the button count**

In `test_the_header_has_no_add_button` change `self.assertEqual(header.count("<button"), 2)` to `3`.

Add:

```python
	def test_submit_needs_saved_unordered_rows_and_no_unsaved_changes(self):
		template, script, _ = get_component_parts(PRESCRIPTION_PANEL)
		header = get_element(template, '<Teleport defer to="#chart-section-actions">')
		start = header.index('data-test="prescription-submit"')
		button = header[start : header.index(">", start)]
		self.assertIn("isDirty", button)
		self.assertIn("!unorderedCount", button)
		self.assertLess(start, header.index('data-test="prescription-save"'))
		self.assertIn("(props.rows || []).filter((row) => (row.medication || row.drug_code) && !row.medication_request)", script)
		submit = script.split("function submitPrescription()", 1)[1].split("\n}", 1)[0]
		self.assertIn("frappe.confirm(", submit)
		self.assertIn('emit("submit")', submit)

	def test_the_chart_orders_and_refreshes(self):
		chart = (CHART_DIR / "DermaChart.vue").read_text()
		self.assertIn('@submit="submitPrescriptionPanel"', chart)
		submit = chart.split("async function submitPrescriptionPanel", 1)[1].split("\n}", 1)[0]
		self.assertIn('"do_derma.api.submit_derma_prescriptions"', submit)
		self.assertIn("applyPrescriptionResponse(response.message)", submit)
```

- [ ] **Step 2: Run, expect FAIL.**

- [ ] **Step 3: Panel**

In the Teleport, inside `<template v-if="canEdit">`, before the Save button:

```html
        <button
          v-if="hasSavedRows"
          type="button"
          class="ghost small"
          data-test="prescription-submit"
          :disabled="loading || saving || isDirty || !unorderedCount"
          :title="isDirty ? __('Save first, then submit') : ''"
          @click="submitPrescription"
        >
          {{ __("Submit Rx") }}
        </button>
```

Script: `defineEmits(["save", "dirty", "print", "submit"])`, plus

```js
const unorderedCount = computed(
  () => (props.rows || []).filter((row) => (row.medication || row.drug_code) && !row.medication_request).length
)
```

and beside `printPrescription`:

```js
function submitPrescription() {
  if (isDirty.value || !unorderedCount.value) return
  frappe.confirm(
    __("Order {0} medications? Ordered rows can't be edited here.").replace("{0}", unorderedCount.value),
    () => emit("submit")
  )
}
```

- [ ] **Step 4: Chart**

On `<PrescriptionPanel>` add `@submit="submitPrescriptionPanel"`. Beside `savePrescriptionPanel`:

```js
async function submitPrescriptionPanel() {
  prescriptionPanel.saving = true
  prescriptionPanel.error = ""
  try {
    const response = await frappe.call({ method: "do_derma.api.submit_derma_prescriptions", args: contextArgs() })
    applyPrescriptionResponse(response.message)
    frappe.show_alert({ message: __("Prescription ordered"), indicator: "green" })
  } catch (error) {
    prescriptionPanel.error = serverErrorText(error, __("The prescription could not be ordered."))
    frappe.show_alert({ message: prescriptionPanel.error, indicator: "red" })
  } finally {
    prescriptionPanel.saving = false
  }
}
```

- [ ] **Step 5: Run `test_chart_theme`; expect PASS.**

- [ ] **Step 6: Commit**

```bash
git add do_derma/public/js/chart do_derma/tests/test_chart_theme.py
git commit -m "feat(prescriptions): Submit Rx button orders saved rows after a confirm"
```

---

### Task 7: Prescription warehouse and linked-item stock — backend

**Files:**
- Modify: `do_derma/do_derma/doctype/derma_settings/derma_settings.json`
- Modify: `do_derma/settings.py`
- Modify: `do_derma/api.py` (new endpoint after `submit_derma_prescriptions`)
- Test: `do_derma/tests/test_encounter_tabs.py` (new class `TestMedicationItems`)

**Interfaces:**
- Produces: `settings.get_prescription_warehouse() -> str | None`.
- Produces: `get_medication_items(medication: str)` → `{"warehouse": str, "items": [{"item_code", "item_name", "stock_uom", "actual_qty": float | None}]}`, in linked-item order, disabled items skipped.

- [ ] **Step 1: Settings JSON**

In `derma_settings.json`, insert `"prescription_section", "prescription_warehouse"` into `field_order` right before `"voice_section"`, and add to `fields`:

```json
  {
   "fieldname": "prescription_section",
   "fieldtype": "Section Break",
   "label": "Prescriptions"
  },
  {
   "description": "The Rx tab shows each linked item's stock in this warehouse.",
   "fieldname": "prescription_warehouse",
   "fieldtype": "Link",
   "label": "Prescription Warehouse",
   "options": "Warehouse"
  },
```

Bump the JSON's `"modified"` timestamp to now (format `YYYY-MM-DD HH:MM:SS.ffffff`) so migrate picks it up. If `derma_settings.py` has an auto-generated `# begin: auto-generated types` block, add `prescription_warehouse: DF.Link | None` to it in alphabetical position.

Run `bench --site dermaone.localhost migrate`.

- [ ] **Step 2: Write failing tests**

```python
class TestMedicationItems(PrescriptionHelpers, IntegrationTestCase):
	"""The Rx tab's item chooser: a medication's linked items with stock in the pharmacy warehouse."""

	def setUp(self):
		super().setUp()
		self.warehouse = frappe.db.get_value("Warehouse", {"is_group": 0}, "name")
		self.medication = frappe.get_doc({"doctype": "Medication", "generic_name": f"DermaMed{frappe.generate_hash(length=8)}"}).insert(ignore_permissions=True).name

	def _set_warehouse(self, warehouse):
		frappe.db.set_single_value("Derma Settings", "prescription_warehouse", warehouse)
		frappe.clear_document_cache("Derma Settings", "Derma Settings")

	def _link_item(self, actual_qty=None, disabled=0):
		token = frappe.generate_hash(length=8)
		item_code = frappe.get_doc(
			{
				"doctype": "Item",
				"item_code": f"DermaRx{token}",
				"item_name": f"Derma Rx {token}",
				"item_group": frappe.db.get_value("Item Group", {"is_group": 0}, "name"),
				"stock_uom": "Nos",
				"is_stock_item": 1,
				"disabled": disabled,
			}
		).insert(ignore_permissions=True).name
		parent = frappe.get_doc("Medication", self.medication)
		frappe.get_doc(
			{
				"doctype": "Medication Linked Item",
				"parent": self.medication,
				"parenttype": "Medication",
				"parentfield": "linked_items",
				"idx": len(parent.linked_items) + 1,
				"item": item_code,
				"item_code": item_code,
			}
		).db_insert()
		if actual_qty is not None:
			frappe.get_doc(
				{"doctype": "Bin", "item_code": item_code, "warehouse": self.warehouse, "actual_qty": actual_qty}
			).insert(ignore_permissions=True)
		return item_code

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
```

- [ ] **Step 3: Run each by bare name; expect FAIL** (`AttributeError: get_medication_items`).

- [ ] **Step 4: Implement**

`do_derma/settings.py`, after `get_expiring_soon_days`:

```python
PRESCRIPTION_WAREHOUSE_FIELD = "prescription_warehouse"


def get_prescription_warehouse() -> str | None:
	"""Where the Rx tab reads stock from, None when the site never set one."""
	settings = get_settings_doc()
	if not settings or not settings.meta.has_field(PRESCRIPTION_WAREHOUSE_FIELD):
		return None
	return settings.get(PRESCRIPTION_WAREHOUSE_FIELD) or None
```

`api.py`: add `get_prescription_warehouse` to the `from do_derma.settings import (...)` block, then after `submit_derma_prescriptions`:

```python
@frappe.whitelist()
def get_medication_items(medication: str) -> dict[str, Any]:
	"""The medication's enabled linked items with their stock in the prescription warehouse."""
	_ensure_clinical_access()
	warehouse = get_prescription_warehouse()
	item_codes = frappe.get_all(
		"Medication Linked Item",
		filters={"parent": medication, "parenttype": "Medication"},
		pluck="item",
		order_by="idx asc",
	)
	items = []
	for item_code in filter(None, item_codes):
		item = frappe.db.get_value("Item", item_code, ["item_name", "stock_uom", "disabled"], as_dict=True)
		if not item or item.disabled:
			continue
		stock = flt(frappe.db.get_value("Bin", {"item_code": item_code, "warehouse": warehouse}, "actual_qty"))
		items.append(
			{
				"item_code": item_code,
				"item_name": item.item_name,
				"stock_uom": item.stock_uom,
				"actual_qty": stock if warehouse else None,
			}
		)
	return {"warehouse": warehouse or "", "items": items}
```

(Only read the `Bin` when a warehouse is set: move the `stock = ...` line under `if warehouse` if the reviewer prefers; behaviour is the same.)

- [ ] **Step 5: Run the class's tests; expect PASS.** Then the full `test_encounter_tabs` module.

- [ ] **Step 6: Lint and commit**

```bash
pipx run ruff check do_derma/api.py do_derma/settings.py do_derma/tests/test_encounter_tabs.py
git add do_derma/api.py do_derma/settings.py do_derma/do_derma/doctype/derma_settings do_derma/tests/test_encounter_tabs.py
git commit -m "feat(prescriptions): linked items with stock from a Derma Settings prescription warehouse"
```

---

### Task 8: Linked-item chooser and chip

**Files:**
- Modify: `PrescriptionRow.vue`, `PrescriptionPanel.vue`
- Test: `do_derma/tests/test_chart_theme.py`

**Interfaces:**
- Consumes: Task 7's `do_derma.api.get_medication_items`.
- Produces: drafts carry `linkedItems: [{item_code, item_name, stock_uom, actual_qty}]` and `warehouse: string`; row emits `choose-item`; panel `openItemChooser(draft)` and `loadMedicationItems(draft)`.

- [ ] **Step 1: Update and add source tests**

In `TestPrescriptionRow`:
- `test_pickers_keep_escape_from_desk`: change `self.assertEqual(len(hosts), 3)` to `2`.
- Replace `test_drug_code_sits_under_the_medication` with:

```python
	def test_the_linked_item_is_a_chip_that_opens_the_chooser(self):
		template, script, _ = get_component_parts(PRESCRIPTION_ROW)
		medication = get_element(template, '<td class="medication-cell"')
		self.assertIn('data-test="prescription-item-chip"', medication)
		self.assertIn("emit('choose-item')", medication)
		self.assertIn('class="chart-spinner"', medication)
		self.assertNotIn("props.row.linkedItems] } }", script)
		self.assertNotIn('drug_code: "Item"', script)

	def test_the_chooser_lists_stock_and_an_alternative(self):
		template, script, style = get_component_parts(PRESCRIPTION_ROW)
		chooser = get_element(template, '<div\n        v-if="openField === \'drug_code\'"')
		self.assertIn('data-test="prescription-item-option"', chooser)
		self.assertIn('data-test="prescription-item-other"', chooser)
		self.assertIn('__("Choose another medication")', chooser)
		self.assertIn("@keydown.escape.stop", chooser)
		self.assertIn("'is-out': item.actual_qty === 0", chooser)
		self.assertIn('__("0 in stock")', script)
		self.assertIn('__("Set a Prescription Warehouse in Derma Settings to see stock.")', template)
		self.assertIn(".item-option.is-out", style)
```

In `TestPrescriptionPanelRestyle` add:

```python
	def test_items_come_from_the_stock_endpoint(self):
		_, script, _ = get_component_parts(PRESCRIPTION_PANEL)
		self.assertIn('"do_derma.api.get_medication_items"', script)
		self.assertNotIn("patient_encounter.get_medications", script)
		apply = script.split("async function applyMedication", 1)[1].split("\n}", 1)[0]
		self.assertIn("draft.linkedItems.length > 1", apply)
		self.assertIn('openPicker.value = { key: draft.key, field: "drug_code" }', apply)
		repeat = script.split("function repeatRow(row)", 1)[1].split("\n}", 1)[0]
		self.assertIn("refreshLinkedItem(draft)", repeat)
```

- [ ] **Step 2: Run `test_chart_theme`; expect FAIL.**

- [ ] **Step 3: Row template**

Replace the `drug_code` picker host and the two buttons/small that follow it (from `<div v-if="openField === 'drug_code'"` through `<small v-else-if="row.values.drug_code" class="drug-code">...</small>`) with:

```html
      <div
        v-if="openField === 'drug_code'"
        class="item-chooser"
        role="listbox"
        data-test="prescription-item-chooser"
        @keydown.escape.stop="closePicker('drug_code')"
      >
        <button
          v-for="item in row.linkedItems"
          :key="item.item_code"
          type="button"
          role="option"
          class="item-option"
          :class="{ 'is-out': item.actual_qty === 0 }"
          :aria-selected="item.item_code === row.values.drug_code ? 'true' : 'false'"
          data-test="prescription-item-option"
          @click="chooseItem(item.item_code)"
        >
          <span>{{ item.item_name || item.item_code }}</span>
          <small>{{ getStockLabel(item) }}</small>
        </button>
        <p v-if="!row.warehouse" class="chooser-hint">
          {{ __("Set a Prescription Warehouse in Derma Settings to see stock.") }}
        </p>
        <button type="button" class="item-option is-other" data-test="prescription-item-other" @click="chooseOtherMedication">
          {{ __("Choose another medication") }}
        </button>
      </div>
      <button
        v-else-if="!readOnly && row.values.medication && (row.values.drug_code || row.linkedItems.length > 1)"
        type="button"
        class="item-chip"
        data-field="drug_code"
        data-test="prescription-item-chip"
        @click="emit('choose-item')"
      >
        {{ itemLabel }}
      </button>
      <small v-else-if="row.values.drug_code" class="drug-code">{{ row.values.drug_code }}</small>
```

- [ ] **Step 4: Row script**

- `LINK_OPTIONS`: delete `drug_code: "Item",`.
- In `mountPicker`, delete the `get_query: field === "drug_code" ? ... : undefined,` line.
- The `openField` watcher must not mount a desk control for the chooser: change its guard to `if (!field || field === "drug_code") return`.
- `defineEmits([... , "choose-item"])`.
- Add:

```js
const selectedItem = computed(() => props.row.linkedItems.find((item) => item.item_code === props.row.values.drug_code))

const itemLabel = computed(() => {
  if (!props.row.values.drug_code) return __("Choose item")
  const item = selectedItem.value
  return item ? `${item.item_name || item.item_code} · ${getStockLabel(item)}` : props.row.values.drug_code
})

function getStockLabel(item) {
  if (item.actual_qty == null) return "—"
  if (item.actual_qty === 0) return __("0 in stock")
  return `${item.actual_qty} ${item.stock_uom || ""}`.trim()
}

function chooseItem(itemCode) {
  emit("update", "drug_code", itemCode)
  closePicker("drug_code")
}

function chooseOtherMedication() {
  emit("update", "medication", "")
  emit("open-picker", "medication")
}
```

Style:

```css
.item-chip {
  display: block;
  max-width: 100%;
  margin-top: 4px;
  padding: 2px 8px;
  border: 1px solid var(--chart-border);
  border-radius: 999px;
  background: var(--chart-surface-muted);
  color: var(--chart-text-soft);
  font-size: 12px;
  text-align: left;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  cursor: pointer;
}

.item-chooser {
  display: grid;
  gap: 2px;
  margin-top: 4px;
  padding: 4px;
  border: 1px solid var(--chart-border);
  border-radius: 8px;
  background: var(--chart-surface);
}

.item-option {
  display: flex;
  justify-content: space-between;
  gap: 8px;
  padding: 5px 8px;
  border: 0;
  border-radius: 6px;
  background: transparent;
  color: var(--chart-text);
  font-size: 13px;
  text-align: left;
  cursor: pointer;
}

.item-option:hover,
.item-option:focus-visible {
  background: var(--chart-surface-muted);
  outline: none;
}

.item-option.is-out {
  color: var(--chart-muted);
}

.item-option.is-other {
  color: var(--chart-accent);
}

.chooser-hint {
  margin: 2px 8px;
  color: var(--chart-muted);
  font-size: 12px;
}
```

Delete any now-unused `.drug-code-link` rule.

- [ ] **Step 5: Panel script**

`makeDraft` adds `warehouse: ""`:

```js
  return { key: ++nextKey, original, values, linkedItems: [], warehouse: "", lookup: 0, filling: false }
```

Add beside `applyMedication`:

```js
async function loadMedicationItems(draft) {
  const response = await frappe.call("do_derma.api.get_medication_items", { medication: draft.values.medication })
  return response?.message || { warehouse: "", items: [] }
}

async function openItemChooser(draft) {
  if (!draft.linkedItems.length) {
    const { warehouse, items } = await loadMedicationItems(draft)
    Object.assign(draft, { warehouse, linkedItems: items })
  }
  openPicker.value = { key: draft.key, field: "drug_code" }
}

// A repeated line keeps its item only while the medication still links it, with today's stock.
async function refreshLinkedItem(draft) {
  try {
    const { warehouse, items } = await loadMedicationItems(draft)
    Object.assign(draft, { warehouse, linkedItems: items })
    if (!items.some((item) => item.item_code === draft.values.drug_code)) {
      draft.values.drug_code = items.length === 1 ? items[0].item_code : ""
    }
  } catch (error) {
    // eslint-disable-next-line no-console
    console.warn("Failed to load linked items", error)
  }
}
```

In `applyMedication`, replace the `get_medications` call inside `Promise.all` with `loadMedicationItems(draft)` and rename `itemsResponse` → `itemsResult`; then:

```js
    if (token !== draft.lookup) return
    draft.linkedItems = itemsResult.items
    draft.warehouse = itemsResult.warehouse
    const defaults = defaultsResponse?.message || {}
    draft.values = {
      ...draft.values,
      drug_code: draft.linkedItems.length === 1 ? draft.linkedItems[0].item_code : "",
      dosage: defaults.default_prescription_dosage || "",
      period: defaults.default_prescription_duration || "",
      dosage_form: defaults.dosage_form || "",
    }
    if (draft.linkedItems.length > 1) openPicker.value = { key: draft.key, field: "drug_code" }
```

`repeatRow` becomes:

```js
function repeatRow(row) {
  if (isPrescribed(row.medication)) return
  ensureTrailingDraft()
  const draft = drafts.value.at(-1)
  draft.values = Object.fromEntries(VALUE_FIELDS.map((field) => [field, row[field] ?? ""]))
  ensureTrailingDraft()
  refreshLinkedItem(draft)
}
```

On `<PrescriptionRow>` add `@choose-item="openItemChooser(draft)"`.

- [ ] **Step 6: Run `test_chart_theme`; expect PASS.**

- [ ] **Step 7: Commit**

```bash
git add do_derma/public/js/chart/components/prescription do_derma/tests/test_chart_theme.py
git commit -m "feat(prescriptions): choose the linked item with its pharmacy stock, or another medication"
```

---

### Task 9: Rx pickers fetch 50 results

**Files:**
- Modify: `PrescriptionRow.vue` (`mountPicker`)
- Test: `do_derma/tests/test_chart_theme.py`

**Interfaces:**
- Produces: `PICKER_PAGE_LENGTH = 50` in the row script.

- [ ] **Step 1: Failing source test** (in `TestPrescriptionRow`)

```python
	def test_pickers_fetch_fifty_results(self):
		"""Desk's Link control reads the site-wide limit; only the Rx pickers ask for more."""
		_, script, _ = get_component_parts(PRESCRIPTION_ROW)
		self.assertIn("const PICKER_PAGE_LENGTH = 50", script)
		self.assertIn("page_length: PICKER_PAGE_LENGTH", script)
		self.assertIn("control.get_search_args = ", script)
		self.assertNotIn("link_field_results_limit", script)
```

- [ ] **Step 2: Run, expect FAIL.**

- [ ] **Step 3: Implement**

Add the constant beside `LINK_COLUMNS`:

```js
const PICKER_PAGE_LENGTH = 50
```

In `mountPicker`, right after `control = frappe.ui.form.make_control({...})`:

```js
  const getSearchArgs = control.get_search_args.bind(control)
  control.get_search_args = (text) => {
    const args = getSearchArgs(text)
    return args && { ...args, page_length: PICKER_PAGE_LENGTH }
  }
```

- [ ] **Step 4: Run, expect PASS.**

- [ ] **Step 5: Commit**

```bash
git add do_derma/public/js/chart/components/prescription/PrescriptionRow.vue do_derma/tests/test_chart_theme.py
git commit -m "feat(prescriptions): medication, dosage and duration pickers list 50 results"
```

---

### Task 10: Build, full-suite diff and live check

- [ ] **Step 1: Build and migrate**

```bash
cd /Users/hameed/Developer/bench-v16
bench --site dermaone.localhost migrate
bench build --app do_derma
```

Restart the web server after the build (assets 404 until it restarts — see memory).

- [ ] **Step 2: Full modules vs. baseline**

Run `test_encounter_tabs`, `test_chart_theme`, `test_api`, `test_encounter_lock` on the branch, collect failing names, then `git switch main`, run the same modules, and diff. Only baseline names may fail. `git switch feat/prescription-submit-and-stock` afterwards.

- [ ] **Step 3: Live check on dermaone.localhost**

`bench --site dermaone.localhost browse --user Administrator` → open a draft encounter's chart → Prescription tab:

1. The Diagnosis field shows the assessment's diagnosis; the tab is not "Unsaved changes" with no rows.
2. Pick a medication with several linked items: the chooser opens listing stock (set `Prescription Warehouse` in Derma Settings first; then unset it and see "—" plus the hint).
3. Type in Notes; no Form/Repeats columns.
4. Medication/Dosage/Duration pickers list more than 10 results (where the master has >10).
5. Save → Submit Rx → confirm → rows turn "Ordered"; Submit disables; add a row, Submit stays disabled until Save.
6. Print → Diagnosis line under Allergies, Notes column.

Clean up any seeded rows / Medication Requests afterwards.

- [ ] **Step 4: Report** the failing-name diff and the live check results; do not push or open a PR without asking.
