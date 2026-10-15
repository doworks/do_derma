from __future__ import annotations


def get_sidebar_items() -> list[dict]:
	"""do_derma's standard items in do_health's sidebar (the do_health_sidebar_items hook)."""
	return [
		{
			"key": "derma_chart",
			"section": "Patient Actions",
			"label": "Derma Chart",
			"display_group": "Clinical",
			"description": "Open the dermatology encounter chart with structured body map findings and treatments.",
			"icon": "fa-regular fa-person-dots-from-line",
			"item_behavior": "Route",
			"route_type": "Custom",
			"route_value": "do_derma.openChart",
			"context_requirement": "patient",
			"missing_context_message": "Select a patient first.",
			"requires_app": "do_derma",
			"sequence": 36,
			"is_footer_action": 1,
		},
		{
			"key": "derma_config",
			"section": "Primary Nav",
			"label": "Derma Configuration",
			"display_group": "Clinical",
			"description": "Body maps, procedure templates, categories and how sessions are gated.",
			"icon": "fa-regular fa-sliders",
			"item_behavior": "Route",
			"route_type": "Page",
			"route_value": "derma-config",
			"context_requirement": "none",
			"requires_app": "do_derma",
			"sequence": 7,
		},
	]
