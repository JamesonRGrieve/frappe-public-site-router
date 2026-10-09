# SPDX-License-Identifier: AGPL-3.0-or-later
"""Unit tests for the pure per-host SEO logic (no bench): canonical host, clean paths, URLs, the
sitemap, robots.txt, the canonical link and moving ERP-host URLs onto a site's host."""

import xml.etree.ElementTree as ET
from datetime import date, datetime

import pytest

from public_site_router import seo

NS = {"s": seo.SITEMAP_NAMESPACE}


class TestPrimaryDomain:
	def test_first_non_www_domain(self):
		assert seo.primary_domain(["www.zephyrex.ca", "zephyrex.ca"]) == "zephyrex.ca"
		assert seo.primary_domain(["3shub.com", "www.3shub.com"]) == "3shub.com"

	def test_subdomain_host(self):
		assert seo.primary_domain(["hannah.thegrieves.ca"]) == "hannah.thegrieves.ca"

	def test_only_www_aliases_fall_back_to_the_bare_host(self):
		assert seo.primary_domain(["www.stifle.ca"]) == "stifle.ca"

	def test_no_domains_is_an_error(self):
		with pytest.raises(ValueError):
			seo.primary_domain([])


class TestCleanPath:
	@pytest.mark.parametrize(
		("endpoint", "expected"),
		[
			("zephyrex-ca/home", ""),
			("/zephyrex-ca/home/", ""),
			("zephyrex-ca/about", "about"),
			("zephyrex-ca/infrastructure/firewalls", "infrastructure/firewalls"),
			("changing-fuel-injectors", "changing-fuel-injectors"),
			("zephyrex-ca-home", "zephyrex-ca-home"),
		],
	)
	def test_maps_endpoints_to_their_public_paths(self, endpoint, expected):
		assert seo.clean_path(endpoint, "zephyrex-ca", "zephyrex-ca/home") == expected

	def test_blog_listing_home(self):
		assert seo.clean_path("blog/3s-hub", "3shub-ca", "blog/3s-hub") == ""


class TestPageUrl:
	def test_home_and_paths(self):
		assert seo.page_url("zephyrex.ca", "") == "https://zephyrex.ca/"
		assert seo.page_url("zephyrex.ca", "/about/") == "https://zephyrex.ca/about"

	def test_quotes_unsafe_characters(self):
		assert seo.page_url("3shub.ca", "posts/a b&c") == "https://3shub.ca/posts/a%20b%26c"


class TestDynamicRoutes:
	@pytest.mark.parametrize("route", ["project/<name>", "blog/:name", ":id"])
	def test_dynamic(self, route):
		assert seo.is_dynamic_route(route)

	def test_static(self):
		assert not seo.is_dynamic_route("zephyrex-ca/services/email-calendar")


class TestSitemap:
	ROUTES = [
		("zephyrex-ca/services", datetime(2026, 10, 3, 18, 45)),
		("zephyrex-ca/home", datetime(2026, 10, 9, 13, 0)),
		("zephyrex-ca/about", date(2026, 10, 1)),
		("zephyrex-ca/contact", None),
		("zephyrex-ca/projects/<name>", datetime(2026, 1, 1)),
		("", datetime(2026, 1, 1)),
	]

	def entries(self, routes=None):
		return seo.sitemap_entries("zephyrex.ca", "zephyrex-ca", "zephyrex-ca/home", routes or self.ROUTES)

	def test_home_first_then_sorted_and_dynamic_or_empty_routes_dropped(self):
		assert [e.loc for e in self.entries()] == [
			"https://zephyrex.ca/",
			"https://zephyrex.ca/about",
			"https://zephyrex.ca/contact",
			"https://zephyrex.ca/services",
		]

	def test_lastmod_is_the_day(self):
		by_loc = {e.loc: e.lastmod for e in self.entries()}
		assert by_loc["https://zephyrex.ca/"] == date(2026, 10, 9)
		assert by_loc["https://zephyrex.ca/about"] == date(2026, 10, 1)
		assert by_loc["https://zephyrex.ca/contact"] is None

	def test_a_url_listed_twice_keeps_its_newest_date(self):
		routes = [("blog/hub", None), ("blog/hub", datetime(2026, 5, 1)), ("blog/hub", datetime(2026, 4, 1))]
		entries = seo.sitemap_entries("3shub.ca", "3shub-ca", "blog/hub", routes)
		assert entries == [seo.SitemapEntry("https://3shub.ca/", date(2026, 5, 1))]

	def test_xml_is_a_valid_urlset(self):
		root = ET.fromstring(seo.sitemap_xml(self.entries()))
		assert root.tag == f"{{{seo.SITEMAP_NAMESPACE}}}urlset"
		urls = root.findall("s:url", NS)
		assert [u.findtext("s:loc", namespaces=NS) for u in urls][0] == "https://zephyrex.ca/"
		assert urls[0].findtext("s:lastmod", namespaces=NS) == "2026-10-09"
		contact = next(u for u in urls if u.findtext("s:loc", namespaces=NS).endswith("/contact"))
		assert contact.find("s:lastmod", NS) is None

	def test_xml_escapes_locations(self):
		xml = seo.sitemap_xml([seo.SitemapEntry("https://a.ca/x?y=1&z=2", None)])
		assert "<loc>https://a.ca/x?y=1&amp;z=2</loc>" in xml
		ET.fromstring(xml)

	def test_empty_sitemap(self):
		assert ET.fromstring(seo.sitemap_xml([])).findall("s:url", NS) == []


class TestRobots:
	def test_names_the_sitemap_on_the_canonical_host(self):
		text = seo.robots_txt("3shub.com")
		assert text.startswith("User-agent: *\n")
		assert text.endswith("\nSitemap: https://3shub.com/sitemap.xml\n")

	def test_disallows_desk_api_and_account_pages(self):
		lines = seo.robots_txt("3shub.com").splitlines()
		for path in ("/app", "/api/", "/login", "/cart"):
			assert f"Disallow: {path}" in lines
		assert "Disallow: /" not in lines


class TestCanonicalLink:
	def test_link(self):
		assert (
			seo.canonical_link("https://zephyrex.ca/") == '<link rel="canonical" href="https://zephyrex.ca/">'
		)

	def test_escapes_the_href(self):
		assert (
			seo.canonical_link('https://a.ca/"x"&y')
			== '<link rel="canonical" href="https://a.ca/&quot;x&quot;&amp;y">'
		)


class TestRehost:
	ERP = {"erp.zephyrex.ca"}

	def test_moves_erp_host_urls_onto_the_site_host(self):
		url = "https://erp.zephyrex.ca/files/site-og-3shub-com__home.png"
		assert seo.rehost(url, self.ERP, "3shub.com") == "https://3shub.com/files/site-og-3shub-com__home.png"

	def test_upgrades_to_https(self):
		assert (
			seo.rehost("http://erp.zephyrex.ca/files/a.png", self.ERP, "zephyrex.ca")
			== "https://zephyrex.ca/files/a.png"
		)

	def test_keeps_other_hosts_and_relative_urls(self):
		assert (
			seo.rehost("https://cdn.example.com/a.png", self.ERP, "zephyrex.ca")
			== "https://cdn.example.com/a.png"
		)
		assert seo.rehost("/files/a.png", self.ERP, "zephyrex.ca") == "/files/a.png"

	def test_host_match_ignores_case(self):
		assert seo.rehost("https://ERP.zephyrex.ca/x", self.ERP, "zephyrex.ca") == "https://zephyrex.ca/x"
