# SPDX-License-Identifier: AGPL-3.0-or-later
"""Page chrome on Public Site hosts.

Each public site brings its own header, so Frappe's standard navbar is left out of its pages: it is hidden by every
site's CSS anyway, and in the HTML it still hands crawlers the ERP's own links (``/all-products``, ``/cart``,
``/login``), which are 404s on a site host. Pages on hosts outside a Public Site keep Frappe's chrome.

On a site with Standalone Pages, its Web Pages also leave out Frappe's website stylesheets and scripts (render-blocking
bundles the site's own design doesn't use), its standard footer and the ``<main>`` Frappe wraps page content in (the
site's content brings its own main landmark)."""

from public_site_router import chrome
from public_site_router.router import get_request_site

# Frappe's own base template, and the one used on Public Site hosts (extends it without the navbar).
FRAPPE_BASE = "templates/base.html"
PUBLIC_SITE_BASE = "public_site_router/templates/public_site_base.html"
# Frappe's Web Page template without its <main> wrapper and breadcrumbs, for standalone pages.
STANDALONE_WEB_PAGE = "public_site_router/templates/standalone_web_page.html"


def update_website_context(context):
	"""update_website_context hook: render site-host pages, including their Not Found page, on the base template
	without Frappe's navbar, and standalone pages without Frappe's website assets. A page that chose its own base
	template or page template keeps it."""
	site = get_request_site()
	if not site or context.get("base_template_path") not in (None, "", FRAPPE_BASE):
		return
	context.base_template_path = PUBLIC_SITE_BASE
	if chrome.is_standalone(site.get("standalone_pages"), context.get("doctype"), context.get("template")):
		context.standalone_page = True
		context.template = STANDALONE_WEB_PAGE
		if context.get("page_builder_html"):
			context.page_builder_html = chrome.wrap_main(context.page_builder_html)
		context.web_include_css = []
		context.web_include_js = []
		context.web_include_icons = []
