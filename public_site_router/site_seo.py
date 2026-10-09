# SPDX-License-Identifier: AGPL-3.0-or-later
"""Frappe side of per-host SEO (pure logic in ``seo``).

On a Public Site's hosts, ``/sitemap.xml`` and ``/robots.txt`` are that site's own (``router`` maps them
to the ``www/public_site_*`` pages), and every page gets a canonical link, ``og:url`` and ``og:site_name``
naming the site's canonical host, with absolute URLs Frappe built on the ERP's host moved onto it."""

import frappe
from frappe.utils import get_url

from public_site_router import seo
from public_site_router.router import get_request_site, normalize_host, page_site, site_home

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
	"""``(endpoint, modified)`` for everything ``site`` publishes: its pages and forms, its blog
	category's posts (and the listing at ``/``), and its store's Website Items."""
	routes = []
	for doctype in ROUTED_DOCTYPES:
		routes += published(doctype, {"route": ["like", f"{site.route_prefix}/%"]})
	if site.get("blog_category"):
		posts = published("Blog Post", {"blog_category": site.blog_category})
		routes += posts
		routes.append((site_home(site), max((modified for _, modified in posts), default=None)))
	if site.get("webshop_store") and frappe.db.table_exists("Website Item"):
		if frappe.get_meta("Website Item").has_field("webshop_store"):
			routes += published("Website Item", {"webshop_store": site.webshop_store})
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
	return seo.robots_txt(canonical_host(require_site()))


def update_website_context(context):
	"""update_website_context hook: canonical link, Open Graph URL tags and the site's favicon on its pages."""
	page = page_site(context)
	if not page:
		return
	site, endpoint = page
	host = canonical_host(site)
	erp_hosts = {normalize_host(get_url())}
	url = seo.page_url(host, seo.clean_path(endpoint, site.route_prefix, site_home(site)))
	head = seo.canonical_link(url)
	if site.get("favicon"):
		# base.html renders `favicon` as the tab icon; the same image is the home-screen icon.
		context.favicon = seo.site_asset_url(site.favicon, erp_hosts, host)
		head += seo.touch_icon_link(context.favicon)
	context.head_html = (context.get("head_html") or "") + head
	tags = context.get("metatags")
	if tags is None:
		return
	tags["og:url"] = url
	tags["og:site_name"] = site.site_name
	for key in IMAGE_TAGS:
		if tags.get(key):
			tags[key] = seo.rehost(tags[key], erp_hosts, host)
