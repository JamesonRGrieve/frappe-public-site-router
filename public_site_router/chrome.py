# SPDX-License-Identifier: AGPL-3.0-or-later
"""Which Public Site pages render standalone, and how the router's head markup reaches every page (pure logic;
``site_chrome``, ``site_seo`` and ``site_analytics`` apply it).

A standalone page carries only what its own content brings: Frappe's website stylesheets and scripts, its standard
footer and its page wrapper are left out."""

from html.parser import HTMLParser

# The site's own pages. Login, webshop, blog and Not Found pages are Frappe's or another app's, styled by their
# bundles, so they keep them.
STANDALONE_DOCTYPES = frozenset({"Web Page"})
# A top-level element of a page's content marked with this attribute is main content. Page Builder renders each block
# on its own, so a page of header / section / footer blocks can't have one block wrap the others in <main>.
MAIN_CONTENT_ATTR = "data-main-content"
# A Builder Page renders its own <head> from this context key, which Builder fills before the update_website_context
# hooks run, and ignores Frappe's ``head_html``.
BUILDER_HEAD_HTML = "_head_html"
VOID = frozenset(
	{"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "source", "track", "wbr"}
)


class _TopLevel(HTMLParser):
	"""Character spans of the top-level elements of an HTML fragment, and whether each is marked main content."""

	def __init__(self, text):
		super().__init__(convert_charrefs=False)
		self.lines = [0]
		for line in text.splitlines(keepends=True):
			self.lines.append(self.lines[-1] + len(line))
		self.depth, self.spans, self.start = 0, [], None

	def position(self):
		line, col = self.getpos()
		return self.lines[line - 1] + col

	def handle_starttag(self, tag, attrs):
		if self.depth == 0:
			self.start = (self.position(), any(name == MAIN_CONTENT_ATTR for name, _ in attrs))
		if tag not in VOID:
			self.depth += 1
		elif self.depth == 0:
			self.spans.append((*self.start, self.position() + len(self.get_starttag_text())))

	def handle_endtag(self, tag):
		if tag in VOID or self.depth == 0:
			return
		self.depth -= 1
		if self.depth == 0:
			end = self.rawdata.index(">", self.position()) + 1
			self.spans.append((self.start[0], self.start[1], end))


def wrap_main(html):
	"""``html`` with the run of its top-level main-content elements (``data-main-content``) wrapped in
	``<main id="main">``, so a page assembled from separate blocks keeps one main landmark around its content and not
	its header or footer. Unchanged when it already has a <main> or marks nothing; the markup is otherwise untouched."""
	if "<main" in html or MAIN_CONTENT_ATTR not in html:
		return html
	parser = _TopLevel(html)
	parser.feed(html)
	parser.close()
	marked = [(start, end) for start, is_main, end in parser.spans if is_main]
	if not marked:
		return html
	first, last = marked[0][0], marked[-1][1]
	return f'{html[:first]}<main id="main">{html[first:last]}</main>{html[last:]}'


def add_head_html(context, html):
	"""Append ``html`` (canonical link, favicon, analytics) to a page's head: ``head_html`` for Frappe's templates, and
	``_head_html`` too on a Builder Page, whose template prints only that."""
	if not html:
		return
	context["head_html"] = (context.get("head_html") or "") + html
	if BUILDER_HEAD_HTML in context:
		context[BUILDER_HEAD_HTML] = (context.get(BUILDER_HEAD_HTML) or "") + html


def is_standalone(standalone_pages, doctype, own_template):
	"""Whether a page renders standalone: its site has Standalone Pages set, it is one of the site's own documents,
	and it hasn't chosen its own template."""
	return bool(standalone_pages) and doctype in STANDALONE_DOCTYPES and not own_template
