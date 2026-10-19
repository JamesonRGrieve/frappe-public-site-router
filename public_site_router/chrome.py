# SPDX-License-Identifier: AGPL-3.0-or-later
"""Which Public Site pages render standalone (pure logic; ``site_chrome`` applies it).

A standalone page carries only what its own content brings: Frappe's website stylesheets and scripts, its standard
footer and its page wrapper are left out."""

# The site's own pages. Login, webshop, blog and Not Found pages are Frappe's or another app's, styled by their
# bundles, so they keep them.
STANDALONE_DOCTYPES = frozenset({"Web Page"})


def is_standalone(standalone_pages, doctype, own_template):
	"""Whether a page renders standalone: its site has Standalone Pages set, it is one of the site's own documents,
	and it hasn't chosen its own template."""
	return bool(standalone_pages) and doctype in STANDALONE_DOCTYPES and not own_template
