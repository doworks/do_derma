import frappe

TITLE = ("Skin & treatments", "البشرة والعلاجات")
QUESTIONS = (
	# (key, English, Arabic, ask, highlight when)
	("pregnant", "Are you pregnant or breastfeeding?", "هل أنتِ حامل أو مرضعة حالياً؟", "Women only", "Yes"),
	("isotretinoin", "Have you taken Roaccutane (isotretinoin) in the last 6 months?", "هل استخدمت روكتان (أيزوتريتينوين) خلال آخر 6 أشهر؟", "Everyone", "Yes"),
	("keloids", "Do you get keloid scars or slow wound healing?", "هل تُصاب بالجدرة أو بطء التئام الجروح؟", "Everyone", "Yes"),
	("photosensitive", "Is your skin sensitive to the sun, or have you had a lot of sun recently?", "هل بشرتك حساسة للشمس، أو تعرضت للشمس كثيراً مؤخراً؟", "Everyone", "Yes"),
	("cold_sores", "Do you get cold sores (herpes)?", "هل تُصاب بقروح البرد (الهربس)؟", "Everyone", "Yes"),
	("implants", "Do you have a pacemaker or metal implants?", "هل لديك جهاز منظّم لضربات القلب أو معادن مزروعة؟", "Everyone", "Yes"),
)


def execute():
	"""Starter questions for the patient health form; staff edit them in Do Health Settings."""
	if not frappe.get_meta("Do Health Settings").has_field("health_form_questions"):
		return
	if frappe.get_all("Patient Health Form Question", filters={"parenttype": "Do Health Settings"}, limit=1):
		return
	for idx, (key, english, arabic, applies_to, flag) in enumerate(QUESTIONS, start=1):
		frappe.get_doc(
			{
				"doctype": "Patient Health Form Question",
				"parent": "Do Health Settings",
				"parenttype": "Do Health Settings",
				"parentfield": "health_form_questions",
				"idx": idx,
				"enabled": 1,
				"question_key": key,
				"label_en": english,
				"label_ar": arabic,
				"answer_type": "Yes / No",
				"applies_to": applies_to,
				"flag_answer": flag,
			}
		).db_insert()
	if not frappe.db.get_single_value("Do Health Settings", "health_form_questions_title"):
		frappe.db.set_single_value("Do Health Settings", "health_form_questions_title", TITLE[0])
		frappe.db.set_single_value("Do Health Settings", "health_form_questions_title_ar", TITLE[1])
	frappe.clear_document_cache("Do Health Settings", "Do Health Settings")
