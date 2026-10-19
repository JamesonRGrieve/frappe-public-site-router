# SPDX-License-Identifier: AGPL-3.0-or-later
"""A Public Site's /BingSiteAuth.xml (the router maps it here on the site's hosts; a 404 anywhere else or when
the site has no Bing code)."""

from public_site_router.site_seo import bing_site_auth_xml

# One endpoint serves every site's file, so it must never be cached by endpoint.
no_cache = 1
base_template_path = "www/public_site_bing.xml"


def get_context(context):
	return {"bing_site_auth_xml": bing_site_auth_xml()}
