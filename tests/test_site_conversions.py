# SPDX-License-Identifier: AGPL-3.0-or-later
"""The CRM Lead ``after_insert`` hook sets the pending-lead cookie only for a website lead on its own site's host,
on a site with GA4 (no bench: Frappe stubbed)."""

import importlib
import sys
import types

import pytest

from public_site_router import conversions


class Site(dict):
	name = "zephyrex.ca"


class Lead(dict):
	pass


class Cookies:
	def __init__(self):
		self.set = []

	def set_cookie(self, key, value, **opts):
		self.set.append((key, value, opts))


@pytest.fixture
def env(monkeypatch):
	state = types.SimpleNamespace(site=Site(ga4_measurement_id="G-B30D03ZZWZ"), cookies=Cookies())
	request = types.SimpleNamespace(scheme="http", headers={"X-Forwarded-Proto": "https"}, cookies={})
	frappe = types.ModuleType("frappe")
	frappe.local = types.SimpleNamespace(request=request, cookie_manager=state.cookies)
	frappe.form_dict = {"web_form": "contact-zephyrex-ca"}
	frappe.db = types.SimpleNamespace(get_value=lambda *_a: "Contact")
	state.logged = []
	frappe.log_error = lambda **kw: state.logged.append(kw)
	router = types.ModuleType("public_site_router.router")
	router.get_request_site = lambda: state.site
	monkeypatch.setitem(sys.modules, "frappe", frappe)
	monkeypatch.setitem(sys.modules, "public_site_router.router", router)
	monkeypatch.delitem(sys.modules, "public_site_router.site_conversions", raising=False)
	state.module = importlib.import_module("public_site_router.site_conversions")
	state.frappe, state.request = frappe, request
	return state


def lead(**change):
	return Lead({"public_site": "zephyrex.ca", "source": "Website", "email": "a@b.ca"} | change)


def test_a_website_lead_sets_the_cookie(env):
	env.module.lead_after_insert(lead())
	[(key, value, opts)] = env.cookies.set
	assert key == conversions.PENDING_COOKIE
	assert conversions.decode(value) == [conversions.lead_event("contact-zephyrex-ca", "Contact")]
	assert opts["httponly"] is False and opts["secure"] is True and opts["samesite"] == "Lax"


def test_leads_still_waiting_are_kept(env):
	env.request.cookies[conversions.PENDING_COOKIE] = conversions.append(
		None, conversions.lead_event("first")
	)
	env.module.lead_after_insert(lead())
	forms = [e["p"]["form_id"] for e in conversions.decode(env.cookies.set[0][1])]
	assert forms == ["first", "contact-zephyrex-ca"]


@pytest.mark.parametrize(
	"case",
	["no_request", "waitlist", "test_email", "other_source", "other_site", "no_site", "no_ga4"],
)
def test_nothing_otherwise(env, case):
	doc = lead()
	if case == "no_request":
		env.frappe.local.request = None
	elif case == "waitlist":
		env.frappe.form_dict["web_form"] = "waitlist-chronos"
	elif case == "test_email":
		doc = lead(email="zephyrex-site-test+r1-contact@example.com")
	elif case == "other_source":
		doc = lead(source="Email")
	elif case == "other_site":
		doc = lead(public_site="3shub.ca")
	elif case == "no_site":
		env.site = None
		sys.modules["public_site_router.router"].get_request_site = lambda: None
	elif case == "no_ga4":
		env.site["ga4_measurement_id"] = ""
	env.module.lead_after_insert(doc)
	assert env.cookies.set == []


@pytest.mark.parametrize("where", ["set_cookie", "site", "title"])
def test_a_failure_never_fails_the_lead(env, monkeypatch, where):
	def boom(*_a, **_k):
		raise TypeError("unexpected keyword argument")

	if where == "set_cookie":
		env.cookies.set_cookie = boom
	elif where == "site":
		monkeypatch.setattr(env.module, "get_request_site", boom)
	else:
		env.frappe.db.get_value = boom
	assert env.module.lead_after_insert(lead()) is None
	assert env.logged == [{"title": env.module.LOG_TITLE}]
