#!/usr/bin/env bash
set -Eeuo pipefail

DOMAIN="${STUDYHUB_TLS_DOMAIN:-study-hub.cn}"
EMAIL="${STUDYHUB_ACME_EMAIL:-}"
LEGO_PATH="${STUDYHUB_LEGO_PATH:-/var/lib/studyhub-acme}"
DEPLOY_DIR="${STUDYHUB_TLS_DEPLOY_DIR:-/etc/studyhub/tls}"
RENEW_BEFORE_DAYS="${STUDYHUB_TLS_RENEW_BEFORE_DAYS:-30}"
DEPLOY_CERT="$DEPLOY_DIR/$DOMAIN.fullchain.pem"
DEPLOY_KEY="$DEPLOY_DIR/$DOMAIN.key"
LEGO_CERT="$LEGO_PATH/certificates/$DOMAIN.crt"
LEGO_KEY="$LEGO_PATH/certificates/$DOMAIN.key"

if [[ "$EUID" -ne 0 ]]; then
  echo "run as root (or with sudo)" >&2
  exit 1
fi
if ! [[ "$RENEW_BEFORE_DAYS" =~ ^[1-9][0-9]*$ ]] || ((RENEW_BEFORE_DAYS > 89)); then
  echo "STUDYHUB_TLS_RENEW_BEFORE_DAYS must be between 1 and 89" >&2
  exit 2
fi
for command_name in lego openssl nginx systemctl install; do
  command -v "$command_name" >/dev/null 2>&1 || {
    echo "missing required command: $command_name" >&2
    exit 1
  }
done
nginx -t

renew_before_seconds=$((RENEW_BEFORE_DAYS * 86400))
if [[ -f "$DEPLOY_CERT" ]] && openssl x509 -checkend "$renew_before_seconds" -noout -in "$DEPLOY_CERT"; then
  echo "$DOMAIN certificate is valid for more than $RENEW_BEFORE_DAYS days; renewal skipped"
  exit 0
fi

if [[ -z "$EMAIL" && -d "$LEGO_PATH/accounts/acme-v02.api.letsencrypt.org" ]]; then
  account_dir="$(find "$LEGO_PATH/accounts/acme-v02.api.letsencrypt.org" -mindepth 1 -maxdepth 1 -type d -print -quit)"
  EMAIL="${account_dir##*/}"
fi
if [[ -z "$EMAIL" ]]; then
  echo "STUDYHUB_ACME_EMAIL is required for the first certificate issuance" >&2
  exit 2
fi

install -d -m 0700 "$LEGO_PATH"
install -d -m 0755 "$DEPLOY_DIR"

nginx_was_active=0
if systemctl is-active --quiet nginx.service; then
  nginx_was_active=1
  systemctl stop nginx.service
fi
restore_nginx() {
  if ((nginx_was_active)); then
    systemctl start nginx.service >/dev/null 2>&1 || true
  fi
}
trap restore_nginx EXIT

lego_args=(
  --path "$LEGO_PATH"
  --email "$EMAIL"
  --accept-tos
  --domains "$DOMAIN"
  --key-type ec256
  --tls
)
if [[ -f "$LEGO_CERT" && -f "$LEGO_KEY" ]]; then
  lego "${lego_args[@]}" renew --days "$RENEW_BEFORE_DAYS" --no-random-sleep
else
  lego "${lego_args[@]}" run
fi

openssl x509 -in "$LEGO_CERT" -noout -checkhost "$DOMAIN"
openssl x509 -in "$LEGO_CERT" -noout -checkend $((45 * 86400))
if ! cmp -s <(openssl x509 -in "$LEGO_CERT" -pubkey -noout) <(openssl pkey -in "$LEGO_KEY" -pubout); then
  echo "issued certificate does not match its private key" >&2
  exit 1
fi

temporary_cert="$DEPLOY_CERT.tmp"
temporary_key="$DEPLOY_KEY.tmp"
install -m 0644 "$LEGO_CERT" "$temporary_cert"
install -m 0600 "$LEGO_KEY" "$temporary_key"
mv -f "$temporary_cert" "$DEPLOY_CERT"
mv -f "$temporary_key" "$DEPLOY_KEY"

nginx -t
if ((nginx_was_active)); then
  systemctl start nginx.service
  nginx_was_active=0
fi
trap - EXIT

openssl x509 -in "$DEPLOY_CERT" -noout -subject -issuer -dates
echo "$DOMAIN certificate renewed and deployed"
