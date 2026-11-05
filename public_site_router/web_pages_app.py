# SPDX-License-Identifier: AGPL-3.0-or-later
"""The "Web Pages" tile on the desk's apps screen.

Frappe v16 lists Web Page under its own Framework app, which shows only to System Managers
(``frappe.permissions.check_app_permission``), and sending a user there whose default app is
``frappe`` lands a Website Manager on "no access". This tile opens the Web Page list instead and
shows to anyone who may edit Web Pages, so a website editor can make it their default app."""

import frappe

ROUTE = "/desk/web-page"


def can_open_web_pages() -> bool:
	"""``has_permission`` hook of the apps-screen entry: a signed-in user who may write Web Pages."""
	if frappe.session.user == "Guest":
		return False
	return bool(frappe.has_permission("Web Page", "write"))
