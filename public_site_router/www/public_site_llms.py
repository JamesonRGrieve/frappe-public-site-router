# SPDX-License-Identifier: AGPL-3.0-or-later
"""A Public Site's /llms.txt (the router maps it here on the site's hosts; a 404 anywhere else or when the site
has none)."""

from public_site_router.site_seo import llms_txt

# One endpoint serves every site's llms.txt, so it must never be cached by endpoint.
no_cache = 1
base_template_path = "www/public_site_llms.txt"


def get_context(context):
	return {"llms_txt": llms_txt()}
