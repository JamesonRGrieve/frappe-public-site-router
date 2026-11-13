# SPDX-License-Identifier: AGPL-3.0-or-later
"""A Public Site's Content-Security-Policy, from what the site itself loads (no Frappe import; unit-tested).

The base policy allows the site's own origin, the inline CSS and JS that Builder and the Web Page renderer emit
('unsafe-inline': every Builder block carries its own style and script), Google Fonts, and https images. It forbids
plugins, foreign <base> tags, form posts to other origins and framing by other sites. Each integration the site has
switched on adds exactly the origins it needs: Google Analytics (with the consent banner), Matomo, and Cloudflare
Turnstile. Anything else a site needs goes in its Extra CSP Sources, one ``<directive> <source> …`` per line.

A site starts in Report-only mode (``Content-Security-Policy-Report-Only``): browsers log what the policy would
block without blocking it. Once every page has been crawled with no violation, the site is switched to Enforce.
"""

import re

MODES = ("Report only", "Enforce")
HEADER = {"Report only": "Content-Security-Policy-Report-Only", "Enforce": "Content-Security-Policy"}

SELF = "'self'"
INLINE = "'unsafe-inline'"
NONE = "'none'"

GA4_SCRIPT = ("https://www.googletagmanager.com",)
GA4_CONNECT = (
	"https://*.google-analytics.com",
	"https://*.analytics.google.com",
	"https://*.googletagmanager.com",
)
TURNSTILE = ("https://challenges.cloudflare.com",)
FONTS_CSS = ("https://fonts.googleapis.com",)
FONTS = ("https://fonts.gstatic.com",)

# Directive order in the header (stable, so a cached page and a fresh one carry the same value).
ORDER = (
	"default-src",
	"script-src",
	"style-src",
	"font-src",
	"img-src",
	"media-src",
	"connect-src",
	"frame-src",
	"frame-ancestors",
	"object-src",
	"base-uri",
	"form-action",
)
# A source is a keyword in quotes, a scheme ("https:", "data:"), or an origin with an optional *. subdomain and port.
SOURCE = re.compile(
	r"^('[a-z0-9-]+'|[a-z][a-z0-9+.-]*:|https?://(\*\.)?[a-z0-9.-]+(:\d+)?(/[^\s;,']*)?)$", re.I
)


def valid_source(source: str) -> bool:
	return bool(SOURCE.match(source)) and ";" not in source


def parse_extra(text: str) -> dict[str, list[str]]:
	"""Extra CSP Sources: one ``<directive> <source> [<source> …]`` per line. Unknown directives and malformed
	sources raise ValueError, so a bad value is refused when the Public Site is saved, not served."""
	extra: dict[str, list[str]] = {}
	for raw in (text or "").splitlines():
		line = raw.strip()
		if not line or line.startswith("#"):
			continue
		directive, *sources = line.split()
		directive = directive.lower()
		if directive not in ORDER:
			raise ValueError(f"unknown CSP directive {directive!r}")
		if not sources:
			raise ValueError(f"{directive} needs at least one source")
		for source in sources:
			if not valid_source(source):
				raise ValueError(f"invalid CSP source {source!r} for {directive}")
		extra.setdefault(directive, []).extend(sources)
	return extra


def policy(*, ga4: bool = False, matomo_base: str = "", turnstile: bool = False, extra: str = "") -> str:
	"""The Content-Security-Policy value for a site with these integrations switched on."""
	d: dict[str, list[str]] = {
		"default-src": [SELF],
		"script-src": [SELF, INLINE],
		"style-src": [SELF, INLINE, *FONTS_CSS],
		"font-src": [SELF, "data:", *FONTS],
		"img-src": [SELF, "data:", "https:"],
		"media-src": [SELF],
		"connect-src": [SELF],
		"frame-src": [SELF],
		"frame-ancestors": [SELF],
		"object-src": [NONE],
		"base-uri": [SELF],
		"form-action": [SELF],
	}
	if ga4:
		d["script-src"] += GA4_SCRIPT
		d["connect-src"] += GA4_CONNECT
	if matomo_base:
		origin = matomo_base.rstrip("/")
		d["script-src"].append(origin)
		d["connect-src"].append(origin)
	if turnstile:
		d["script-src"] += TURNSTILE
		d["frame-src"] += TURNSTILE
	for directive, sources in parse_extra(extra).items():
		d[directive] += sources
	parts = []
	for directive in ORDER:
		seen: list[str] = []
		for source in d[directive]:
			if source not in seen:
				seen.append(source)
		parts.append(f"{directive} {' '.join(seen)}")
	return "; ".join(parts)


def header(mode: str, value: str) -> dict[str, str]:
	"""The response header for ``mode`` (empty when CSP is off)."""
	name = HEADER.get(mode or "")
	return {name: value} if name else {}
