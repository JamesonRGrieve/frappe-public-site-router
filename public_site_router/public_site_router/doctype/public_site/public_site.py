# SPDX-License-Identifier: AGPL-3.0-or-later
import re

import frappe
from frappe import _
from frappe.model.document import Document

from public_site_router.router import clear_site_map, normalize_host

PREFIX_PATTERN = re.compile(r"^[a-z0-9][a-z0-9-]*$")


class PublicSite(Document):
	def validate(self):
		self.validate_route_prefix()
		self.normalize_domains()
		self.validate_unique_domains()
		self.validate_webshop_store()
		self.validate_blog_category()
		self.home_route = self.home_route.strip("/")

	def on_update(self):
		clear_site_map()

	def on_trash(self):
		clear_site_map()

	def validate_route_prefix(self):
		self.route_prefix = (self.route_prefix or "").strip("/").lower()
		if not PREFIX_PATTERN.match(self.route_prefix):
			frappe.throw(_("Route Prefix must be one URL segment of lowercase letters, digits and dashes."))

	def normalize_domains(self):
		for row in self.domains:
			row.domain = normalize_host(row.domain)

	def validate_unique_domains(self):
		mine = [row.domain for row in self.domains]
		if len(mine) != len(set(mine)):
			frappe.throw(_("A domain is listed twice on this site."))
		taken = frappe.get_all(
			"Public Site Domain",
			filters={"parenttype": "Public Site", "parent": ["!=", self.name], "domain": ["in", mine]},
			fields=["domain", "parent"],
		)
		if taken:
			frappe.throw(
				_("Domain {0} already belongs to site {1}.").format(taken[0].domain, taken[0].parent)
			)

	def validate_webshop_store(self):
		if not self.webshop_store:
			return
		if not frappe.db.table_exists("Webshop Store"):
			frappe.throw(_("Webshop Store needs the frappe-webshop fork installed."))
		if not frappe.db.exists("Webshop Store", self.webshop_store):
			frappe.throw(_("Webshop Store {0} does not exist.").format(self.webshop_store))

	def validate_blog_category(self):
		if not self.blog_category:
			return
		if not frappe.db.table_exists("Blog Category"):
			frappe.throw(_("Blog Category needs the blog app installed."))
		if not frappe.db.exists("Blog Category", self.blog_category):
			frappe.throw(_("Blog Category {0} does not exist.").format(self.blog_category))
		taken = frappe.db.get_value(
			"Public Site", {"blog_category": self.blog_category, "name": ["!=", self.name]}, "name"
		)
		if taken:
			frappe.throw(
				_("Blog Category {0} already belongs to site {1}.").format(self.blog_category, taken)
			)
