#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
ENV_FILE="$ROOT_DIR/private/.env.backup"
DATABASE_NAME="studyhub_restore_drill"
DATABASE_USER="studyhub_restore_drill"

if [[ "$EUID" -eq 0 ]]; then
  echo "run as the application user; this script uses sudo only for MySQL and systemd configuration"
  exit 2
fi
if ! command -v mysql >/dev/null || ! command -v openssl >/dev/null; then
  echo "mysql client and openssl are required"
  exit 1
fi

sudo -n install -m 0644 "$ROOT_DIR/deploy/mysql/studyhub-restore-drill.cnf" \
  /etc/mysql/mysql.conf.d/studyhub-restore-drill.cnf
sudo -n systemctl restart mysql.service
for _attempt in $(seq 1 30); do
  if sudo -n mysqladmin --protocol=socket ping --silent >/dev/null 2>&1 \
    && ss -lnt | grep -qE '127[.]0[.]0[.]1:3307[[:space:]]'; then
    break
  fi
  sleep 1
done
sudo -n mysqladmin --protocol=socket ping --silent >/dev/null
ss -lnt | grep -qE '127[.]0[.]0[.]1:3307[[:space:]]'

password="$(openssl rand -hex 24)"
sudo -n mysql --protocol=socket <<SQL
CREATE DATABASE IF NOT EXISTS \`$DATABASE_NAME\` CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
CREATE USER IF NOT EXISTS '$DATABASE_USER'@'127.0.0.1' IDENTIFIED BY '$password';
ALTER USER '$DATABASE_USER'@'127.0.0.1' IDENTIFIED BY '$password';
GRANT ALL PRIVILEGES ON \`$DATABASE_NAME\`.* TO '$DATABASE_USER'@'127.0.0.1';
FLUSH PRIVILEGES;
SQL

umask 0077
install -m 0600 /dev/null "$ENV_FILE"
printf 'STUDYHUB_RESTORE_DRILL_DATABASE_URL=mysql+pymysql://%s:%s@127.0.0.1:3307/%s?charset=utf8mb4\n' \
  "$DATABASE_USER" "$password" "$DATABASE_NAME" > "$ENV_FILE"

sudo -n install -m 0644 "$ROOT_DIR/deploy/systemd/studyhub-db-restore-drill.service" \
  /etc/systemd/system/studyhub-db-restore-drill.service
sudo -n install -m 0644 "$ROOT_DIR/deploy/systemd/studyhub-db-restore-drill.timer" \
  /etc/systemd/system/studyhub-db-restore-drill.timer
sudo -n systemctl daemon-reload
sudo -n systemctl start studyhub-db-restore-drill.service
sudo -n systemctl enable --now studyhub-db-restore-drill.timer
echo "isolated restore drill passed; monthly timer enabled"
