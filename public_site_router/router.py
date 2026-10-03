# SPDX-License-Identifier: AGPL-3.0-or-later
"""Host-isolated public websites on one Frappe site.

Each ``Public Site`` owns a set of host names and a route prefix. On one of its hosts:

* ``/`` serves the page routed ``<prefix>/<home_route>``;
* ``/<path>`` serves the page routed ``<prefix>/<path>`` when one exists;
* any path whose first segment is a site prefix (its own or another's) is a 404, so a
  site's pages are reachable only through its own clean URLs;
* anything else (assets, API, login, webshop cart and product routes, global pages)
  passes through unchanged.

Hosts that belong to no Public Site (e.g. the ERP's own host) are not rewritten.

Rendered pages are cached by endpoint, and endpoints are host-specific here, so one
site's cached HTML is never served on another site's host."""

import frappe
from frappe.website.path_resolver import resolve_path as frappe_resolve_path

SITE_MAP_CACHE_KEY = "public_site_router_site_map"
OWN_RESOLVER = "public_site_router.router.resolve_path"
ROUTED_DOCTYPES = ("Web Page", "Web Form", "Builder Page")


def normalize_host(host):
	return (host or "").split(":", 1)[0].strip().lower().rstrip(".")


def get_site_map():
	"""{"hosts": {host: site}, "prefixes": {prefix: site}} for every enabled Public Site."""

	def build():
		# Installed but not yet migrated (hooks live, tables absent): route nothing rather
		# than fail every web request. Not cached, so the map appears once migrate runs.
		if not frappe.db.table_exists("Public Site"):
			return None
		enabled = frappe.get_all("Public Site", filters={"enabled": 1}, fields=["name", "route_prefix"])
		names = {s.name for s in enabled}
		domains = frappe.get_all(
			"Public Site Domain",
			filters={"parenttype": "Public Site", "parent": ["in", list(names) or [""]]},
			fields=["parent", "domain"],
		)
		return {
			"hosts": {normalize_host(d.domain): d.parent for d in domains},
			"prefixes": {s.route_prefix: s.name for s in enabled},
		}

	return frappe.cache.get_value(SITE_MAP_CACHE_KEY, build) or {"hosts": {}, "prefixes": {}}


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
	return False


def site_endpoint(site, path, prefixes):
	"""The route ``path`` maps to on ``site``'s hosts (None = pass through unchanged)."""
	if not path:
		return f"{site.route_prefix}/{site.home_route}"
	if path.split("/", 1)[0] in prefixes:
		raise frappe.PageDoesNotExistError
	candidate = f"{site.route_prefix}/{path}"
	return candidate if page_exists(candidate) else None


def resolve_path(path):
	"""website_path_resolver hook."""
	site = get_request_site()
	if site:
		path = site_endpoint(site, path, get_site_map()["prefixes"]) or path
	return resolve_with_other_resolvers(path)


def resolve_with_other_resolvers(path):
	"""Resolve ``path`` as the remaining chain would have (other apps' resolvers, else Frappe's)."""
	endpoint = None
	for handler in frappe.get_hooks("website_path_resolver"):
		if handler != OWN_RESOLVER:
			endpoint = frappe.get_attr(handler)(path)
	return endpoint if endpoint is not None else frappe_resolve_path(path)
