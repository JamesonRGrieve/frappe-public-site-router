# SPDX-License-Identifier: AGPL-3.0-or-later
"""The Google tag's script run in Node against a minimal browser stub: consent order, the banner, and conversions
(pending-lead cookie, fetch hook, link clicks). Skipped where Node isn't installed."""

import json
import shutil
import subprocess

import pytest

from public_site_router import analytics, conversions

NODE = shutil.which("node")
pytestmark = pytest.mark.skipif(NODE is None, reason="node not installed")

# A browser just big enough for the snippet: document (cookie jar, listeners, head/body), localStorage, navigator,
# fetch, XMLHttpRequest. After the script and the scenario run, it prints what reached the dataLayer and the page.
HARNESS = r"""
var listeners = {}, docListeners = {}, cookies = {}, cleared = [], store = {}, appended = [], events = [];
function el(tag) {
  return { tag: tag, children: [], dataset: {}, attrs: {}, handlers: {}, style: {},
    setAttribute: function (k, v) { this.attrs[k] = v; },
    appendChild: function (c) { this.children.push(c); appended.push(c); return c; },
    addEventListener: function (n, f) { this.handlers[n] = f; },
    remove: function () { this.removed = true; },
    closest: function () { return null; }, getAttribute: function (k) { return this.attrs[k]; } };
}
global.window = global;
global.location = { protocol: 'https:', reload: function () { events.push('reload'); } };
Object.defineProperty(global, 'navigator', { value: CONFIG.navigator, configurable: true });
global.localStorage = { getItem: function (k) { return k in store ? store[k] : null; },
  setItem: function (k, v) { store[k] = String(v); }, removeItem: function (k) { delete store[k]; } };
if (CONFIG.stored) store[CONFIG.key] = CONFIG.stored;
global.document = { readyState: 'complete', visibilityState: 'visible', head: el('head'), body: el('body'),
  createElement: el,
  addEventListener: function (n, f) { (docListeners[n] = docListeners[n] || []).push(f); },
  dispatchEvent: function (e) { events.push(['dispatch', e.type, e.detail]); } };
Object.defineProperty(document, 'cookie', {
  get: function () { return Object.keys(cookies).map(function (k) { return k + '=' + cookies[k]; }).join('; '); },
  set: function (v) { var kv = v.split(';')[0], i = kv.indexOf('='), k = kv.slice(0, i);
    if (/Max-Age=0/.test(v)) { delete cookies[k]; cleared.push(v); } else cookies[k] = kv.slice(i + 1); } });
global.addEventListener = function (n, f) { (listeners[n] = listeners[n] || []).push(f); };
global.CustomEvent = function (type, o) { this.type = type; this.detail = o.detail; };
global.fetch = function () { if (CONFIG.fetchSets) cookies[CONFIG.cookie] = CONFIG.fetchSets; return Promise.resolve('ok'); };
global.XMLHttpRequest = function () {}; XMLHttpRequest.prototype.send = function () {};
global.atob = function (b) { return Buffer.from(b, 'base64').toString('binary'); };
if (CONFIG.pending) cookies[CONFIG.cookie] = CONFIG.pending;
function click(href, reset) {
  var a = el('a'); a.attrs.href = href;
  var t = { closest: function (s) { return s === 'a[href]' ? (href ? a : null) : (reset ? {} : null); } };
  docListeners.click.forEach(function (f) { f({ target: t, preventDefault: function () {} }); });
}
function banner() { return appended.filter(function (c) { return c.className === 'psr-consent'; })[0]; }
function button(choice) { return banner().children[1].children.filter(function (b) { return b.dataset.choice === choice; })[0]; }
SCRIPT
Promise.resolve().then(function () { SCENARIO }).then(function () { return new Promise(function (r) { setTimeout(r, 5); }); })
  .then(function () {
    process.stdout.write(JSON.stringify({
      layer: dataLayer.map(function (a) { return Array.prototype.slice.call(a); }),
      banner: !!banner(), store: store, cleared: cleared.length, events: events,
      scripts: appended.filter(function (c) { return c.tag === 'script'; }).map(function (c) { return c.src; }) }));
  });
"""


def run(scenario="", *, stored=None, pending=None, fetch_sets=None, navigator=None, debug=False):
	snippet = analytics.ga4_snippet("G-B30D03ZZWZ", "/privacy", debug=debug)
	script = snippet.removeprefix("<script>").removesuffix("</script>")
	config = {
		"key": analytics.CONSENT_STORAGE_KEY,
		"cookie": conversions.PENDING_COOKIE,
		"stored": stored,
		"pending": pending,
		"fetchSets": fetch_sets,
		"navigator": navigator or {},
	}
	source = HARNESS.replace("SCRIPT", script).replace("SCENARIO", scenario)
	source = f"var CONFIG = {json.dumps(config)};\n" + source
	out = subprocess.run([NODE, "-e", source], capture_output=True, text=True, timeout=30, check=True)
	return json.loads(out.stdout)


def gtag_calls(result, command):
	return [call for call in result["layer"] if call and call[0] == command]


def events(result):
	return [(call[1], call[2]) for call in gtag_calls(result, "event")]


def lead(form="contact-zephyrex-ca"):
	return conversions.append(None, conversions.lead_event(form, "Contact"))


def test_first_visit_regional_defaults_then_tag_and_banner():
	result = run()
	consent = gtag_calls(result, "consent")
	assert [c[1] for c in consent] == ["default", "default"]
	assert consent[0][2]["region"] == list(analytics.CONSENT_REGIONS)
	assert consent[0][2]["analytics_storage"] == "denied" and consent[1][2]["analytics_storage"] == "granted"
	assert gtag_calls(result, "config") == [["config", "G-B30D03ZZWZ"]]
	assert result["scripts"] == ["https://www.googletagmanager.com/gtag/js?id=G-B30D03ZZWZ"]
	assert result["banner"]


@pytest.mark.parametrize(
	("stored", "navigator", "expected"),
	[
		("granted", {}, {"analytics_storage": "granted"}),
		("denied", {}, {"analytics_storage": "denied", "ad_storage": "denied"}),
		(None, {"doNotTrack": "1"}, {"analytics_storage": "denied", "ad_user_data": "denied"}),
		(
			None,
			{"globalPrivacyControl": True},
			{"analytics_storage": "denied", "ad_personalization": "denied"},
		),
	],
)
def test_a_known_answer_updates_consent_before_config_and_hides_the_banner(stored, navigator, expected):
	result = run(stored=stored, navigator=navigator)
	layer = result["layer"]
	update = next(i for i, c in enumerate(layer) if c[:2] == ["consent", "update"])
	assert expected.items() <= layer[update][2].items()
	assert update < next(i for i, c in enumerate(layer) if c[0] == "config")
	assert result["scripts"]  # the tag loads anyway: cookieless pings when denied
	assert not result["banner"]


@pytest.mark.parametrize(("choice", "analytics_storage"), [("granted", "granted"), ("denied", "denied")])
def test_banner_answer_is_stored_applied_and_announced(choice, analytics_storage):
	result = run(f"button('{choice}').handlers.click();")
	assert result["store"][analytics.CONSENT_STORAGE_KEY] == choice
	assert gtag_calls(result, "consent")[-1][2]["analytics_storage"] == analytics_storage
	assert ["dispatch", analytics.CONSENT_EVENT, choice] in result["events"]


def test_a_pending_lead_is_reported_once_and_cleared():
	result = run(
		"window.dispatchEvent && 0; listeners.pageshow.forEach(function (f) { f(); });", pending=lead()
	)
	assert events(result) == [("generate_lead", {"form_id": "contact-zephyrex-ca", "form_name": "Contact"})]
	assert result["cleared"] == 1


def test_a_lead_is_reported_when_even_consent_is_denied():
	result = run(pending=lead(), stored="denied")
	assert [e[0] for e in events(result)] == ["generate_lead"]


def test_the_form_submissions_response_hands_over_the_lead():
	result = run(
		"return fetch('/api/method/frappe.website.doctype.web_form.web_form.accept');", fetch_sets=lead()
	)
	assert [e[0] for e in events(result)] == ["generate_lead"]


def test_unknown_events_in_the_cookie_are_ignored():
	result = run(pending=conversions.encode([{"e": "purchase", "p": {}}]))
	assert events(result) == []


def test_phone_and_email_links():
	result = run("click('TEL:+1 403 555 0100'); click('mailto:a@b.ca'); click('/contact');")
	assert events(result) == [("click_to_call", {"link_url": "tel:+1 403 555 0100"}), ("click_email", {})]


def test_debug_mode_marks_events():
	result = run("click('tel:1');", debug=True)
	assert events(result) == [("click_to_call", {"link_url": "tel:1", "debug_mode": True})]


def test_consent_reset_clears_the_answer():
	result = run("click(null, true);", stored="granted")
	assert analytics.CONSENT_STORAGE_KEY not in result["store"]
	assert "reload" in result["events"]
