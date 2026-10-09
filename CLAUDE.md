# frappe-public-site-router — Agent Operating Guide

AGPL-3.0-or-later Frappe v16 app. One Frappe/ERPNext site serves several separate businesses'
public websites, each isolated to its own host names. No Frappe fork: it uses Frappe's
`website_path_resolver` hook.

## Model

- **Public Site**: `site_name`, `enabled`, `company`, `route_prefix` (one lowercase URL segment,
  unique; by convention the primary domain with its dots as hyphens, e.g. `zephyrex-ca`), analytics
  (`view_tracking`, `ga4_measurement_id`, `matomo_url`, `matomo_site_id`), `home_route` (under the prefix, default `home`), `webshop_store` (name of a
  frappe-webshop fork `Webshop Store`, optional), `blog_category` (name of a blog-app `Blog Category`,
  optional, one site per category), `domains` (child **Public Site Domain**, host
  names normalised to lowercase, no port; unique across sites).

## Routing (`router.py`)

On a host that belongs to an enabled Public Site:
- `/` → `<prefix>/<home_route>`
- `/<path>` → `<prefix>/<path>` when a published Web Page / Web Form / Builder Page has that route
- `/<any site prefix>/...` (its own or another's) → `PageDoesNotExistError` (one URL per page; no
  cross-site access)
- `/sitemap.xml` and `/robots.txt` → the site's own (`public_site_sitemap.xml` /
  `public_site_robots.txt` in `www/`, built by `site_seo`); see **SEO** below
- technical pages (`404`, `error`, `message`, `website_script.js`) pass through on
  every site host; account/portal routes (`login`, `me`, `orders`, …), webshop pages (`cart`,
  `all-products`, …) and published Website Item / Item Group pages pass through only on a site
  with a `webshop_store`
- on a site with a `blog_category`: `/` → that category's listing (`blog/<category>`, instead of the
  home route), and `/<path>` → a published Blog Post of that category routed `<path>`. Posts keep
  **root** routes (not prefixed) because the blog app links posts as `/<route>` in its listing,
  RSS and sitemap; the category is what isolates them. A site page with the same path wins.
- anything else (ERPNext's generic about/contact pages, desk, the global sitemap, other global
  pages) → `PageDoesNotExistError`, so a site shows only what it published.

Hosts of a **disabled** Public Site serve nothing (every website route → `PageDoesNotExistError`), so
a domain can be live in DNS before its site launches without exposing the ERP's own website. Static
files and the API are not website routes and are never affected. Hosts with no Public Site at all
(e.g. the ERP's own host) are not rewritten.

`resolve_path` then hands the (possibly rewritten) path to the rest of the resolver chain: every
other app's `website_path_resolver` (Builder's resolves Builder Pages incl. dynamic routes), else
Frappe's own `resolve_path`. **Frappe keeps only the LAST handler's endpoint**, so this app must be
installed after any other app that registers `website_path_resolver`.

The host → site map is cached (`public_site_router_site_map`) and cleared on Public Site save/delete.

## SEO (`seo.py` pure, `site_seo.py` Frappe)

- A site's **canonical host** is its first domain that is not a `www.` alias. Every URL the site
  publishes names it, so apex and `www` render identical HTML (Frappe caches pages per endpoint).
- `/sitemap.xml`: the site's published Web Pages, Builder Pages and Web Forms under its prefix (as
  clean URLs; the home page is `/`), its blog category's published posts (and the listing at `/`), and
  its store's published Website Items. Dynamic routes are left out. `lastmod` is the document's
  `modified` day.
- `/robots.txt`: disallows the desk, API and account pages and names the site's sitemap.
- `update_website_context` hook: appends `<link rel="canonical">` to `head_html`, sets `og:url` and
  `og:site_name`, and moves absolute image URLs Frappe built on the ERP's own host (`get_url()`) onto
  the canonical host. Nothing on technical pages, 404s or hosts outside a Public Site.
- `favicon` (Public Site, square PNG): the same hook sets `context.favicon` (base.html's tab icon) and adds
  an `apple-touch-icon` link, both on the canonical host. Empty keeps the Website Settings favicon.
- Both `www/public_site_*` pages are `no_cache` (one endpoint serves every site) and 404 off a site host.
- Per-page titles, descriptions, `meta_image` (Open Graph card) and JSON-LD belong to the page content
  (Web Page fields and its HTML), not this app.

## Analytics (`analytics.py` pure, `site_analytics.py` Frappe)

Per Public Site, any combination of providers, each added to every page of that site by the
`update_website_context` hook:
- **Frappe view tracking** (`view_tracking`, default on): a cookieless beacon (referrer, time zone, UTM
  tags; skipped under Do Not Track / Global Privacy Control) to `site_analytics.log_view`, which records a
  `Web Page View` stamped with `public_site` (a custom field created by the `after_migrate` hook). Frappe's
  own `make_view_log` cannot serve public sites: it accepts only Referers on the ERP's host and records no
  host. The global Website Settings `enable_view_tracking` is not needed.
- **Google Analytics 4** (`ga4_measurement_id`, validated `G-…`): the Google tag.
- **Matomo** (`matomo_url` https + `matomo_site_id` numeric): the standard tracker.

Values are validated on save and re-validated before they reach a snippet; strings are embedded with
`json.dumps`. Saving a Public Site clears the website page cache so a change shows at once.

## Webshop stores

Implements the frappe-webshop fork's `webshop_store_resolver` hook: the request's site's
`webshop_store`. One host list drives both page isolation and store selection.

## Caching

Frappe caches rendered pages by endpoint. Endpoints here are host-specific (`<prefix>/...`), so a
site's cached HTML is never served on another host. Shared routes whose content varies by host
(webshop product/listing pages) are made `no_cache` by the fork in multi-store mode.

## Testing

`bench --site <site> run-tests --app public_site_router` (real DB). The webshop test class runs
end-to-end through the fork when `webshop` is installed, and is skipped otherwise.

The pure SEO logic is unit-tested without a bench: `uv run --no-project --with pytest python -I -m pytest`
(`tests/`). Lint: `uvx ruff format --check . && uvx ruff check .`
