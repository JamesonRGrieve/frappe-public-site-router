# SPDX-License-Identifier: AGPL-3.0-or-later
"""Frappe side of Public Site form spam protection (pure logic in ``forms``).

``update_website_context`` adds Cloudflare Turnstile to every page of a site with a Turnstile site key.
``accept`` replaces Frappe's Web Form submission endpoint (``override_whitelisted_methods``): on a host whose
Public Site has a Turnstile secret key, a submission is accepted only with a token Cloudflare verifies for one of
that site's hosts. Everywhere else it is Frappe's own ``accept``, unchanged."""

import frappe
import requests
from frappe import _
from frappe.website.doctype.web_form.web_form import accept as frappe_accept

from public_site_router import chrome, forms
from public_site_router.router import get_request_site, page_site_or_not_found

VERIFY_TIMEOUT_SECONDS = 10


def update_website_context(context):
	"""update_website_context hook: the Turnstile script and widget loader on a protected site's pages, its Not Found
	page included (the Contact popover in its footer was refused with 403 for want of a token, 2026-11-13)."""
	page = page_site_or_not_found(context)
	if not page:
		return
	site, _endpoint = page
	chrome.add_head_html(context, forms.head_html(site.get("turnstile_site_key") or ""))


def _secret(site) -> str:
	if not site.get("turnstile_site_key"):
		return ""
	return site.get_password("turnstile_secret_key", raise_exception=False) or ""


def check_submission(site, form_dict) -> None:
	"""Raise unless the submission carries a Turnstile token Cloudflare verifies for this site (no-op for a site
	without a secret key)."""
	secret = _secret(site)
	if not secret:
		return
	token = forms.token_from(form_dict)
	if not token:
		frappe.throw(_("Please complete the human check and send the form again."), frappe.PermissionError)
	try:
		resp = requests.post(
			forms.VERIFY_URL,
			data=forms.verify_payload(secret, token, frappe.local.request_ip),
			timeout=VERIFY_TIMEOUT_SECONDS,
		)
		result = resp.json()
	except requests.RequestException, ValueError:
		frappe.log_error(title="Public Site Turnstile verification failed")
		frappe.throw(_("The human check could not be verified. Please try again."), frappe.ValidationError)
	hosts = {row.domain for row in site.domains}
	if not forms.verified(result, hosts):
		frappe.throw(_("The human check failed. Please try again."), frappe.PermissionError)


@frappe.whitelist(allow_guest=True)
def accept(web_form, data, *args, **kwargs):
	"""Frappe's Web Form ``accept``, after the Turnstile check on a protected Public Site's hosts.

	Frappe calls a whitelisted method with the whole ``form_dict`` (``cmd``, the Turnstile token field, …), so this
	override takes extra arguments, but Frappe's own ``accept(web_form, data)`` takes none: only those two are passed
	on (forwarding the rest made every guest submission fail with ``TypeError: … unexpected keyword argument 'cmd'``)."""
	site = get_request_site()
	if site:
		check_submission(site, frappe.form_dict)
	return frappe_accept(web_form, data)
