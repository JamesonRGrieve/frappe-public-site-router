# SPDX-License-Identifier: AGPL-3.0-or-later
"""Unit tests for App Hosts' pure logic: host and route rules, which requests an app host redirects, the open-redirect
guard, the handoff URLs and the desk's app links (no bench)."""

from urllib.parse import parse_qs, urlsplit

import pytest

from public_site_router import app_routing
from public_site_router.app_routing import AppHost, RequestAction

CRM = AppHost(host="crm.omg.test", app_route="crm", login_host="erp.omg.test", label="CRM")
HR = AppHost(host="hr.omg.test", app_route="hr", login_host="erp.omg.test")
OTHER = AppHost(host="crm.zx.test", app_route="crm", login_host="erp.zx.test")
APP_HOSTS = {app_host.host: app_host for app_host in (CRM, HR, OTHER)}
BROWSER_ACCEPT = "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"
STATE = "s" * 32


def action(path, method="GET", is_guest=True, accept=BROWSER_ACCEPT, is_ajax=False):
	return app_routing.request_action(CRM, method, path, is_guest=is_guest, accept=accept, is_ajax=is_ajax)


class TestHosts:
	@pytest.mark.parametrize(
		("raw", "host"),
		[
			("CRM.OMG.test", "crm.omg.test"),
			("crm.omg.test:443", "crm.omg.test"),
			(" crm.omg.test. ", "crm.omg.test"),
		],
	)
	def test_normalize_host(self, raw, host):
		assert app_routing.normalize_host(raw) == host

	def test_normalize_host_of_nothing(self):
		assert app_routing.normalize_host(None) == ""

	@pytest.mark.parametrize("host", ["crm.obsessedmediagroup.ca", "a.b", "x-1.example.com"])
	def test_valid_host(self, host):
		assert app_routing.valid_host(host)

	@pytest.mark.parametrize(
		"host",
		[
			"",
			"localhost",
			"crm.omg.test/evil",
			"https://crm.omg.test",
			"user@crm.omg.test",
			"-a.test",
			"a..test",
		],
	)
	def test_invalid_host(self, host):
		assert not app_routing.valid_host(host)


class TestAppRoute:
	@pytest.mark.parametrize(("raw", "route"), [("/CRM/", "crm"), (" hr ", "hr"), (None, "")])
	def test_normalize(self, raw, route):
		assert app_routing.normalize_app_route(raw) == route

	@pytest.mark.parametrize("route", ["crm", "hr", "lms", "insights", "builder", "my_app", "app-2"])
	def test_valid(self, route):
		assert app_routing.valid_app_route(route)

	@pytest.mark.parametrize("route", ["", "crm/leads", "-crm", "CRM", "c rm"])
	def test_not_one_lowercase_segment(self, route):
		assert not app_routing.valid_app_route(route)

	@pytest.mark.parametrize("route", sorted(app_routing.RESERVED_ROUTES))
	def test_frappe_routes_are_reserved(self, route):
		assert not app_routing.valid_app_route(route)

	@pytest.mark.parametrize("path", ["/crm", "/crm/", "/crm/leads/CRM-LEAD-1"])
	def test_app_path(self, path):
		assert app_routing.is_app_path(path, "crm")

	@pytest.mark.parametrize("path", ["/", "/crmx", "/hr/crm", "/api/method/crm", "crm"])
	def test_not_app_path(self, path):
		assert not app_routing.is_app_path(path, "crm")


class TestRequestAction:
	@pytest.mark.parametrize("is_guest", [True, False])
	@pytest.mark.parametrize("method", ["GET", "HEAD", "get"])
	def test_root_opens_the_app(self, is_guest, method):
		assert action("/", method=method, is_guest=is_guest) is RequestAction.ROOT

	@pytest.mark.parametrize("path", ["/crm", "/crm/leads", "/crm/leads/view/list"])
	def test_signed_out_app_page_is_handed_off(self, path):
		assert action(path) is RequestAction.HANDOFF

	def test_signed_in_app_page_passes(self):
		assert action("/crm/leads", is_guest=False) is None

	@pytest.mark.parametrize("method", ["POST", "PUT", "DELETE", "OPTIONS"])
	def test_non_navigation_passes(self, method):
		assert action("/crm", method=method) is None
		assert action("/", method=method) is None

	@pytest.mark.parametrize(
		"path",
		[
			"/api/method/crm.api.session.get_users",
			"/api/method/public_site_router.app_hosts.accept",
			"/api/method/public_site_router.app_hosts.handoff",
			"/assets/crm/frontend/assets/index.js",
			"/files/logo.png",
			"/private/files/x.pdf",
			"/socket.io/",
			"/desk",
			"/app/lead",
			"/login",
			"/hr",
		],
	)
	def test_everything_else_passes(self, path):
		assert action(path) is None

	def test_api_like_requests_pass(self):
		assert action("/crm", accept="application/json") is None
		assert action("/crm", is_ajax=True) is None

	@pytest.mark.parametrize("accept", [None, "", "*/*", "text/html", "application/xhtml+xml"])
	def test_page_requests_are_handed_off(self, accept):
		assert action("/crm", accept=accept) is RequestAction.HANDOFF


class TestNextPath:
	@pytest.mark.parametrize("path", ["/crm", "/crm/leads?view=list&x=1", "/crm#top", "/hr"])
	def test_same_host_paths_are_kept(self, path):
		assert app_routing.is_safe_relative_path(path)
		assert app_routing.safe_next_path(path, "crm") == path

	@pytest.mark.parametrize(
		"value",
		[
			None,
			"",
			"crm",
			"//evil.test/crm",
			"/\\evil.test",
			"/crm\\..\\x",
			"https://evil.test/crm",
			"javascript:alert(1)",
			"/\t/evil.test",
			"/\n/evil.test",
			"/ /evil.test",
			"\x00/crm",
			"/crm\x7f",
		],
	)
	def test_anything_else_falls_back_to_the_app(self, value):
		assert not app_routing.is_safe_relative_path(value)
		assert app_routing.safe_next_path(value, "crm") == "/crm"

	def test_path_with_query(self):
		assert (
			app_routing.path_with_query("/crm/leads", "view=list&q=a%20b") == "/crm/leads?view=list&q=a%20b"
		)
		assert app_routing.path_with_query("/crm", "") == "/crm"

	def test_decoded_path_is_quoted_again(self):
		assert app_routing.path_with_query("/crm/a b/%", "") == "/crm/a%20b/%25"
		assert app_routing.path_with_query("", "") == "/"


class TestHandoffUrls:
	def test_handoff_url_names_the_login_host_and_round_trips(self):
		url = urlsplit(app_routing.handoff_url(CRM, "/crm/leads?view=list&a=b", STATE))
		assert (url.scheme, url.netloc, url.path) == (
			"https",
			"erp.omg.test",
			"/api/method/public_site_router.app_hosts.handoff",
		)
		assert parse_qs(url.query) == {
			"target": ["crm.omg.test"],
			"next": ["/crm/leads?view=list&a=b"],
			"state": [STATE],
		}

	def test_handoff_path_is_relative_for_the_login_page(self):
		path = app_routing.handoff_path("crm.omg.test", "/crm", STATE)
		assert path.startswith("/api/method/public_site_router.app_hosts.handoff?")
		assert app_routing.is_safe_relative_path(path)

	def test_login_path_carries_the_handoff_as_redirect_to(self):
		handoff = app_routing.handoff_path("crm.omg.test", "/crm?x=1&y=2", STATE)
		url = urlsplit(app_routing.login_path(handoff))
		assert url.path == "/login"
		assert parse_qs(url.query) == {"redirect-to": [handoff]}

	def test_accept_url_names_the_app_host(self):
		url = urlsplit(app_routing.accept_url("crm.omg.test", "tok-en_1"))
		assert (url.scheme, url.netloc, url.path) == (
			"https",
			"crm.omg.test",
			"/api/method/public_site_router.app_hosts.accept",
		)
		assert parse_qs(url.query) == {"token": ["tok-en_1"]}

	@pytest.mark.parametrize("state", ["a" * 16, "A-b_c" * 8])
	def test_valid_state(self, state):
		assert app_routing.valid_state(state)

	@pytest.mark.parametrize(
		"state", [None, "", "short", "a" * 15, "a" * 129, "a" * 20 + "=", "a" * 20 + "/"]
	)
	def test_invalid_state(self, state):
		assert not app_routing.valid_state(state)


class TestAppLinks:
	def test_login_host_links_its_own_apps(self):
		assert app_routing.app_links(APP_HOSTS, "erp.omg.test") == {
			"crm": "crm.omg.test",
			"hr": "hr.omg.test",
		}

	def test_app_host_links_its_login_hosts_apps(self):
		assert app_routing.app_links(APP_HOSTS, "hr.omg.test") == {"crm": "crm.omg.test", "hr": "hr.omg.test"}
		assert app_routing.app_links(APP_HOSTS, "crm.zx.test") == {"crm": "crm.zx.test"}

	def test_other_hosts_keep_frappes_links(self):
		assert app_routing.app_links(APP_HOSTS, "obsessedmediagroup.test") == {}
		assert app_routing.app_links(APP_HOSTS, "") == {}
		assert app_routing.app_links({}, "erp.omg.test") == {}

	@pytest.mark.parametrize(
		("route", "url"),
		[
			("/crm", "https://crm.omg.test/crm"),
			("/crm/leads?x=1", "https://crm.omg.test/crm/leads?x=1"),
			("/hr", "https://hr.omg.test/hr"),
		],
	)
	def test_app_routes_move_to_their_host(self, route, url):
		assert app_routing.rewrite_route(route, {"crm": "crm.omg.test", "hr": "hr.omg.test"}) == url

	@pytest.mark.parametrize("route", ["/desk", "/lms", "", None, "https://frappe.io/crm", "//crm", "/crmx"])
	def test_other_routes_are_unchanged(self, route):
		assert app_routing.rewrite_route(route, {"crm": "crm.omg.test"}) == route

	def test_rewrite_apps_copies(self):
		apps = [{"name": "crm", "route": "/crm"}, {"name": "erpnext", "route": "/desk"}, {"name": "x"}]
		rewritten = app_routing.rewrite_apps(apps, "route", {"crm": "crm.omg.test"})
		assert rewritten == [
			{"name": "crm", "route": "https://crm.omg.test/crm"},
			{"name": "erpnext", "route": "/desk"},
			{"name": "x"},
		]
		assert apps[0] == {"name": "crm", "route": "/crm"}
		assert all(new is not old for new, old in zip(rewritten, apps, strict=True))
