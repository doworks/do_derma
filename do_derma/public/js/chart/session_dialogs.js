const __ = window.__ || ((text) => text)

export const NEW_VISIT = "new"

function askInDialog(build) {
  return new Promise((resolve) => {
    let answer = null
    const dialog = build((value) => {
      answer = value
      dialog.hide()
    })
    dialog.onhide = () => resolve(answer)
    dialog.show()
  })
}

export function confirmOtherDate(date) {
  return new Promise((resolve) => {
    const shown = window.frappe.datetime.str_to_user(date)
    window.frappe.confirm(
      __("This visit is dated {0}, not today. Start it anyway?", [shown]),
      () => resolve(true),
      () => resolve(false)
    )
  })
}

export function pickTodaysVisit(visits) {
  const describe = (visit) =>
    [String(visit.appointment_time || "").slice(0, 5), visit.practitioner_name, visit.appointment_type]
      .filter(Boolean)
      .join(" · ")
  return askInDialog(
    (answer) =>
      new window.frappe.ui.Dialog({
        title: __("Which visit is this?"),
        fields: [
          {
            fieldname: "visit",
            fieldtype: "Select",
            label: __("Today's visits"),
            reqd: 1,
            options: [
              ...visits.map((visit) => ({ value: visit.name, label: describe(visit) })),
              { value: NEW_VISIT, label: __("New visit") },
            ],
            default: visits[0].name,
          },
        ],
        primary_action_label: __("Start Session"),
        primary_action: (values) => answer(values.visit),
      })
  )
}

export function promptNewVisit(defaults = {}) {
  return askInDialog(
    (answer) =>
      new window.frappe.ui.Dialog({
        title: __("Start Session"),
        fields: [
          {
            fieldname: "practitioner",
            fieldtype: "Link",
            options: "Healthcare Practitioner",
            label: __("Doctor"),
            reqd: 1,
            default: defaults.practitioner || "",
          },
          {
            fieldname: "appointment_type",
            fieldtype: "Link",
            options: "Appointment Type",
            label: __("Appointment Type"),
            reqd: 1,
            default: defaults.appointment_type || "",
            get_query: () => ({ filters: { allow_booking_for: "Practitioner" } }),
          },
          {
            fieldname: "appointment_category",
            fieldtype: "Select",
            label: __("Appointment Category"),
            options: ["First Time", "Follow-up"].join("\n"),
            default: "First Time",
          },
        ],
        primary_action_label: __("Start Session"),
        primary_action: (values) => answer(values),
      })
  )
}
