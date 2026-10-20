# SPDX-License-Identifier: AGPL-3.0-or-later
"""App Hosts: this site's apps on their own host names, one sign-in for all (``app_routing`` holds the pure logic).

* ``before_request`` hook, on an enabled App Host: ``/`` redirects to the app's route, and a signed-out visitor
  opening one of the app's pages is sent to ``handoff`` on the login host, carrying a fresh anti-forgery state that
  is also kept in a host-only cookie on the app host.
* ``handoff`` (login host): a signed-out visitor goes through the normal login page and comes back; a signed-in one
  gets a single-use token (60 s, bound to the app host and the state) and is sent to ``accept`` on the app host.
* ``accept`` (app host): takes the token (atomically, so it works once), checks its host and state, resumes the
  session it names through Frappe's own LoginManager (which validates the session and sets Frappe's own cookies,
  host-only, on this host), and sends the visitor on to the page they asked for.
* ``update_website_context`` hook and the ``frappe.apps.get_apps`` override: on a login host or an app host, the
  desk's apps screen, app switcher and Frappe apps' own app menus link each app with an App Host on that host.

Logging out deletes the session server-side, so every host's cookie for it stops working at once."""

import hmac
import json
import secrets

import frappe
import werkzeug.utils
from frappe import _
from frappe.apps import get_apps as frappe_get_apps
from frappe.auth import LoginManager, clear_cookies
from werkzeug.exceptions import HTTPException

from public_site_router import app_routing
from public_site_router.app_routing import AppHost, RequestAction, normalize_host

APP_HOST_MAP_CACHE_KEY = "public_site_router_app_host_map"
HANDOFF_TOKEN_CACHE_PREFIX = "public_site_router_app_host_handoff:"
HANDOFF_TOKEN_TTL_SECONDS = 60
HANDOFF_TOKEN_BYTES = 32
STATE_COOKIE = "psr_handoff_state"
STATE_BYTES = 24
STATE_COOKIE_MAX_AGE_SECONDS = 15 * 60
HTTP_FOUND = 302
HTTP_FORBIDDEN = 403
GUEST = "Guest"


def get_app_hosts() -> dict[str, AppHost]:
	"""``{host: AppHost}`` for every enabled App Host."""

	def build():
		# Installed but not yet migrated: no App Hosts rather than failing every request. Not cached.
		if not frappe.db.table_exists("App Host"):
			return None
		rows = frappe.get_all(
			"App Host", filters={"enabled": 1}, fields=["host", "app_route", "login_host", "label"]
		)
		return {
			row.host: {
				"host": row.host,
				"app_route": row.app_route,
				"login_host": row.login_host,
				"label": row.label or "",
			}
			for row in rows
		}

	hosts = frappe.cache.get_value(APP_HOST_MAP_CACHE_KEY, build) or {}
	return {host: AppHost(**values) for host, values in hosts.items()}


def clear_app_host_map() -> None:
	frappe.cache.delete_value(APP_HOST_MAP_CACHE_KEY)


def get_request_host() -> str:
	request = getattr(frappe.local, "request", None)
	return normalize_host(request.host) if request else ""


def redirect_now(location: str) -> HTTPException:
	"""An exception whose response is a redirect: what a ``before_request`` hook raises to answer the request itself
	(frappe.app.application turns a raised Werkzeug HTTPException into its response)."""
	return HTTPException(response=werkzeug.utils.redirect(location, HTTP_FOUND))


def redirect(location: str) -> None:
	"""Answer this whitelisted method with a redirect (frappe.utils.response's ``redirect`` response type)."""
	frappe.local.response["type"] = "redirect"
	frappe.local.response["location"] = location


def deny() -> None:
	frappe.respond_as_web_page(
		_("Not Permitted"),
		_("This sign-in link is invalid or has expired. Open the app again to sign in."),
		http_status_code=HTTP_FORBIDDEN,
		indicator_color="red",
	)


def handoff_state() -> str:
	"""The app host's anti-forgery state: the one its cookie already holds (so two tabs share it), else a new one,
	kept in a host-only cookie for the handoff to come back to."""
	state = frappe.local.request.cookies.get(STATE_COOKIE)
	if not app_routing.valid_state(state):
		state = secrets.token_urlsafe(STATE_BYTES)
	frappe.local.cookie_manager.set_cookie(
		STATE_COOKIE, state, max_age=STATE_COOKIE_MAX_AGE_SECONDS, httponly=True
	)
	return state


def before_request() -> None:
	"""before_request hook: on an enabled App Host, ``/`` is the app and a signed-out visitor is handed off."""
	request = frappe.local.request
	app_host = get_app_hosts().get(get_request_host())
	if not app_host:
		return
	action = app_routing.request_action(
		app_host,
		request.method,
		request.path,
		is_guest=frappe.session.user == GUEST,
		accept=request.headers.get("Accept"),
		is_ajax=bool(frappe.local.is_ajax),
	)
	query = request.query_string.decode("latin-1")
	if action is RequestAction.ROOT:
		raise redirect_now(app_routing.path_with_query(app_host.root, query))
	if action is RequestAction.HANDOFF:
		next_path = app_routing.path_with_query(request.path, query)
		raise redirect_now(app_routing.handoff_url(app_host, next_path, handoff_state()))


def token_cache_key(token: str) -> bytes:
	return frappe.cache.make_key(f"{HANDOFF_TOKEN_CACHE_PREFIX}{token}")


def store_token(payload: dict) -> str:
	"""A new single-use token for ``payload``, expiring in HANDOFF_TOKEN_TTL_SECONDS. Stored in Redis directly (not
	frappe.cache.set_value, which also keeps the value in this request's local cache)."""
	token = secrets.token_urlsafe(HANDOFF_TOKEN_BYTES)
	frappe.cache.set(token_cache_key(token), json.dumps(payload), ex=HANDOFF_TOKEN_TTL_SECONDS)
	return token


def take_token(token: str) -> dict | None:
	"""The payload of ``token``, deleted in the same Redis command (GETDEL), so a token works once."""
	if not token:
		return None
	value = frappe.cache.getdel(token_cache_key(token))
	return json.loads(value) if value else None


@frappe.whitelist(allow_guest=True, methods=["GET"])
def handoff(target: str, next: str = "", state: str = "") -> None:
	"""On the login host: send a signed-in visitor back to ``target`` (an App Host of this login host) with a
	single-use token for their session; a signed-out one signs in first and comes back here. ``next`` is the
	query parameter's name (the page to open on the app host)."""
	app_host = get_app_hosts().get(normalize_host(target))
	if not app_host or app_host.login_host != get_request_host() or not app_routing.valid_state(state):
		return deny()
	next_path = app_routing.safe_next_path(next, app_host.app_route)
	if frappe.session.user == GUEST:
		# Frappe's login page keeps redirect-to through password, email-link and social (OAuth state) sign-in.
		return redirect(app_routing.login_path(app_routing.handoff_path(app_host.host, next_path, state)))
	token = store_token(
		{
			"sid": frappe.session.sid,
			"user": frappe.session.user,
			"target": app_host.host,
			"next": next_path,
			"state": state,
		}
	)
	redirect(app_routing.accept_url(app_host.host, token))


@frappe.whitelist(allow_guest=True, methods=["GET"])
def accept(token: str) -> None:
	"""On an App Host: sign the visitor in here to the session a ``handoff`` token names, then open their page."""
	payload = take_token(token)
	host = get_request_host()
	app_host = get_app_hosts().get(host)
	cookie_state = frappe.local.request.cookies.get(STATE_COOKIE) or ""
	if (
		not payload
		or not app_host
		or payload.get("target") != host
		or not app_routing.valid_state(cookie_state)
		or not hmac.compare_digest(str(payload.get("state") or "").encode(), cookie_state.encode())
	):
		return deny()
	# Frappe's own resume path (as frappe.www.login.login_via_token does): Session reads the sid from form_dict and
	# validates it (expiry, session end, IP restriction); set_user_info sets sid and the companion cookies.
	frappe.local.form_dict.sid = payload["sid"]
	frappe.local.login_manager = LoginManager()
	if frappe.session.user != payload.get("user") or frappe.session.user == GUEST:
		clear_cookies()
		return deny()
	cookie_manager = frappe.local.cookie_manager
	# This request started signed out; if it carried a stale sid, Frappe queued the old cookies for deletion, and
	# flush_cookies writes deletions after the cookies it sets, which would delete the new session's cookies too.
	cookie_manager.to_delete = [key for key in cookie_manager.to_delete if key not in cookie_manager.cookies]
	cookie_manager.delete_cookie(STATE_COOKIE)
	redirect(app_routing.safe_next_path(payload.get("next"), app_host.app_route))


def request_app_links() -> tuple[dict[str, str], str | None]:
	"""The request's ``(app links, fallback host)``: see ``app_routing.app_links`` and ``app_routing.fallback_host``."""
	app_hosts, host = get_app_hosts(), get_request_host()
	return app_routing.app_links(app_hosts, host), app_routing.fallback_host(app_hosts, host)


def update_website_context(context) -> None:
	"""update_website_context hook: on a login or app host, the boot data the desk (``app_data``: apps screen and app
	switcher) and website pages (``apps_data``) render from links each app with an App Host on that host, and on an
	app host every other app on the login host."""
	boot = context.get("boot")
	links, fallback = request_app_links() if boot else ({}, None)
	if not links:
		return
	boot = frappe._dict(boot)
	if boot.get("app_data"):
		boot.app_data = app_routing.rewrite_apps(boot.app_data, "app_route", links, fallback)
	apps_data = boot.get("apps_data")
	if apps_data and apps_data.get("apps"):
		boot.apps_data = {
			**apps_data,
			"apps": app_routing.rewrite_apps(apps_data["apps"], "route", links, fallback),
		}
	context.boot = boot


@frappe.whitelist()
def get_apps() -> list[dict]:
	"""Override of ``frappe.apps.get_apps`` (the app menus of Frappe's own app frontends, e.g. CRM's), with each app
	that has an App Host linked on that host, and on an app host every other app on the login host."""
	links, fallback = request_app_links()
	return app_routing.rewrite_apps(frappe_get_apps(), "route", links, fallback)


@frappe.whitelist()
def get_builder_apps() -> list[dict]:
	"""Override of ``builder.api.get_apps`` (Builder's own app menu, which lists Desk as ``/app``), rewritten the same
	way. Builder's result is Redis-cached across hosts, so it is rewritten after the cache, per request."""
	from builder.api import get_apps as builder_get_apps

	links, fallback = request_app_links()
	return app_routing.rewrite_apps(builder_get_apps(), "route", links, fallback)
