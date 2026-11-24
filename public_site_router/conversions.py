# SPDX-License-Identifier: AGPL-3.0-or-later
"""Conversions reported to Google Analytics 4: which CRM Leads count as a website lead, and the cookie that hands a
confirmed lead to the browser.

Pure functions with no Frappe import. The event names and the cookie's format are the same as OMG's
wp-conversion-tracking WordPress plugin, so one set of GA4 key events covers WordPress and Frappe sites.

A lead is counted on the server, where the CRM Lead was really created, never on a button click: a failed or refused
submission is not a conversion. The server can't send the event itself without a Measurement Protocol secret and the
visitor's GA client ID, so it hands the event to the browser in a short-lived cookie that the Google tag's script
(``analytics.ga4_snippet``) reports once and clears."""

import base64
import json

LEAD_EVENT = "generate_lead"
# Every event the Google tag's script reports; anything else in the cookie is dropped.
EVENTS = (LEAD_EVENT, "click_to_call", "click_email")
PENDING_COOKIE = "psr_pending"
PENDING_SECONDS = 600
# The newest few; a cookie can't grow without bound however many forms a visitor sends.
MAX_PENDING = 5
# CRM Lead.source of a Web Form submission (crm_multi_company sets it with public_site).
LEAD_SOURCE = "Website"
# Waitlist forms are sent server to server by the apps: no browser is there to report the event.
SERVER_FORM_PREFIX = "waitlist-"
# The site test suite's leads (zephyrex-site-test+<run>-<label>@example.com).
TEST_EMAIL_DOMAIN = "@example.com"


def counts_as_lead(
	*, public_site: str | None, source: str | None, web_form: str | None, email: str | None
) -> bool:
	"""Whether a new CRM Lead is a website lead to report: created by a site's Web Form from a browser, not a
	waitlist sign-up or a test lead."""
	web_form = (web_form or "").strip()
	return bool(
		public_site
		and source == LEAD_SOURCE
		and web_form
		and not web_form.startswith(SERVER_FORM_PREFIX)
		and not (email or "").strip().lower().endswith(TEST_EMAIL_DOMAIN)
	)


def lead_event(web_form: str, title: str = "") -> dict:
	"""The ``generate_lead`` event for a submission of ``web_form`` (params as the WordPress plugin sends them)."""
	return {"e": LEAD_EVENT, "p": {"form_id": web_form, "form_name": title or web_form}}


def encode(events: list[dict]) -> str:
	"""``events`` as the cookie value: base64url (no padding) of a JSON list."""
	raw = json.dumps(events, ensure_ascii=False, separators=(",", ":")).encode()
	return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def decode(value: str | None) -> list[dict]:
	"""The valid events in a cookie value (the newest ``MAX_PENDING``); anything malformed is dropped."""
	if not value:
		return []
	try:
		raw = base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))
		items = json.loads(raw)
	except ValueError, TypeError:
		return []
	if not isinstance(items, list):
		return []
	events = []
	for item in items:
		if not isinstance(item, dict) or item.get("e") not in EVENTS:
			continue
		params = item.get("p") if isinstance(item.get("p"), dict) else {}
		clean = {
			k: v for k, v in params.items() if isinstance(k, str) and isinstance(v, str | int | float | bool)
		}
		events.append({"e": item["e"], "p": clean})
	return events[-MAX_PENDING:]


def append(existing: str | None, event: dict) -> str:
	"""The cookie value with ``event`` added after any events still waiting in ``existing``."""
	return encode([*decode(existing), event][-MAX_PENDING:])
