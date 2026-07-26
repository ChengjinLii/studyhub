#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
LOCK_FILE="${STUDYHUB_AGENTIC_VENDOR_LOCK:-$ROOT_DIR/reports/recagent/agentic-platform/references/vendor-lock.yaml}"
VENDOR_ROOT="${STUDYHUB_AGENTIC_VENDOR_DIR:-$ROOT_DIR/.local-research/vendor}"

fail() {
  printf 'sync-agentic-vendors: %s\n' "$*" >&2
  exit 1
}

parse_vendor_lock() {
  awk '
    function emit() {
      if (name != "") {
        if (repository == "" || commit == "" || license == "") {
          printf "invalid vendor entry: %s\n", name > "/dev/stderr"
          exit 2
        }
        printf "%s\t%s\t%s\t%s\n", name, repository, commit, license
      }
    }
    /^vendors:[[:space:]]*$/ { inside = 1; next }
    inside && /^papers:[[:space:]]*$/ { emit(); inside = 0; exit }
    !inside { next }
    /^  - name:[[:space:]]*/ {
      emit()
      name = $0
      sub(/^[[:space:]]*-[[:space:]]*name:[[:space:]]*/, "", name)
      repository = ""
      commit = ""
      license = ""
      next
    }
    /^    repository:[[:space:]]*/ {
      repository = $0
      sub(/^[^:]*:[[:space:]]*/, "", repository)
      next
    }
    /^    commit:[[:space:]]*/ {
      commit = $0
      sub(/^[^:]*:[[:space:]]*/, "", commit)
      next
    }
    /^    license:[[:space:]]*/ {
      license = $0
      sub(/^[^:]*:[[:space:]]*/, "", license)
      next
    }
    END { if (inside) emit() }
  ' "$LOCK_FILE"
}

command -v git >/dev/null 2>&1 || fail "git is required"
[[ -f "$LOCK_FILE" ]] || fail "vendor lock not found: $LOCK_FILE"
mkdir -p "$VENDOR_ROOT"

vendor_count=0
while IFS=$'\t' read -r name repository commit declared_license; do
  [[ "$name" =~ ^[a-z0-9][a-z0-9-]*$ ]] || fail "unsafe vendor name: $name"
  [[ "$commit" != "TO_BE_PINNED" ]] || fail "vendor $name still has TO_BE_PINNED commit"
  [[ "$commit" =~ ^[0-9a-f]{40}$ ]] || fail "vendor $name has invalid immutable SHA: $commit"

  target="$VENDOR_ROOT/$name"
  case "$target" in
    "$VENDOR_ROOT"/*) ;;
    *) fail "vendor target escaped root: $target" ;;
  esac

  if [[ -e "$target" && ! -d "$target/.git" ]]; then
    fail "vendor target is not a Git checkout: $target"
  fi
  if [[ ! -e "$target" ]]; then
    git clone --filter=blob:none --no-checkout "$repository" "$target"
  else
    [[ -z "$(git -C "$target" status --porcelain)" ]] || fail "vendor checkout is dirty: $target"
    origin_url="$(git -C "$target" remote get-url origin)"
    [[ "$origin_url" == "$repository" || "$origin_url" == "$repository.git" ]] || fail "vendor origin mismatch for $name"
  fi

  git -C "$target" fetch --depth=1 origin "$commit"
  git -C "$target" checkout --detach "$commit"
  actual_commit="$(git -C "$target" rev-parse HEAD)"
  [[ "$actual_commit" == "$commit" ]] || fail "vendor $name resolved to $actual_commit, expected $commit"

  license_file="$(find "$target" -maxdepth 1 -type f \( -iname 'LICENSE' -o -iname 'LICENSE.*' -o -iname 'LICENSE-*' -o -iname 'COPYING*' \) -print -quit)"
  [[ -n "$license_file" ]] || fail "vendor $name has no root License/COPYING file at $commit"

  printf '%s commit=%s license_file=%s declared_license=%s\n' \
    "$name" "$actual_commit" "${license_file#"$target"/}" "$declared_license"
  ((vendor_count += 1))
done < <(parse_vendor_lock)

((vendor_count > 0)) || fail "no vendors parsed from $LOCK_FILE"
