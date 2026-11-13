#!/usr/bin/env bash
# SPDX-License-Identifier: AGPL-3.0-or-later
#
# Runs this app's Frappe-backed tests on a throwaway podman bench: MariaDB, Redis and a bench container (the
# official ERPNext v16 image + payments + Builder at the commit production runs + this app, installed last as in
# production) with one site that has them installed. Builds from a copy of the working tree taken at the start,
# removes everything it created on exit, and exits non-zero unless tests actually ran and passed.
#
# usage: tests/e2e/run.sh   (BUILDER_REF: another Builder commit; SOURCE_REF: test that commit of this app instead
#                            of the working tree, e.g. to show a failure predates a change)
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
PREFIX="${E2E_PREFIX:-psr-e2e-$$}"
NETWORK="${PREFIX}-net"
DB="${PREFIX}-db"
REDIS="${PREFIX}-redis"
BENCH="${PREFIX}-bench"
SITES="${PREFIX}-sites"
IMAGE="localhost/${PREFIX}:latest"
SITE="psr.test"
STATE="$(mktemp -d)"
# The ERPNext image production's Frappe comes from, and the Builder commit it runs (tofu-providers
# opentofu/zephyrex/svc_frappe_apps.tf).
ERPNEXT_IMAGE="docker.io/frappe/erpnext:v16.50.0"
DB_IMAGE="docker.io/library/mariadb:11.8"
REDIS_IMAGE="docker.io/library/redis:7-alpine"
BUILDER_REF="${BUILDER_REF:-37e958bc4f801d06d0438c21b97b42c45c4eaa51}"
PAYMENTS_REF="cca07d9f9392e2ea0e521c5975151db9e4b6c321"
DB_ROOT_PASSWORD="e2e-root"
ADMIN_PASSWORD="e2e-admin"
DB_READY_ATTEMPTS=120
DB_READY_INTERVAL_S=1
# Builder first: this app must be the last with a website_path_resolver hook.
APPS=(erpnext payments builder public_site_router)
TEST_APPS=(public_site_router)

# A podman store of the suite's own, with a run root keyed by its path, so concurrent environments with
# different homes never share (and corrupt) one run root's mount bookkeeping.
STORE="${E2E_STORE:-${XDG_DATA_HOME:-$HOME/.local/share}/frappe-public-site-router/e2e-podman}"
RUN_ROOT="${XDG_RUNTIME_DIR:-/tmp}/psr-$(printf '%s' "$STORE" | sha256sum | cut -c1-12)"
STORE_ARGS=(--root "$STORE/graph" --runroot "$RUN_ROOT/run" --tmpdir "$RUN_ROOT/tmp")

podman() {
	command podman "${STORE_ARGS[@]}" "$@"
}

bench() {
	podman exec -i -w /home/frappe/frappe-bench "$BENCH" bench "$@"
}

# Copies a repository's working tree (tracked and untracked files, nothing ignored) into a build context.
copy_tree() {
	local repo="$1" target="$2"
	mkdir -p "$target"
	git -C "$repo" ls-files -z --cached --others --exclude-standard \
		| (cd "$repo" && xargs -0 cp --parents --no-dereference -t "$target" 2>/dev/null || true)
}

down() {
	podman rm -f --volumes "$BENCH" "$REDIS" "$DB" >/dev/null 2>&1 || true
	podman volume rm -f "$SITES" >/dev/null 2>&1 || true
	podman network rm -f "$NETWORK" >/dev/null 2>&1 || true
	podman rmi -f "$IMAGE" >/dev/null 2>&1 || true
	rm -rf "$STATE"
}
trap down EXIT

wait_for_db() {
	for _ in $(seq "$DB_READY_ATTEMPTS"); do
		podman exec "$DB" mariadb-admin ping -h 127.0.0.1 --protocol=tcp -uroot -p"$DB_ROOT_PASSWORD" --silent >/dev/null 2>&1 && return 0
		sleep "$DB_READY_INTERVAL_S"
	done
	echo "MariaDB never became ready" >&2
	return 1
}

echo "== build $(date -u +%T)"
if [ -n "${SOURCE_REF:-}" ]; then
	mkdir -p "$STATE/context/public_site_router"
	git -C "$ROOT" archive "$SOURCE_REF" | tar -x -m -C "$STATE/context/public_site_router"
else
	copy_tree "$ROOT" "$STATE/context/public_site_router"
fi
podman build --quiet --tag "$IMAGE" --build-arg ERPNEXT_IMAGE="$ERPNEXT_IMAGE" --build-arg BUILDER_REF="$BUILDER_REF" \
	--build-arg PAYMENTS_REF="$PAYMENTS_REF" \
	--file "$ROOT/tests/e2e/Containerfile" "$STATE/context" >/dev/null

echo "== up $(date -u +%T)"
podman network create "$NETWORK" >/dev/null
podman volume create "$SITES" >/dev/null
podman run -d --name "$DB" --network "$NETWORK" --network-alias db -e MARIADB_ROOT_PASSWORD="$DB_ROOT_PASSWORD" "$DB_IMAGE" \
	--character-set-server=utf8mb4 --collation-server=utf8mb4_unicode_ci --skip-character-set-client-handshake >/dev/null
podman run -d --name "$REDIS" --network "$NETWORK" --network-alias redis "$REDIS_IMAGE" >/dev/null
podman run -d --name "$BENCH" --network "$NETWORK" -v "$SITES:/home/frappe/frappe-bench/sites" "$IMAGE" sleep infinity >/dev/null
printf '%s\n' frappe "${APPS[@]}" | podman exec -i "$BENCH" tee /home/frappe/frappe-bench/sites/apps.txt >/dev/null
bench set-config -g db_host db
bench set-config -gp db_port 3306
bench set-config -g redis_cache redis://redis:6379
bench set-config -g redis_queue redis://redis:6379
bench set-config -g redis_socketio redis://redis:6379
wait_for_db

echo "== new-site $(date -u +%T)"
install=()
for app in "${APPS[@]}"; do install+=(--install-app "$app"); done
bench new-site "$SITE" --db-root-password "$DB_ROOT_PASSWORD" --admin-password "$ADMIN_PASSWORD" \
	--mariadb-user-host-login-scope=% "${install[@]}" >/dev/null
bench --site "$SITE" set-config allow_tests true

rc=0
for app in "${TEST_APPS[@]}"; do
	echo "== run-tests $app $(date -u +%T)"
	set +e
	bench --site "$SITE" run-tests --app "$app" 2>&1 | tee "$STATE/tests-$app.log"
	app_rc=${PIPESTATUS[0]}
	set -e
	# A run that discovered nothing exits 0 too: it only counts if tests actually ran.
	grep -Eq "^Ran [1-9][0-9]* " "$STATE/tests-$app.log" || { echo "NO_TESTS_RAN $app"; app_rc=3; }
	echo "== $app rc=$app_rc"
	[ "$app_rc" -eq 0 ] || rc=$app_rc
done
echo "== RESULT rc=$rc $(date -u +%T)"
exit "$rc"
