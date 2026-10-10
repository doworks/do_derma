<template>
  <tr ref="rowElement" class="prescription-row" :class="{ 'is-next': isNext }" data-test="prescription-row">
    <td class="medication-cell">
      <div
        v-if="openField === 'medication'"
        :ref="setPickerHost"
        class="picker-host"
        @keydown.escape.stop="closePicker('medication')"
      ></div>
      <button
        v-else
        type="button"
        class="cell-input medication-name"
        :class="{ 'is-empty': !row.values.medication && !readOnly, 'is-missing': missing.includes('medication') }"
        data-field="medication"
        data-test="prescription-medication"
        :disabled="readOnly"
        @click="emit('open-picker', 'medication')"
      >
        {{ medicationLabel }}
      </button>
      <div
        v-if="openField === 'drug_code'"
        :ref="setPickerHost"
        class="picker-host"
        @keydown.escape.stop="closePicker('drug_code')"
      ></div>
      <button
        v-else-if="row.linkedItems.length > 1 && !readOnly"
        type="button"
        class="drug-code-link"
        data-field="drug_code"
        data-test="prescription-choose-item"
        @click="emit('open-picker', 'drug_code')"
      >
        {{ row.values.drug_code || __("Choose item") }}
      </button>
      <small v-else-if="row.values.drug_code" class="drug-code">{{ row.values.drug_code }}</small>
      <small v-if="duplicateOf" class="duplicate-note" data-test="prescription-duplicate">
        <i class="fa-solid fa-triangle-exclamation" aria-hidden="true"></i>
        {{ __("Also prescribed in row {0}").replace("{0}", duplicateOf) }}
      </small>
      <span v-if="row.filling" class="filling" data-test="prescription-filling">
        <span class="chart-spinner" aria-hidden="true"></span>
        {{ __("Filling in dosage and duration...") }}
      </span>
    </td>
    <td v-for="column in LINK_COLUMNS" :key="column.field">
      <div
        v-if="openField === column.field"
        :ref="setPickerHost"
        class="picker-host"
        @keydown.escape.stop="closePicker(column.field)"
      ></div>
      <button
        v-else
        type="button"
        class="cell-input"
        :class="{ 'is-empty': !row.values[column.field], 'is-missing': missing.includes(column.field) }"
        :data-field="column.field"
        :data-test="`prescription-${column.field}`"
        :disabled="readOnly"
        @click="emit('open-picker', column.field)"
      >
        {{ row.values[column.field] || (readOnly ? "—" : column.placeholder) }}
      </button>
    </td>
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
    <td class="row-actions">
      <button
        v-if="!readOnly && !isNext"
        type="button"
        class="icon-btn danger"
        data-test="prescription-delete"
        :title="__('Remove medication')"
        :aria-label="__('Remove medication')"
        @click="emit('remove')"
      >
        <i class="fa-regular fa-trash-can"></i>
      </button>
    </td>
  </tr>
</template>

<script setup>
import { computed, nextTick, ref, watch } from "vue"

const __ = window.__ || ((text) => text)

const LINK_OPTIONS = {
  medication: "Medication",
  drug_code: "Item",
  dosage: "Prescription Dosage",
  period: "Prescription Duration",
}
const LINK_COLUMNS = [
  { field: "dosage", placeholder: __("Dosage") },
  { field: "period", placeholder: __("Duration") },
]

const props = defineProps({
  row: { type: Object, required: true },
  readOnly: { type: Boolean, default: false },
  isNext: { type: Boolean, default: false },
  duplicateOf: { type: Number, default: 0 },
  openField: { type: String, default: "" },
  missing: { type: Array, default: () => [] },
})

const emit = defineEmits(["update", "open-picker", "close-picker", "remove"])

// Older rows carry only a drug name or item code.
const medicationLabel = computed(() => {
  const { medication, drug_code: drugCode } = props.row.values
  if (medication) return medication
  if (props.readOnly) return props.row.original.drug_name || drugCode || "—"
  return __("Choose medication")
})

const rowElement = ref(null)
let pickerHost = null
let control = null

watch(
  () => props.openField,
  async (field) => {
    if (!field) return
    await nextTick()
    mountPicker(field)
  },
  { immediate: true }
)

function setPickerHost(element) {
  pickerHost = element || null
}

function mountPicker(field) {
  if (!pickerHost || !window.frappe?.ui?.form?.make_control) return
  pickerHost.innerHTML = ""
  control = frappe.ui.form.make_control({
    parent: pickerHost,
    df: {
      fieldtype: "Link",
      fieldname: field,
      options: LINK_OPTIONS[field],
      placeholder: __(LINK_OPTIONS[field]),
      only_select: 1,
      get_query: field === "drug_code" ? () => ({ filters: { name: ["in", props.row.linkedItems] } }) : undefined,
      change: () => {
        emit("update", field, control.get_value() || "")
        closePicker(field)
      },
    },
    render_input: true,
  })
  // Seeded without firing `change`; desk's blur only reports values that differ from `last_value`.
  const current = props.row.values[field] || ""
  control.set_input(current)
  control.last_value = current
  control.$input?.focus()
}

// Save calls this so a typed value desk is still validating reaches the row first.
async function commitPicker() {
  if (!props.openField || !control?.$input) return
  await control.parse_validate_and_set_in_model(control.get_input_value())
}

defineExpose({ commitPicker })

function closePicker(field) {
  emit("close-picker")
  nextTick(() => rowElement.value?.querySelector(`[data-field="${field}"]`)?.focus())
}



</script>

<style scoped>
.cell-input {
  display: block;
  width: 100%;
  min-height: 30px;
  padding: 5px 8px;
  border: 1px solid var(--chart-border);
  border-radius: 6px;
  background: var(--chart-surface);
  color: var(--chart-text);
  font-size: 13px;
  text-align: left;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  cursor: pointer;
}

.cell-input:hover:not(:disabled),
.cell-input:focus-visible {
  border-color: var(--chart-accent);
  outline: none;
}

.cell-input.is-empty {
  color: var(--chart-muted);
}

.prescription-row.is-next .cell-input {
  border-style: dashed;
  background: transparent;
}

.cell-input.is-missing {
  border-color: var(--chart-danger-text);
  background: var(--chart-danger-soft);
}

.cell-input:disabled {
  padding-left: 0;
  border-color: transparent;
  background: transparent;
  color: var(--chart-text);
  opacity: 1;
  cursor: default;
}

.medication-name {
  font-weight: 600;
}

.notes-input {
  cursor: text;
}

.drug-code,
.drug-code-link {
  display: block;
  margin-top: 3px;
  color: var(--chart-muted);
  font-size: 12px;
}

.drug-code-link {
  padding: 0;
  border: 0;
  background: none;
  color: var(--chart-accent-strong);
  text-decoration: underline dotted;
  cursor: pointer;
}

.duplicate-note {
  display: flex;
  align-items: center;
  gap: 5px;
  margin-top: 4px;
  color: var(--chart-caution-text);
  font-size: 12px;
}

.filling {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  margin-top: 4px;
  color: var(--chart-muted);
  font-size: 12px;
}

.picker-host :deep(.frappe-control) {
  margin-bottom: 0;
}

.picker-host :deep(.control-label) {
  display: none;
}

.row-actions {
  white-space: nowrap;
  text-align: right;
}

.icon-btn {
  width: 28px;
  height: 28px;
  border: 0;
  border-radius: 8px;
  background: transparent;
  color: var(--chart-muted);
  font-size: 13px;
  cursor: pointer;
}

.icon-btn:hover:not(:disabled),
.icon-btn:focus-visible {
  background: var(--chart-surface-muted);
  color: var(--chart-text);
}

.icon-btn.danger:hover:not(:disabled),
.icon-btn.danger:focus-visible {
  background: var(--chart-danger-soft);
  color: var(--chart-danger-text);
}
</style>
