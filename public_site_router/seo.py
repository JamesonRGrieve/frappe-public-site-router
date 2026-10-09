# SPDX-License-Identifier: AGPL-3.0-or-later
"""Per-host SEO for Public Sites: canonical URLs, the sitemap and robots.txt.

Pure functions with no Frappe import, so they are unit-tested without a bench. ``site_seo`` feeds them
from the database and the request.

A site's canonical host is its first domain that is not a ``www.`` alias. Every URL a site publishes
(canonical link, ``og:url``, sitemap, robots.txt) names that host, so apex and www serve identical HTML
and Frappe's per-endpoint page cache stays correct for both.
"""

from dataclasses import dataclass
from datetime import date, datetime
from html import escape
from urllib.parse import quote, urlsplit, urlunsplit
from xml.sax.saxutils import escape as xml_escape

SCHEME = "https"
WWW = "www."
SITEMAP_PATH = "sitemap.xml"
SITEMAP_NAMESPACE = "http://www.sitemaps.org/schemas/sitemap/0.9"
URL_PATH_SAFE = "/-._~"
# Paths crawlers have no use for on a public site: the desk, the API and per-visitor account pages.
ROBOTS_DISALLOW = (
	"/app",
	"/api/",
	"/login",
	"/update-password",
	"/cart",
	"/me",
	"/orders",
	"/quotations",
	"/invoices",
	"/addresses",
)


def primary_domain(domains: list[str]) -> str:
	"""The host a site's canonical URLs name: its first domain that is not a www alias."""
	if not domains:
		raise ValueError("a Public Site has at least one domain")
	for domain in domains:
		if not domain.startswith(WWW):
			return domain
	return domains[0][len(WWW) :]


def is_dynamic_route(route: str) -> bool:
	"""A route with parameters (``/project/<name>``, ``/blog/:name``) names no single page."""
	return "<" in route or any(part.startswith(":") for part in route.split("/"))


def clean_path(endpoint: str, route_prefix: str, home_endpoint: str) -> str:
	"""The path ``endpoint`` is served at on its site's hosts ("" for the home page)."""
	endpoint = endpoint.strip("/")
	if endpoint == home_endpoint.strip("/"):
		return ""
	prefix = f"{route_prefix}/"
	return endpoint[len(prefix) :] if endpoint.startswith(prefix) else endpoint


def page_url(host: str, path: str) -> str:
	return f"{SCHEME}://{host}/{quote(path.strip('/'), safe=URL_PATH_SAFE)}"


@dataclass(frozen=True)
class SitemapEntry:
	loc: str
	lastmod: date | None


def _day(modified: date | datetime | None) -> date | None:
	return modified.date() if isinstance(modified, datetime) else modified


def sitemap_entries(
	host: str, route_prefix: str, home_endpoint: str, routes: list[tuple[str, date | datetime | None]]
) -> list[SitemapEntry]:
	"""One entry per URL a site publishes, from ``(endpoint, modified)`` pairs: the home page first,
	then by URL; a URL listed twice keeps its newest date. Dynamic routes are left out."""
	newest: dict[str, date | None] = {}
	for route, modified in routes:
		if not route or is_dynamic_route(route):
			continue
		loc = page_url(host, clean_path(route, route_prefix, home_endpoint))
		day = _day(modified)
		if loc not in newest or (day is not None and (newest[loc] is None or day > newest[loc])):
			newest[loc] = day
	home = page_url(host, "")
	return sorted(
		(SitemapEntry(loc, day) for loc, day in newest.items()), key=lambda e: (e.loc != home, e.loc)
	)


def sitemap_xml(entries: list[SitemapEntry]) -> str:
	urls = "".join(
		f"\n\t<url><loc>{xml_escape(e.loc)}</loc>"
		+ (f"<lastmod>{e.lastmod.isoformat()}</lastmod>" if e.lastmod else "")
		+ "</url>"
		for e in entries
	)
	return f'<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="{SITEMAP_NAMESPACE}">{urls}\n</urlset>\n'


def robots_txt(host: str, disallow: tuple[str, ...] = ROBOTS_DISALLOW) -> str:
	rules = "".join(f"Disallow: {path}\n" for path in disallow)
	return f"User-agent: *\n{rules}\nSitemap: {page_url(host, SITEMAP_PATH)}\n"


def canonical_link(url: str) -> str:
	return f'<link rel="canonical" href="{escape(url, quote=True)}">'


def rehost(url: str, from_hosts: set[str], host: str) -> str:
	"""``url`` moved onto ``host`` when it is an absolute URL on one of ``from_hosts`` (e.g. the ERP's
	own host, which Frappe uses for every absolute URL it builds); anything else unchanged."""
	parts = urlsplit(url)
	if parts.netloc and parts.netloc.lower() in from_hosts:
		return urlunsplit(parts._replace(scheme=SCHEME, netloc=host))
	return url


def site_asset_url(url: str, from_hosts: set[str], host: str) -> str:
	"""A file URL as the site's canonical host serves it: a site-relative path (``/files/x.png``) gains
	the host, an ERP-host URL moves onto it, and any other absolute URL is kept."""
	if url.startswith("/") and not url.startswith("//"):
		return f"{SCHEME}://{host}{url}"
	return rehost(url, from_hosts, host)


def touch_icon_link(url: str) -> str:
	return f'<link rel="apple-touch-icon" href="{escape(url, quote=True)}">'
