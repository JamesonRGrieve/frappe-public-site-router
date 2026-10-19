# SPDX-License-Identifier: AGPL-3.0-or-later
"""Per-host SEO for Public Sites: canonical URLs, the sitemap and robots.txt.

Pure functions with no Frappe import, so they are unit-tested without a bench. ``site_seo`` feeds them
from the database and the request.

A site's canonical host is its first domain that is not a ``www.`` alias. Every URL a site publishes
(canonical link, ``og:url``, sitemap, robots.txt) names that host, so apex and www serve identical HTML
and Frappe's per-endpoint page cache stays correct for both.
"""

import re
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
# contentsignals.org: how crawlers may use a site's content once fetched.
CONTENT_SIGNALS = ("search", "ai-input", "ai-train")
CONTENT_SIGNAL_PREAMBLE = (
	"# Content signals (https://contentsignals.org): search = building a search index and showing links\n"
	"# and short excerpts; ai-input = using content as input to AI answers; ai-train = training or\n"
	"# fine-tuning AI models.\n"
)
BING_CODE = re.compile(r"^[A-Za-z0-9]{8,64}$")
# Response headers every page of a site with Security Headers carries (OWASP Secure Headers). HSTS is one year
# without includeSubDomains or preload (operator, 2026-10-19), so it can be lowered and browsers forget it in a year.
SECURITY_HEADERS = {
	"Strict-Transport-Security": "max-age=31536000",
	"X-Content-Type-Options": "nosniff",
	"X-Frame-Options": "SAMEORIGIN",
	"Referrer-Policy": "strict-origin-when-cross-origin",
}


def missing_security_headers(present: set[str]) -> dict[str, str]:
	"""The security headers a response lacks (``present``: its header names, any case); one it already sets wins."""
	have = {name.lower() for name in present}
	return {name: value for name, value in SECURITY_HEADERS.items() if name.lower() not in have}


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


def content_signal(value: str | None) -> str | None:
	"""``value`` as a normalised Content-Signal line value (``search=yes, ai-input=yes, ai-train=no``), "" for
	none, or None when it is not one: each part a known signal set to yes or no, each signal at most once."""
	parts = [p.strip().lower() for p in (value or "").split(",") if p.strip()]
	seen = {}
	for part in parts:
		name, _, answer = (s.strip() for s in part.partition("="))
		if name not in CONTENT_SIGNALS or answer not in ("yes", "no") or name in seen:
			return None
		seen[name] = answer
	return ", ".join(f"{name}={answer}" for name, answer in seen.items())


def robots_txt(host: str, disallow: tuple[str, ...] = ROBOTS_DISALLOW, signal: str = "") -> str:
	"""The site's robots.txt; with ``signal`` (a valid Content-Signal value), the contentsignals.org line that
	tells crawlers how the content may be used (search, AI answers, AI training)."""
	rules = "".join(f"Disallow: {path}\n" for path in disallow)
	preamble, signal_line = "", ""
	if signal:
		preamble = CONTENT_SIGNAL_PREAMBLE
		signal_line = f"Content-Signal: {signal}\n"
	return f"{preamble}User-agent: *\n{signal_line}{rules}\nSitemap: {page_url(host, SITEMAP_PATH)}\n"


def valid_bing_code(code: str | None) -> bool:
	return bool(BING_CODE.match(code or ""))


def bing_site_auth_xml(code: str) -> str:
	"""Bing Webmaster Tools' ownership file (``/BingSiteAuth.xml``) for verification ``code``."""
	if not valid_bing_code(code):
		raise ValueError(f"not a Bing verification code: {code!r}")
	return f'<?xml version="1.0"?>\n<users>\n\t<user>{code}</user>\n</users>\n'


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
