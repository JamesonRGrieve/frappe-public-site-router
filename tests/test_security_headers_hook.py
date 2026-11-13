# SPDX-License-Identifier: AGPL-3.0-or-later
"""The security_headers after_request hook on a site host (no bench: Frappe is stubbed).

The hook adds the security headers and the site's CSP, and keeps Frappe's script-readable session-info cookies off
a site host: dropped for a guest, HttpOnly for a signed-in user on a Standalone Pages site."""

import importlib
import sys
import types

import pytest


class Headers(dict):
	def keys(self):
		return list(super().keys())

	def update(self, other):
		for k, v in other.items():
			self[k] = v

	def setdefault(self, k, v):
		if k not in self:
			self[k] = v


class Response:
	def __init__(self):
		self.headers = Headers()


class Site(dict):
	def get(self, key, default=None):
		return super().get(key, default)


def info_cookies():
	return {
		name: {"value": "x", "httponly": False}
		for name in ("system_user", "full_name", "user_id", "user_lang")
	} | {"sid": {"value": "s", "httponly": True}}


@pytest.fixture
def load(monkeypatch):
	def _load(site, user="Guest"):
		frappe = types.ModuleType("frappe")
		frappe.local = types.SimpleNamespace(cookie_manager=types.SimpleNamespace(cookies=info_cookies()))
		frappe.session = types.SimpleNamespace(user=user)
		frappe.whitelist = lambda **_kw: lambda fn: fn
		path_resolver = types.ModuleType("frappe.website.path_resolver")
		path_resolver.resolve_path = lambda path: path
		for name, mod in {
			"frappe": frappe,
			"frappe.website": types.ModuleType("frappe.website"),
			"frappe.website.path_resolver": path_resolver,
		}.items():
			monkeypatch.setitem(sys.modules, name, mod)
		monkeypatch.delitem(sys.modules, "public_site_router.router", raising=False)
		router = importlib.import_module("public_site_router.router")
		monkeypatch.setattr(router, "get_request_site", lambda: site)
		return router, frappe

	return _load


def test_off_site_host_untouched(load):
	router, frappe = load(None)
	response = Response()
	router.security_headers(response, None)
	assert response.headers == {}
	assert "full_name" in frappe.local.cookie_manager.cookies


def test_guest_info_cookies_dropped_sid_kept(load):
	router, frappe = load(Site(security_headers=1))
	router.security_headers(Response(), None)
	assert set(frappe.local.cookie_manager.cookies) == {"sid"}


def test_signed_in_on_standalone_site_made_httponly(load):
	router, frappe = load(Site(security_headers=1, standalone_pages=1), user="editor@example.com")
	router.security_headers(Response(), None)
	cookies = frappe.local.cookie_manager.cookies
	assert all(cookies[n]["httponly"] for n in ("system_user", "full_name", "user_id", "user_lang"))


def test_report_only_csp_and_headers(load):
	router, _ = load(
		Site(security_headers=1, csp_mode="Report only", turnstile_site_key="0x4AAAAAAAB1cDeFgHiJkLmN")
	)
	response = Response()
	router.security_headers(response, None)
	assert "X-Frame-Options" in response.headers
	value = response.headers["Content-Security-Policy-Report-Only"]
	assert "challenges.cloudflare.com" in value
	assert "Content-Security-Policy" not in response.headers


def test_enforce(load):
	router, _ = load(Site(security_headers=1, csp_mode="Enforce"))
	response = Response()
	router.security_headers(response, None)
	assert "object-src 'none'" in response.headers["Content-Security-Policy"]


def test_security_headers_off_does_nothing(load):
	router, frappe = load(Site(security_headers=0, csp_mode="Enforce"))
	response = Response()
	router.security_headers(response, None)
	assert response.headers == {}
	assert "full_name" in frappe.local.cookie_manager.cookies
