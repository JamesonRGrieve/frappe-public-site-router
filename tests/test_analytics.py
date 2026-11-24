# SPDX-License-Identifier: AGPL-3.0-or-later
"""Unit tests for the pure analytics providers (no bench): validation, the GA4, Matomo and Frappe tracker
snippets, which providers a site gets, and which Referers count as page views."""

import json
import re

import pytest

from public_site_router import analytics, conversions

ENDPOINT = "/api/method/public_site_router.site_analytics.log_view"


class TestGa4:
	@pytest.mark.parametrize("value", ["G-B30D03ZZWZ", "G-6H9MBE4V6L", "G-PRMYMK7L44", "G-L4DRDNYPM4"])
	def test_valid_ids(self, value):
		assert analytics.valid_ga4_id(value)

	@pytest.mark.parametrize(
		"value", ["", None, "UA-12345-1", "g-b30d03zzwz", "G-", "G-ABC", 'G-AB"><script>', "G-ABCD EFG"]
	)
	def test_invalid_ids(self, value):
		assert not analytics.valid_ga4_id(value)

	def test_snippet_is_the_google_tag_behind_consent(self):
		snippet = analytics.ga4_snippet("G-B30D03ZZWZ")
		assert "window.dataLayer=window.dataLayer||[]" in snippet
		assert 'ID="G-B30D03ZZWZ"' in snippet
		assert "https://www.googletagmanager.com/gtag/js?id='+ID" in snippet
		assert "gtag('config',ID)" in snippet

	def test_google_script_loads_on_every_page(self):
		# Consent Mode v2 decides what Google may store; the tag itself always loads (operator, 2026-11-24).
		snippet = analytics.ga4_snippet("G-B30D03ZZWZ")
		assert "<script async src=" not in snippet
		assert "function load()" not in snippet
		assert snippet.index("s.src='https://www.googletagmanager.com") < snippet.index("function banner()")

	def test_consent_defaults_are_regional(self):
		snippet = analytics.ga4_snippet("G-B30D03ZZWZ")
		regional = snippet.index("gtag('consent','default'")
		everywhere = snippet.index("gtag('consent','default'", regional + 1)
		denied = snippet[regional:everywhere]
		for signal in ("ad_storage", "ad_user_data", "ad_personalization", "analytics_storage"):
			assert f"{signal}:'denied'" in denied
			assert f"{signal}:'granted'" in snippet[everywhere : everywhere + 160]
		assert f"wait_for_update:{analytics.CONSENT_WAIT_MS}" in denied
		assert f"region:{json.dumps(list(analytics.CONSENT_REGIONS))}" in denied
		# The region default comes first; both precede the tag's config.
		assert everywhere < snippet.index("gtag('config',ID)")

	def test_regions_match_the_wordpress_plugin(self):
		eea = {
			"AT",
			"BE",
			"BG",
			"HR",
			"CY",
			"CZ",
			"DK",
			"EE",
			"FI",
			"FR",
			"DE",
			"GR",
			"HU",
			"IE",
			"IT",
			"LV",
			"LT",
		}
		eea |= {"LU", "MT", "NL", "PL", "PT", "RO", "SK", "SI", "ES", "SE", "IS", "LI", "NO"}
		assert set(analytics.CONSENT_REGIONS) == eea | {"GB", "CH", "CA-QC"}
		assert len(analytics.CONSENT_REGIONS) == len(set(analytics.CONSENT_REGIONS))

	def test_a_stored_answer_applies_before_the_tag_configures(self):
		snippet = analytics.ga4_snippet("G-B30D03ZZWZ")
		applied = snippet.index(
			"if(c==='granted')answer('granted');else if(c==='denied'||off)answer('denied');"
		)
		assert applied < snippet.index("gtag('config',ID)")
		assert "gtag('consent','update',v==='granted'?{analytics_storage:'granted'}:" in snippet

	def test_do_not_track_and_gpc_count_as_a_refusal(self):
		snippet = analytics.ga4_snippet("G-B30D03ZZWZ")
		assert "var off=!!(navigator.globalPrivacyControl||navigator.doNotTrack==='1');" in snippet
		assert "if(c==='granted'||c==='denied'||off)return;" in snippet

	def test_reports_the_plugins_conversion_events(self):
		snippet = analytics.ga4_snippet("G-B30D03ZZWZ")
		assert f"C={json.dumps(conversions.PENDING_COOKIE)}" in snippet
		assert f"E={json.dumps(list(conversions.EVENTS))}" in snippet
		assert "report('click_to_call',{link_url:h})" in snippet
		assert "report('click_email',{})" in snippet  # never the address

	def test_debug_mode_only_when_asked(self):
		assert "D=false" in analytics.ga4_snippet("G-B30D03ZZWZ")
		assert "D=true" in analytics.ga4_snippet("G-B30D03ZZWZ", debug=True)

	def test_every_placeholder_is_filled(self):
		snippet = analytics.ga4_snippet("G-B30D03ZZWZ", "/privacy", debug=True)
		assert not re.search(r"@[A-Z]+@", snippet)

	def test_banner_links_the_privacy_page_when_given(self):
		assert 'P="/privacy"' in analytics.ga4_snippet("G-B30D03ZZWZ", "/privacy")
		assert 'P=""' in analytics.ga4_snippet("G-B30D03ZZWZ")

	def test_privacy_url_cannot_close_the_script(self):
		snippet = analytics.ga4_snippet("G-B30D03ZZWZ", '/x"</script><img src=x>')
		# Only the snippet's own closing tag remains; the value is a quoted JS string with < escaped.
		assert snippet.count("</script>") == 1 and snippet.endswith("</script>")
		assert 'P="/x\\"\\u003c/script>\\u003cimg src=x>"' in snippet

	def test_choice_is_stored_and_resettable(self):
		snippet = analytics.ga4_snippet("G-B30D03ZZWZ")
		assert f'K="{analytics.CONSENT_STORAGE_KEY}"' in snippet
		assert "[data-psr-consent-reset]" in snippet

	def test_snippet_refuses_an_invalid_id(self):
		with pytest.raises(ValueError):
			analytics.ga4_snippet('G-X"><img src=x>')


class TestMatomo:
	def test_base_url_gains_a_trailing_slash(self):
		assert analytics.matomo_base("https://matomo.zephyrex.ca") == "https://matomo.zephyrex.ca/"
		assert analytics.matomo_base(" https://zephyrex.ca/matomo ") == "https://zephyrex.ca/matomo/"

	@pytest.mark.parametrize(
		"url",
		[
			"",
			None,
			"http://matomo.zephyrex.ca/",
			"https://",
			"https://m.ca/?x=1",
			"https://m.ca/#a",
			"https://m.ca/'",
		],
	)
	def test_rejects_non_https_or_odd_urls(self, url):
		assert analytics.matomo_base(url) is None

	def test_site_id_is_numeric(self):
		assert analytics.valid_matomo_site_id("3")
		assert not analytics.valid_matomo_site_id("3a")
		assert not analytics.valid_matomo_site_id("")

	def test_snippet_uses_the_base_and_site_id(self):
		snippet = analytics.matomo_snippet("https://matomo.zephyrex.ca", "7")
		assert 'var u="https://matomo.zephyrex.ca/"' in snippet
		assert "_paq.push(['setSiteId',\"7\"])" in snippet
		assert "u+'matomo.js'" in snippet and "u+'matomo.php'" in snippet

	def test_cookieless_until_consent(self):
		snippet = analytics.matomo_snippet("https://matomo.zephyrex.ca", "7")
		require = snippet.index("_paq.push(['requireCookieConsent'])")
		assert require < snippet.index("_paq.push(['trackPageView'])")
		assert f"localStorage.getItem({json.dumps(analytics.CONSENT_STORAGE_KEY)})" in snippet
		assert "if(c==='granted')_paq.push(['setCookieConsentGiven'])" in snippet
		assert f"document.addEventListener({json.dumps(analytics.CONSENT_EVENT)}" in snippet

	def test_dnt_and_gpc_are_not_tracked(self):
		snippet = analytics.matomo_snippet("https://matomo.zephyrex.ca", "7")
		guard = snippet.index("if(navigator.doNotTrack==='1'||navigator.globalPrivacyControl)return;")
		assert guard < snippet.index("_paq.push(['trackPageView'])")

	def test_banner_answer_tells_matomo(self):
		banner = analytics.ga4_snippet("G-ABC123")
		assert f"new CustomEvent({json.dumps(analytics.CONSENT_EVENT)},{{detail:v}})" in banner
		assert "Google Analytics" not in analytics.CONSENT_TEXT  # the choice covers Matomo's cookies too

	def test_snippet_refuses_bad_config(self):
		with pytest.raises(ValueError):
			analytics.matomo_snippet("http://m.ca", "1")
		with pytest.raises(ValueError):
			analytics.matomo_snippet("https://m.ca", "x")


class TestViewTracker:
	def test_posts_to_the_endpoint_and_honours_dnt_and_gpc(self):
		snippet = analytics.view_tracker_snippet(ENDPOINT)
		assert json.dumps(ENDPOINT) in snippet
		assert "navigator.doNotTrack==='1'" in snippet
		assert "navigator.globalPrivacyControl" in snippet
		assert "sendBeacon" in snippet

	def test_sends_only_referrer_time_zone_and_utm_tags(self):
		snippet = analytics.view_tracker_snippet(ENDPOINT)
		assert set(re.findall(r"b\.set\('(\w+)'", snippet)) == {"referrer", "user_tz"}
		assert '["source", "medium", "campaign", "content"]' in snippet
		assert "cookie" not in snippet and "localStorage" not in snippet

	def test_visitor_ids_add_a_stored_id_after_the_privacy_check(self):
		snippet = analytics.view_tracker_snippet(ENDPOINT, visitor_ids=True)
		assert set(re.findall(r"b\.set\('(\w+)'", snippet)) == {"referrer", "user_tz", "visitor_id"}
		assert 'localStorage.getItem("psr_vid")' in snippet
		assert "crypto.randomUUID()" in snippet
		assert "cookie" not in snippet
		assert snippet.index("globalPrivacyControl") < snippet.index("localStorage")
		assert snippet.index("visitor_id") < snippet.index("sendBeacon")


class TestVisitorId:
	def test_accepts_the_trackers_ids(self):
		assert (
			analytics.clean_visitor_id(" 0123456789ABCDEF0123456789abcdef ")
			== "0123456789abcdef0123456789abcdef"
		)

	@pytest.mark.parametrize("value", [None, "", "short", "g" * 32, "0123456789abcdef" * 3, "<script>" * 4])
	def test_rejects_anything_else(self, value):
		assert analytics.clean_visitor_id(value) is None


class TestHeadSnippets:
	def snippets(self, **overrides):
		config = {
			"view_tracking": True,
			"ga4_measurement_id": "G-B30D03ZZWZ",
			"matomo_url": "https://matomo.zephyrex.ca/",
			"matomo_site_id": "2",
			"log_endpoint": ENDPOINT,
		}
		return analytics.head_snippets(**(config | overrides))

	def test_every_configured_provider(self):
		html = self.snippets()
		assert ENDPOINT in html and "G-B30D03ZZWZ" in html and "matomo.php" in html

	def test_ga4_debug_reaches_the_snippet(self):
		assert "D=false" in self.snippets()
		assert "D=true" in self.snippets(ga4_debug=True)

	def test_visitor_ids_only_when_enabled(self):
		assert "psr_vid" not in self.snippets()
		assert "psr_vid" in self.snippets(visitor_ids=True)
		assert "psr_vid" not in self.snippets(view_tracking=False, visitor_ids=True)

	def test_nothing_configured_adds_nothing(self):
		assert (
			self.snippets(view_tracking=False, ga4_measurement_id="", matomo_url="", matomo_site_id="") == ""
		)

	def test_half_configured_or_invalid_providers_add_nothing(self):
		html = self.snippets(view_tracking=False, ga4_measurement_id="UA-1-1", matomo_site_id="")
		assert html == ""

	def test_order_is_frappe_ga4_matomo(self):
		html = self.snippets()
		assert html.index(ENDPOINT) < html.index("googletagmanager") < html.index("matomo.js")


class TestViewPath:
	HOSTS = {"zephyrex.ca", "www.zephyrex.ca"}

	@pytest.mark.parametrize(
		("referer", "expected"),
		[
			("https://zephyrex.ca/", "/"),
			("https://www.zephyrex.ca/about", "about"),
			("https://zephyrex.ca/services/email-calendar/?utm_source=x", "services/email-calendar"),
			("https://ZEPHYREX.CA:443/about", "about"),
			("https://zephyrex.ca/apple-guide", "apple-guide"),
		],
	)
	def test_pages_on_the_sites_hosts(self, referer, expected):
		assert analytics.view_path(referer, self.HOSTS) == expected

	@pytest.mark.parametrize(
		"referer",
		[
			None,
			"",
			"/about",
			"https://3shub.com/",
			"https://erp.zephyrex.ca/app/lead",
			"javascript:alert(1)",
			"https://zephyrex.ca/app",
			"https://zephyrex.ca/app/web-page",
			"https://zephyrex.ca/api/method/x",
			"https://zephyrex.ca/assets/a.css",
			"https://zephyrex.ca/files/a.png",
			"https://zephyrex.ca/private/files/a.pdf",
		],
	)
	def test_everything_else_is_not_a_view(self, referer):
		assert analytics.view_path(referer, self.HOSTS) is None


class TestReferrer:
	def test_drops_the_query_string(self):
		assert analytics.clean_referrer("https://google.com/search?q=private") == "https://google.com/search"

	def test_caps_the_length(self):
		assert len(analytics.clean_referrer("https://a.ca/" + "x" * 500)) == analytics.REFERRER_MAX

	def test_empty(self):
		assert analytics.clean_referrer(None) is None
		assert analytics.clean_referrer("") is None


def test_consent_banner_looks_the_same_on_builder_pages():
	# Builder's base CSS sets font-variation-settings on text elements and lets buttons inherit letter-spacing
	from public_site_router.analytics import CONSENT_CSS

	assert ".psr-consent,.psr-consent *{font-variation-settings:normal}" in CONSENT_CSS
	button = CONSENT_CSS.split(".psr-consent button{", 1)[1].split("}", 1)[0]
	assert "letter-spacing:normal" in button
