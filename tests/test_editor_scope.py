# SPDX-License-Identifier: AGPL-3.0-or-later
"""Site Editors' scope (editor_scope): what pages, components and patterns a scoped editor may touch."""

import pytest

from public_site_router import editor_scope as es

HANNAH = "hannah@thegrieves.ca"
SCOPE = es.EditorScope((es.SiteRef("Handmade by Hannah", "hannah-thegrieves-ca"),))
TWO_SITES = es.EditorScope(
	(es.SiteRef("Stifle", "stifle-ca"), es.SiteRef("Stifle Apiary", "apiary-stifle-ca")),
)


@pytest.mark.parametrize(
	("roles", "scoped"),
	[
		({"Site Editor"}, True),
		({"Site Editor", "Sales Manager"}, True),
		({"Site Editor", "Website Manager"}, False),
		({"Site Editor", "System Manager"}, False),
		({"Website Manager"}, False),
		(set(), False),
	],
)
def test_only_a_site_editor_without_a_manager_role_is_scoped(roles, scoped):
	assert es.is_scoped(roles) is scoped


@pytest.mark.parametrize(
	("route", "allowed"),
	[
		("hannah-thegrieves-ca/home", True),
		("hannah-thegrieves-ca", True),
		("hannah-thegrieves-ca-builder/home", True),
		("/hannah-thegrieves-ca/shop/cups/", True),
		("zephyrex-ca/home", False),
		# a prefix that merely starts the same way is another site
		("hannah-thegrieves-ca2/home", False),
		("hannah-thegrieves-cax", False),
		("hannah-thegrieves-ca-builderx/home", False),
		("", False),
		(None, False),
	],
)
def test_route_allowed_only_under_own_and_preview_prefixes(route, allowed):
	assert SCOPE.route_allowed(route) is allowed


def test_an_unrouted_page_is_allowed_only_to_its_creator():
	assert SCOPE.page_allowed(None, HANNAH, HANNAH)
	assert SCOPE.page_allowed("", HANNAH, HANNAH)
	assert not SCOPE.page_allowed(None, "jameson@zephyrex.ca", HANNAH)


def test_a_routed_page_follows_its_route_whoever_made_it():
	# a page Hannah created and moved to another site's route is no longer hers to edit
	assert not SCOPE.page_allowed("zephyrex-ca/about", HANNAH, HANNAH)
	assert SCOPE.page_allowed("hannah-thegrieves-ca/about", "jameson@zephyrex.ca", HANNAH)


def test_editors_of_several_sites_reach_each():
	assert TWO_SITES.route_allowed("stifle-ca/home")
	assert TWO_SITES.route_allowed("apiary-stifle-ca-builder/home")
	assert not TWO_SITES.route_allowed("manufacturing-stifle-ca/home")


def test_an_editor_with_no_sites_reaches_nothing():
	empty = es.EditorScope(())
	assert not empty.route_allowed("zephyrex-ca/home")
	assert not empty.component_allowed("zephyrex-ca-header", "x", HANNAH)


def test_components_by_prefix_or_owner():
	assert SCOPE.component_allowed("hannah-thegrieves-ca-header", "Administrator", HANNAH)
	assert SCOPE.component_allowed("a1b2c3", HANNAH, HANNAH)
	assert not SCOPE.component_allowed("zephyrex-ca-header", "Administrator", HANNAH)
	assert not SCOPE.component_allowed("hannah-thegrieves-cax-header", "Administrator", HANNAH)


def test_patterns_by_site_name_or_owner():
	assert SCOPE.pattern_allowed("Handmade by Hannah · Hero", "Administrator", HANNAH)
	assert SCOPE.pattern_allowed("My section", HANNAH, HANNAH)
	assert not SCOPE.pattern_allowed("Zephyrex · Hero", "Administrator", HANNAH)
	assert not SCOPE.pattern_allowed("Handmade by Hannah Hero", "Administrator", HANNAH)


@pytest.mark.parametrize(
	("before", "after", "added"),
	[
		("<p>Hi</p>", "<p>Hi there</p>", []),
		("<p>Hi</p>", "<p>{{ frappe.db.sql('select 1') }}</p>", ["{{ frappe.db.sql('select 1') }}"]),
		("", "{% for x in y %}{% endfor %}", ["{% endfor %}", "{% for x in y %}"]),
		(None, "{# note #}", ["{# note #}"]),
		# an expression already on the page may stay or move
		("<p>{{ title }}</p>", "<h1>{{ title }}</h1>", []),
		# a second copy of an existing one is new
		("{{ title }}", "{{ title }}{{ title }}", ["{{ title }}"]),
		# spanning lines
		("", "{{\n frappe.get_all('User')\n}}", ["{{\n frappe.get_all('User')\n}}"]),
		("<p>{ not a template }</p>", "<p>{ not a template } {single}</p>", []),
	],
)
def test_new_template_expressions(before, after, added):
	assert es.new_template_expressions(before, after) == sorted(added)


def test_page_condition_matches_own_prefixes_and_own_unrouted_pages():
	sql = es.page_condition(SCOPE, HANNAH, table="p")
	assert "p.route = 'hannah-thegrieves-ca'" in sql
	assert "p.route like 'hannah-thegrieves-ca/%'" in sql
	assert "p.route like 'hannah-thegrieves-ca-builder/%'" in sql
	assert "p.owner = 'hannah@thegrieves.ca'" in sql
	assert "zephyrex" not in sql


def test_like_patterns_escape_wildcards_and_quotes():
	scope = es.EditorScope((es.SiteRef("O'Brien_%", "a_b"),))
	# like_escape's backslashes are doubled again inside the SQL string literal
	assert "like 'a\\\\_b/%'" in es.page_condition(scope, "x")
	assert "like 'O''Brien\\\\_\\\\% · %'" in es.name_condition(["O'Brien_% · "], "x", "t")
	assert "t.owner = 'o''x'" in es.name_condition([], "o'x", "t")


def test_an_editor_with_no_sites_lists_only_their_own_drafts():
	sql = es.page_condition(es.EditorScope(()), HANNAH, table="p")
	assert sql == (
		"(((coalesce(p.route, '') = '' or (p.route like 'pages/%' and p.route not like 'pages/%/%'))"
		" and p.owner = 'hannah@thegrieves.ca'))"
	)


@pytest.mark.parametrize(
	("route", "draft"),
	[
		(None, True),
		("", True),
		("pages/page-1a2b", True),
		("pages/", False),
		("pages/a/b", False),
		("pagesx/a", False),
	],
)
def test_draft_routes(route, draft):
	assert es.is_draft_route(route) is draft


def test_builders_default_route_is_a_draft_only_for_its_creator():
	# Builder routes a new or duplicated page to pages/<hash>
	assert SCOPE.page_allowed("pages/page-1a2b", HANNAH, HANNAH)
	assert not SCOPE.page_allowed("pages/page-1a2b", "jameson@zephyrex.ca", HANNAH)
	assert not SCOPE.page_allowed("pages/a/b", HANNAH, HANNAH)


@pytest.mark.parametrize(
	("path", "cmd", "method"),
	[
		("/api/method/builder.ai.api.run", None, "builder.ai.api.run"),
		("/api/v2/method/builder.ai.api.run", None, "builder.ai.api.run"),
		("/api/v1/method/builder.api.delete_folder/", None, "builder.api.delete_folder"),
		("/", "builder.ai.api.run", "builder.ai.api.run"),
		("/api/resource/Builder Page", None, None),
		("/hannah-thegrieves-ca/home", None, None),
	],
)
def test_requested_method_by_any_route(path, cmd, method):
	assert es.requested_method(path, cmd) == method


@pytest.mark.parametrize(
	("method", "refused"),
	[
		("builder.ai.api.run", True),
		("builder.ai.agent.anything", True),
		("builder.api.delete_folder", True),
		("builder.builder.doctype.builder_settings.builder_settings.replace_component", True),
		("builder.builder.doctype.builder_page.builder_page.get_block_data", True),
		("builder.api.duplicate_page", False),
		("builder.aix.api.run", False),
		("frappe.client.save", False),
		(None, False),
	],
)
def test_refused_methods(method, refused):
	assert es.refused_method(method) is refused


def test_new_names_may_not_follow_another_sites_naming():
	everyone = (*SCOPE.sites, es.SiteRef("Zephyrex", "zephyrex-ca"))
	assert es.names_of_other_sites("zephyrex-ca-header", SCOPE, everyone)
	assert es.names_of_other_sites("Zephyrex · Hero", SCOPE, everyone)
	assert not es.names_of_other_sites("hannah-thegrieves-ca-header", SCOPE, everyone)
	assert not es.names_of_other_sites("a1b2c3", SCOPE, everyone)
