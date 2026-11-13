# SPDX-License-Identifier: AGPL-3.0-or-later
"""Unit tests for a Public Site's Content-Security-Policy (no bench)."""

import pytest

from public_site_router import csp


def directives(value: str) -> dict[str, list[str]]:
	return {part.split()[0]: part.split()[1:] for part in value.split("; ")}


class TestBasePolicy:
	def test_hardening_directives(self):
		d = directives(csp.policy())
		assert d["object-src"] == ["'none'"]
		assert d["frame-ancestors"] == ["'self'"]
		assert d["base-uri"] == ["'self'"]
		assert d["form-action"] == ["'self'"]
		assert d["default-src"] == ["'self'"]

	def test_builder_inline_css_and_js_and_google_fonts(self):
		d = directives(csp.policy())
		assert "'unsafe-inline'" in d["script-src"] and "'unsafe-inline'" in d["style-src"]
		assert "https://fonts.googleapis.com" in d["style-src"]
		assert "https://fonts.gstatic.com" in d["font-src"]

	def test_no_integration_origins_unless_switched_on(self):
		value = csp.policy()
		assert "googletagmanager" not in value
		assert "challenges.cloudflare.com" not in value

	def test_directive_order_is_stable(self):
		assert [p.split()[0] for p in csp.policy().split("; ")] == list(csp.ORDER)


class TestIntegrations:
	def test_ga4(self):
		d = directives(csp.policy(ga4=True))
		assert "https://www.googletagmanager.com" in d["script-src"]
		assert "https://*.google-analytics.com" in d["connect-src"]

	def test_matomo(self):
		d = directives(csp.policy(matomo_base="https://stats.example.com/"))
		assert "https://stats.example.com" in d["script-src"]
		assert "https://stats.example.com" in d["connect-src"]

	def test_turnstile(self):
		d = directives(csp.policy(turnstile=True))
		assert "https://challenges.cloudflare.com" in d["script-src"]
		assert "https://challenges.cloudflare.com" in d["frame-src"]


class TestExtraSources:
	def test_added_once(self):
		d = directives(csp.policy(extra="frame-src https://www.youtube-nocookie.com\nimg-src https:"))
		assert d["frame-src"] == ["'self'", "https://www.youtube-nocookie.com"]
		assert d["img-src"].count("https:") == 1

	def test_comments_and_blanks_ignored(self):
		assert csp.parse_extra("# note\n\n") == {}

	@pytest.mark.parametrize(
		"text",
		[
			"script-srcx https://a.example",
			"img-src",
			"img-src https://a.example;script-src *",
			"img-src javascript",
			"img-src 'unsafe-inline' 'x y'",
		],
	)
	def test_refused(self, text):
		with pytest.raises(ValueError):
			csp.parse_extra(text)


class TestHeader:
	def test_modes(self):
		assert csp.header("Report only", "v") == {"Content-Security-Policy-Report-Only": "v"}
		assert csp.header("Enforce", "v") == {"Content-Security-Policy": "v"}
		assert csp.header("", "v") == {}
