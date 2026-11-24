# SPDX-License-Identifier: AGPL-3.0-or-later
"""Frappe side of conversion reporting (pure logic in ``conversions``).

``lead_after_insert`` (CRM Lead ``after_insert``) hands a website lead to the visitor's browser: when a site's Web
Form submission creates a CRM Lead on a host of that site, and the site has a GA4 measurement ID, the response sets
the ``conversions.PENDING_COOKIE`` cookie, which the Google tag's script reports as ``generate_lead`` once."""

from datetime import UTC, datetime, timedelta

import frappe

from public_site_router import analytics, conversions
from public_site_router.router import get_request_site

LOG_TITLE = "public_site_router: generate_lead cookie"


def _https(request) -> bool:
	return request.scheme == "https" or request.headers.get("X-Forwarded-Proto", "").lower() == "https"


def lead_after_insert(doc, method=None):
	"""doc_events hook: set the pending-lead cookie for a website lead (nothing outside a browser's request). It never
	raises: any failure is logged and the lead is kept."""
	request = getattr(frappe.local, "request", None)
	if request is None:
		return
	try:
		web_form = frappe.form_dict.get("web_form") or ""
		if not conversions.counts_as_lead(
			public_site=doc.get("public_site"),
			source=doc.get("source"),
			web_form=web_form,
			email=doc.get("email"),
		):
			return
		site = get_request_site()
		if not site or site.name != doc.get("public_site"):
			return
		if not analytics.valid_ga4_id(site.get("ga4_measurement_id") or ""):
			return
		title = frappe.db.get_value("Web Form", web_form, "title") or web_form
		value = conversions.append(
			request.cookies.get(conversions.PENDING_COOKIE), conversions.lead_event(web_form, title)
		)
		frappe.local.cookie_manager.set_cookie(
			conversions.PENDING_COOKIE,
			value,
			expires=datetime.now(UTC) + timedelta(seconds=conversions.PENDING_SECONDS),
			secure=_https(request),
			httponly=False,
			samesite="Lax",
		)
	except Exception:
		# Never fail the lead: this runs inside the CRM Lead's insert, and an exception here would roll back the
		# visitor's real enquiry. A missed GA event is the lesser loss.
		frappe.log_error(title=LOG_TITLE)
