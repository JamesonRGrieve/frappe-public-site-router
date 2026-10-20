# frappe-public-site-router — Agent Operating Guide

AGPL-3.0-or-later Frappe v16 app. One Frappe/ERPNext site serves several separate businesses'
public websites, each isolated to its own host names. No Frappe fork: it uses Frappe's
`website_path_resolver` hook.

## Model

- **Public Site**: `site_name`, `enabled`, `company`, `route_prefix` (one lowercase URL segment,
  unique; by convention the primary domain with its dots as hyphens, e.g. `zephyrex-ca`), analytics
  (`view_tracking`, `visitor_ids`, `ga4_measurement_id`, `matomo_url`, `matomo_site_id`), `home_route` (under the prefix, default `home`), `webshop_store` (name of a
  frappe-webshop fork `Webshop Store`, optional), `blog_category` (name of a blog-app `Blog Category`,
  optional, one site per category), `standalone_pages` (see **Page chrome**), `not_found_route` and
  `privacy_route` (routes under the prefix; see **Routing** and **Analytics**), `security_headers`, `content_signal`,
  `llms_txt` and `bing_site_auth` (see **SEO**), `domains` (child **Public Site Domain**, host
  names normalised to lowercase, no port; unique across sites).
- **App Host** (named by `host`): `host`, `app_route`, `login_host`, `enabled`, `label`; see **App Hosts**.

## Routing (`router.py`)

On a host that belongs to an enabled Public Site:
- `/` → `<prefix>/<home_route>`
- `/<path>` → `<prefix>/<path>` when a published Web Page / Web Form / Builder Page has that route
- `/<any site prefix>/...` (its own or another's) → `PageDoesNotExistError` (one URL per page; no
  cross-site access)
- `/sitemap.xml`, `/robots.txt`, `/llms.txt` and `/BingSiteAuth.xml` → the site's own
  (`public_site_sitemap.xml` / `_robots.txt` / `_llms.txt` / `_bing.xml` in `www/`, built by
  `site_seo`); see **SEO** below
- a missing page (any `PageDoesNotExistError` above) on a site with `not_found_route` → that published
  Web Page (`<prefix>/<not_found_route>`, in the site's own design), still answered with status 404;
  its own address is a 404 too and it is left out of the sitemap. Without one, Frappe's Not Found page
- technical pages (`404`, `error`, `message`, `website_script.js`, and Builder's colour-token stylesheet
  `builder_assets/tokens.css`, which every Builder Page links) pass through on every site host; account/portal routes (`login`, `me`, `orders`, …), webshop pages (`cart`,
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
- `/robots.txt`: disallows the desk, API and account pages and names the site's sitemap. With
  `content_signal` (validated `search|ai-input|ai-train = yes|no`, contentsignals.org) it adds a
  `Content-Signal:` line to the `User-agent: *` group, after a comment explaining the signals.
- **Security Headers** (`security_headers`, default off): an `after_request` hook gives every response on
  the site's hosts `Strict-Transport-Security: max-age=31536000` (no `includeSubDomains`, no `preload`),
  `X-Content-Type-Options: nosniff`, `X-Frame-Options: SAMEORIGIN` and `Referrer-Policy:
  strict-origin-when-cross-origin` (`seo.SECURITY_HEADERS`), unless the response already sets one. Set at
  the app, not the edge: HAProxy's header rewrites apply to every service behind the frontend.
- `/llms.txt` (`llms_txt`, Markdown, llmstxt.org) and `/BingSiteAuth.xml` (`bing_site_auth`, Bing
  Webmaster Tools' ownership code) are served only when set; otherwise they are 404s.
- `update_website_context` hook: appends `<link rel="canonical">` to `head_html`, sets `og:url` and
  `og:site_name`, and moves absolute image URLs Frappe built on the ERP's own host (`get_url()`) onto
  the canonical host. Nothing on technical pages, 404s or hosts outside a Public Site. The page's URL comes from the
  endpoint the router resolved (`flags.public_site_endpoint`), not Frappe's path, which for `/` is the global home page.
- **Builder Pages' canonical**: Builder prints its own canonical link after the hooks run, from the page's
  `canonical_url` rendered as Jinja with the page context (else its prefixed route, a 404 on the site). So the hook puts
  the URL in the context (`public_site_canonical_url`) and adds no link of its own on a Builder Page, and every Builder
  Page under a site prefix with no `canonical_url` of its own carries `{{ public_site_canonical_url }}`: set on
  validate, and backfilled after migrate. Off a site host it renders empty and Builder prints none.
- `favicon` (Public Site, square PNG): the same hook sets `context.favicon` (base.html's tab icon) and adds
  an `apple-touch-icon` link, both on the canonical host. Empty keeps the Website Settings favicon.
- All `www/public_site_*` pages are `no_cache` (one endpoint serves every site) and 404 off a site host.
- Per-page titles, descriptions, `meta_image` (Open Graph card) and JSON-LD belong to the page content
  (Web Page fields and its HTML), not this app.

## Page chrome (`site_chrome.py`)

**Builder Pages** render on Builder's own template, which prints its `_head_html` and not Frappe's `head_html`, and
Builder fills it before the `update_website_context` hooks run. So every head addition (canonical, favicon, analytics)
goes through `chrome.add_head_html`, which appends to `head_html` and, on a Builder Page, to `_head_html` too.

Every public site brings its own header, so on a Public Site host the `update_website_context` hook
renders pages (their Not Found page included) on `templates/public_site_base.html`: Frappe's
`base.html` with the `navbar` block emptied. Frappe's standard navbar would otherwise stay in the HTML
(hidden by the site's CSS) and hand crawlers the ERP's own links (`/all-products`, `/cart`, `/login`),
which are 404s on a site host. A page that set its own `base_template_path` keeps it; hosts outside a
Public Site keep Frappe's chrome.

**Standalone Pages** (`standalone_pages`, default off): for sites whose pages bring all their own CSS and
JS. Their Web Pages (`chrome.is_standalone`, pure) render on `templates/standalone_web_page.html`
(Frappe's Web Page template without its `<main>` wrapper and breadcrumbs: the site's content brings its own
landmarks, either its own `<main>` or top-level blocks marked `data-main-content`, whose run `chrome.wrap_main`
wraps in one `<main id="main">`. Page Builder renders each block separately, so a header / sections / footer page
can't have one block wrap the others; the header and footer stay outside), and the base template leaves out Frappe's website stylesheet, `web_include_css/js/icons`
(the ERPNext, webshop and blog bundles, icon sprites), `frappe-web.bundle.js` with `frappe.boot`, and the
standard footer. The head keeps `head_html` (canonical, favicon, analytics) and `frappe.csrf_token` still
lands on the `window.frappe` object base.html creates. Login, webshop, blog and Not Found pages keep
Frappe's assets: their styling comes from those bundles.

## Analytics (`analytics.py` pure, `site_analytics.py` Frappe)

Per Public Site, any combination of providers, each added to every page of that site by the
`update_website_context` hook:
- **Frappe view tracking** (`view_tracking`, default on): a cookieless beacon (referrer, time zone, UTM
  tags; skipped under Do Not Track / Global Privacy Control) to `site_analytics.log_view`, which records a
  `Web Page View` stamped with `public_site` (a custom field created by the `after_migrate` hook). Frappe's
  own `make_view_log` cannot serve public sites: it accepts only Referers on the ERP's host and records no
  host. The global Website Settings `enable_view_tracking` is not needed.
  - **Visitor IDs** (`visitor_ids`, default off, needs `view_tracking`): the tracker keeps an anonymous
    32-hex ID per browser in `localStorage["psr_vid"]` (created after the DNT/GPC check, so those
    visitors never get one; no cookie) and sends it; `log_view` stores it in `Web Page View.visitor_id`
    only on such a site. A lead form reads the same key so a CRM app (e.g. frappe-crm-heat-tracking)
    can link the visitor's pages to the lead.
- **Google Analytics 4** (`ga4_measurement_id`, validated `G-…`): the Google tag **behind a consent
  banner**. Consent Mode v2 defaults every signal to denied, and `gtag.js` is fetched only after the
  visitor accepts, so nothing reaches Google before that. The choice is kept in
  `localStorage["psr_consent"]`; Do Not Track / Global Privacy Control count as a refusal (no banner);
  any element with `data-psr-consent-reset` (e.g. on the privacy page) clears it. The banner (bottom,
  `.psr-consent`, restylable) links the site's `privacy_route` when set. Values are embedded with
  `analytics.js_string` (JSON with `<` escaped), so no field can close the script.
- **Matomo** (`matomo_url` https + `matomo_site_id` numeric): the standard tracker.

Values are validated on save and re-validated before they reach a snippet; strings are embedded with
`json.dumps`. Saving a Public Site clears the website page cache so a change shows at once.

## App Hosts (`app_routing.py` pure, `app_hosts.py` Frappe)

The site's apps on their own host names with one sign-in, e.g. OMG's ERP (desk and login on
`erp.obsessedmediagroup.ca`) serving `crm.` → `/crm`, `hr.` → `/hrms` (Frappe HR's own app; its desk workspace is
not an app route), `lms.`, `insights.`, `builder.`.

- **Model**: `host` (unique, a plain DNS name, normalised like Public Site domains), `app_route` (one lowercase segment,
  not one Frappe serves itself: `api`, `assets`, `files`, `desk`, `login`, … `app_routing.RESERVED_ROUTES`), `login_host`
  (the host holding the sign-in; differs from `host`, is not itself an App Host, and an App Host's host is no other's
  login host), `enabled`, `label`. One host per app route per login host. Neither host nor login host may be a Public
  Site domain (checked on both doctypes). The enabled-host map is cached (`public_site_router_app_host_map`), cleared on
  save/delete.
- **Routing** (`before_request` hook, raising a Werkzeug `HTTPException` carrying a 302, which `frappe.app.application`
  returns as the response): on an enabled App Host, `GET`/`HEAD /` → `/<app_route>` (query kept); a signed-out page
  request (`GET`/`HEAD`, `/<app_route>[/...]`, not XHR, Accept naming HTML) → the login host's `handoff`. Everything
  else (the app's API calls, `/assets`, `/files`, `socket.io`, the accept endpoint, desk links, other methods) passes.
- **Handoff**: the app host sets a host-only, HttpOnly anti-forgery state cookie (`psr_handoff_state`, reused while
  valid) and sends the visitor to `https://<login_host>/api/method/public_site_router.app_hosts.handoff?target=&next=&state=`.
  `handoff` (GET, guest-allowed) answers only on the login host of an enabled App Host named by `target` (else 403). A
  signed-out visitor goes to `/login?redirect-to=<this handoff, relative>`: Frappe keeps `redirect-to` through
  password login (login.js `sanitise_redirect`), the email link and social login (it is the OAuth `state`'s stored
  redirect). A signed-in one gets a token (`secrets.token_urlsafe(32)`, in Redis for 60 s with the sid, user, target,
  next and state) and goes to `https://<target>/api/method/public_site_router.app_hosts.accept?token=`.
- **Accept** (GET, guest-allowed, on the app host): takes the token with `GETDEL` (single use, even on failure), and
  answers 403 unless it exists, names this host, this host is an enabled App Host and the state cookie matches
  (constant-time). It then resumes the session through Frappe's own `LoginManager` with the sid in `form_dict` (as
  `frappe.www.login.login_via_token` does), so Frappe validates it (expiry, session end, IP restriction) and sets its
  own cookies on this host: `sid` (HttpOnly, `max_age` = session expiry) and `system_user`, `full_name`, `user_id`,
  `user_image`, `user_lang`, all host-only, `SameSite=Lax`, `Secure` on https. A session that is gone or another
  user's is a 403. `next` is followed only as a same-host relative path (one leading `/`, no scheme or host, no
  backslash, control character or space); otherwise `/<app_route>`.
- **Why not a parent-domain cookie**: `Domain=.obsessedmediagroup.ca` would send staff session cookies to every name in
  the zone, including the third-party `link.` CNAME (SMTP2GO click tracking) and the client WordPress dev subdomains.
  The session is server-side and valid on any host of the site, so only the cookie is copied, per host, on demand.
- **Logout** deletes the session server-side (`delete_session`), so every host's cookie for it stops working at once:
  the next request on an app host resumes as Guest (Frappe clears that host's cookies) and hands off again, to a login
  host that is signed out too. Nothing else is needed.
- **Desk links**: on a login host or an app host (never elsewhere), the `update_website_context` hook rewrites the
  boot data the desk and website pages render from (`boot.app_data[].app_route`: apps screen and app switcher;
  `boot.apps_data.apps[].route`: website pages' Apps link) to `https://<host>/<route>` for apps with an App Host of that
  login host, on copies. On an app host, every other relative route (the desk, apps without an App Host) becomes a URL
  on the login host: on the app host it would only show a second sign-in. `override_whitelisted_methods` replaces
  `frappe.apps.get_apps` (what Frappe apps' own app menus, e.g. CRM's, call) and `builder.api.get_apps` (Builder's
  menu, Redis-cached across hosts, so rewritten after the cache) with the same rewrite. `extend_bootinfo` /
  `boot_session` can't do it: `apps_data` is set after `extend_bootinfo` runs, and `boot_session` output is cached per
  user, not per host. The desk's apps screen opens absolute routes in a new tab (desktop.js).
- **Deploying**: each app host must reach this Frappe site (DNS, TLS, the proxy, and Frappe's site resolution by host:
  a bench domain or `X-Frappe-Site-Name`).

## Webshop stores

Implements the frappe-webshop fork's `webshop_store_resolver` hook: the request's site's
`webshop_store`. One host list drives both page isolation and store selection.

## Caching

Frappe caches rendered pages by endpoint. Endpoints here are host-specific (`<prefix>/...`), so a
site's cached HTML is never served on another host. Shared routes whose content varies by host
(webshop product/listing pages) are made `no_cache` by the fork in multi-store mode.

## Deploying

A release that adds or changes a hook (`after_request`, `update_website_context`, …) only takes effect once
frappe's cached hook map (`app_hooks`) is rebuilt from the new code. The old workers re-cache it during build and
migrate, so clear the caches after the units restart (the tofu `frappe_app` provider does since 63f83277), then
check the hook's effect on a live response (e.g. the security headers), not just that the commit is installed.

## Testing

`bench --site <site> run-tests --app public_site_router` (real DB). The webshop test class runs
end-to-end through the fork when `webshop` is installed, and is skipped otherwise.

The pure logic (SEO, analytics, chrome, App Hosts) is unit-tested without a bench: `uv run --no-project --with pytest python -I -m pytest`
(`tests/`). Lint: `uvx ruff format --check . && uvx ruff check .`
