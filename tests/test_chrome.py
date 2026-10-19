# SPDX-License-Identifier: AGPL-3.0-or-later
"""Unit tests for which Public Site pages render standalone (no bench)."""

import pytest

from public_site_router import chrome


class TestIsStandalone:
	def test_web_page_on_a_standalone_site(self):
		assert chrome.is_standalone(1, "Web Page", None)

	@pytest.mark.parametrize("setting", [0, None, False])
	def test_site_without_the_setting_keeps_frappe_assets(self, setting):
		# None is also a site whose Standalone Pages column a migrate hasn't added yet.
		assert not chrome.is_standalone(setting, "Web Page", None)

	@pytest.mark.parametrize(
		"doctype", ["Website Item", "Item Group", "Blog Post", "Web Form", "Builder Page", None]
	)
	def test_pages_other_apps_style_keep_frappe_assets(self, doctype):
		assert not chrome.is_standalone(1, doctype, None)

	def test_page_with_its_own_template_keeps_it(self):
		assert not chrome.is_standalone(1, "Web Page", "templates/custom.html")
