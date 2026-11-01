<template>
  <DermaChart :context="context" />
</template>

<script setup>
import { onBeforeUnmount, onMounted, ref } from "vue"
import DermaChart from "./DermaChart.vue"

const context = ref({})
let unsubscribe = null

function updateContext(source = {}) {
  const route = window.frappe?.route_options
  const sidebar = source?.patient ? source : window.doHealthSidebar?.getSelectedPatient?.() || window.do_health?.patientWatcher?.read?.() || {}
  // A route and the sidebar each name one whole visit: fields from both would mix two patients.
  const next = route?.patient && !isOtherVisit(sidebar, route) ? route : sidebar
  if (route?.patient && next === sidebar) window.frappe.route_options = null
  context.value = {
    patient: next.patient,
    appointment: next.appointment,
    encounter: next.encounter_name || next.encounter,
  }
}

function isOtherVisit(sidebar, route) {
  if (!sidebar.patient || !context.value.patient) return false
  return sidebar.patient !== route.patient || Boolean(route.appointment && sidebar.appointment !== route.appointment)
}

onMounted(() => {
  if (window.do_health?.patientWatcher) {
    unsubscribe = window.do_health.patientWatcher.subscribe(updateContext)
  }
  updateContext()
})

onBeforeUnmount(() => {
  if (unsubscribe) unsubscribe()
})
</script>
