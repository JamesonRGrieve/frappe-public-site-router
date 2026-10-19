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


HEADER = '<header class="h"><a href="#main">Skip</a><nav>Menu</nav></header>'
FOOTER = "<footer>Foot</footer>"


class TestWrapMain:
	def test_wraps_the_marked_run_between_header_and_footer(self):
		blocks = '<section data-main-content class="a">A</section>\n<div data-main-content><p>B</p></div>'
		html = HEADER + blocks + FOOTER
		assert chrome.wrap_main(html) == f'{HEADER}<main id="main">{blocks}</main>{FOOTER}'

	def test_unmarked_blocks_inside_the_run_stay_in_it(self):
		html = (
			HEADER
			+ "<section data-main-content>A</section><aside>X</aside><section data-main-content>B</section>"
			+ FOOTER
		)
		out = chrome.wrap_main(html)
		assert (
			out.index('<main id="main">')
			< out.index("<aside>")
			< out.index("</main>")
			< out.index("<footer>")
		)

	def test_content_with_its_own_main_is_untouched(self):
		html = HEADER + '<div class="zx"><main id="zx-main" data-main-content>A</main></div>' + FOOTER
		assert chrome.wrap_main(html) == html

	def test_nothing_marked_is_untouched(self):
		html = HEADER + "<section>A</section>" + FOOTER
		assert chrome.wrap_main(html) == html

	def test_nested_markers_do_not_count(self):
		html = HEADER + '<div class="w"><section data-main-content>A</section></div>' + FOOTER
		assert chrome.wrap_main(html) == html

	def test_scripts_styles_and_void_tags_are_handled(self):
		html = (
			HEADER + '<style>.a>b{}</style><img src="x"><section data-main-content>A<br>B</section>'
			'<script>if (a < b && c > d) { x("</p>"); }</script>' + FOOTER
		)
		out = chrome.wrap_main(html)
		assert '<main id="main"><section data-main-content>A<br>B</section></main><script>' in out
		assert out.replace('<main id="main">', "").replace("</main>", "") == html
