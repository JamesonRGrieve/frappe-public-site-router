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
posts and store items, a `/robots.txt` that names it, and a canonical link and `og:url` on every page,
all on the site's canonical host (its first non-`www` domain).

## Install

```sh
bench get-app https://github.com/JamesonRGrieve/frappe-public-site-router
bench --site <site> install-app public_site_router
```

Install it after any other app that registers `website_path_resolver` (e.g. Frappe Builder).

## License

AGPL-3.0-or-later
