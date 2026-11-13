# SPDX-License-Identifier: AGPL-3.0-or-later
"""The apps-screen "Web Pages" tile: declared once, opens the Web Page list on the desk, and its permission
hook resolves to the module's function (no bench)."""

import ast
import pathlib
import re

HOOKS = pathlib.Path(__file__).resolve().parents[1] / "public_site_router" / "hooks.py"


def _apps_screen():
	tree = ast.parse(HOOKS.read_text())
	for node in tree.body:
		if isinstance(node, ast.Assign) and any(
			getattr(t, "id", "") == "add_to_apps_screen" for t in node.targets
		):
			return ast.literal_eval(node.value)
	raise AssertionError("hooks.py declares no add_to_apps_screen")


def test_one_web_pages_tile_on_the_desk():
	(tile,) = _apps_screen()
	assert tile["name"] == "public_site_router" and tile["title"] == "Web Pages"
	# Frappe treats /desk and /desk/* as desk routes (frappe.apps.DESK_APP_PATTERN).
	assert re.match(r"^/desk(/.*)?$", tile["route"]) and tile["route"] == "/desk/web-page"


def test_permission_hook_names_the_module_function():
	(tile,) = _apps_screen()
	module, func = tile["has_permission"].rsplit(".", 1)
	path = HOOKS.parent.parent / (module.replace(".", "/") + ".py")
	assert func in {n.name for n in ast.parse(path.read_text()).body if isinstance(n, ast.FunctionDef)}
	assert (HOOKS.parent / "public" / "images" / "web-pages.svg").exists()
