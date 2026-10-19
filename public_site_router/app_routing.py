# SPDX-License-Identifier: AGPL-3.0-or-later
"""App Hosts (pure logic; ``app_hosts`` applies it): one Frappe site's apps on their own host names, with one sign-in.

An App Host is a host name (``crm.example.com``) that serves one app's route (``/crm``) of the site whose desk and
sign-in live on its login host (``erp.example.com``). Frappe's ``sid`` cookie stays host-only, so a visitor without a
session on an app host is handed off: the app host sends them to the login host, which (once they are signed in)
mints a single-use token bound to the app host and sends them back to the app host's accept endpoint, which sets the
cookies for the same server-side session there.

Host names and routes are normalised here; requests are classified here; every URL of the flow is built here."""

import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from enum import Enum
from urllib.parse import quote, urlencode, urlsplit

APP_HOST_SCHEME = "https"
HANDOFF_METHOD = "public_site_router.app_hosts.handoff"
ACCEPT_METHOD = "public_site_router.app_hosts.accept"
API_METHOD_PATH = "/api/method/"
LOGIN_PATH = "/login"
# Methods a page navigation uses; anything else (the app's own POSTs, OPTIONS preflights) passes through.
NAVIGATION_METHODS = frozenset({"GET", "HEAD"})
# An Accept header naming one of these asks for a page (a browser navigation); the app's API calls ask for JSON.
HTML_MEDIA_TYPES = ("text/html", "application/xhtml+xml", "*/*")
# First path segments Frappe serves itself on every host; an app route may not take one of them, which also keeps the
# handoff/accept endpoints, assets, files and the socket.io endpoint out of the redirect.
RESERVED_ROUTES = frozenset(
	{
		"api",
		"app",
		"apps",
		"assets",
		"backups",
		"desk",
		"files",
		"login",
		"logout",
		"me",
		"private",
		"socket.io",
		"update-password",
		".well-known",
	}
)
APP_ROUTE_PATTERN = re.compile(r"^[a-z0-9][a-z0-9_-]*$")
HOST_LABEL = r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?"
HOST_PATTERN = re.compile(rf"^{HOST_LABEL}(?:\.{HOST_LABEL})+$")
# The anti-forgery state the app host keeps in a cookie and the handoff carries (secrets.token_urlsafe output).
STATE_PATTERN = re.compile(r"^[A-Za-z0-9_-]{16,128}$")
# Characters kept as they are when a request path is put back into a URL (RFC 3986 pchar plus "/").
PATH_SAFE = "/:@!$&'()*+,;=-._~"


@dataclass(frozen=True)
class AppHost:
	host: str
	app_route: str
	login_host: str
	label: str = ""

	@property
	def root(self) -> str:
		return f"/{self.app_route}"


class RequestAction(Enum):
	ROOT = "root"  # ``/`` on an app host: the app's own route
	HANDOFF = "handoff"  # a signed-out visitor opening the app: sign in on the login host


def normalize_host(host: str | None) -> str:
	return (host or "").split(":", 1)[0].strip().lower().rstrip(".")


def valid_host(host: str) -> bool:
	"""A plain DNS host name (no scheme, port, path or user info), so it can be put into a URL as is."""
	return bool(HOST_PATTERN.match(host))


def normalize_app_route(route: str | None) -> str:
	return (route or "").strip().strip("/").lower()


def valid_app_route(route: str) -> bool:
	"""One lowercase URL segment that Frappe does not serve itself."""
	return bool(APP_ROUTE_PATTERN.match(route)) and route not in RESERVED_ROUTES


def valid_state(state: str | None) -> bool:
	return bool(state and STATE_PATTERN.match(state))


def is_app_path(path: str, app_route: str) -> bool:
	return path == f"/{app_route}" or path.startswith(f"/{app_route}/")


def accepts_html(accept: str | None) -> bool:
	"""Whether a request with this Accept header wants a page. A request that names none is treated as one."""
	accept = (accept or "").lower()
	return not accept.strip() or any(media_type in accept for media_type in HTML_MEDIA_TYPES)


def request_action(
	app_host: AppHost,
	method: str,
	path: str,
	is_guest: bool,
	accept: str | None,
	is_ajax: bool,
) -> RequestAction | None:
	"""What an app host does with a request before Frappe handles it; None passes it through unchanged."""
	if method.upper() not in NAVIGATION_METHODS:
		return None
	if path in ("", "/"):
		return RequestAction.ROOT
	if is_guest and not is_ajax and accepts_html(accept) and is_app_path(path, app_host.app_route):
		return RequestAction.HANDOFF
	return None


def is_safe_relative_path(value: str | None) -> bool:
	"""A path on the same host: starts with one ``/``, names no scheme or host, and holds nothing a browser would
	read as one (a backslash, which it treats as ``/``, or a control character or space, which it strips)."""
	if not value or not value.startswith("/") or value.startswith("//"):
		return False
	if "\\" in value or any(ord(char) <= 0x20 or ord(char) == 0x7F for char in value):
		return False
	url = urlsplit(value)
	return not (url.scheme or url.netloc)


def safe_next_path(value: str | None, app_route: str) -> str:
	"""``value`` when it is a same-host relative path, else the app's own route."""
	return value if is_safe_relative_path(value) else f"/{app_route}"


def path_with_query(path: str, query: str) -> str:
	"""A request's path (as decoded by Werkzeug) and raw query string, put back into a relative URL."""
	quoted = quote(path or "/", safe=PATH_SAFE)
	return f"{quoted}?{query}" if query else quoted


def handoff_path(target: str, next_path: str, state: str) -> str:
	"""The handoff endpoint on the login host, relative (what the login page's redirect-to accepts)."""
	query = urlencode({"target": target, "next": next_path, "state": state})
	return f"{API_METHOD_PATH}{HANDOFF_METHOD}?{query}"


def handoff_url(app_host: AppHost, next_path: str, state: str) -> str:
	return f"{APP_HOST_SCHEME}://{app_host.login_host}{handoff_path(app_host.host, next_path, state)}"


def login_path(redirect_to: str) -> str:
	return f"{LOGIN_PATH}?{urlencode({'redirect-to': redirect_to})}"


def accept_url(target: str, token: str) -> str:
	return f"{APP_HOST_SCHEME}://{target}{API_METHOD_PATH}{ACCEPT_METHOD}?{urlencode({'token': token})}"


def login_group(app_hosts: Mapping[str, AppHost], request_host: str) -> str | None:
	"""The login host whose apps a request belongs to: the request's own host when it is a login host, the app host's
	login host on an app host, else None (any other host, e.g. a public website)."""
	if request_host in app_hosts:
		return app_hosts[request_host].login_host
	if any(app_host.login_host == request_host for app_host in app_hosts.values()):
		return request_host
	return None


def app_links(app_hosts: Mapping[str, AppHost], request_host: str) -> dict[str, str]:
	"""``{app_route: host}`` for the App Hosts of the request's login group (empty outside one)."""
	group = login_group(app_hosts, request_host)
	if group is None:
		return {}
	return {
		app_host.app_route: app_host.host for app_host in app_hosts.values() if app_host.login_host == group
	}


def rewrite_route(route: str | None, links: Mapping[str, str]) -> str | None:
	"""A relative app route (``/crm`` or ``/crm/...``) of an app that has an App Host, as a URL on that host; any other
	route unchanged."""
	if not route or not is_safe_relative_path(route):
		return route
	segment = urlsplit(route).path.strip("/").split("/", 1)[0]
	host = links.get(segment)
	return f"{APP_HOST_SCHEME}://{host}{route}" if host else route


def rewrite_apps(apps: Iterable[Mapping], route_key: str, links: Mapping[str, str]) -> list[dict]:
	"""Copies of ``apps`` (Frappe's app lists) with each ``route_key`` rewritten by ``rewrite_route``."""
	return [
		{**app, route_key: rewrite_route(app.get(route_key), links)} if route_key in app else dict(app)
		for app in apps
	]
