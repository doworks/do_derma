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
        type="button"
        class="ghost small"
        data-test="prescription-previous-repeat"
        :disabled="!canRepeat || card.lines.every((line) => prescribed.includes(line.medication))"
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
