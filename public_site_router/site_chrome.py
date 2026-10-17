# SPDX-License-Identifier: AGPL-3.0-or-later
"""Page chrome on Public Site hosts.

Each public site brings its own header, so Frappe's standard navbar is left out of its pages: it is hidden by every
site's CSS anyway, and in the HTML it still hands crawlers the ERP's own links (``/all-products``, ``/cart``,
``/login``), which are 404s on a site host. Pages on hosts outside a Public Site keep Frappe's chrome."""

from public_site_router.router import get_request_site

# Frappe's own base template, and the one used on Public Site hosts (extends it without the navbar).
FRAPPE_BASE = "templates/base.html"
PUBLIC_SITE_BASE = "public_site_router/templates/public_site_base.html"


def update_website_context(context):
	"""update_website_context hook: render site-host pages, including their Not Found page, on the base template
	without Frappe's navbar. A page that chose its own base template keeps it."""
	if get_request_site() and context.get("base_template_path") in (None, "", FRAPPE_BASE):
		context.base_template_path = PUBLIC_SITE_BASE
