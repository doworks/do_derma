<template>
  <tr ref="rowElement" class="prescription-row" :class="{ 'is-next': isNext }" data-test="prescription-row">
    <td class="medication-cell">
      <MedicationSearch
        v-if="openField === 'medication'"
        :encounter="encounter"
        :value="row.values.medication"
        @pick="emit('pick-medication', $event)"
        @close="closePicker('medication')"
      />
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
          <small>
            <span v-if="item.is_suggested" class="suggested-tag">{{ __("suggested") }}</span>
            {{ getStockLabel(item) }}
          </small>
        </button>
        <p v-if="!row.warehouse" class="chooser-hint">
          {{ __("Set a Prescription Warehouse in Derma Settings to see stock.") }}
        </p>
        <button type="button" class="item-option is-other" data-test="prescription-item-other" @click="chooseOtherMedication">
          {{ __("Choose another medication") }}
        </button>
      </div>
      <button
        v-else-if="!readOnly && row.values.medication && (row.values.drug_code || row.linkedItems.length)"
        type="button"
        class="item-chip"
        data-field="drug_code"
        data-test="prescription-item-chip"
        @click="emit('choose-item')"
      >
        {{ itemLabel }}
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
        @keydown.enter.prevent="emit('notes-enter')"
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
import MedicationSearch from "./MedicationSearch.vue"
import { getStockLabel } from "./stock.js"

const __ = window.__ || ((text) => text)

const LINK_OPTIONS = {
  dosage: "Prescription Dosage",
  period: "Prescription Duration",
}
const PICKER_PAGE_LENGTH = 50
const LINK_COLUMNS = [
  { field: "dosage", placeholder: __("Dosage") },
  { field: "period", placeholder: __("Duration") },
]

const props = defineProps({
  row: { type: Object, required: true },
  encounter: { type: String, default: "" },
  readOnly: { type: Boolean, default: false },
  isNext: { type: Boolean, default: false },
  duplicateOf: { type: Number, default: 0 },
  openField: { type: String, default: "" },
  missing: { type: Array, default: () => [] },
})

const emit = defineEmits(["update", "open-picker", "close-picker", "choose-item", "pick-medication", "remove", "advance", "notes-enter"])

// Older rows carry only a drug name or item code.
const medicationLabel = computed(() => {
  const { medication, drug_code: drugCode } = props.row.values
  if (medication) return medication
  if (props.readOnly) return props.row.original.drug_name || drugCode || "—"
  return __("Choose medication")
})

const selectedItem = computed(() =>
  props.row.linkedItems.find((item) => item.item_code === props.row.values.drug_code)
)

const itemLabel = computed(() => {
  if (!props.row.values.drug_code) return __("Choose item")
  const item = selectedItem.value
  return item ? `${item.item_name || item.item_code} · ${getStockLabel(item)}` : props.row.values.drug_code
})

const rowElement = ref(null)
let pickerHost = null
let control = null

watch(
  () => props.openField,
  async (field) => {
    if (!LINK_OPTIONS[field]) {
      control = null
      return
    }
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
  const linkControl = frappe.ui.form.make_control({
    parent: pickerHost,
    df: {
      fieldtype: "Link",
      fieldname: field,
      options: LINK_OPTIONS[field],
      placeholder: __(LINK_OPTIONS[field]),
      only_select: 1,
      change: () => {
        if (linkControl !== control) return
        const value = linkControl.get_value() || ""
        emit("update", field, value)
        if (value && pickerHost?.contains(document.activeElement)) emit("advance")
        else closePicker(field)
      },
    },
    render_input: true,
  })
  control = linkControl
  const getSearchArgs = control.get_search_args.bind(control)
  control.get_search_args = (text) => {
    const args = getSearchArgs(text)
    return args && { ...args, page_length: PICKER_PAGE_LENGTH }
  }
  // Seeded without firing `change`; desk's blur only reports values that differ from `last_value`.
  const current = props.row.values[field] || ""
  control.set_input(current)
  control.last_value = current
  control.$input?.focus()
}

// Save calls this so a typed value desk is still validating reaches the row first.
async function commitPicker() {
  if (!LINK_OPTIONS[props.openField] || !control?.$input) return
  await control.parse_validate_and_set_in_model(control.get_input_value())
}

function focusNotes() {
  rowElement.value?.querySelector('[data-test="prescription-notes"]')?.focus()
}

// True when the doctor moved focus to another control on purpose.
function hasFocusElsewhere() {
  if (!rowElement.value) return false
  const active = document.activeElement
  return Boolean(active) && active !== document.body && !rowElement.value.contains(active)
}

defineExpose({ commitPicker, focusNotes, hasFocusElsewhere })

function chooseItem(itemCode) {
  emit("update", "drug_code", itemCode)
  emit("advance")
}

function chooseOtherMedication() {
  emit("update", "medication", "")
  emit("open-picker", "medication")
}

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

.drug-code {
  display: block;
  margin-top: 3px;
  color: var(--chart-muted);
  font-size: 12px;
}

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

.suggested-tag {
  margin-right: 6px;
  padding: 0 6px;
  border-radius: 999px;
  background: var(--chart-accent-soft);
  color: var(--chart-accent-strong);
  font-size: 11px;
}

.chooser-hint {
  margin: 2px 8px;
  color: var(--chart-muted);
  font-size: 12px;
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
