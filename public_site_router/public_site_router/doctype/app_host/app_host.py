# SPDX-License-Identifier: AGPL-3.0-or-later
import frappe
from frappe import _
from frappe.model.document import Document

from public_site_router import app_routing
from public_site_router.app_hosts import clear_app_host_map
from public_site_router.app_routing import normalize_host


def public_site_of(host: str) -> str | None:
	"""The Public Site that has ``host`` among its domains, if any."""
	return frappe.db.get_value("Public Site Domain", {"parenttype": "Public Site", "domain": host}, "parent")


class AppHost(Document):
	def before_naming(self):
		# Named by its host, so normalise it before the name is taken from it.
		self.host = normalize_host(self.host)

	def validate(self):
		self.host = normalize_host(self.host)
		self.login_host = normalize_host(self.login_host)
		self.app_route = app_routing.normalize_app_route(self.app_route)
		self.label = (self.label or "").strip()
		for field in ("host", "login_host"):
			if not app_routing.valid_host(self.get(field)):
				frappe.throw(
					_("{0} must be a host name such as crm.example.com (no scheme, port or path).").format(
						self.meta.get_label(field)
					)
				)
		if not app_routing.valid_app_route(self.app_route):
			frappe.throw(
				_(
					"App Route must be one URL segment of lowercase letters, digits, dashes and underscores, "
					"and not one Frappe serves itself ({0})."
				).format(", ".join(sorted(app_routing.RESERVED_ROUTES)))
			)
		if self.login_host == self.host:
			frappe.throw(_("Login Host must be a different host from the app's own host."))
		self.validate_not_public_site()
		self.validate_login_hosts()
		self.validate_unique_route()

	def validate_not_public_site(self):
		for field in ("host", "login_host"):
			site = public_site_of(self.get(field))
			if site:
				frappe.throw(
					_("{0} {1} is a domain of Public Site {2}.").format(
						self.meta.get_label(field), self.get(field), site
					)
				)

	def validate_login_hosts(self):
		# A login host that were also an app host would hand its own sign-in off in a loop.
		others = {"name": ["!=", self.name]}
		if frappe.db.exists("App Host", {**others, "login_host": self.host}):
			frappe.throw(_("Host {0} is the Login Host of another App Host.").format(self.host))
		if frappe.db.exists("App Host", {**others, "host": self.login_host}):
			frappe.throw(_("Login Host {0} is itself an App Host.").format(self.login_host))

	def validate_unique_route(self):
		# The desk links each app route of a login host to one host.
		taken = frappe.db.get_value(
			"App Host",
			{"name": ["!=", self.name], "login_host": self.login_host, "app_route": self.app_route},
			"host",
		)
		if taken:
			frappe.throw(
				_("App Route {0} of Login Host {1} is already served on {2}.").format(
					self.app_route, self.login_host, taken
				)
			)

	def on_update(self):
		clear_app_host_map()

	def on_trash(self):
		clear_app_host_map()
