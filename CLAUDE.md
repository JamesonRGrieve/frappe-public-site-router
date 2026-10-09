# frappe-public-site-router — Agent Operating Guide

AGPL-3.0-or-later Frappe v16 app. One Frappe/ERPNext site serves several separate businesses'
public websites, each isolated to its own host names. No Frappe fork: it uses Frappe's
`website_path_resolver` hook.

## Model

- **Public Site**: `site_name`, `enabled`, `company`, `route_prefix` (one lowercase URL segment,
  unique), `home_route` (under the prefix, default `home`), `webshop_store` (name of a
  frappe-webshop fork `Webshop Store`, optional), `blog_category` (name of a blog-app `Blog Category`,
  optional, one site per category), `domains` (child **Public Site Domain**, host
  names normalised to lowercase, no port; unique across sites).

## Routing (`router.py`)

On a host that belongs to an enabled Public Site:
- `/` → `<prefix>/<home_route>`
- `/<path>` → `<prefix>/<path>` when a published Web Page / Web Form / Builder Page has that route
- `/<any site prefix>/...` (its own or another's) → `PageDoesNotExistError` (one URL per page; no
  cross-site access)
- technical pages (`404`, `error`, `message`, `robots.txt`, `website_script.js`) pass through on
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
