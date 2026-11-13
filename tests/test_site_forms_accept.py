# SPDX-License-Identifier: AGPL-3.0-or-later
"""The Web Form ``accept`` override hands Frappe only the arguments Frappe's own ``accept`` takes (no bench).

Frappe calls a whitelisted method with the whole ``form_dict``, so the override receives ``cmd`` and the Turnstile
token field too. Forwarding them made every guest Web Form submission fail with
``TypeError: accept() got an unexpected keyword argument 'cmd'`` (Boden ERP, 2026-11-12)."""

import importlib
import sys
import types

import pytest


def _strict_frappe_accept(web_form, data):
	"""Frappe v16's signature: exactly these two parameters."""
	return {"web_form": web_form, "data": data}


@pytest.fixture
def site_forms(monkeypatch):
	frappe = types.ModuleType("frappe")
	frappe.whitelist = lambda **_kw: lambda fn: fn
	frappe._ = lambda s: s
	frappe.form_dict = {}
	frappe.throw = lambda *a, **k: (_ for _ in ()).throw(RuntimeError(a[0] if a else ""))
	frappe.PermissionError = type("PermissionError", (Exception,), {})
	frappe.ValidationError = type("ValidationError", (Exception,), {})
	web_form = types.ModuleType("frappe.website.doctype.web_form.web_form")
	web_form.accept = _strict_frappe_accept
	modules = {
		"frappe": frappe,
		"frappe.website": types.ModuleType("frappe.website"),
		"frappe.website.doctype": types.ModuleType("frappe.website.doctype"),
		"frappe.website.doctype.web_form": types.ModuleType("frappe.website.doctype.web_form"),
		"frappe.website.doctype.web_form.web_form": web_form,
	}
	router = types.ModuleType("public_site_router.router")
	router.get_request_site = lambda: None  # a host with no Public Site: plain Frappe accept
	router.page_site_or_not_found = lambda _context: None
	chrome = types.ModuleType("public_site_router.chrome")
	chrome.add_head_html = lambda *_a: None
	modules["public_site_router.router"] = router
	modules["public_site_router.chrome"] = chrome
	for name, mod in modules.items():
		monkeypatch.setitem(sys.modules, name, mod)
	monkeypatch.delitem(sys.modules, "public_site_router.site_forms", raising=False)
	return importlib.import_module("public_site_router.site_forms")


def test_extra_form_dict_arguments_are_not_forwarded(site_forms):
	result = site_forms.accept(
		"lead-form", '{"email": "a@example.com"}', cmd="x", **{"cf-turnstile-response": "t"}
	)
	assert result == {"web_form": "lead-form", "data": '{"email": "a@example.com"}'}


def test_plain_call_is_frappes_accept(site_forms):
	assert site_forms.accept("lead-form", "{}") == {"web_form": "lead-form", "data": "{}"}
