# SPDX-License-Identifier: AGPL-3.0-or-later
"""Unit tests for the pure form spam protection (no bench): site key validation, the Turnstile head snippet,
the submitted token, the siteverify body and how Cloudflare's answer is judged."""

import pytest

from public_site_router import forms

KEY = "0x4AAAAAAAB1cDeFgHiJkLmN"


class TestSiteKey:
	@pytest.mark.parametrize("value", [KEY, "1x00000000000000000000AA", "3x00000000000000000000FF"])
	def test_valid(self, value):
		assert forms.valid_site_key(value)

	@pytest.mark.parametrize(
		"value", ["", None, "0x", "abc", "0x123", '0x4AAAAAAAB1"><script>', "0x4AAA AAAAB1cDeF"]
	)
	def test_invalid(self, value):
		assert not forms.valid_site_key(value)


class TestHeadHtml:
	def test_no_key_no_snippet(self):
		assert forms.head_html("") == ""
		assert forms.head_html("not-a-key") == ""

	def test_script_is_in_the_served_html(self):
		html = forms.head_html(KEY)
		assert f'src="{forms.SCRIPT_URL}"' in html
		assert "challenges.cloudflare.com/turnstile" in html

	def test_loader_adds_a_widget_per_web_form(self):
		html = forms.head_html(KEY)
		assert "form[data-web-form]" in html
		assert "cf-turnstile" in html
		assert f'"{KEY}"' in html

	def test_loader_attaches_the_token_to_web_form_submissions(self):
		html = forms.head_html(KEY)
		assert f'"{forms.ACCEPT_PATH}"' in html
		assert f'"{forms.RESPONSE_FIELD}"' in html
		assert "window.fetch" in html and "turnstile.reset" in html

	def test_key_cannot_close_the_script(self):
		assert "</script><script>" not in forms.head_html(KEY).replace(
			f'<script src="{forms.SCRIPT_URL}" async defer></script>\n<script>', ""
		)


class TestToken:
	def test_token_present(self):
		assert forms.token_from({forms.RESPONSE_FIELD: "abc.def"}) == "abc.def"

	@pytest.mark.parametrize("value", [None, "", 5, ["x"], "x" * (forms.TOKEN_MAX + 1)])
	def test_missing_or_invalid(self, value):
		assert forms.token_from({forms.RESPONSE_FIELD: value}) == ""
		assert forms.token_from({}) == ""


class TestVerify:
	def test_payload(self):
		assert forms.verify_payload("s", "t", "203.0.113.5") == {
			"secret": "s",
			"response": "t",
			"remoteip": "203.0.113.5",
		}
		assert forms.verify_payload("s", "t", None) == {"secret": "s", "response": "t"}

	def test_success_on_a_site_host(self):
		assert forms.verified(
			{"success": True, "hostname": "zephyrex.ca"}, {"zephyrex.ca", "www.zephyrex.ca"}
		)

	def test_hostname_is_case_insensitive(self):
		assert forms.verified({"success": True, "hostname": "Zephyrex.CA"}, {"zephyrex.ca"})

	def test_solved_on_another_host_fails(self):
		assert not forms.verified({"success": True, "hostname": "evil.example"}, {"zephyrex.ca"})

	@pytest.mark.parametrize("result", [{"success": False}, {}, None, {"success": "true"}, []])
	def test_failures(self, result):
		assert not forms.verified(result, {"zephyrex.ca"})
