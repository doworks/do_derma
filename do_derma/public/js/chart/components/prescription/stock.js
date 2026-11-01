const __ = window.__ || ((text) => text)

/** "12 Nos", "0 in stock", or "—" when no prescription warehouse is set. */
export function getStockLabel(item) {
  if (item.actual_qty == null) return "—"
  if (item.actual_qty === 0) return __("0 in stock")
  return `${item.actual_qty} ${item.stock_uom || ""}`.trim()
}
