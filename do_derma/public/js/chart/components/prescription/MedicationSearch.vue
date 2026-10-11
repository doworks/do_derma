<template>
  <div class="medication-search" @keydown.escape.stop="emit('close')">
    <input
      ref="inputElement"
      v-model="query"
      type="text"
      class="search-input"
      data-test="medication-search-input"
      role="combobox"
      aria-autocomplete="list"
      :aria-expanded="options.length ? 'true' : 'false'"
      :placeholder="__('Search medication')"
      @input="scheduleSearch"
      @keydown.down.prevent="move(1)"
      @keydown.up.prevent="move(-1)"
      @keydown.enter.prevent="pick(options[activeIndex])"
      @blur="emit('close')"
    />
    <ul class="search-list" role="listbox">
      <li v-if="loading && !options.length" class="search-note">{{ __("Searching...") }}</li>
      <li v-else-if="!options.length" class="search-note">{{ __("No medications match.") }}</li>
      <li
        v-for="(option, index) in options"
        :key="option.key"
        role="option"
        class="search-option"
        :class="{ 'is-item': option.item, 'is-active': index === activeIndex, 'is-out': option.item && option.item.actual_qty === 0 }"
        :aria-selected="index === activeIndex ? 'true' : 'false'"
        :data-test="option.item ? 'medication-item-option' : 'medication-option'"
        @mousedown.prevent="pick(option)"
        @mouseenter="activeIndex = index"
      >
        <template v-if="option.item">
          <span class="option-name">{{ option.item.item_name || option.item.item_code }}</span>
          <span class="option-meta">
            <span v-if="option.item.is_suggested" class="suggested-tag">{{ __("suggested") }}</span>
            {{ getStockLabel(option.item) }}
          </span>
        </template>
        <template v-else>
          <span class="option-name">{{ option.medication }}</span>
          <span v-if="option.doctorUses" class="option-meta">{{ __("used {0}×").replace("{0}", option.doctorUses) }}</span>
        </template>
      </li>
    </ul>
  </div>
</template>

<script setup>
import { computed, onMounted, ref } from "vue"
import { getStockLabel } from "./stock.js"

const __ = window.__ || ((text) => text)

const SEARCH_DELAY_MS = 200

const props = defineProps({
  encounter: { type: String, default: "" },
  value: { type: String, default: "" },
})

const emit = defineEmits(["pick", "close"])

const inputElement = ref(null)
const query = ref(props.value)
const results = ref([])
const warehouse = ref("")
const loading = ref(false)
const activeIndex = ref(0)
let searchToken = 0
let searchTimer = null

// One list for the keyboard: each medication, then its items indented under it.
const options = computed(() =>
  results.value.flatMap((result) => [
    { key: result.medication, medication: result.medication, doctorUses: result.doctor_uses },
    ...result.items.map((item) => ({ key: `${result.medication}:${item.item_code}`, medication: result.medication, item })),
  ])
)

onMounted(() => {
  inputElement.value?.focus()
  inputElement.value?.select()
  search()
})

function scheduleSearch() {
  clearTimeout(searchTimer)
  searchTimer = setTimeout(search, SEARCH_DELAY_MS)
}

async function search() {
  const token = ++searchToken
  loading.value = true
  try {
    const response = await frappe.call("do_derma.api.search_prescription_medications", {
      txt: query.value,
      encounter: props.encounter,
    })
    if (token !== searchToken) return
    results.value = response?.message?.results || []
    warehouse.value = response?.message?.warehouse || ""
    activeIndex.value = 0
  } finally {
    if (token === searchToken) loading.value = false
  }
}

function move(step) {
  if (!options.value.length) return
  activeIndex.value = (activeIndex.value + step + options.value.length) % options.value.length
}

function pick(option) {
  if (!option) return
  const items = results.value.find((result) => result.medication === option.medication)?.items || []
  emit("pick", {
    medication: option.medication,
    drugCode: option.item?.item_code || "",
    items,
    warehouse: warehouse.value,
  })
}
</script>

<style scoped>
.medication-search {
  position: relative;
}

.search-input {
  display: block;
  width: 100%;
  min-height: 30px;
  padding: 5px 8px;
  border: 1px solid var(--chart-accent);
  border-radius: 6px;
  background: var(--chart-surface);
  color: var(--chart-text);
  font-size: 13px;
  outline: none;
}

.search-list {
  position: absolute;
  z-index: 20;
  top: calc(100% + 4px);
  left: 0;
  width: max(100%, 440px);
  max-height: 340px;
  margin: 0;
  padding: 4px;
  overflow-y: auto;
  border: 1px solid var(--chart-border);
  border-radius: 8px;
  background: var(--chart-surface);
  box-shadow: var(--chart-shadow);
  list-style: none;
}

.search-option {
  display: flex;
  justify-content: space-between;
  gap: 12px;
  padding: 6px 8px;
  border-radius: 6px;
  color: var(--chart-text);
  font-size: 13px;
  cursor: pointer;
}

.search-option.is-active {
  background: var(--chart-surface-muted);
}

.search-option.is-item {
  padding-left: 24px;
  color: var(--chart-text-soft);
  font-size: 12px;
}

.search-option.is-out {
  color: var(--chart-muted);
}

.option-name {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.option-meta {
  flex-shrink: 0;
  color: var(--chart-muted);
  font-size: 12px;
}

.suggested-tag {
  margin-right: 6px;
  padding: 0 6px;
  border-radius: 999px;
  background: var(--chart-accent-soft);
  color: var(--chart-accent-strong);
  font-size: 11px;
}

.search-note {
  padding: 6px 8px;
  color: var(--chart-muted);
  font-size: 12px;
}
</style>
