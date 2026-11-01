# SPDX-License-Identifier: AGPL-3.0-or-later
"""Spam protection for Public Site forms: Cloudflare Turnstile.

Pure functions with no Frappe import. A Public Site with a Turnstile site key gets Cloudflare's script on every page
(so the protection is in the served HTML) and a small loader that renders one widget inside each Web Form on the
page; a site with the matching secret key has every Web Form submission from its hosts verified with Cloudflare
before Frappe accepts it (site_forms.accept). Values are validated before they reach a snippet and embedded with
analytics.js_string, so no field can close the script."""

import re

from .analytics import js_string

SCRIPT_URL = "https://challenges.cloudflare.com/turnstile/v0/api.js"
VERIFY_URL = "https://challenges.cloudflare.com/turnstile/v0/siteverify"
# The hidden input Turnstile adds inside its widget, and the form field the page sends the token in.
RESPONSE_FIELD = "cf-turnstile-response"
# Frappe's Web Form submission endpoint (site_forms.accept overrides it on protected sites).
ACCEPT_PATH = "/api/method/frappe.website.doctype.web_form.web_form.accept"
# Cloudflare site keys: "0x" then the key body (test keys are e.g. 1x00000000000000000000AA).
SITE_KEY = re.compile(r"^[0-9]x[A-Za-z0-9_-]{10,64}$")
# A token is at most 2048 characters (Cloudflare's documented limit).
TOKEN_MAX = 2048


def valid_site_key(value: str) -> bool:
	return bool(SITE_KEY.match(value or ""))


def head_html(site_key: str) -> str:
	"""Cloudflare's Turnstile script plus a loader that renders one widget in each Web Form (form[data-web-form])
	that has none yet, for a site with a valid ``site_key``; "" otherwise."""
	if not valid_site_key(site_key):
		return ""
	# The loader also attaches the widget's token to the page's own Web Form submission (a fetch to ACCEPT_PATH
	# with a URLSearchParams body), so a site's form script needs no change, and resets the widget after the call
	# so a second submission gets a fresh token.
	loader = (
		"(function(){var K=" + js_string(site_key) + ",A=" + js_string(ACCEPT_PATH) + ","
		"R=" + js_string(RESPONSE_FIELD) + ";"
		"function add(){document.querySelectorAll('form[data-web-form]').forEach(function(f){"
		"if(f.querySelector('.cf-turnstile'))return;var d=document.createElement('div');"
		"d.className='cf-turnstile';d.setAttribute('data-sitekey',K);d.setAttribute('data-appearance','interaction-only');"
		"var s=f.querySelector('[type=submit],button:not([type])');if(s&&s.parentNode===f)f.insertBefore(d,s);"
		"else f.appendChild(d);if(window.turnstile)window.turnstile.render(d);});}"
		"if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',add);else add();"
		"var F=window.fetch;if(!F)return;window.fetch=function(u,o){var hit=String(u).indexOf(A)!==-1;"
		"if(hit&&o&&o.body instanceof URLSearchParams&&!o.body.has(R)&&window.turnstile){try{"
		"var a=document.activeElement,f=a&&a.closest?a.closest('form'):null,"
		"w=f?f.querySelector('.cf-turnstile'):null,t=w?window.turnstile.getResponse(w):window.turnstile.getResponse();"
		"if(t)o.body.append(R,t);}catch(e){}}"
		"var p=F.apply(this,arguments);if(hit)p.then(function(){try{document.querySelectorAll('.cf-turnstile')"
		".forEach(function(w){window.turnstile&&window.turnstile.reset(w);});}catch(e){}},function(){});return p;};})();"
	)
	return f'<script src="{SCRIPT_URL}" async defer></script>\n<script>{loader}</script>'


def token_from(form: dict) -> str:
	"""The Turnstile token a submission carries, or "" when it carries none (or an oversized one)."""
	token = form.get(RESPONSE_FIELD) or ""
	return token if isinstance(token, str) and 0 < len(token) <= TOKEN_MAX else ""


def verify_payload(secret: str, token: str, remote_ip: str | None) -> dict:
	"""The form body Cloudflare's siteverify endpoint takes."""
	body = {"secret": secret, "response": token}
	if remote_ip:
		body["remoteip"] = remote_ip
	return body


def verified(result: dict, expected_hosts: set[str]) -> bool:
	"""Cloudflare's siteverify answer passes: success, and the challenge was solved on one of the site's hosts."""
	if not isinstance(result, dict) or result.get("success") is not True:
		return False
	hostname = (result.get("hostname") or "").lower()
	return not expected_hosts or hostname in expected_hosts
