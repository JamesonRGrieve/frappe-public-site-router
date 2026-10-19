# frappe-public-site-router

Run several businesses' public websites off one Frappe/ERPNext site, each on its own domains and
isolated from the others.

Each **Public Site** has a company, its host names, and a route prefix its pages live under. A
visitor to `zephyrex.ca/about` sees the page routed `zx/about`; on `3shub.com` that URL is a
different site's page, and `zx/...` paths are a 404 there. Shared routes (assets, API, login) work
everywhere.

It also tells the [frappe-webshop fork](https://github.com/JamesonRGrieve/frappe-webshop) which
store each request belongs to, so each business can have its own shop.

Built on Frappe v16's `website_path_resolver` hook; Frappe itself is not modified.

Each site also gets its own SEO surface on its hosts: a `/sitemap.xml` of only its published pages,
posts and store items, a `/robots.txt` that names it (with optional content signals for AI crawlers), an
optional `/llms.txt` and Bing verification file, and a canonical link and `og:url` on every page, all on
the site's canonical host (its first non-`www` domain).

Analytics are per site too: Frappe's own page-view tracking (cookieless, each view stamped with its
site), Google Analytics 4 (behind a consent banner: nothing reaches Google until the visitor accepts) and
Matomo, in any combination, configured on the Public Site. A site can also
give each browser an anonymous visitor ID (off by default; never under Do Not Track), so a lead form
can link a visitor's earlier pages to their enquiry.

Sites bring their own header, so their pages are rendered without Frappe's standard navbar (whose links
to the ERP's shop, cart and login would otherwise sit in every page's HTML). A site whose pages bring all
their own CSS and JavaScript can turn on **Standalone Pages**: its Web Pages then load none of Frappe's
render-blocking website bundles (Frappe, ERPNext, webshop, blog). A missing page on a site's host is a
real 404, shown as the site's own Not Found page (with its header and menu) when it names one.

The ERP's own apps can have host names too: an **App Host** serves one app (say `crm.example.com` for
`/crm`) with one sign-in on the ERP's login host. A signed-out visitor is sent to sign in there and comes back
with a single-use, 60-second token for that host only; the session cookie stays host-only, so it never reaches
other names in the zone. The desk's app links point at each app's host.

## Install

```sh
bench get-app https://github.com/JamesonRGrieve/frappe-public-site-router
bench --site <site> install-app public_site_router
```

Install it after any other app that registers `website_path_resolver` (e.g. Frappe Builder).

## License

AGPL-3.0-or-later
