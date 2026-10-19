# SPDX-License-Identifier: AGPL-3.0-or-later
"""App Hosts against a real test site: validation, the app host's redirects (before_request), the handoff on the
login host (signed-out visitors sign in first; only the login host of a configured target may hand off), the accept
endpoint on the app host (single-use, expiring token bound to its host and the anti-forgery state; Frappe's own
session cookies set host-only) and the desk's app links."""

import time
from urllib.parse import parse_qs, urlsplit

import frappe
from frappe.auth import CookieManager, LoginManager
from frappe.sessions import delete_session, get_expiry_in_seconds
from frappe.tests.utils import FrappeTestCase
from werkzeug.exceptions import HTTPException
from werkzeug.test import EnvironBuilder
from werkzeug.wrappers import Request, Response

from public_site_router import app_hosts, app_routing

LOGIN_HOST = "erp.apphost.test"
CRM_HOST = "crm.apphost.test"
HR_HOST = "hr.apphost.test"
SITE_HOST = "apphost.test"
SITE = "_Test App Host Site"
STATE = "S" * 32
BROWSER_ACCEPT = "text/html,application/xhtml+xml,*/*;q=0.8"
USER = "Administrator"


def on_request(host, path="/", method="GET", query="", cookies=None, accept=BROWSER_ACCEPT):
	"""Make the current request a real Werkzeug request (as Frappe serves it) with a fresh response and cookie jar."""
	headers = {"Accept": accept}
	if cookies:
		headers["Cookie"] = "; ".join(f"{key}={value}" for key, value in cookies.items())
	environ = EnvironBuilder(
		base_url=f"https://{host}", path=path, method=method, query_string=query, headers=headers
	).get_environ()
	frappe.local.request = Request(environ)
	frappe.local.request_ip = "127.0.0.1"
	frappe.local.is_ajax = False
	frappe.local.form_dict = frappe._dict(frappe.local.request.args.to_dict())
	frappe.local.response = frappe._dict({"docs": []})
	frappe.local.cookie_manager = CookieManager()


def as_guest():
	frappe.local.session = frappe._dict(user="Guest", sid="Guest", data=frappe._dict())


def make_app_host(host, app_route, login_host=LOGIN_HOST, enabled=1):
	if frappe.db.exists("App Host", host):
		frappe.delete_doc("App Host", host, force=True)
	return frappe.get_doc(
		{
			"doctype": "App Host",
			"host": host,
			"app_route": app_route,
			"login_host": login_host,
			"enabled": enabled,
		}
	).insert()


def response_location():
	assert frappe.local.response.get("type") == "redirect", frappe.local.response
	return frappe.local.response["location"]


class TestAppHost(FrappeTestCase):
	def setUp(self):
		frappe.set_user("Administrator")
		make_app_host(CRM_HOST, "crm")
		make_app_host(HR_HOST, "hr")
		app_hosts.clear_app_host_map()

	def tearDown(self):
		frappe.set_user("Administrator")
		for host in (CRM_HOST, HR_HOST, "lms.apphost.test"):
			if frappe.db.exists("App Host", host):
				frappe.delete_doc("App Host", host, force=True)
		if frappe.db.exists("Public Site", SITE):
			frappe.delete_doc("Public Site", SITE, force=True)
		# Signing in commits (Session.start), so the fixtures are removed and committed rather than rolled back.
		frappe.db.commit()
		app_hosts.clear_app_host_map()
		frappe.local.request = None

	def sign_in(self):
		"""A real session for USER on the login host, as the login page creates one; its sid."""
		on_request(LOGIN_HOST, "/login")
		as_guest()
		frappe.local.login_manager = LoginManager()
		frappe.local.login_manager.login_as(USER)
		return frappe.session.sid

	def mint_token(self, target=CRM_HOST, next_path="/crm/leads?view=list"):
		sid = self.sign_in()
		on_request(LOGIN_HOST, "/api/method/public_site_router.app_hosts.handoff")
		app_hosts.handoff(target=target, next=next_path, state=STATE)
		url = urlsplit(response_location())
		self.assertEqual((url.scheme, url.netloc), ("https", target))
		self.assertEqual(url.path, "/api/method/public_site_router.app_hosts.accept")
		return sid, parse_qs(url.query)["token"][0]

	def accept_on(self, host, token, state=STATE):
		on_request(
			host,
			"/api/method/public_site_router.app_hosts.accept",
			query=f"token={token}",
			cookies={app_hosts.STATE_COOKIE: state} if state else None,
		)
		as_guest()
		app_hosts.accept(token=token)

	def assert_denied(self):
		self.assertEqual(frappe.local.response.get("type"), "page")
		self.assertEqual(frappe.local.response.get("http_status_code"), app_hosts.HTTP_FORBIDDEN)
		self.assertNotEqual(frappe.local.cookie_manager.cookies.get("sid", {}).get("value"), self.sid)

	# Validation

	def test_host_and_route_are_normalised(self):
		doc = make_app_host("LMS.AppHost.test:443", "/LMS/", login_host="ERP.apphost.test")
		self.assertEqual(
			(doc.name, doc.host, doc.app_route, doc.login_host),
			("lms.apphost.test", "lms.apphost.test", "lms", "erp.apphost.test"),
		)

	def test_reserved_or_nested_route_rejected(self):
		for route in ("api", "assets", "desk", "crm/leads"):
			with self.assertRaises(frappe.ValidationError):
				make_app_host("lms.apphost.test", route)

	def test_login_host_must_differ(self):
		with self.assertRaises(frappe.ValidationError):
			make_app_host("lms.apphost.test", "lms", login_host="lms.apphost.test")

	def test_host_with_path_rejected(self):
		with self.assertRaises(frappe.ValidationError):
			make_app_host("lms.apphost.test", "lms", login_host="erp.apphost.test/evil")

	def test_app_route_once_per_login_host(self):
		with self.assertRaises(frappe.ValidationError):
			make_app_host("lms.apphost.test", "crm")

	def test_login_host_is_not_an_app_host(self):
		with self.assertRaises(frappe.ValidationError):
			make_app_host("lms.apphost.test", "lms", login_host=CRM_HOST)
		with self.assertRaises(frappe.ValidationError):
			make_app_host(LOGIN_HOST, "lms", login_host="other.apphost.test")

	def test_public_site_domain_and_app_host_exclude_each_other(self):
		frappe.get_doc(
			{
				"doctype": "Public Site",
				"site_name": SITE,
				"enabled": 1,
				"route_prefix": "apphost-test",
				"home_route": "home",
				"domains": [{"domain": SITE_HOST}],
			}
		).insert()
		with self.assertRaises(frappe.ValidationError):
			make_app_host(SITE_HOST, "lms")
		site = frappe.get_doc("Public Site", SITE)
		site.append("domains", {"domain": CRM_HOST})
		with self.assertRaises(frappe.ValidationError):
			site.save()

	# before_request on an app host

	def before_request(self, host, path, method="GET", query="", guest=True, accept=BROWSER_ACCEPT):
		on_request(host, path, method=method, query=query, accept=accept)
		if guest:
			as_guest()
		else:
			frappe.set_user(USER)
		try:
			app_hosts.before_request()
		except HTTPException as redirect:
			self.assertEqual(redirect.response.status_code, app_hosts.HTTP_FOUND)
			return redirect.response.headers["Location"]
		return None

	def test_root_opens_the_app_keeping_the_query(self):
		self.assertEqual(self.before_request(CRM_HOST, "/", query="utm=x"), "/crm?utm=x")
		self.assertEqual(self.before_request(CRM_HOST, "/", guest=False), "/crm")

	def test_signed_out_app_page_goes_to_the_login_host(self):
		location = urlsplit(self.before_request(CRM_HOST, "/crm/leads", query="view=list"))
		self.assertEqual((location.scheme, location.netloc), ("https", LOGIN_HOST))
		self.assertEqual(location.path, "/api/method/public_site_router.app_hosts.handoff")
		query = parse_qs(location.query)
		self.assertEqual(query["target"], [CRM_HOST])
		self.assertEqual(query["next"], ["/crm/leads?view=list"])
		state_cookie = frappe.local.cookie_manager.cookies[app_hosts.STATE_COOKIE]
		self.assertEqual(query["state"], [state_cookie["value"]])
		self.assertTrue(state_cookie["httponly"])
		self.assertTrue(state_cookie["secure"])

	def test_existing_state_is_kept(self):
		on_request(CRM_HOST, "/crm", cookies={app_hosts.STATE_COOKIE: STATE})
		as_guest()
		with self.assertRaises(HTTPException) as raised:
			app_hosts.before_request()
		self.assertEqual(
			parse_qs(urlsplit(raised.exception.response.headers["Location"]).query)["state"], [STATE]
		)

	def test_everything_else_passes_through(self):
		self.assertIsNone(self.before_request(CRM_HOST, "/crm", guest=False))
		self.assertIsNone(self.before_request(CRM_HOST, "/crm", method="POST"))
		self.assertIsNone(self.before_request(CRM_HOST, "/crm", accept="application/json"))
		for path in (
			"/api/method/crm.api.get",
			"/api/method/public_site_router.app_hosts.accept",
			"/assets/x.js",
		):
			self.assertIsNone(self.before_request(CRM_HOST, path))
		self.assertIsNone(self.before_request(LOGIN_HOST, "/"))
		self.assertIsNone(self.before_request("unrelated.apphost.test", "/crm"))

	def test_disabled_app_host_passes_through(self):
		frappe.db.set_value("App Host", CRM_HOST, "enabled", 0)
		app_hosts.clear_app_host_map()
		self.assertIsNone(self.before_request(CRM_HOST, "/"))

	# handoff on the login host

	def test_signed_out_handoff_goes_through_the_login_page(self):
		on_request(LOGIN_HOST, "/api/method/public_site_router.app_hosts.handoff")
		as_guest()
		app_hosts.handoff(target=CRM_HOST, next="/crm/leads", state=STATE)
		location = urlsplit(response_location())
		self.assertEqual((location.netloc, location.path), ("", "/login"))
		self.assertEqual(
			parse_qs(location.query)["redirect-to"],
			[app_routing.handoff_path(CRM_HOST, "/crm/leads", STATE)],
		)

	def test_handoff_only_on_the_targets_login_host(self):
		self.sid = self.sign_in()
		for host, target, state in (
			(CRM_HOST, CRM_HOST, STATE),  # on the app host itself
			("unrelated.apphost.test", CRM_HOST, STATE),
			(LOGIN_HOST, "lms.apphost.test", STATE),  # not an App Host
			(LOGIN_HOST, CRM_HOST, ""),  # no anti-forgery state
		):
			on_request(host, "/api/method/public_site_router.app_hosts.handoff")
			app_hosts.handoff(target=target, next="/crm", state=state)
			self.assert_denied()

	def test_handoff_ignores_an_off_host_next(self):
		self.sid, token = self.mint_token(next_path="https://evil.test/")
		self.accept_on(CRM_HOST, token)
		self.assertEqual(response_location(), "/crm")

	# accept on the app host

	def test_accept_signs_in_on_the_app_host(self):
		self.sid, token = self.mint_token()
		self.accept_on(CRM_HOST, token)
		self.assertEqual(response_location(), "/crm/leads?view=list")
		self.assertEqual(frappe.session.user, USER)
		self.assertEqual(frappe.session.sid, self.sid)
		cookies = frappe.local.cookie_manager.cookies
		sid = cookies["sid"]
		self.assertEqual(sid["value"], self.sid)
		self.assertTrue(sid["httponly"])
		self.assertTrue(sid["secure"])
		self.assertEqual(sid["samesite"], "Lax")
		self.assertEqual(sid["max_age"], get_expiry_in_seconds())
		self.assertEqual(cookies["system_user"]["value"], "yes")
		self.assertEqual(cookies["user_id"]["value"], USER)
		for name in ("full_name", "user_image", "user_lang"):
			self.assertIn(name, cookies)
			self.assertFalse(cookies[name]["httponly"])
		self.assertIn(app_hosts.STATE_COOKIE, frappe.local.cookie_manager.to_delete)
		self.assertNotIn("sid", frappe.local.cookie_manager.to_delete)

	def test_cookies_are_host_only(self):
		self.sid, token = self.mint_token()
		self.accept_on(CRM_HOST, token)
		response = Response()
		frappe.local.cookie_manager.flush_cookies(response)
		headers = response.headers.getlist("Set-Cookie")
		self.assertTrue(any(header.startswith("sid=") for header in headers))
		for header in headers:
			self.assertNotIn("domain=", header.lower())

	def test_token_works_once(self):
		self.sid, token = self.mint_token()
		self.accept_on(CRM_HOST, token)
		self.assertEqual(frappe.session.user, USER)
		self.accept_on(CRM_HOST, token)
		self.assert_denied()

	def test_token_expires(self):
		self.sid, token = self.mint_token()
		key = app_hosts.token_cache_key(token)
		self.assertLessEqual(frappe.cache.ttl(key), app_hosts.HANDOFF_TOKEN_TTL_SECONDS)
		frappe.cache.pexpire(key, 1)
		time.sleep(0.05)
		self.accept_on(CRM_HOST, token)
		self.assert_denied()

	def test_token_is_bound_to_its_host(self):
		self.sid, token = self.mint_token(target=CRM_HOST)
		self.accept_on(HR_HOST, token)
		self.assert_denied()
		# and spent by the attempt
		self.accept_on(CRM_HOST, token)
		self.assert_denied()

	def test_token_needs_the_app_hosts_state(self):
		self.sid, token = self.mint_token()
		self.accept_on(CRM_HOST, token, state="T" * 32)
		self.assert_denied()
		self.sid, token = self.mint_token()
		self.accept_on(CRM_HOST, token, state=None)
		self.assert_denied()

	def test_logged_out_session_is_not_resumed(self):
		self.sid, token = self.mint_token()
		delete_session(self.sid, user=USER, reason="User Manually Logged Out")
		self.accept_on(CRM_HOST, token)
		self.assert_denied()
		self.assertEqual(frappe.session.user, "Guest")

	def test_unknown_token_denied(self):
		self.sid = None
		self.accept_on(CRM_HOST, "not-a-token")
		self.assert_denied()

	# desk links

	def boot(self):
		return frappe._dict(
			app_data=[
				{"app_name": "crm", "app_route": "/crm"},
				{"app_name": "lms", "app_route": "/lms"},
				{"app_name": "erpnext", "app_route": "/desk"},
			],
			apps_data={
				"apps": [{"name": "crm", "route": "/crm"}, {"name": "hr", "route": "/hr"}],
				"is_desk_apps": 0,
			},
		)

	def test_desk_links_apps_on_their_hosts(self):
		for host in (LOGIN_HOST, HR_HOST):
			on_request(host, "/desk")
			context = frappe._dict(boot=self.boot())
			app_hosts.update_website_context(context)
			self.assertEqual(
				[app["app_route"] for app in context.boot.app_data],
				["https://crm.apphost.test/crm", "/lms", "/desk"],
			)
			self.assertEqual(
				[app["route"] for app in context.boot.apps_data["apps"]],
				["https://crm.apphost.test/crm", "https://hr.apphost.test/hr"],
			)

	def test_other_hosts_keep_frappes_links(self):
		on_request("unrelated.apphost.test", "/desk")
		boot = self.boot()
		context = frappe._dict(boot=boot)
		app_hosts.update_website_context(context)
		self.assertIs(context.boot, boot)
		self.assertEqual(context.boot.app_data[0]["app_route"], "/crm")
