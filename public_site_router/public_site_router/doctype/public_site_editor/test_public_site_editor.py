# SPDX-License-Identifier: AGPL-3.0-or-later
"""Site Editors against a real site with Builder installed: a user listed on one Public Site sees and changes only
that site's Builder Pages, Components, patterns, client scripts and snapshots; can't add Jinja or change a data
script; can't reach another site's documents through Builder's own methods; and a Website Manager is unaffected."""

import json
import unittest

import frappe
from frappe.tests.utils import FrappeTestCase

from public_site_router import site_editors

OWN = "_Test Editor Own Site"
OTHER = "_Test Editor Other Site"
EDITOR = "site-editor@psr.test"
OTHER_EDITOR = "other-editor@psr.test"
MANAGER = "website-manager@psr.test"
BLOCKS = json.dumps([{"blockId": "root", "element": "div", "children": [], "innerHTML": "Hello"}])
HAS_BUILDER = "builder" in frappe.get_installed_apps()


def make_user(email, roles):
	if not frappe.db.exists("User", email):
		frappe.get_doc(
			{"doctype": "User", "email": email, "first_name": email.split("@")[0], "send_welcome_email": 0}
		).insert()
	user = frappe.get_doc("User", email)
	user.set("roles", [])
	user.add_roles(*roles)
	return user


def make_site(name, prefix, domain, editors):
	if frappe.db.exists("Public Site", name):
		frappe.delete_doc("Public Site", name, force=True)
	return frappe.get_doc(
		{
			"doctype": "Public Site",
			"site_name": name,
			"enabled": 1,
			"route_prefix": prefix,
			"home_route": "home",
			"domains": [{"domain": domain}],
			"editors": [{"user": u} for u in editors],
		}
	).insert()


def make_page(route, owner="Administrator", **fields):
	frappe.set_user(owner)
	page = frappe.get_doc(
		{
			"doctype": "Builder Page",
			"page_title": route or "draft",
			"route": route,
			"blocks": BLOCKS,
			**fields,
		}
	)
	page.insert()
	frappe.set_user("Administrator")
	return page


def make_component(component_id, **fields):
	if frappe.db.exists("Builder Component", component_id):
		frappe.delete_doc("Builder Component", component_id, force=True)
	return frappe.get_doc(
		{
			"doctype": "Builder Component",
			"component_id": component_id,
			"component_name": component_id,
			"block": BLOCKS,
			**fields,
		}
	).insert()


def make_pattern(name):
	if frappe.db.exists("Block Template", name):
		frappe.delete_doc("Block Template", name, force=True)
	return frappe.get_doc(
		{
			"doctype": "Block Template",
			"template_name": name,
			"block": BLOCKS,
			"category": "Structure",
			"preview": "/files/p.png",
		}
	).insert()


def as_user(user):
	frappe.set_user(user)
	site_editors.clear_scope_cache()


@unittest.skipUnless(HAS_BUILDER, "Builder is not installed")
class TestSiteEditors(FrappeTestCase):
	def setUp(self):
		frappe.set_user("Administrator")
		site_editors.ensure_role()
		make_user(EDITOR, ["Site Editor"])
		make_user(OTHER_EDITOR, ["Site Editor"])
		make_user(MANAGER, ["Website Manager"])
		make_site(OWN, "own-test", "own.psr.test", [EDITOR])
		make_site(OTHER, "other-test", "other.psr.test", [OTHER_EDITOR])
		frappe.db.delete("Builder Page", {"route": ["like", "%-test%"]})
		self.own = make_page("own-test/home")
		self.preview = make_page("own-test-builder/home")
		self.other = make_page("other-test/home")
		site_editors.clear_scope_cache()

	def tearDown(self):
		frappe.set_user("Administrator")
		site_editors.clear_scope_cache()

	# ---- reading ----------------------------------------------------------------------------------------------

	def test_list_shows_only_own_sites_pages(self):
		as_user(EDITOR)
		routes = set(frappe.get_list("Builder Page", pluck="route"))
		self.assertIn("own-test/home", routes)
		self.assertIn("own-test-builder/home", routes)
		self.assertNotIn("other-test/home", routes)

	def test_other_sites_page_is_unreadable(self):
		as_user(EDITOR)
		self.assertTrue(frappe.has_permission("Builder Page", "read", self.own.name))
		self.assertFalse(frappe.has_permission("Builder Page", "read", self.other.name))
		with self.assertRaises(frappe.PermissionError):
			frappe.get_doc("Builder Page", self.other.name).check_permission("read")

	def test_website_manager_sees_every_site(self):
		as_user(MANAGER)
		routes = set(frappe.get_list("Builder Page", pluck="route"))
		self.assertTrue({"own-test/home", "other-test/home"} <= routes)

	def test_site_editor_role_alone_reaches_nothing(self):
		make_user("nobody-editor@psr.test", ["Site Editor"])
		as_user("nobody-editor@psr.test")
		self.assertFalse(frappe.has_permission("Builder Page", "read", self.own.name))
		self.assertFalse(
			{"own-test/home", "other-test/home"} & set(frappe.get_list("Builder Page", pluck="route"))
		)

	# ---- writing ----------------------------------------------------------------------------------------------

	def test_editor_saves_own_page(self):
		as_user(EDITOR)
		page = frappe.get_doc("Builder Page", self.own.name)
		page.page_title = "New title"
		page.save()
		self.assertEqual(frappe.db.get_value("Builder Page", self.own.name, "page_title"), "New title")

	def test_editor_cannot_save_other_sites_page(self):
		as_user(EDITOR)
		page = frappe.get_doc({**self.other.as_dict(), "page_title": "Hijacked"})
		with self.assertRaises(frappe.PermissionError):
			page.save()

	def test_editor_cannot_move_own_page_to_another_site(self):
		as_user(EDITOR)
		page = frappe.get_doc("Builder Page", self.own.name)
		page.route = "other-test/stolen"
		with self.assertRaises(frappe.PermissionError):
			page.save()

	def test_editor_cannot_pull_another_sites_page_into_own_prefix(self):
		# the new values pass the per-document check; the stored document must not
		as_user(EDITOR)
		page = frappe.get_doc({**self.other.as_dict(), "route": "own-test/taken"})
		with self.assertRaises(frappe.PermissionError):
			page.save()
		self.assertEqual(frappe.db.get_value("Builder Page", self.other.name, "route"), "other-test/home")

	def test_editor_creates_unrouted_page_only_they_see(self):
		draft = make_page(None, owner=EDITOR)
		as_user(OTHER_EDITOR)
		self.assertFalse(frappe.has_permission("Builder Page", "read", draft.name))
		as_user(EDITOR)
		self.assertTrue(frappe.has_permission("Builder Page", "write", draft.name))
		draft = frappe.get_doc("Builder Page", draft.name)
		draft.route = "own-test/new"
		draft.save()

	def test_editor_cannot_create_page_on_another_site(self):
		as_user(EDITOR)
		with self.assertRaises(frappe.PermissionError):
			frappe.get_doc(
				{"doctype": "Builder Page", "page_title": "x", "route": "other-test/x", "blocks": BLOCKS}
			).insert()

	# ---- server-side code ---------------------------------------------------------------------------------------

	def test_editor_cannot_add_jinja(self):
		as_user(EDITOR)
		page = frappe.get_doc("Builder Page", self.own.name)
		page.blocks = BLOCKS.replace("Hello", "{{ frappe.db.sql('select name from tabUser') }}")
		with self.assertRaises(frappe.PermissionError):
			page.save()
		page = frappe.get_doc("Builder Page", self.own.name)
		page.head_html = "{% set x = 1 %}"
		with self.assertRaises(frappe.PermissionError):
			page.save()

	def test_existing_jinja_may_stay(self):
		self.own.db_set("body_html", "<p>{{ title }}</p>")
		as_user(EDITOR)
		page = frappe.get_doc("Builder Page", self.own.name)
		page.body_html = "<div>{{ title }}</div>"
		page.save()

	def test_editor_cannot_change_page_data_script(self):
		as_user(EDITOR)
		page = frappe.get_doc("Builder Page", self.own.name)
		page.page_data_script = "data.users = frappe.get_all('User')"
		with self.assertRaises(frappe.PermissionError):
			page.save()

	def test_website_manager_may_add_jinja_and_scripts(self):
		as_user(MANAGER)
		page = frappe.get_doc("Builder Page", self.own.name)
		page.body_html = "<p>{{ title }}</p>"
		page.page_data_script = "data.x = 1"
		page.save()

	# ---- components, patterns, scripts, snapshots ----------------------------------------------------------------

	def test_components_by_site(self):
		make_component("own-test-header")
		make_component("other-test-header")
		as_user(EDITOR)
		names = set(frappe.get_list("Builder Component", pluck="name"))
		self.assertIn("own-test-header", names)
		self.assertNotIn("other-test-header", names)
		self.assertFalse(frappe.has_permission("Builder Component", "write", "other-test-header"))
		component = frappe.get_doc("Builder Component", "own-test-header")
		component.component_data_script = "data.x = frappe.get_all('User')"
		with self.assertRaises(frappe.PermissionError):
			component.save()

	def test_editor_cannot_name_a_component_for_another_site(self):
		as_user(EDITOR)
		with self.assertRaises(frappe.PermissionError):
			frappe.get_doc(
				{
					"doctype": "Builder Component",
					"component_id": "other-test-footer",
					"component_name": "x",
					"block": BLOCKS,
				}
			).insert()

	def test_patterns_by_site(self):
		make_pattern(f"{OWN} · Hero")
		make_pattern(f"{OTHER} · Hero")
		as_user(EDITOR)
		names = set(frappe.get_list("Block Template", pluck="name"))
		self.assertIn(f"{OWN} · Hero", names)
		self.assertNotIn(f"{OTHER} · Hero", names)

	def test_client_scripts_follow_the_pages_using_them(self):
		for name, page in (("_test-own-script", self.own), ("_test-other-script", self.other)):
			if not frappe.db.exists("Builder Client Script", name):
				frappe.get_doc(
					{
						"doctype": "Builder Client Script",
						"name": name,
						"script": "1",
						"script_type": "JavaScript",
					}
				).insert()
			doc = frappe.get_doc("Builder Page", page.name)
			doc.append("client_scripts", {"builder_script": name})
			doc.save()
		as_user(EDITOR)
		self.assertTrue(frappe.has_permission("Builder Client Script", "write", "_test-own-script"))
		self.assertFalse(frappe.has_permission("Builder Client Script", "read", "_test-other-script"))
		names = set(frappe.get_list("Builder Client Script", pluck="name"))
		self.assertIn("_test-own-script", names)
		self.assertNotIn("_test-other-script", names)

	def test_snapshots_follow_their_page(self):
		own = frappe.get_doc(
			{
				"doctype": "Builder Snapshot",
				"reference_doctype": "Builder Page",
				"reference_name": self.own.name,
				"data": "{}",
			}
		).insert(ignore_permissions=True)
		other = frappe.get_doc(
			{
				"doctype": "Builder Snapshot",
				"reference_doctype": "Builder Page",
				"reference_name": self.other.name,
				"data": "{}",
			}
		).insert(ignore_permissions=True)
		as_user(EDITOR)
		self.assertTrue(frappe.has_permission("Builder Snapshot", "read", own.name))
		self.assertFalse(frappe.has_permission("Builder Snapshot", "read", other.name))
		names = set(frappe.get_list("Builder Snapshot", pluck="name"))
		self.assertIn(own.name, names)
		self.assertNotIn(other.name, names)

	# ---- Builder's whitelisted methods ---------------------------------------------------------------------------

	def test_duplicate_page_checks_the_source(self):
		as_user(EDITOR)
		with self.assertRaises(frappe.PermissionError):
			site_editors.duplicate_page(self.other.name)
		copy = site_editors.duplicate_page(self.own.name)
		# Builder gives the copy its default draft route, pages/<hash>
		self.assertTrue(copy.route.startswith("pages/"))
		self.assertEqual(copy.owner, EDITOR)

	def test_update_page_folder_checks_every_page(self):
		as_user(EDITOR)
		with self.assertRaises(frappe.PermissionError):
			site_editors.update_page_folder([self.own.name, self.other.name], "Stolen")
		self.assertFalse(frappe.db.get_value("Builder Page", self.other.name, "project_folder"))

	def test_sync_component_checks_the_component(self):
		make_component("other-test-header")
		as_user(EDITOR)
		with self.assertRaises(frappe.PermissionError):
			site_editors.sync_component("other-test-header")

	def test_component_data_runs_only_the_stored_script(self):
		make_component("own-test-header")
		as_user(EDITOR)
		with self.assertRaises(frappe.PermissionError):
			site_editors.get_component_data("own-test-header", "{}", "data.x = frappe.get_all('User')")

	def test_refused_methods_raise_for_editors_only(self):
		from werkzeug.test import EnvironBuilder
		from werkzeug.wrappers import Request

		previous = getattr(frappe.local, "request", None)
		frappe.local.request = Request(EnvironBuilder(path="/api/method/builder.ai.api.run").get_environ())
		try:
			as_user(EDITOR)
			with self.assertRaises(frappe.PermissionError):
				site_editors.before_request()
			as_user(MANAGER)
			site_editors.before_request()
		finally:
			# later tests (view tracking's rate limit) read the request; leave it as it was
			frappe.local.request = previous

	# ---- the role ----------------------------------------------------------------------------------------------

	def test_ensure_role_is_idempotent(self):
		site_editors.ensure_role()
		site_editors.ensure_role()
		rows = frappe.get_all(
			"Custom DocPerm",
			filters={"parent": "Builder Page", "role": "Site Editor"},
			fields=["read", "write", "create", "delete"],
		)
		self.assertEqual(len(rows), 1)
		self.assertEqual(dict(rows[0]), {"read": 1, "write": 1, "create": 1, "delete": 1})

	def test_editor_listed_twice_is_refused(self):
		with self.assertRaises(frappe.ValidationError):
			make_site("_Test Editor Twice", "twice-test", "twice.psr.test", [EDITOR, EDITOR])
