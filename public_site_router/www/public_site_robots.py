# SPDX-License-Identifier: AGPL-3.0-or-later
"""A Public Site's /robots.txt (the router maps it here on the site's hosts; a 404 anywhere else)."""

from public_site_router.site_seo import robots_txt

# One endpoint serves every site's robots.txt, so it must never be cached by endpoint.
no_cache = 1
base_template_path = "www/public_site_robots.txt"


def get_context(context):
	return {"robots_txt": robots_txt()}
