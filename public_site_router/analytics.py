# SPDX-License-Identifier: AGPL-3.0-or-later
"""Per-site analytics providers for Public Sites: Frappe view tracking, Google Analytics 4, Matomo.

Pure functions with no Frappe import. Each provider is configured per Public Site and adds its snippet
to every page of that site; values are validated before they reach a snippet, and strings are embedded
with json.dumps, so a snippet never carries markup from a field.

Frappe's own view logging only accepts views whose Referer is on the ERP's host (``is_site_link``), so it
drops every view on a public site's domain and records no host. The router's tracker posts to its own
endpoint instead, which stamps each view with its site."""

import json
import re
from urllib.parse import urlsplit

GA4_ID = re.compile(r"^G-[A-Z0-9]{4,20}$")
MATOMO_SITE_ID = re.compile(r"^[0-9]{1,9}$")
# Paths that are never page views: the API, the desk and files.
UNTRACKED_PATHS = frozenset({"app", "api"})
UNTRACKED_PREFIXES = ("api/", "app/", "assets/", "files/", "private/")
# Web Page View stores the referrer in a Data field.
REFERRER_MAX = 140
UTM_FIELDS = ("source", "medium", "campaign", "content")


def valid_ga4_id(value: str) -> bool:
	return bool(GA4_ID.match(value or ""))


def matomo_base(url: str) -> str | None:
	"""``url`` as a Matomo base URL ending in ``/``, or None if it is not a plain https URL."""
	parts = urlsplit((url or "").strip())
	if (
		parts.scheme != "https"
		or not parts.netloc
		or parts.query
		or parts.fragment
		or '"' in url
		or "'" in url
	):
		return None
	path = parts.path if parts.path.endswith("/") else f"{parts.path}/"
	return f"https://{parts.netloc}{path}"


def valid_matomo_site_id(value: str) -> bool:
	return bool(MATOMO_SITE_ID.match(value or ""))


def ga4_snippet(measurement_id: str) -> str:
	if not valid_ga4_id(measurement_id):
		raise ValueError(f"not a GA4 measurement ID: {measurement_id!r}")
	return (
		f'<script async src="https://www.googletagmanager.com/gtag/js?id={measurement_id}"></script>'
		"<script>window.dataLayer=window.dataLayer||[];function gtag(){dataLayer.push(arguments);}"
		f"gtag('js',new Date());gtag('config',{json.dumps(measurement_id)});</script>"
	)


def matomo_snippet(url: str, site_id: str) -> str:
	base = matomo_base(url)
	if base is None or not valid_matomo_site_id(site_id):
		raise ValueError(f"not a Matomo base URL and site ID: {url!r}, {site_id!r}")
	return (
		"<script>var _paq=window._paq=window._paq||[];_paq.push(['trackPageView']);_paq.push(['enableLinkTracking']);"
		f"(function(){{var u={json.dumps(base)};_paq.push(['setTrackerUrl',u+'matomo.php']);"
		f"_paq.push(['setSiteId',{json.dumps(site_id)}]);var d=document,g=d.createElement('script'),"
		"s=d.getElementsByTagName('script')[0];g.async=true;g.src=u+'matomo.js';s.parentNode.insertBefore(g,s);})();"
		"</script>"
	)


def view_tracker_snippet(endpoint: str) -> str:
	"""Cookieless page-view beacon to ``endpoint``: referrer, time zone and UTM tags only. It honours
	Do Not Track and Global Privacy Control."""
	return (
		"<script>(function(){try{if(navigator.doNotTrack==='1'||navigator.globalPrivacyControl)return;"
		"var q=new URLSearchParams(location.search),b=new URLSearchParams();b.set('referrer',document.referrer||'');"
		"try{b.set('user_tz',Intl.DateTimeFormat().resolvedOptions().timeZone)}catch(e){}"
		f"{json.dumps(list(UTM_FIELDS))}.forEach(function(k){{var v=q.get('utm_'+k);if(v)b.set(k,v)}});"
		f"var u={json.dumps(endpoint)};if(navigator.sendBeacon)navigator.sendBeacon(u,b);"
		"else fetch(u,{method:'POST',body:b,keepalive:true});}catch(e){}})();</script>"
	)


def head_snippets(
	*, view_tracking: bool, ga4_measurement_id: str, matomo_url: str, matomo_site_id: str, log_endpoint: str
) -> str:
	"""Every configured provider's snippet for one site. A half-configured or invalid provider adds
	nothing (Public Site validation rejects those values on save)."""
	snippets = []
	if view_tracking:
		snippets.append(view_tracker_snippet(log_endpoint))
	if valid_ga4_id(ga4_measurement_id):
		snippets.append(ga4_snippet(ga4_measurement_id))
	if matomo_base(matomo_url) and valid_matomo_site_id(matomo_site_id):
		snippets.append(matomo_snippet(matomo_url, matomo_site_id))
	return "".join(snippets)


def view_path(referer: str, site_hosts: set[str]) -> str | None:
	"""The page a view beacon came from, as Web Page View stores it ("/" for the home page, else the path
	without its leading slash), when its Referer is on one of the site's hosts and is a page."""
	parts = urlsplit(referer or "")
	host = parts.netloc.split(":", 1)[0].lower()
	if parts.scheme not in ("http", "https") or host not in site_hosts:
		return None
	path = parts.path.strip("/")
	if not path:
		return "/"
	if path in UNTRACKED_PATHS or path.startswith(UNTRACKED_PREFIXES):
		return None
	return path


def clean_referrer(referrer: str | None) -> str | None:
	"""The visitor's previous page without its query string (which can carry personal data)."""
	return referrer.split("?", 1)[0][:REFERRER_MAX] if referrer else None
