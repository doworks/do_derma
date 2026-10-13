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
