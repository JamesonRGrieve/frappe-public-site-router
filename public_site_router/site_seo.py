# SPDX-License-Identifier: AGPL-3.0-or-later
"""Frappe side of per-host SEO (pure logic in ``seo``).

On a Public Site's hosts, ``/sitemap.xml``, ``/robots.txt``, ``/llms.txt`` and ``/BingSiteAuth.xml`` are
that site's own (``router`` maps them to the ``www/public_site_*`` pages), and every page gets a canonical
link, ``og:url`` and ``og:site_name`` naming the site's canonical host, with absolute URLs Frappe built on
the ERP's host moved onto it."""

import frappe
from frappe.utils import get_url

from public_site_router import chrome, seo
from public_site_router.router import (
	get_request_host,
	get_request_site,
	get_site_map,
	normalize_host,
	not_found_endpoint,
	page_site,
	site_home,
)

ROUTED_DOCTYPES = ("Web Page", "Builder Page", "Web Form")
IMAGE_TAGS = ("image", "og:image", "twitter:image")


def canonical_host(site):
	return seo.primary_domain([row.domain for row in sorted(site.domains, key=lambda row: row.idx)])


def published(doctype, filters):
	if not frappe.db.table_exists(doctype):
		return []
	return [
		(row.route, row.modified)
		for row in frappe.get_all(doctype, filters={"published": 1, **filters}, fields=["route", "modified"])
	]


def site_routes(site):
	"""``(endpoint, modified)`` for everything ``site`` publishes: its pages and forms (not its Not Found
	page), its blog category's posts (and the listing at ``/``), and its store's Website Items."""
	routes = []
	not_found = not_found_endpoint(site)
	for doctype in ROUTED_DOCTYPES:
		routes += [
			r for r in published(doctype, {"route": ["like", f"{site.route_prefix}/%"]}) if r[0] != not_found
		]
	if site.get("blog_category"):
		posts = published("Blog Post", {"blog_category": site.blog_category})
		routes += posts
		routes.append((site_home(site), max((modified for _, modified in posts), default=None)))
	if site.get("webshop_store") and frappe.db.table_exists("Website Item"):
		if frappe.get_meta("Website Item").has_field("webshop_store"):
			routes += published("Website Item", {"webshop_store": site.webshop_store})
	# Pages behind a dynamic-route Web Page, which only the app serving them can list: each
	# ``public_site_sitemap_routes`` hook takes the site and returns ``(endpoint, modified)`` pairs.
	for method in frappe.get_hooks("public_site_sitemap_routes"):
		routes += [
			(route, modified)
			for route, modified in frappe.get_attr(method)(site)
			if route.startswith(f"{site.route_prefix}/")
		]
	return routes


def require_site():
	site = get_request_site()
	if not site:
		raise frappe.PageDoesNotExistError
	return site


def sitemap_xml():
	site = require_site()
	entries = seo.sitemap_entries(canonical_host(site), site.route_prefix, site_home(site), site_routes(site))
	return seo.sitemap_xml(entries)


def robots_txt():
	site = require_site()
	return seo.robots_txt(canonical_host(site), signal=seo.content_signal(site.get("content_signal")) or "")


def llms_txt():
	"""The site's /llms.txt (llmstxt.org): its own text, or a 404 when it has none."""
	text = (require_site().get("llms_txt") or "").strip()
	if not text:
		raise frappe.PageDoesNotExistError
	return text + "\n"


def bing_site_auth_xml():
	"""The site's /BingSiteAuth.xml (Bing Webmaster Tools ownership), or a 404 when it has no code."""
	code = (require_site().get("bing_site_auth") or "").strip()
	if not seo.valid_bing_code(code):
		raise frappe.PageDoesNotExistError
	return seo.bing_site_auth_xml(code)


def update_website_context(context):
	"""update_website_context hook: canonical link, Open Graph URL tags and the site's favicon on its pages."""
	# A Builder Page's canonical_url arrives here as its raw field. On a normal page Builder renders it after this hook;
	# on a page served as a 404 (the site's Not Found page) it doesn't, and would print the template itself. Blank, it
	# prints no canonical, which is right for a 404.
	if context.get("canonical_url") in seo.BUILDER_CANONICAL_TEMPLATES:
		context.canonical_url = ""
	page = page_site(context)
	if not page:
		if chrome.BUILDER_HEAD_HTML in context and frappe.local.request:
			# Off a site host (e.g. a preview on the ERP's own host) the template names the page's own address.
			set_canonical_parts(context, get_request_host(), frappe.local.request.path or "/")
		return
	site, endpoint = page
	host = canonical_host(site)
	erp_hosts = {normalize_host(get_url())}
	url = seo.page_url(host, seo.clean_path(endpoint, site.route_prefix, site_home(site)))
	set_canonical_parts(context, *seo.url_host_and_path(url))
	# A Builder Page prints its own canonical link from canonical_url (BUILDER_CANONICAL_TEMPLATE, set on save), so a
	# second one here would give the page two.
	head = "" if chrome.BUILDER_HEAD_HTML in context else seo.canonical_link(url)
	if site.get("favicon"):
		# base.html renders `favicon` as the tab icon; the same image is the home-screen icon.
		context.favicon = seo.site_asset_url(site.favicon, erp_hosts, host)
		head += seo.touch_icon_link(context.favicon)
	chrome.add_head_html(context, head)
	tags = context.get("metatags")
	if tags is None:
		return
	tags["og:url"] = url
	tags["og:site_name"] = site.site_name
	for key in IMAGE_TAGS:
		if tags.get(key):
			tags[key] = seo.rehost(tags[key], erp_hosts, host)


def set_canonical_parts(context, host, path):
	"""The values ``seo.BUILDER_CANONICAL_TEMPLATE`` renders from."""
	context[seo.CANONICAL_HOST_KEY] = host
	context[seo.CANONICAL_PATH_KEY] = path


def set_builder_canonical(doc, method=None):
	"""Builder Page validate hook: a page under a site prefix with no canonical_url of its own gets the template that
	names its clean URL on the site's canonical host (``seo.BUILDER_CANONICAL_TEMPLATE``)."""
	url = seo.builder_canonical_url(doc.route, get_site_map()["prefixes"], doc.get("canonical_url"))
	if url:
		doc.canonical_url = url


def backfill_builder_canonicals():
	"""after_migrate hook: the template on every existing site Builder Page without a canonical_url, or with a legacy
	template (idempotent)."""
	if not frappe.db.table_exists("Builder Page"):
		return
	prefixes = get_site_map()["prefixes"]
	for row in frappe.get_all("Builder Page", fields=["name", "route", "canonical_url"]):
		url = seo.builder_canonical_url(row.route, prefixes, row.canonical_url)
		if url:
			frappe.db.set_value("Builder Page", row.name, "canonical_url", url, update_modified=False)
			frappe.clear_document_cache("Builder Page", row.name)
