# SPDX-License-Identifier: AGPL-3.0-or-later
"""Which website documents a Site Editor may touch (pure; the Frappe side is ``site_editors``).

A **Site Editor** is a user listed in a Public Site's Editors table who holds the Site Editor role and neither
Website Manager nor System Manager. They edit their own sites in Builder and nothing else:

- a **Builder Page** whose route is under one of their sites' prefixes (``<prefix>/…``) or the matching preview
  prefix (``<prefix>-builder/…``), or a page with no route yet that they created (a fresh duplicate);
- a **Builder Component** whose name starts ``<prefix>-`` (``zephyrex-ca-header``), or that they created;
- a **Block Template** (pattern) whose name starts ``<Site name> · ``, or that they created.

Builder renders every page's content, head and body HTML through Jinja, whose globals read any table; and page and
component data scripts run server-side. So a Site Editor's save may not add a template expression or change a data
script (``new_template_expressions``): those stay with Website Managers.
"""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Callable, Iterable
from dataclasses import dataclass

EDITOR_ROLE = "Site Editor"
# Roles that edit every site; a user holding one is never scoped.
UNSCOPED_ROLES = frozenset({"System Manager", "Website Manager"})
PREVIEW_SUFFIX = "-builder"
# Builder routes a page it creates without one (new or duplicated) to pages/<hash>: a draft, not on any site. The hash
# is not the page's final name (Builder names the page again on insert), so any one-segment pages/ route is a draft.
DRAFT_ROUTE_PREFIX = "pages/"
COMPONENT_SEPARATOR = "-"
PATTERN_SEPARATOR = " · "
# Builder's whitelisted methods a Site Editor may never call: they act on every site at once, or run a script the
# caller passes, or (the AI agent) save with ignore_permissions.
REFUSED_METHOD_PREFIXES = ("builder.ai.",)
REFUSED_METHODS = frozenset(
	{
		"builder.api.delete_folder",
		"builder.builder.doctype.builder_settings.builder_settings.replace_component",
		"builder.builder.doctype.builder_page.builder_page.get_block_data",
	}
)
# Frappe dispatches a whitelisted method from either REST version's path, or from a legacy ``cmd`` form value.
API_METHOD_PATHS = ("/api/method/", "/api/v1/method/", "/api/v2/method/")
# Jinja's three delimiters, as Frappe's environment uses them.
TEMPLATE_EXPRESSION = re.compile(r"\{\{.*?\}\}|\{%.*?%\}|\{#.*?#\}", re.DOTALL)


def is_scoped(roles: Iterable[str]) -> bool:
	"""Whether a user with these roles is a Site Editor limited to their own sites."""
	held = set(roles)
	return EDITOR_ROLE in held and not held & UNSCOPED_ROLES


def requested_method(path: str, cmd: str | None = None) -> str | None:
	"""The whitelisted method a request calls, by path or by ``cmd``, or None."""
	if cmd:
		return cmd.strip()
	for prefix in API_METHOD_PATHS:
		if path.startswith(prefix):
			return path[len(prefix) :].strip("/") or None
	return None


def refused_method(method: str | None) -> bool:
	"""Whether a whitelisted method is one Site Editors are refused."""
	return bool(method) and (method in REFUSED_METHODS or method.startswith(REFUSED_METHOD_PREFIXES))


@dataclass(frozen=True)
class SiteRef:
	name: str  # the Public Site's name (its site_name)
	prefix: str  # its route prefix


@dataclass(frozen=True)
class EditorScope:
	sites: tuple[SiteRef, ...]

	@property
	def route_prefixes(self) -> tuple[str, ...]:
		"""Every route prefix the editor's pages may live under: each site's own and its preview prefix."""
		return tuple(p for site in self.sites for p in (site.prefix, site.prefix + PREVIEW_SUFFIX))

	def route_allowed(self, route: str | None) -> bool:
		route = (route or "").strip("/")
		return any(route == p or route.startswith(p + "/") for p in self.route_prefixes)

	def page_allowed(self, route: str | None, owner: str | None, user: str) -> bool:
		"""A page on one of the editor's sites, or a draft (no route, or Builder's default one) they created."""
		if is_draft_route(route):
			return owner == user
		return self.route_allowed(route)

	def component_allowed(self, name: str | None, owner: str | None, user: str) -> bool:
		return owner == user or any(
			(name or "").startswith(s.prefix + COMPONENT_SEPARATOR) for s in self.sites
		)

	def pattern_allowed(self, name: str | None, owner: str | None, user: str) -> bool:
		return owner == user or any((name or "").startswith(s.name + PATTERN_SEPARATOR) for s in self.sites)


def names_of_other_sites(name: str, scope: EditorScope, all_sites: Iterable[SiteRef]) -> bool:
	"""Whether a new component or pattern's name follows another site's naming (which only that site's editors use)."""
	own = {site.name for site in scope.sites}
	return any(
		name.startswith(site.prefix + COMPONENT_SEPARATOR) or name.startswith(site.name + PATTERN_SEPARATOR)
		for site in all_sites
		if site.name not in own
	)


def is_draft_route(route: str | None) -> bool:
	route = (route or "").strip("/")
	rest = route[len(DRAFT_ROUTE_PREFIX) :] if route.startswith(DRAFT_ROUTE_PREFIX) else None
	return not route or (bool(rest) and "/" not in rest)


def template_expressions(text: str | None) -> Counter[str]:
	return Counter(TEMPLATE_EXPRESSION.findall(text or ""))


def new_template_expressions(before: str | None, after: str | None) -> list[str]:
	"""The Jinja expressions ``after`` holds beyond those ``before`` already held (a count each)."""
	return sorted((template_expressions(after) - template_expressions(before)).elements())


Quote = Callable[[str], str]


def sql_quote(value: str) -> str:
	"""A single-quoted SQL string literal (the tests' stand-in for ``frappe.db.escape``)."""
	return "'" + value.replace("\\", "\\\\").replace("'", "''") + "'"


def like_escape(value: str) -> str:
	return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def page_condition(
	scope: EditorScope, user: str, quote: Quote = sql_quote, table: str = "`tabBuilder Page`"
) -> str:
	"""The SQL a list of Builder Pages is filtered by: routes under the editor's prefixes, or their own unrouted pages."""
	clauses = [f"{table}.route = {quote(p)}" for p in scope.route_prefixes]
	clauses += [f"{table}.route like {quote(like_escape(p) + '/%')}" for p in scope.route_prefixes]
	draft = (
		f"(coalesce({table}.route, '') = '' or ({table}.route like {quote(DRAFT_ROUTE_PREFIX + '%')}"
		f" and {table}.route not like {quote(DRAFT_ROUTE_PREFIX + '%/%')}))"
	)
	clauses.append(f"({draft} and {table}.owner = {quote(user)})")
	return "(" + " or ".join(clauses) + ")"


def name_condition(prefixes: Iterable[str], user: str, table: str, quote: Quote = sql_quote) -> str:
	"""The SQL a list of components or patterns is filtered by: a name starting with one of ``prefixes``, or theirs."""
	clauses = [f"{table}.name like {quote(like_escape(p) + '%')}" for p in prefixes]
	clauses.append(f"{table}.owner = {quote(user)}")
	return "(" + " or ".join(clauses) + ")"
