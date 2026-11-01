from frappe.model.document import Document


class DermaStyleRule(Document):
	"""One doctor's writing preference. Learned as Suggested; only Active rules reach the note prompt."""
