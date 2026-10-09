# SPDX-License-Identifier: AGPL-3.0-or-later
"""Frappe side of per-site analytics (pure logic in ``analytics``).

``update_website_context`` adds each Public Site's configured providers to its pages. ``log_view`` is the
Frappe view-tracking endpoint for public site hosts: it records a Web Page View stamped with the site, which
Frappe's own ``make_view_log`` cannot do (it only accepts views on the ERP's host)."""

import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields
from frappe.rate_limiter import rate_limit

from public_site_router import analytics
from public_site_router.router import get_request_site, page_site

LOG_ENDPOINT = "/api/method/public_site_router.site_analytics.log_view"
# One beacon per page load; generous for a person, tight for a script.
VIEWS_PER_MINUTE = 60
SECONDS_PER_MINUTE = 60
WEB_PAGE_VIEW_FIELDS = {
	"Web Page View": [
		{
			"fieldname": "public_site",
			"label": "Public Site",
			"fieldtype": "Link",
			"options": "Public Site",
			"insert_after": "path",
			"read_only": 1,
			"in_standard_filter": 1,
		}
	]
}


def ensure_custom_fields():
	"""after_migrate hook: Web Page View's ``public_site`` field (idempotent)."""
	create_custom_fields(WEB_PAGE_VIEW_FIELDS, update=True)


def update_website_context(context):
	"""update_website_context hook: the request's site's analytics snippets on its pages."""
	page = page_site(context)
	if not page:
		return
	site, _endpoint = page
	snippets = analytics.head_snippets(
		view_tracking=bool(site.get("view_tracking")),
		ga4_measurement_id=site.get("ga4_measurement_id") or "",
		matomo_url=site.get("matomo_url") or "",
		matomo_site_id=site.get("matomo_site_id") or "",
		log_endpoint=LOG_ENDPOINT,
	)
	if snippets:
		context.head_html = (context.get("head_html") or "") + snippets


@frappe.whitelist(allow_guest=True, methods=["POST"])
@rate_limit(limit=VIEWS_PER_MINUTE, seconds=SECONDS_PER_MINUTE)
def log_view(referrer=None, user_tz=None, source=None, medium=None, campaign=None, content=None):
	"""Record one page view on a public site's host (the tracker's beacon); anything else is ignored."""
	site = get_request_site()
	if not site or not site.get("view_tracking"):
		return
	hosts = {row.domain for row in site.domains}
	path = analytics.view_path(frappe.request.headers.get("Referer"), hosts)
	if path is None:
		return
	view = frappe.new_doc("Web Page View")
	view.update(
		{
			"path": path,
			"public_site": site.name,
			"referrer": analytics.clean_referrer(referrer),
			"time_zone": user_tz,
			"user_agent": frappe.request.headers.get("User-Agent"),
			"source": source,
			"medium": (medium or "").lower(),
			"campaign": campaign,
			"content": content,
		}
	)
	view.deferred_insert()
