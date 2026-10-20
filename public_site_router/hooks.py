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

# Rewrites a redirect to a site's prefixed route into its clean URL on that site's hosts, gives a page the
# router refused its real 404 status (Frappe renders a resolver's refusal as a 200 Not Found), and adds the
# security headers on sites that ask for them.
after_request = [
	"public_site_router.router.clean_redirect",
	"public_site_router.router.not_found_status",
	"public_site_router.router.security_headers",
]

# Canonical link, og:url and og:site_name naming the request's site's canonical host, the site's
# analytics providers (Frappe view tracking, GA4, Matomo), and the base template without Frappe's navbar.
update_website_context = [
	"public_site_router.site_seo.update_website_context",
	"public_site_router.site_analytics.update_website_context",
	"public_site_router.site_chrome.update_website_context",
	# On a login or app host: the desk's apps screen / app switcher link each app with an App Host on its host.
	"public_site_router.app_hosts.update_website_context",
]

# App Hosts: on an app's own host, / opens the app and a signed-out visitor is handed off to the login host.
before_request = ["public_site_router.app_hosts.before_request"]

# Frappe apps' own app menus (e.g. CRM's) read frappe.apps.get_apps; on a login or app host it links each app with
# an App Host on its host.
override_whitelisted_methods = {
	"frappe.apps.get_apps": "public_site_router.app_hosts.get_apps",
	# Builder's own app menu (only called where Builder is installed).
	"builder.api.get_apps": "public_site_router.app_hosts.get_builder_apps",
}

# Web Page View's public_site field (views stamped with their site), and the canonical-URL template on site Builder
# Pages saved before it existed.
after_migrate = [
	"public_site_router.site_analytics.ensure_custom_fields",
	"public_site_router.site_seo.backfill_builder_canonicals",
]

# A site's Builder Pages name their clean URL as canonical (Builder prints its own canonical link from canonical_url).
doc_events = {"Builder Page": {"validate": "public_site_router.site_seo.set_builder_canonical"}}

# Answers the frappe-webshop fork's multi-store hook: which Webshop Store serves this request.
webshop_store_resolver = "public_site_router.router.get_request_store"
