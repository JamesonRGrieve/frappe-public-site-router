# SPDX-License-Identifier: AGPL-3.0-or-later
from . import __version__ as _version

app_name = "public_site_router"
app_title = "Public Site Router"
app_publisher = "Zephyrex Technologies Limited"
app_description = "Isolate several businesses' public websites and webshop stores on one Frappe site, by host"
app_email = "jameson@zephyrex.ca"
app_license = "AGPL-3.0-or-later"
app_version = _version

required_apps = ["frappe"]

# Maps each request path to its host's site before the rest of the chain (Frappe's own
# resolver and any other app's, e.g. Builder) resolves it. Frappe keeps only the LAST
# handler's endpoint, so this app must be installed after any other app that registers
# website_path_resolver; router.resolve_path then calls those handlers itself.
website_path_resolver = "public_site_router.router.resolve_path"

# Rewrites a redirect to a site's prefixed route into its clean URL on that site's hosts.
after_request = ["public_site_router.router.clean_redirect"]

# Canonical link, og:url and og:site_name naming the request's site's canonical host, and the site's
# analytics providers (Frappe view tracking, GA4, Matomo).
update_website_context = [
	"public_site_router.site_seo.update_website_context",
	"public_site_router.site_analytics.update_website_context",
]

# Web Page View's public_site field (views stamped with their site).
after_migrate = ["public_site_router.site_analytics.ensure_custom_fields"]

# Answers the frappe-webshop fork's multi-store hook: which Webshop Store serves this request.
webshop_store_resolver = "public_site_router.router.get_request_store"
