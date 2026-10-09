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

from public_site_router import site_analytics, site_seo
from public_site_router.router import (
	clean_redirect,
	clear_site_map,
	get_request_host,
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


def make_site(name, prefix, domains, company=None, webshop_store=None, blog_category=None):
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
			"blog_category": blog_category,
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
		for route in ("404", "message", "website_script.js"):
			self.assertEqual(resolve_path(route), route)

	def test_sitemap_and_robots_are_the_sites_own(self):
		on_host("zephyrex.test")
		self.assertEqual(resolve_path("sitemap.xml"), "public_site_sitemap.xml")
		self.assertEqual(resolve_path("robots.txt"), "public_site_robots.txt")

	def test_seo_pages_are_404_by_their_own_name_on_a_site_host(self):
		on_host("zephyrex.test")
		for route in ("public_site_sitemap.xml", "public_site_robots.txt"):
			with self.assertRaises(frappe.PageDoesNotExistError):
				resolve_path(route)

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


@unittest.skipUnless("blog" in frappe.get_installed_apps(), "blog app not installed")
class TestPublicSiteBlog(FrappeTestCase):
	"""Root-routed Blog Posts served only on the site whose Blog Category they belong to."""

	def setUp(self):
		frappe.set_user("Administrator")
		if not frappe.db.exists("Blogger", "_test-blogger"):
			frappe.get_doc(
				{"doctype": "Blogger", "short_name": "_test-blogger", "full_name": "Test Blogger"}
			).insert()
		self.hub_category = self.category("_Test Hub Blog")
		self.zx_category = self.category("_Test ZX Blog")
		make_site(ZX, "zx", ["zephyrex.test"], blog_category=self.zx_category)
		make_site(HUB, "3sh", ["3shub.test"], blog_category=self.hub_category)
		make_web_page("3sh/clash", "Hub Clash Page")
		self.post("hub-guide", self.hub_category)
		self.post("zx-notes", self.zx_category)
		self.post("hub-draft", self.hub_category, published=0)
		self.post("clash", self.hub_category)
		clear_site_map()

	def tearDown(self):
		on_host(None)
		frappe.db.rollback()
		clear_site_map()

	@staticmethod
	def category(title):
		name = frappe.db.get_value("Blog Category", {"title": title})
		return (
			name or frappe.get_doc({"doctype": "Blog Category", "title": title, "published": 1}).insert().name
		)

	@staticmethod
	def post(route, category, published=1):
		if not frappe.db.exists("Blog Post", {"route": route}):
			frappe.get_doc(
				{
					"doctype": "Blog Post",
					"title": f"_Test {route}",
					"route": route,
					"blog_category": category,
					"blogger": "_test-blogger",
					"content_type": "HTML",
					"content_html": f"<p>{route}</p>",
					"published": published,
				}
			).insert()

	def test_sitemap_lists_the_listing_and_own_published_posts(self):
		on_host("3shub.test")
		xml = site_seo.sitemap_xml()
		self.assertIn("<loc>https://3shub.test/</loc>", xml)
		self.assertIn("<loc>https://3shub.test/hub-guide</loc>", xml)
		self.assertIn("<loc>https://3shub.test/clash</loc>", xml)
		self.assertNotIn("hub-draft", xml)
		self.assertNotIn("zx-notes", xml)

	def test_post_route_kept_at_root(self):
		self.assertEqual(frappe.db.get_value("Blog Post", {"title": "_Test hub-guide"}, "route"), "hub-guide")

	def test_own_post_passes_through(self):
		on_host("erp.example.test")
		expected = resolve_path("hub-guide")
		on_host("3shub.test")
		self.assertEqual(resolve_path("hub-guide"), expected)

	def test_other_sites_post_is_404(self):
		on_host("3shub.test")
		with self.assertRaises(frappe.PageDoesNotExistError):
			resolve_path("zx-notes")
		on_host("zephyrex.test")
		with self.assertRaises(frappe.PageDoesNotExistError):
			resolve_path("hub-guide")

	def test_unpublished_post_is_404(self):
		on_host("3shub.test")
		with self.assertRaises(frappe.PageDoesNotExistError):
			resolve_path("hub-draft")

	def test_root_is_category_listing(self):
		on_host("3shub.test")
		self.assertEqual(
			resolve_path(""),
			resolve_path_off_site(frappe.db.get_value("Blog Category", self.hub_category, "route")),
		)

	def test_site_page_wins_over_post(self):
		on_host("3shub.test")
		self.assertEqual(resolve_path("clash"), "3sh/clash")

	def test_blog_category_unique_per_site(self):
		with self.assertRaises(frappe.ValidationError):
			make_site("_Test Clash Site", "clash", ["clash.test"], blog_category=self.hub_category)

	def test_unknown_blog_category_rejected(self):
		with self.assertRaises(frappe.ValidationError):
			make_site(
				"_Test Bad Blog Site", "badblog", ["badblog.test"], blog_category="_Test No Such Category"
			)


def resolve_path_off_site(route):
	"""``route`` as a host with no Public Site resolves it (the router passes it on unchanged)."""
	host = get_request_host()
	on_host("erp.example.test")
	try:
		return resolve_path(route)
	finally:
		on_host(host)


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

	def test_sitemap_lists_only_the_sites_store_items(self):
		zx_route = frappe.db.get_value("Website Item", self.zx_item, "route")
		hub_route = frappe.db.get_value("Website Item", self.hub_item, "route")
		on_host("zephyrex.test")
		xml = site_seo.sitemap_xml()
		self.assertIn(f"<loc>https://zephyrex.test/{zx_route}</loc>", xml)
		self.assertNotIn(hub_route, xml)

	def test_cart_quotation_uses_store_company(self):
		from webshop.webshop.shopping_cart.cart import _get_cart_quotation

		on_host("3shub.test")
		quotation = _get_cart_quotation(frappe.get_doc("Customer", "_Test Customer"))
		self.assertEqual(quotation.company, "_Test Company 1")


class TestPublicSiteSeo(FrappeTestCase):
	"""Per-host sitemap, robots.txt, canonical link and Open Graph URLs, against a real test site."""

	def setUp(self):
		frappe.set_user("Administrator")
		make_site(ZX, "zx", ["www.zephyrex.test", "zephyrex.test"])
		make_site(HUB, "3sh", ["3shub.test"])
		for route, title in (
			("zx/home", "ZX Home"),
			("zx/about", "ZX About"),
			("zx/infrastructure/firewalls", "ZX Firewalls"),
			("3sh/home", "Hub Home"),
			("shared-legal", "Shared Legal"),
		):
			make_web_page(route, title)
		make_web_page("zx/draft", "ZX Draft")
		frappe.db.set_value("Web Page", {"route": "zx/draft"}, "published", 0)
		clear_site_map()

	def tearDown(self):
		on_host(None)
		frappe.local.path = None
		frappe.db.rollback()
		clear_site_map()

	def test_sitemap_lists_only_the_sites_published_pages_on_its_canonical_host(self):
		on_host("www.zephyrex.test")
		xml = site_seo.sitemap_xml()
		for path in ("", "about", "infrastructure/firewalls"):
			self.assertIn(f"<loc>https://zephyrex.test/{path}</loc>", xml)
		for absent in ("zx/", "/home<", "draft", "shared-legal", "3sh", "www."):
			self.assertNotIn(absent, xml)

	def test_robots_names_the_sites_sitemap(self):
		on_host("www.zephyrex.test")
		self.assertIn("Sitemap: https://zephyrex.test/sitemap.xml", site_seo.robots_txt())

	def test_seo_pages_are_404_off_a_site_host(self):
		on_host("erp.example.test")
		with self.assertRaises(frappe.PageDoesNotExistError):
			site_seo.sitemap_xml()
		with self.assertRaises(frappe.PageDoesNotExistError):
			site_seo.robots_txt()

	def context(self, endpoint, **values):
		frappe.local.path = endpoint
		return frappe._dict({"metatags": frappe._dict(), "head_html": "<meta name=x>"} | values)

	def test_canonical_and_og_url_name_the_clean_url_on_the_canonical_host(self):
		on_host("www.zephyrex.test")
		context = self.context("zx/infrastructure/firewalls")
		site_seo.update_website_context(context)
		url = "https://zephyrex.test/infrastructure/firewalls"
		self.assertEqual(context.head_html, f'<meta name=x><link rel="canonical" href="{url}">')
		self.assertEqual(context.metatags["og:url"], url)
		self.assertEqual(context.metatags["og:site_name"], ZX)

	def test_home_canonical_is_the_root(self):
		on_host("zephyrex.test")
		context = self.context("zx/home")
		site_seo.update_website_context(context)
		self.assertEqual(context.metatags["og:url"], "https://zephyrex.test/")

	def test_images_on_the_erp_host_move_to_the_site_host(self):
		on_host("zephyrex.test")
		erp_image = frappe.utils.get_url("/files/card.png")
		context = self.context("zx/about", metatags=frappe._dict({"image": erp_image, "og:image": erp_image}))
		site_seo.update_website_context(context)
		self.assertEqual(context.metatags["og:image"], "https://zephyrex.test/files/card.png")
		self.assertEqual(context.metatags["image"], "https://zephyrex.test/files/card.png")

	def test_nothing_added_off_site_or_on_technical_pages(self):
		on_host("erp.example.test")
		context = self.context("zx/about")
		site_seo.update_website_context(context)
		self.assertEqual(context.head_html, "<meta name=x>")
		on_host("zephyrex.test")
		for endpoint in ("404", "message"):
			context = self.context(endpoint)
			site_seo.update_website_context(context)
			self.assertNotIn("og:url", context.metatags)

	def test_not_found_page_gets_no_canonical(self):
		on_host("zephyrex.test")
		context = self.context("zx/missing", http_status_code=404)
		site_seo.update_website_context(context)
		self.assertNotIn("canonical", context.head_html)

	def test_renders_sitemap_and_robots_through_frappe(self):
		from frappe.website.serve import get_response

		on_host("zephyrex.test")
		sitemap = get_response("sitemap.xml")
		self.assertEqual(sitemap.status_code, 200)
		# Frappe takes the type from the endpoint's extension; the system's mime.types decides which.
		self.assertIn(sitemap.mimetype, ("application/xml", "text/xml"))
		self.assertIn(b"<loc>https://zephyrex.test/about</loc>", sitemap.data)
		robots = get_response("robots.txt")
		self.assertEqual(robots.status_code, 200)
		self.assertEqual(robots.mimetype, "text/plain")
		self.assertIn(b"Sitemap: https://zephyrex.test/sitemap.xml", robots.data)


class TestPublicSiteAnalytics(FrappeTestCase):
	"""Per-site analytics providers and site-stamped Frappe view tracking, against a real test site."""

	GA4 = "G-B30D03ZZWZ"

	def setUp(self):
		frappe.set_user("Administrator")
		site_analytics.ensure_custom_fields()
		self.zx = make_site(ZX, "zx", ["zephyrex.test", "www.zephyrex.test"])
		make_site(HUB, "3sh", ["3shub.test"])
		make_web_page("zx/home", "ZX Home")
		clear_site_map()

	def tearDown(self):
		on_host(None)
		frappe.local.path = None
		frappe.db.rollback()
		clear_site_map()

	def configure(self, **values):
		self.zx.update(values)
		self.zx.save()
		clear_site_map()

	def page_head(self, endpoint="zx/home"):
		frappe.local.path = endpoint
		context = frappe._dict({"metatags": frappe._dict(), "head_html": ""})
		site_analytics.update_website_context(context)
		return context.head_html

	def test_ga4_id_is_validated_and_normalised(self):
		self.configure(ga4_measurement_id=" g-b30d03zzwz ")
		self.assertEqual(self.zx.ga4_measurement_id, self.GA4)
		with self.assertRaises(frappe.ValidationError):
			self.configure(ga4_measurement_id="UA-1234-1")

	def test_matomo_needs_an_https_url_and_a_site_id(self):
		self.configure(matomo_url="https://matomo.zephyrex.test", matomo_site_id="4")
		self.assertEqual(self.zx.matomo_url, "https://matomo.zephyrex.test/")
		with self.assertRaises(frappe.ValidationError):
			self.configure(matomo_url="http://matomo.zephyrex.test", matomo_site_id="4")
		with self.assertRaises(frappe.ValidationError):
			self.configure(matomo_url="https://matomo.zephyrex.test", matomo_site_id="")

	def test_configured_providers_are_on_the_sites_pages_only(self):
		self.configure(
			view_tracking=1,
			ga4_measurement_id=self.GA4,
			matomo_url="https://m.zephyrex.test",
			matomo_site_id="4",
		)
		on_host("zephyrex.test")
		head = self.page_head()
		self.assertIn(site_analytics.LOG_ENDPOINT, head)
		self.assertIn(self.GA4, head)
		self.assertIn("matomo.php", head)
		on_host("3shub.test")
		self.assertNotIn(self.GA4, self.page_head("3sh/home"))
		on_host("erp.example.test")
		self.assertEqual(self.page_head(), "")

	def test_no_snippets_on_technical_pages(self):
		self.configure(ga4_measurement_id=self.GA4)
		on_host("zephyrex.test")
		self.assertEqual(self.page_head("404"), "")

	def beacon(self, host, referer):
		frappe.local.request = Request(
			EnvironBuilder(
				base_url=f"https://{host}/", method="POST", headers={"Referer": referer, "User-Agent": "test"}
			).get_environ()
		)
		before = frappe.db.count("Web Page View")
		site_analytics.log_view(
			referrer="https://search.test/?q=private", user_tz="America/Edmonton", source="news"
		)
		from frappe.deferred_insert import save_to_db

		save_to_db()
		return frappe.db.count("Web Page View") - before

	def test_view_is_stamped_with_its_site(self):
		self.configure(view_tracking=1)
		self.assertEqual(
			self.beacon("www.zephyrex.test", "https://www.zephyrex.test/about?utm_source=news"), 1
		)
		view = frappe.get_last_doc("Web Page View")
		self.assertEqual((view.path, view.public_site), ("about", ZX))
		self.assertEqual(view.referrer, "https://search.test/")
		self.assertEqual((view.time_zone, view.source), ("America/Edmonton", "news"))

	def test_views_off_site_or_disabled_are_ignored(self):
		self.configure(view_tracking=1)
		self.assertEqual(self.beacon("zephyrex.test", "https://3shub.test/"), 0)
		self.assertEqual(self.beacon("erp.example.test", "https://erp.example.test/"), 0)
		self.assertEqual(self.beacon("zephyrex.test", "https://zephyrex.test/app/lead"), 0)
		self.configure(view_tracking=0)
		self.assertEqual(self.beacon("zephyrex.test", "https://zephyrex.test/"), 0)

	def test_web_page_view_has_the_public_site_field(self):
		self.assertTrue(frappe.get_meta("Web Page View").has_field("public_site"))
