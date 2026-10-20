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
# A site with visitor IDs keeps one anonymous ID per browser in localStorage under this key: a random
# UUID without dashes. Other apps (a lead form) read it from the same key.
VISITOR_STORAGE_KEY = "psr_vid"
VISITOR_ID = re.compile(r"^[0-9a-f]{32}$")
# A visitor's analytics cookie choice ("granted" / "denied") in localStorage under this key. It covers Google Analytics
# (loaded only once granted) and Matomo's cookies (Matomo itself counts without cookies until then).
CONSENT_STORAGE_KEY = "psr_consent"
# Fired on document when the visitor answers the banner (detail: "granted" / "denied"), so Matomo can start using
# cookies on the same page.
CONSENT_EVENT = "psr-consent"
CONSENT_TEXT = (
	"With your OK, we use analytics cookies to see which pages are useful. Nothing is used for ads."
)
# The banner sits at the bottom, small enough never to cover the page; sites restyle .psr-consent if they want.
CONSENT_CSS = (
	".psr-consent{position:fixed;left:50%;bottom:1rem;transform:translateX(-50%);z-index:2147483000;"
	"box-sizing:border-box;width:min(40rem,calc(100% - 2rem));display:flex;flex-wrap:wrap;align-items:center;"
	"gap:.75rem 1rem;padding:.9rem 1rem;background:#fff;color:#1a1a1a;border:1px solid rgba(0,0,0,.15);"
	"border-radius:.75rem;box-shadow:0 8px 30px rgba(0,0,0,.18);font:400 15px/1.45 system-ui,sans-serif}"
	".psr-consent p{flex:1 1 16rem;margin:0}.psr-consent a{color:inherit;text-decoration:underline}"
	".psr-consent__actions{display:flex;gap:.5rem}.psr-consent button{min-height:44px;padding:.5rem 1rem;"
	"font:600 15px/1 system-ui,sans-serif;border-radius:.5rem;cursor:pointer;border:1px solid #1a1a1a;"
	"background:#fff;color:#1a1a1a}.psr-consent button[data-choice=granted]{background:#1a1a1a;color:#fff}"
	".psr-consent button:focus-visible,.psr-consent a:focus-visible{outline:3px solid #1a5fd0;outline-offset:2px}"
)


def js_string(value: str) -> str:
	"""``value`` as a JavaScript string literal that is also safe inside a <script> element (no ``</script>``)."""
	return json.dumps(value).replace("<", "\\u003c")


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


def ga4_snippet(measurement_id: str, privacy_url: str = "") -> str:
	"""The Google tag behind a consent banner. Consent Mode v2 starts with everything denied, and Google's
	script is fetched only once the visitor accepts, so nothing reaches Google before that. The choice is kept
	in ``localStorage[CONSENT_STORAGE_KEY]``; Do Not Track / Global Privacy Control count as a refusal (no
	banner). Any element with ``data-psr-consent-reset`` (e.g. on the privacy page) clears the choice."""
	if not valid_ga4_id(measurement_id):
		raise ValueError(f"not a GA4 measurement ID: {measurement_id!r}")
	key, gid, event = json.dumps(CONSENT_STORAGE_KEY), json.dumps(measurement_id), json.dumps(CONSENT_EVENT)
	return (
		"<script>window.dataLayer=window.dataLayer||[];function gtag(){dataLayer.push(arguments);}"
		"gtag('consent','default',{ad_storage:'denied',ad_user_data:'denied',ad_personalization:'denied',"
		"analytics_storage:'denied'});"
		f"(function(){{var K={key},ID={gid},P={js_string(privacy_url)},T={js_string(CONSENT_TEXT)};"
		"function store(v){try{localStorage.setItem(K,v)}catch(e){}}"
		"function load(){gtag('consent','update',{analytics_storage:'granted'});var s=document.createElement('script');"
		"s.async=true;s.src='https://www.googletagmanager.com/gtag/js?id='+ID;document.head.appendChild(s);"
		"gtag('js',new Date());gtag('config',ID);}"
		"document.addEventListener('click',function(e){var r=e.target.closest&&e.target.closest('[data-psr-consent-reset]');"
		"if(r){e.preventDefault();try{localStorage.removeItem(K)}catch(x){}location.reload();}});"
		"var c=null;try{c=localStorage.getItem(K)}catch(e){}"
		"if(c==='granted'){load();return;}"
		"if(c==='denied'||navigator.globalPrivacyControl||navigator.doNotTrack==='1')return;"
		f"function banner(){{var st=document.createElement('style');st.textContent={js_string(CONSENT_CSS)};"
		"document.head.appendChild(st);var b=document.createElement('div');b.className='psr-consent';"
		"b.setAttribute('role','region');b.setAttribute('aria-label','Cookie consent');"
		"var p=document.createElement('p');p.textContent=T+' ';"
		"if(P){var a=document.createElement('a');a.href=P;a.textContent='Privacy';p.appendChild(a);}"
		"var w=document.createElement('div');w.className='psr-consent__actions';"
		"function btn(t,v){var x=document.createElement('button');x.type='button';x.textContent=t;"
		"x.dataset.choice=v;x.addEventListener('click',function(){store(v);b.remove();if(v==='granted')load();"
		f"document.dispatchEvent(new CustomEvent({event},{{detail:v}}));}});"
		"w.appendChild(x);}"
		"btn('Decline','denied');btn('Accept','granted');b.appendChild(p);b.appendChild(w);document.body.appendChild(b);}"
		"if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',banner);else banner();"
		"})();</script>"
	)


def matomo_snippet(url: str, site_id: str) -> str:
	"""The Matomo tracker, cookieless until the visitor accepts the consent banner: ``requireCookieConsent`` counts
	visits without cookies (and clears any it set before), and the stored or just-given ``granted`` choice turns them
	on. Do Not Track / Global Privacy Control visitors are not tracked at all, as with the Frappe view tracker."""
	base = matomo_base(url)
	if base is None or not valid_matomo_site_id(site_id):
		raise ValueError(f"not a Matomo base URL and site ID: {url!r}, {site_id!r}")
	key, event = json.dumps(CONSENT_STORAGE_KEY), json.dumps(CONSENT_EVENT)
	return (
		"<script>(function(){if(navigator.doNotTrack==='1'||navigator.globalPrivacyControl)return;"
		"var _paq=window._paq=window._paq||[];_paq.push(['requireCookieConsent']);"
		f"var c=null;try{{c=localStorage.getItem({key})}}catch(e){{}}if(c==='granted')_paq.push(['setCookieConsentGiven']);"
		f"document.addEventListener({event},function(e){{if(e.detail==='granted')_paq.push(['setCookieConsentGiven']);}});"
		"_paq.push(['trackPageView']);_paq.push(['enableLinkTracking']);"
		f"var u={json.dumps(base)};_paq.push(['setTrackerUrl',u+'matomo.php']);"
		f"_paq.push(['setSiteId',{json.dumps(site_id)}]);var d=document,g=d.createElement('script'),"
		"s=d.getElementsByTagName('script')[0];g.async=true;g.src=u+'matomo.js';s.parentNode.insertBefore(g,s);})();"
		"</script>"
	)


def clean_visitor_id(value: str | None) -> str | None:
	"""``value`` if it is a visitor ID the tracker generates, else None."""
	value = (value or "").strip().lower()
	return value if VISITOR_ID.match(value) else None


def visitor_id_script() -> str:
	"""Tracker fragment: the browser's anonymous visitor ID (created on first use) on beacon ``b``. It runs
	after the Do Not Track / Global Privacy Control check, so those visitors never get one."""
	key = json.dumps(VISITOR_STORAGE_KEY)
	return (
		f"try{{var i=localStorage.getItem({key});if(!/^[0-9a-f]{{32}}$/.test(i||'')){{"
		f"i=crypto.randomUUID().replace(/-/g,'');localStorage.setItem({key},i)}}b.set('visitor_id',i)}}catch(e){{}}"
	)


def view_tracker_snippet(endpoint: str, visitor_ids: bool = False) -> str:
	"""Page-view beacon to ``endpoint``: referrer, time zone and UTM tags, and with ``visitor_ids`` the
	browser's anonymous visitor ID. No cookies either way. It honours Do Not Track and Global Privacy
	Control."""
	return (
		"<script>(function(){try{if(navigator.doNotTrack==='1'||navigator.globalPrivacyControl)return;"
		"var q=new URLSearchParams(location.search),b=new URLSearchParams();b.set('referrer',document.referrer||'');"
		"try{b.set('user_tz',Intl.DateTimeFormat().resolvedOptions().timeZone)}catch(e){}"
		f"{json.dumps(list(UTM_FIELDS))}.forEach(function(k){{var v=q.get('utm_'+k);if(v)b.set(k,v)}});"
		f"{visitor_id_script() if visitor_ids else ''}"
		f"var u={json.dumps(endpoint)};if(navigator.sendBeacon)navigator.sendBeacon(u,b);"
		"else fetch(u,{method:'POST',body:b,keepalive:true});}catch(e){}})();</script>"
	)


def head_snippets(
	*,
	view_tracking: bool,
	ga4_measurement_id: str,
	matomo_url: str,
	matomo_site_id: str,
	log_endpoint: str,
	visitor_ids: bool = False,
	privacy_url: str = "",
) -> str:
	"""Every configured provider's snippet for one site. A half-configured or invalid provider adds
	nothing (Public Site validation rejects those values on save)."""
	snippets = []
	if view_tracking:
		snippets.append(view_tracker_snippet(log_endpoint, visitor_ids))
	if valid_ga4_id(ga4_measurement_id):
		snippets.append(ga4_snippet(ga4_measurement_id, privacy_url))
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
