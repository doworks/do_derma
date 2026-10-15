from __future__ import annotations

from do_derma.patches.helpers import sync_sidebar_items


def execute():
	"""Give the configuration workspace its only entry point in the app (do_derma.sidebar)."""
	sync_sidebar_items()
