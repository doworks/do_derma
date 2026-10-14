<template>
  <section v-if="cards.length" class="previous-prescriptions" data-test="prescription-previous">
    <article
      v-if="summary?.lines"
      class="previous-card previous-summary"
      data-test="prescription-previous-summary"
    >
      <span class="summary-percent">{{ dispensedPercent }}%</span>
      <small>{{ __("dispensed by pharmacy") }}</small>
      <div
        class="summary-bar"
        role="progressbar"
        aria-valuemin="0"
        aria-valuemax="100"
        :aria-valuenow="dispensedPercent"
      >
        <span :style="{ width: `${dispensedPercent}%` }"></span>
      </div>
      <small>{{ summaryText }}</small>
    </article>
    <article v-for="card in cards" :key="card.encounter" class="previous-card" data-test="prescription-previous-card">
      <header class="previous-card-head">
        <span class="previous-date">{{ formatDate(card.encounter_date) }}</span>
        <span class="previous-practitioner" :title="card.practitioner_name">{{ card.practitioner_name }}</span>
        <button
          type="button"
          class="previous-repeat"
          data-test="prescription-previous-repeat"
          :title="__('Repeat these medications')"
          :aria-label="__('Repeat these medications')"
          :disabled="!canRepeat || card.lines.every((line) => prescribed.includes(line.medication))"
          @click="emit('repeat', card.lines)"
        >
          <i class="fa-solid fa-rotate-right" aria-hidden="true"></i>
        </button>
      </header>
      <ul class="previous-lines">
        <li
          v-for="(line, index) in card.lines"
          :key="index"
          :data-status="line.status"
          :title="getLineTitle(line)"
        >
          <i :class="STATUS_ICONS[line.status]" aria-hidden="true"></i>
          <span class="sr-only">{{ __(line.status) }}</span>
          <span class="previous-medication">{{ line.medication || line.drug_name }}</span>
        </li>
      </ul>
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
import { computed, ref, watch } from "vue"

const __ = window.__ || ((text) => text)

const PAGE_SIZE = 5
const STATUS_ICONS = {
  "Dispensed": "fa-solid fa-circle-check",
  "Partially dispensed": "fa-solid fa-circle-half-stroke",
  "Not dispensed": "fa-regular fa-circle",
}

const props = defineProps({
  encounter: { type: String, default: "" },
  canRepeat: { type: Boolean, default: false },
  prescribed: { type: Array, default: () => [] },
})

const emit = defineEmits(["repeat"])

const cards = ref([])
const summary = ref(null)
const hasMore = ref(false)
const loading = ref(false)
let requestId = 0

const dispensedPercent = computed(() => Math.round((summary.value.dispensed / summary.value.lines) * 100))
const summaryText = computed(() => {
  const counts = __("{0} of {1} lines")
    .replace("{0}", summary.value.dispensed)
    .replace("{1}", summary.value.lines)
  return summary.value.partial ? `${counts} · ${__("{0} partial").replace("{0}", summary.value.partial)}` : counts
})

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
    if (!start) summary.value = page.summary || null
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

function getLineTitle(line) {
  const directions = [line.dosage, line.period].filter(Boolean).join(" · ")
  const handed = __("{0}: {1} of {2}")
    .replace("{0}", __(line.status))
    .replace("{1}", line.dispensed_qty)
    .replace("{2}", line.prescribed_qty)
  return [line.medication || line.drug_name, directions, handed].filter(Boolean).join("\n")
}
</script>

<style scoped>
.previous-prescriptions {
  display: flex;
  gap: 6px;
  overflow-x: auto;
  margin-bottom: 12px;
  padding-bottom: 4px;
}

.previous-card {
  display: flex;
  flex: 0 0 180px;
  flex-direction: column;
  gap: 2px;
  min-width: 0;
  padding: 6px 8px;
  border: 1px solid var(--chart-border);
  border-radius: 8px;
  background: var(--chart-surface);
  color: var(--chart-text);
  font-size: 12px;
}

.previous-summary {
  flex-basis: 140px;
  justify-content: center;
  background: var(--chart-surface-muted);
}

.summary-percent {
  font-size: 20px;
  font-weight: 700;
  line-height: 1.1;
}

.summary-bar {
  height: 4px;
  margin: 2px 0;
  border-radius: 2px;
  background: var(--chart-border);
  overflow: hidden;
}

.summary-bar span {
  display: block;
  height: 100%;
  background: var(--chart-ok);
}

.previous-summary small,
.previous-practitioner {
  color: var(--chart-muted);
}

.previous-card-head {
  display: flex;
  align-items: center;
  gap: 6px;
}

.previous-date {
  font-weight: 600;
  white-space: nowrap;
}

.previous-practitioner {
  flex: 1;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.previous-repeat {
  padding: 2px 4px;
  border: 0;
  border-radius: 4px;
  background: transparent;
  color: var(--chart-text-soft);
  cursor: pointer;
}

.previous-repeat:hover:not(:disabled) {
  background: var(--chart-accent-soft);
  color: var(--chart-accent-text);
}

.previous-repeat:disabled {
  color: var(--chart-faint);
  cursor: default;
}

.previous-lines {
  display: flex;
  flex-direction: column;
  gap: 1px;
  margin: 0;
  padding: 0;
  list-style: none;
}

.previous-lines li {
  display: flex;
  align-items: center;
  gap: 6px;
  min-width: 0;
}

.previous-lines li[data-status="Dispensed"] i {
  color: var(--chart-ok-text);
}

.previous-lines li[data-status="Partially dispensed"] i {
  color: var(--chart-caution-text);
}

.previous-lines li[data-status="Not dispensed"] i {
  color: var(--chart-muted);
}

.previous-medication {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.previous-more {
  align-items: center;
  justify-content: center;
  border-style: dashed;
  color: var(--chart-text-soft);
  cursor: pointer;
}
</style>
