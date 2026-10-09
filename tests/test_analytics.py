# SPDX-License-Identifier: AGPL-3.0-or-later
"""Unit tests for the pure analytics providers (no bench): validation, the GA4, Matomo and Frappe tracker
snippets, which providers a site gets, and which Referers count as page views."""

import json
import re

import pytest

from public_site_router import analytics

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

	def test_snippet_is_the_google_tag(self):
		snippet = analytics.ga4_snippet("G-B30D03ZZWZ")
		assert (
			'<script async src="https://www.googletagmanager.com/gtag/js?id=G-B30D03ZZWZ"></script>'
			in snippet
		)
		assert "gtag('config',\"G-B30D03ZZWZ\")" in snippet
		assert "window.dataLayer=window.dataLayer||[]" in snippet

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
