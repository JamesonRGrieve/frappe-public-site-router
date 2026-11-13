# SPDX-License-Identifier: AGPL-3.0-or-later
"""Site Editors: Builder access limited to the sites a user is listed on (rules in ``editor_scope``).

Frappe's own roles can't do this: Website Manager edits every site on the ERP. A Site Editor gets doctype-level
rights on Builder's doctypes from the Site Editor role (``ensure_role``, after migrate), and the hooks here narrow
them per document:

- ``has_permission`` and ``permission_query_conditions`` for Builder Page, Builder Component, Block Template,
  Builder Client Script and Builder Snapshot;
- ``validate`` events that check the stored document too (a save can't move another site's page into one's own
  prefix) and refuse new Jinja expressions and data-script changes;
- overrides of Builder's whitelisted methods that write with ``frappe.db.set_value`` or run a script passed by the
  caller, which bypass the checks above; ``before_request`` refuses Builder's AI agent, which saves with
  ``ignore_permissions``.

Users with Website Manager or System Manager are never scoped: every hook returns at once for them.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import frappe
from frappe import _

from public_site_router import editor_scope as es
from public_site_router import seo

EDITOR_TABLE = "Public Site Editor"
# Per-request cache of each user's scope (Frappe resets flags for every request).
SCOPE_CACHE_FLAG = "public_site_editor_scopes"
# Doctype-level rights the Site Editor role carries; the hooks narrow each to the editor's own documents.
ROLE_PERMISSIONS: dict[str, tuple[str, ...]] = {
	"Builder Page": ("read", "write", "create", "delete"),
	"Builder Component": ("read", "write", "create"),
	"Block Template": ("read", "write", "create"),
	"Builder Client Script": ("read", "write", "create"),
	"Builder Project Folder": ("read", "create"),
	"Builder Snapshot": ("read",),
	"Builder Settings": ("read",),
	"Builder Token": ("read",),
	"User Font": ("read", "create"),
}
# Builder Page fields Builder renders through Jinja (canonical_url is checked separately: the router sets it).
PAGE_TEMPLATE_FIELDS = ("blocks", "draft_blocks", "head_html", "body_html", "page_title", "meta_description")


# ---- who is scoped ------------------------------------------------------------------------------------------


def scope_for(user: str | None = None) -> es.EditorScope | None:
	"""The user's editor scope, or None when they aren't a scoped Site Editor. Cached for the request."""
	user = user or frappe.session.user
	cache = frappe.local.flags.setdefault(SCOPE_CACHE_FLAG, {})
	if user not in cache:
		cache[user] = _load_scope(user)
	return cache[user]


def _load_scope(user: str) -> es.EditorScope | None:
	if user in ("Administrator", "Guest") or not es.is_scoped(frappe.get_roles(user)):
		return None
	names = frappe.get_all(EDITOR_TABLE, filters={"user": user, "parenttype": "Public Site"}, pluck="parent")
	sites = frappe.get_all(
		"Public Site",
		filters={"name": ["in", names or [""]]},
		fields=["name", "route_prefix"],
		order_by="name",
	)
	return es.EditorScope(tuple(es.SiteRef(s.name, s.route_prefix) for s in sites))


def clear_scope_cache() -> None:
	frappe.local.flags.pop(SCOPE_CACHE_FLAG, None)


# ---- per-document permission ----------------------------------------------------------------------------------


def _owner(doc: Any) -> str | None:
	return doc.get("owner") or (frappe.session.user if doc.is_new() else None)


def page_permission(doc: Any, ptype: str | None = None, user: str | None = None, **_kwargs: Any) -> bool:
	scope = scope_for(user)
	return scope is None or scope.page_allowed(doc.get("route"), _owner(doc), user or frappe.session.user)


def component_permission(doc: Any, ptype: str | None = None, user: str | None = None, **_kwargs: Any) -> bool:
	scope = scope_for(user)
	return scope is None or scope.component_allowed(doc.name, _owner(doc), user or frappe.session.user)


def pattern_permission(doc: Any, ptype: str | None = None, user: str | None = None, **_kwargs: Any) -> bool:
	scope = scope_for(user)
	return scope is None or scope.pattern_allowed(doc.name, _owner(doc), user or frappe.session.user)


def script_permission(doc: Any, ptype: str | None = None, user: str | None = None, **_kwargs: Any) -> bool:
	"""A client script the editor created, or one that a page of theirs uses."""
	user = user or frappe.session.user
	scope = scope_for(user)
	if scope is None or _owner(doc) == user:
		return True
	return bool(
		frappe.db.sql(f"select 1 from ({_scripts_in_scope(scope, user)}) s where s.name = %s", doc.name)
	)


def snapshot_permission(doc: Any, ptype: str | None = None, user: str | None = None, **_kwargs: Any) -> bool:
	scope = scope_for(user)
	if scope is None:
		return True
	if doc.get("reference_doctype") != "Builder Page":
		return False
	return frappe.has_permission("Builder Page", "read", doc.get("reference_name"), user=user)


# ---- list filters ---------------------------------------------------------------------------------------------


def _conditions(user: str | None, build: Callable[[es.EditorScope, str], str]) -> str:
	user = user or frappe.session.user
	scope = scope_for(user)
	return "" if scope is None else build(scope, user)


def _scripts_in_scope(scope: es.EditorScope, user: str) -> str:
	pages = es.page_condition(scope, user, frappe.db.escape, table="p")
	return (
		"select cs.builder_script as name from `tabBuilder Page Client Script` cs"
		f" join `tabBuilder Page` p on p.name = cs.parent where {pages}"
	)


def page_conditions(user: str | None = None, doctype: str | None = None) -> str:
	return _conditions(user, lambda scope, u: es.page_condition(scope, u, frappe.db.escape))


def component_conditions(user: str | None = None, doctype: str | None = None) -> str:
	return _conditions(
		user,
		lambda scope, u: es.name_condition(
			[s.prefix + es.COMPONENT_SEPARATOR for s in scope.sites],
			u,
			"`tabBuilder Component`",
			frappe.db.escape,
		),
	)


def pattern_conditions(user: str | None = None, doctype: str | None = None) -> str:
	return _conditions(
		user,
		lambda scope, u: es.name_condition(
			[s.name + es.PATTERN_SEPARATOR for s in scope.sites], u, "`tabBlock Template`", frappe.db.escape
		),
	)


def script_conditions(user: str | None = None, doctype: str | None = None) -> str:
	return _conditions(
		user,
		lambda scope, u: (
			f"(`tabBuilder Client Script`.owner = {frappe.db.escape(u)}"
			f" or `tabBuilder Client Script`.name in ({_scripts_in_scope(scope, u)}))"
		),
	)


def snapshot_conditions(user: str | None = None, doctype: str | None = None) -> str:
	return _conditions(
		user,
		lambda scope, u: (
			"(`tabBuilder Snapshot`.reference_doctype = 'Builder Page' and `tabBuilder Snapshot`.reference_name in"
			f" (select p.name from `tabBuilder Page` p where {es.page_condition(scope, u, frappe.db.escape, 'p')}))"
		),
	)


# ---- saves ----------------------------------------------------------------------------------------------------


def _refuse_new_expressions(doc: Any, fields: tuple[str, ...]) -> None:
	before = doc.get_doc_before_save()
	for field in fields:
		added = es.new_template_expressions(before.get(field) if before else None, doc.get(field))
		if added:
			frappe.throw(
				_(
					"Template code like {0} can only be added by a Website Manager. Remove it and save again."
				).format(frappe.bold(added[0])),
				frappe.PermissionError,
			)


def _refuse_changed(doc: Any, field: str, label: str) -> None:
	before = doc.get_doc_before_save()
	if (doc.get(field) or "") != ((before.get(field) if before else None) or ""):
		frappe.throw(_("Only a Website Manager can change the {0}.").format(label), frappe.PermissionError)


def _refuse_outside(allowed: bool) -> None:
	if not allowed:
		frappe.throw(_("You can only edit your own site's pages and blocks."), frappe.PermissionError)


def _refuse_other_sites_name(doc: Any, scope: es.EditorScope) -> None:
	if not doc.is_new():
		return
	sites = [
		es.SiteRef(s.name, s.route_prefix)
		for s in frappe.get_all("Public Site", fields=["name", "route_prefix"])
	]
	if es.names_of_other_sites(doc.name or "", scope, sites):
		frappe.throw(_("That name belongs to another site. Choose another name."), frappe.PermissionError)


def validate_page(doc: Any, method: str | None = None) -> None:
	user = frappe.session.user
	scope = scope_for(user)
	if scope is None:
		return
	before = doc.get_doc_before_save()
	_refuse_outside(scope.page_allowed(doc.route, _owner(doc), user))
	if before:
		_refuse_outside(scope.page_allowed(before.route, before.owner, user))
	_refuse_changed(doc, "page_data_script", _("page data script"))
	_refuse_new_expressions(doc, PAGE_TEMPLATE_FIELDS)
	if doc.canonical_url and doc.canonical_url not in seo.BUILDER_CANONICAL_TEMPLATES:
		_refuse_new_expressions(doc, ("canonical_url",))


def validate_component(doc: Any, method: str | None = None) -> None:
	user = frappe.session.user
	scope = scope_for(user)
	if scope is None:
		return
	before = doc.get_doc_before_save()
	_refuse_outside(scope.component_allowed(doc.name, _owner(doc), user))
	if before:
		_refuse_outside(scope.component_allowed(before.name, before.owner, user))
	_refuse_other_sites_name(doc, scope)
	_refuse_changed(doc, "component_data_script", _("component data script"))
	_refuse_new_expressions(doc, ("block",))


def validate_pattern(doc: Any, method: str | None = None) -> None:
	user = frappe.session.user
	scope = scope_for(user)
	if scope is None:
		return
	_refuse_outside(scope.pattern_allowed(doc.name, _owner(doc), user))
	_refuse_other_sites_name(doc, scope)
	_refuse_new_expressions(doc, ("block",))


# ---- Builder's whitelisted methods ----------------------------------------------------------------------------


def before_request() -> None:
	"""Refuse a Site Editor the Builder methods that act on every site or save without permission checks."""
	request = getattr(frappe.local, "request", None)
	if request is None:
		return
	method = es.requested_method(request.path, frappe.form_dict.get("cmd"))
	if es.refused_method(method) and scope_for() is not None:
		raise frappe.PermissionError(_("Site editors can't use this Builder feature."))


def _require(doctype: str, ptype: str, name: str) -> None:
	if scope_for() is not None:
		frappe.has_permission(doctype, ptype, name, throw=True)


@frappe.whitelist()
def duplicate_page(page_name: str) -> Any:
	from builder import api

	_require("Builder Page", "read", page_name)
	return api.duplicate_page(page_name)


@frappe.whitelist()
def update_page_folder(pages: list[str] | str, folder_name: str) -> None:
	from builder import api

	pages = frappe.parse_json(pages) if isinstance(pages, str) else pages
	for page in pages or []:
		_require("Builder Page", "write", page)
	api.update_page_folder(pages, folder_name)


@frappe.whitelist()
def reorder_client_scripts(script_order: list[str] | str) -> None:
	from builder import api

	script_order = frappe.parse_json(script_order) if isinstance(script_order, str) else script_order
	if scope_for() is not None:
		for row in script_order or []:
			page = frappe.db.get_value("Builder Page Client Script", row, "parent")
			if not page:
				frappe.throw(_("Unknown client script row {0}.").format(row))
			_require("Builder Page", "write", page)
	api.reorder_client_scripts(script_order)


@frappe.whitelist()
def sync_component(component_id: str) -> None:
	from builder import api

	_require("Builder Component", "write", component_id)
	api.sync_component(component_id)


@frappe.whitelist()
def get_component_data(
	component_name: str, props: dict | str | None = None, script: str | None = None
) -> dict:
	"""A Site Editor may preview a component's stored data script, never run a script of their own."""
	from builder import api

	if scope_for() is not None:
		frappe.has_permission("Builder Component", "read", component_name, throw=True)
		stored = frappe.db.get_value("Builder Component", component_name, "component_data_script")
		if script is not None and (script or "") != (stored or ""):
			frappe.throw(
				_("Only a Website Manager can run a changed component data script."), frappe.PermissionError
			)
	return api.get_component_data(component_name, props, script)


# ---- the role -------------------------------------------------------------------------------------------------


def ensure_role() -> None:
	"""The Site Editor role and its doctype-level rights on every installed Builder doctype (idempotent)."""
	from frappe.permissions import add_permission, update_permission_property

	if not frappe.db.exists("Role", es.EDITOR_ROLE):
		frappe.get_doc({"doctype": "Role", "role_name": es.EDITOR_ROLE, "desk_access": 1}).insert(
			ignore_permissions=True
		)
	for doctype, ptypes in ROLE_PERMISSIONS.items():
		if not frappe.db.exists("DocType", doctype):
			continue
		if not frappe.db.exists(
			"Custom DocPerm", {"parent": doctype, "role": es.EDITOR_ROLE, "permlevel": 0}
		):
			add_permission(doctype, es.EDITOR_ROLE, 0)
		for ptype in ptypes:
			update_permission_property(doctype, es.EDITOR_ROLE, 0, ptype, 1, validate=False)
