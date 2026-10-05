# SPDX-License-Identifier: AGPL-3.0-or-later
"""Host isolation against a real test site: host → site, path → site page, other sites'
prefixes as 404s, only technical routes (plus store routes on store sites) passed through
and everything else a 404, and (with the frappe-webshop fork
installed) per-store listing, search, product pages and cart quotations through the
webshop_store_resolver hook."""

import unittest

import frappe
from frappe.tests.utils import FrappeTestCase
from werkzeug.test import EnvironBuilder
from werkzeug.wrappers import Request, Response

from public_site_router.router import (
	clean_redirect,
	clear_site_map,
	get_request_site,
	get_request_store,
	normalize_host,
	resolve_path,
)

ZX = "_Test Zephyrex Site"
HUB = "_Test 3S Hub Site"
ZX_STORE = "_Test Zephyrex Store"
HUB_STORE = "_Test 3S Hub Store"


def on_host(host):
	"""Make the current request a real Werkzeug request for ``host`` (as Frappe serves it)."""
	frappe.local.request = Request(EnvironBuilder(base_url=f"http://{host}/").get_environ()) if host else None


def make_site(name, prefix, domains, company=None, webshop_store=None):
	if frappe.db.exists("Public Site", name):
		frappe.delete_doc("Public Site", name, force=True)
	return frappe.get_doc(
		{
			"doctype": "Public Site",
			"site_name": name,
			"enabled": 1,
			"company": company,
			"route_prefix": prefix,
			"home_route": "home",
			"webshop_store": webshop_store,
			"domains": [{"domain": d} for d in domains],
		}
	).insert()


def make_web_page(route, title):
	if not frappe.db.exists("Web Page", {"route": route}):
		frappe.get_doc(
			{"doctype": "Web Page", "title": title, "route": route, "published": 1, "main_section": title}
		).insert()


class TestPublicSiteRouting(FrappeTestCase):
	def setUp(self):
		frappe.set_user("Administrator")
		make_site(ZX, "zx", ["zephyrex.test", "www.zephyrex.test"])
		make_site(HUB, "3sh", ["3shub.test"])
		for route, title in (
			("zx/home", "ZX Home"),
			("zx/infrastructure/firewalls", "ZX Firewalls"),
			("3sh/home", "Hub Home"),
			("shared-legal", "Shared Legal"),
		):
			make_web_page(route, title)
		clear_site_map()

	def tearDown(self):
		on_host(None)
		frappe.db.rollback()
		clear_site_map()

	def test_normalize_host(self):
		self.assertEqual(normalize_host("WWW.Zephyrex.TEST:443"), "www.zephyrex.test")
		self.assertEqual(normalize_host("zephyrex.test."), "zephyrex.test")
		self.assertEqual(normalize_host(None), "")

	def test_host_selects_site(self):
		on_host("www.zephyrex.test:8443")
		self.assertEqual(get_request_site().name, ZX)
		on_host("3shub.test")
		self.assertEqual(get_request_site().name, HUB)
		on_host("erp.example.test")
		self.assertIsNone(get_request_site())

	def test_root_is_site_home(self):
		on_host("zephyrex.test")
		self.assertEqual(resolve_path(""), "zx/home")
		on_host("3shub.test")
		self.assertEqual(resolve_path(""), "3sh/home")

	def test_clean_path_maps_into_site_prefix(self):
		on_host("zephyrex.test")
		self.assertEqual(resolve_path("infrastructure/firewalls"), "zx/infrastructure/firewalls")

	def test_same_path_on_other_site_is_404(self):
		on_host("3shub.test")
		with self.assertRaises(frappe.PageDoesNotExistError):
			resolve_path("infrastructure/firewalls")

	def test_other_sites_prefix_is_404(self):
		on_host("3shub.test")
		with self.assertRaises(frappe.PageDoesNotExistError):
			resolve_path("zx/infrastructure/firewalls")

	def test_own_prefix_is_404(self):
		# a site's pages have exactly one URL: the clean one
		on_host("zephyrex.test")
		with self.assertRaises(frappe.PageDoesNotExistError):
			resolve_path("zx/home")

	def test_technical_routes_pass_through(self):
		on_host("zephyrex.test")
		for route in ("404", "message", "robots.txt", "website_script.js"):
			self.assertEqual(resolve_path(route), route)

	def test_unpublished_by_site_is_404(self):
		# global pages, ERPNext's generic about/contact, desk and the global sitemap
		on_host("zephyrex.test")
		for route in ("shared-legal", "about", "contact", "contact/new", "app", "sitemap.xml"):
			with self.subTest(route=route), self.assertRaises(frappe.PageDoesNotExistError):
				resolve_path(route)

	def test_store_routes_404_without_store(self):
		on_host("zephyrex.test")
		for route in ("login", "me", "orders", "cart", "all-products", "product_search"):
			with self.subTest(route=route), self.assertRaises(frappe.PageDoesNotExistError):
				resolve_path(route)

	def test_store_routes_pass_through_with_store(self):
		frappe.db.set_value("Public Site", HUB, "webshop_store", "_Test Any Store", update_modified=False)
		frappe.clear_document_cache("Public Site", HUB)
		for route in (
			"login",
			"update-password",
			"orders",
			"cart",
			"all-products",
			"shop-by-category/x",
			"order/SO-1",
		):
			# passed through unchanged: resolved exactly as on a host with no Public Site
			on_host("erp.example.test")
			expected = resolve_path(route)
			on_host("3shub.test")
			self.assertEqual(resolve_path(route), expected)
		for route in ("about", "app", "shared-legal"):
			with self.subTest(route=route), self.assertRaises(frappe.PageDoesNotExistError):
				resolve_path(route)

	def test_erp_host_keeps_everything(self):
		on_host("erp.example.test")
		for route in ("login", "app", "about", "shared-legal"):
			self.assertEqual(resolve_path(route), route)

	def test_unmapped_host_is_unchanged(self):
		on_host("erp.example.test")
		self.assertEqual(resolve_path("zx/home"), "zx/home")

	def test_disabled_site_is_not_routed(self):
		frappe.db.set_value("Public Site", HUB, "enabled", 0)
		clear_site_map()
		on_host("3shub.test")
		self.assertIsNone(get_request_site())

	def test_disabled_site_hosts_serve_nothing(self):
		frappe.db.set_value("Public Site", HUB, "enabled", 0)
		clear_site_map()
		on_host("3shub.test")
		for route in ("", "login", "about", "3sh/home", "404"):
			with self.subTest(route=route), self.assertRaises(frappe.PageDoesNotExistError):
				resolve_path(route)
		on_host("erp.example.test")  # hosts of no site at all are still untouched
		self.assertEqual(resolve_path("login"), "login")

	def test_duplicate_domain_rejected(self):
		with self.assertRaises(frappe.ValidationError):
			make_site("_Test Clash Site", "clash", ["3shub.test"])

	def test_bad_prefix_rejected(self):
		with self.assertRaises(frappe.ValidationError):
			make_site("_Test Bad Prefix Site", "two/segments", ["bad.test"])

	def test_web_form_and_sub_pages_map_into_site_prefix(self):
		if not frappe.db.exists("Web Form", {"route": "zx/contact"}):
			frappe.get_doc(
				{
					"doctype": "Web Form",
					"title": "_Test ZX Contact",
					"route": "zx/contact",
					"doc_type": "ToDo",
					"module": "Website",
					"published": 1,
					"web_form_fields": [
						{"fieldname": "description", "fieldtype": "Text", "label": "Description"}
					],
				}
			).insert()
		on_host("zephyrex.test")
		self.assertEqual(resolve_path("contact"), "zx/contact")
		self.assertEqual(resolve_path("contact/new"), "zx/contact/new")
		on_host("3shub.test")
		with self.assertRaises(frappe.PageDoesNotExistError):
			resolve_path("contact/new")

	def test_redirect_to_own_prefix_is_cleaned(self):
		on_host("www.zephyrex.test")
		for location, expected in (
			("/zx/contact/new", "/contact/new"),
			("/zx/contact/new?key=abc", "/contact/new?key=abc"),
			("/zx/home", "/"),
			("/zx", "/"),
			("https://www.zephyrex.test/zx/contact/new", "https://www.zephyrex.test/contact/new"),
			("https://3shub.test/zx/contact/new", "https://3shub.test/zx/contact/new"),
			("/zxother/page", "/zxother/page"),
			("/login", "/login"),
		):
			response = Response(status=302, headers={"Location": location})
			clean_redirect(response, frappe.local.request)
			self.assertEqual(response.headers["Location"], expected)

	def test_redirect_untouched_off_site_or_not_redirect(self):
		on_host("erp.example.test")
		response = Response(status=302, headers={"Location": "/zx/contact/new"})
		clean_redirect(response, frappe.local.request)
		self.assertEqual(response.headers["Location"], "/zx/contact/new")
		on_host("zephyrex.test")
		response = Response(status=201, headers={"Location": "/zx/contact/new"})
		clean_redirect(response, frappe.local.request)
		self.assertEqual(response.headers["Location"], "/zx/contact/new")

	def test_no_store_without_webshop_store(self):
		on_host("zephyrex.test")
		self.assertIsNone(get_request_store())


@unittest.skipUnless("webshop" in frappe.get_installed_apps(), "frappe-webshop fork not installed")
class TestPublicSiteWebshop(FrappeTestCase):
	"""End-to-end through the frappe-webshop fork's webshop_store_resolver hook."""

	def setUp(self):
		from webshop.webshop.doctype.website_item.website_item import make_website_item

		frappe.set_user("Administrator")
		settings = frappe.get_doc("Webshop Settings")
		settings.update(
			{
				"enabled": 1,
				"company": "_Test Company",
				"default_customer_group": "_Test Customer Group",
				"quotation_series": "_T-Quotation-",
				"price_list": "_Test Price List India",
			}
		)
		settings.save()
		for store, company, price_list in (
			(ZX_STORE, "_Test Company", "_Test Price List India"),
			(HUB_STORE, "_Test Company 1", "_Test Price List"),
		):
			if not frappe.db.exists("Webshop Store", store):
				frappe.get_doc(
					{
						"doctype": "Webshop Store",
						"store_name": store,
						"enabled": 1,
						"company": company,
						"price_list": price_list,
						"default_customer_group": "_Test Customer Group",
						"quotation_series": "_T-Quotation-",
					}
				).insert()
		make_site(ZX, "zx", ["zephyrex.test"], company="_Test Company", webshop_store=ZX_STORE)
		make_site(HUB, "3sh", ["3shub.test"], company="_Test Company 1", webshop_store=HUB_STORE)
		clear_site_map()

		def web_item(item_code, store):
			name = frappe.db.get_value("Website Item", {"item_code": item_code})
			if not name:
				name = make_website_item(frappe.get_cached_doc("Item", item_code))[0]
			frappe.db.set_value("Website Item", name, {"webshop_store": store, "published": 1})
			return name

		self.zx_item = web_item("_Test Item", ZX_STORE)
		self.hub_item = web_item("_Test Item 2", HUB_STORE)

	def tearDown(self):
		on_host(None)
		frappe.db.rollback()
		clear_site_map()
		frappe.clear_document_cache("Webshop Settings", "Webshop Settings")

	def test_store_follows_host(self):
		from webshop.webshop.doctype.webshop_settings.webshop_settings import get_shopping_cart_settings

		on_host("3shub.test")
		self.assertEqual(get_request_store(), HUB_STORE)
		self.assertEqual(get_shopping_cart_settings().company, "_Test Company 1")
		on_host("erp.example.test")
		self.assertEqual(get_shopping_cart_settings().company, "_Test Company")

	def test_listing_is_store_scoped(self):
		from webshop.webshop.product_data_engine.query import ProductQuery

		on_host("zephyrex.test")
		names = [r["name"] for r in ProductQuery().query(fields={})["items"]]
		self.assertIn(self.zx_item, names)
		self.assertNotIn(self.hub_item, names)

	def test_search_is_store_scoped(self):
		from webshop.templates.pages.product_search import get_product_data

		on_host("3shub.test")
		codes = [r.item_code for r in get_product_data(search="_Test Item", limit=50)]
		self.assertIn("_Test Item 2", codes)
		self.assertNotIn("_Test Item", codes)

	def test_other_stores_product_page_is_404(self):
		on_host("3shub.test")
		with self.assertRaises(frappe.PageDoesNotExistError):
			frappe.get_doc("Website Item", self.zx_item).get_context(frappe._dict())

	def test_product_page_not_cached_in_multi_store(self):
		on_host("zephyrex.test")
		doc = frappe.get_doc("Website Item", self.zx_item)
		# the context Frappe's document renderer starts from: the document's own fields
		context = frappe._dict(doc.as_dict())
		doc.get_context(context)
		self.assertEqual(context.no_cache, 1)

	def test_cart_quotation_uses_store_company(self):
		from webshop.webshop.shopping_cart.cart import _get_cart_quotation

		on_host("3shub.test")
		quotation = _get_cart_quotation(frappe.get_doc("Customer", "_Test Customer"))
		self.assertEqual(quotation.company, "_Test Company 1")
