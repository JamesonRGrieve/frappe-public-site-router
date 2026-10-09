# SPDX-License-Identifier: AGPL-3.0-or-later
"""Host-isolated public websites on one Frappe site.

Each ``Public Site`` owns a set of host names and a route prefix. On one of its hosts:

* ``/`` serves the page routed ``<prefix>/<home_route>``;
* ``/<path>`` serves the page routed ``<prefix>/<path>`` when one exists (a Web Page or
  Builder Page, or a Web Form and its sub-pages), and a redirect to ``/<prefix>/<path>``
  is sent to ``/<path>`` instead;
* any path whose first segment is a site prefix (its own or another's) is a 404, so a
  site's pages are reachable only through its own clean URLs;
* a few technical pages (404/error/message, robots.txt, website_script.js) pass through
  everywhere; account, portal and webshop routes (login, cart, listing, product and item-group
  pages) pass through only on a site with a Webshop Store;
* on a site with a Blog Category, ``/`` serves that category's post listing and ``/<path>``
  serves a published Blog Post (blog app) of that category routed ``<path>``. Posts keep root
  routes, so the blog app's own links to them are already the clean URLs;
* anything else (ERPNext's generic about/contact pages, desk, the global sitemap, other
  pages) is a 404, so a site shows nothing it did not publish.

Hosts of a disabled Public Site serve nothing (every website route is a 404). Static files and
the API are not website routes and are never affected. Hosts that belong to no Public Site
(e.g. the ERP's own host) are not rewritten.

Rendered pages are cached by endpoint, and endpoints are host-specific here, so one
site's cached HTML is never served on another site's host."""

from urllib.parse import urlsplit, urlunsplit

import frappe
from frappe.website.path_resolver import resolve_path as frappe_resolve_path

SITE_MAP_CACHE_KEY = "public_site_router_site_map"
OWN_RESOLVER = "public_site_router.router.resolve_path"
ROUTED_DOCTYPES = ("Web Page", "Builder Page")
# Website routes every Public Site host serves besides its own pages.
TECHNICAL_ROUTES = frozenset({"404", "error", "message", "robots.txt", "website_script.js"})
# Website routes served only on a site with a Webshop Store: customer account + portal pages
# and the webshop's own pages (first path segment). Item/Item Group pages are matched by route.
STORE_ACCOUNT_ROUTES = frozenset(
	{
		"login",
		"logout",
		"update-password",
		"complete_signup",
		"me",
		"orders",
		"quotations",
		"invoices",
		"addresses",
	}
)
STORE_PAGE_SEGMENTS = frozenset(
	{"cart", "all-products", "shop-by-category", "product_search", "order", "wishlist", "customer_reviews"}
)
STORE_GENERATOR_DOCTYPES = ("Website Item", "Item Group")


def normalize_host(host):
	return (host or "").split(":", 1)[0].strip().lower().rstrip(".")


def get_site_map():
	"""{"hosts": {host: site}, "prefixes": {prefix: site}} for every enabled Public Site, plus
	"closed_hosts": {host: site} for disabled ones (a site not yet launched, or taken down)."""

	def build():
		# Installed but not yet migrated (hooks live, tables absent): route nothing rather
		# than fail every web request. Not cached, so the map appears once migrate runs.
		if not frappe.db.table_exists("Public Site"):
			return None
		sites = frappe.get_all("Public Site", fields=["name", "route_prefix", "enabled"])
		enabled = {s.name for s in sites if s.enabled}
		domains = frappe.get_all(
			"Public Site Domain", filters={"parenttype": "Public Site"}, fields=["parent", "domain"]
		)
		return {
			"hosts": {normalize_host(d.domain): d.parent for d in domains if d.parent in enabled},
			"closed_hosts": {normalize_host(d.domain): d.parent for d in domains if d.parent not in enabled},
			"prefixes": {s.route_prefix: s.name for s in sites if s.enabled},
		}

	return frappe.cache.get_value(SITE_MAP_CACHE_KEY, build) or {
		"hosts": {},
		"closed_hosts": {},
		"prefixes": {},
	}


def clear_site_map():
	frappe.cache.delete_value(SITE_MAP_CACHE_KEY)


def get_request_host():
	request = getattr(frappe.local, "request", None)
	return normalize_host(request.host) if request else ""


def get_request_site():
	"""The Public Site serving this request, or None."""
	host = get_request_host()
	site = get_site_map()["hosts"].get(host) if host else None
	return frappe.get_cached_doc("Public Site", site) if site else None


def get_request_store():
	"""webshop_store_resolver hook (frappe-webshop fork): this request's Webshop Store."""
	site = get_request_site()
	return site.webshop_store if site and site.webshop_store else None


def page_exists(route):
	for doctype in ROUTED_DOCTYPES:
		if frappe.db.table_exists(doctype) and frappe.db.exists(doctype, {"route": route, "published": 1}):
			return True
	return is_web_form_route(route)


def is_web_form_route(route):
	"""A published Web Form's own route or one of its sub-pages (new, list, <name>, <name>/edit)."""
	return any(
		route == form_route or route.startswith(f"{form_route}/")
		for form_route in frappe.get_all("Web Form", filters={"published": 1}, pluck="route")
	)


def is_store_generator_route(route):
	"""A published Website Item or Item Group page (the webshop's product and category pages)."""
	return any(
		frappe.db.table_exists(doctype) and frappe.db.exists(doctype, {"route": route, "published": 1})
		for doctype in STORE_GENERATOR_DOCTYPES
	)


def is_site_blog_post(site, route):
	"""A published Blog Post (blog app) in ``site``'s Blog Category, routed ``route``."""
	return bool(
		site.blog_category
		and frappe.db.table_exists("Blog Post")
		and frappe.db.exists(
			"Blog Post", {"route": route, "published": 1, "blog_category": site.blog_category}
		)
	)


def site_home(site):
	"""The route ``/`` maps to: a blog site's category listing, else its home page."""
	if site.blog_category:
		return frappe.db.get_value("Blog Category", site.blog_category, "route")
	return f"{site.route_prefix}/{site.home_route}"


def is_shared_route(site, path):
	"""Whether ``path`` (not one of ``site``'s own pages) may be served on ``site``'s hosts."""
	if path in TECHNICAL_ROUTES:
		return True
	if not site.webshop_store:
		return False
	return (
		path in STORE_ACCOUNT_ROUTES
		or path.split("/", 1)[0] in STORE_PAGE_SEGMENTS
		or is_store_generator_route(path)
	)


def site_endpoint(site, path, prefixes):
	"""The route ``path`` maps to on ``site``'s hosts (None = pass through unchanged)."""
	if not path:
		return site_home(site)
	if path.split("/", 1)[0] in prefixes:
		raise frappe.PageDoesNotExistError
	candidate = f"{site.route_prefix}/{path}"
	if page_exists(candidate):
		return candidate
	if is_site_blog_post(site, path) or is_shared_route(site, path):
		return None
	raise frappe.PageDoesNotExistError


def resolve_path(path):
	"""website_path_resolver hook. A disabled site's hosts serve nothing (404), so a domain can go
	live in DNS before its site launches without exposing the ERP's own website on it."""
	site = get_request_site()
	if site:
		path = site_endpoint(site, path, get_site_map()["prefixes"]) or path
	elif get_request_host() in get_site_map().get("closed_hosts", {}):
		raise frappe.PageDoesNotExistError
	return resolve_with_other_resolvers(path)


def clean_location(site, location):
	"""``location`` with ``site``'s own route prefix removed, so it names the clean URL."""
	url = urlsplit(location)
	if url.netloc and normalize_host(url.netloc) != get_request_host():
		return location
	prefix = f"/{site.route_prefix}"
	if url.path == f"{prefix}/{site.home_route}":
		path = "/"
	elif url.path == prefix or url.path.startswith(f"{prefix}/"):
		path = url.path[len(prefix) :] or "/"
	else:
		return location
	return urlunsplit(url._replace(path=path))


def clean_redirect(response, request):
	"""after_request hook: pages that redirect to their own route (a Web Form sends ``/<route>``
	to ``/<route>/new``) name the prefixed endpoint, which is a 404 on the site's hosts."""
	location = response.headers.get("Location")
	if not location or not 300 <= response.status_code < 400:
		return
	site = get_request_site()
	if site:
		response.headers["Location"] = clean_location(site, location)


def resolve_with_other_resolvers(path):
	"""Resolve ``path`` as the remaining chain would have (other apps' resolvers, else Frappe's)."""
	endpoint = None
	for handler in frappe.get_hooks("website_path_resolver"):
		if handler != OWN_RESOLVER:
			endpoint = frappe.get_attr(handler)(path)
	return endpoint if endpoint is not None else frappe_resolve_path(path)
