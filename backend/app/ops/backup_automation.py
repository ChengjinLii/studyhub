from __future__ import annotations

import argparse
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
import gzip
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile

import oss2
from sqlalchemy.engine import URL, make_url

from app.core.config import Settings, get_settings
from app.ops.db_admin import command_backup


BACKUP_PATTERN = re.compile(r"^studyhub-production-(\d{8}T\d{6}Z)\.sql\.gz\.age$")


@dataclass(frozen=True)
class BackupArtifact:
    name: str
    created_at: datetime


def _parse_artifact(name: str) -> BackupArtifact | None:
    match = BACKUP_PATTERN.fullmatch(Path(name).name)
    if not match:
        return None
    created_at = datetime.strptime(match.group(1), "%Y%m%dT%H%M%SZ").replace(tzinfo=UTC)
    return BackupArtifact(name=name, created_at=created_at)


def _retained_names(
    artifacts: Iterable[BackupArtifact],
    *,
    daily: int,
    weekly: int,
    monthly: int,
) -> set[str]:
    ordered = sorted(artifacts, key=lambda item: item.created_at, reverse=True)
    retained: set[str] = set()

    def retain_latest(bucket: Callable[[datetime], object], count: int) -> None:
        seen: set[object] = set()
        for artifact in ordered:
            key = bucket(artifact.created_at)
            if key in seen:
                continue
            seen.add(key)
            retained.add(artifact.name)
            if len(seen) >= count:
                break

    retain_latest(lambda value: value.date(), max(0, daily))
    retain_latest(lambda value: value.isocalendar()[:2], max(0, weekly))
    retain_latest(lambda value: (value.year, value.month), max(0, monthly))
    return retained


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _require_program(name: str) -> str:
    executable = shutil.which(name)
    if not executable:
        raise RuntimeError(f"缺少必要程序：{name}")
    return executable


def _run(command: list[str], *, stdin=None, stdout=None, env: dict[str, str] | None = None) -> None:
    result = subprocess.run(command, stdin=stdin, stdout=stdout, stderr=subprocess.PIPE, env=env, check=False)
    if result.returncode != 0:
        message = result.stderr.decode("utf-8", errors="replace").strip()
        raise RuntimeError(f"命令执行失败（{command[0]}）：{message or result.returncode}")


def _encrypt(source: Path, target: Path, recipient_file: Path) -> None:
    recipient = recipient_file.read_text(encoding="utf-8").strip()
    if not recipient.startswith("age1"):
        raise RuntimeError("age recipient 文件无效。")
    _run([_require_program("age"), "--recipient", recipient, "--output", str(target), str(source)])
    os.chmod(target, 0o600)


def _verify_encrypted_backup(path: Path, identity_file: Path) -> None:
    age = _require_program("age")
    with subprocess.Popen(
        [age, "--decrypt", "--identity", str(identity_file), str(path)],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    ) as decrypt:
        assert decrypt.stdout is not None
        assert decrypt.stderr is not None
        try:
            with gzip.GzipFile(fileobj=decrypt.stdout, mode="rb") as source:
                prefix = source.read(256)
                while source.read(1024 * 1024):
                    pass
        except (OSError, EOFError) as exc:
            decrypt.kill()
            raise RuntimeError(f"加密备份解密或 gzip 校验失败：{exc}") from exc
        stderr = decrypt.stderr.read().decode("utf-8", errors="replace")
        if decrypt.wait() != 0:
            raise RuntimeError(f"加密备份解密校验失败：{stderr.strip()}")
    if b"MySQL dump" not in prefix and b"MariaDB dump" not in prefix:
        raise RuntimeError("解密后的文件不是可识别的 MySQL dump。")


def _oss_bucket(settings: Settings):
    required = {
        "STUDYHUB_OSS_ENDPOINT": settings.oss_endpoint,
        "STUDYHUB_OSS_BUCKET": settings.oss_bucket,
        "STUDYHUB_OSS_ACCESS_KEY_ID": settings.oss_access_key_id,
        "STUDYHUB_OSS_ACCESS_KEY_SECRET": settings.oss_access_key_secret,
    }
    missing = [name for name, value in required.items() if not value]
    if missing:
        raise RuntimeError(f"OSS 备份缺少配置：{', '.join(missing)}")
    auth = oss2.Auth(settings.oss_access_key_id, settings.oss_access_key_secret)
    return oss2.Bucket(auth, settings.oss_endpoint, settings.oss_bucket)


def _prune_local(root: Path, *, daily: int, weekly: int, monthly: int) -> list[str]:
    artifacts = [artifact for path in root.iterdir() if (artifact := _parse_artifact(path.name))]
    retained = _retained_names(artifacts, daily=daily, weekly=weekly, monthly=monthly)
    removed: list[str] = []
    for artifact in artifacts:
        if artifact.name not in retained:
            (root / artifact.name).unlink()
            removed.append(artifact.name)
    return removed


def _prune_oss(bucket, *, prefix: str, daily: int, monthly: int) -> list[str]:
    keys = [item.key for item in oss2.ObjectIterator(bucket, prefix=prefix)]
    artifacts = [artifact for key in keys if (artifact := _parse_artifact(key))]
    retained = _retained_names(artifacts, daily=daily, weekly=0, monthly=monthly)
    removed: list[str] = []
    for artifact in artifacts:
        if artifact.name not in retained:
            bucket.delete_object(artifact.name)
            removed.append(artifact.name)
    return removed


def run_backup(settings: Settings) -> dict[str, object]:
    if not settings.is_production:
        raise RuntimeError("自动异地备份只允许在 production 环境执行。")
    root = settings.private_dir / "backups" / "production-encrypted"
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(root, 0o700)
    key_root = settings.private_dir / "backups" / "keys"
    recipient_file = Path(os.getenv("STUDYHUB_BACKUP_AGE_RECIPIENT_FILE", key_root / "production.age-recipient"))
    identity_file = Path(os.getenv("STUDYHUB_BACKUP_AGE_IDENTITY_FILE", key_root / "production.agekey"))
    if not recipient_file.is_file() or not identity_file.is_file():
        raise RuntimeError("缺少 age 备份密钥。请先按 scripts/db/README.md 生成并离线保存私钥。")

    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    name = f"studyhub-production-{timestamp}.sql.gz.age"
    target = root / name
    if target.exists():
        raise RuntimeError(f"备份目标已存在：{target}")

    with tempfile.TemporaryDirectory(prefix="studyhub-db-backup-", dir=str(root)) as temp_dir:
        plaintext = Path(temp_dir) / name.removesuffix(".age")
        command_backup(settings, output=plaintext)
        _encrypt(plaintext, target, recipient_file)
        _verify_encrypted_backup(target, identity_file)

    digest = _sha256(target)
    bucket = _oss_bucket(settings)
    prefix = os.getenv("STUDYHUB_BACKUP_OSS_PREFIX", "private-backups/database/production/").strip("/") + "/"
    object_key = f"{prefix}{name}"
    headers = {"x-oss-object-acl": "private", "x-oss-meta-sha256": digest}
    bucket.put_object_from_file(object_key, str(target), headers=headers)
    remote = bucket.head_object(object_key)
    if int(remote.content_length) != target.stat().st_size:
        raise RuntimeError("OSS 备份上传后的大小校验失败。")

    local_removed = _prune_local(
        root,
        daily=int(os.getenv("STUDYHUB_BACKUP_LOCAL_DAILY", "7")),
        weekly=int(os.getenv("STUDYHUB_BACKUP_LOCAL_WEEKLY", "4")),
        monthly=int(os.getenv("STUDYHUB_BACKUP_LOCAL_MONTHLY", "6")),
    )
    remote_removed = _prune_oss(
        bucket,
        prefix=prefix,
        daily=int(os.getenv("STUDYHUB_BACKUP_OSS_DAILY", "10")),
        monthly=int(os.getenv("STUDYHUB_BACKUP_OSS_MONTHLY", "12")),
    )
    return {
        "backupFile": str(target),
        "backupSizeBytes": target.stat().st_size,
        "backupSha256": digest,
        "ossObject": object_key,
        "localRemoved": local_removed,
        "ossRemoved": remote_removed,
    }


def _database_identity(url: URL) -> tuple[str, int, str]:
    return (url.host or "127.0.0.1", url.port or 3306, url.database or "")


def require_isolated_restore_target(production_url: str, target_url: str) -> URL:
    production = make_url(production_url)
    target = make_url(target_url)
    if target.get_backend_name().lower() != "mysql" or not target.database:
        raise RuntimeError("恢复演练目标必须是独立 MySQL 数据库。")
    if _database_identity(production) == _database_identity(target):
        raise RuntimeError("恢复演练目标与生产数据库相同，已拒绝执行。")
    if "drill" not in target.database.lower():
        raise RuntimeError("恢复演练数据库名称必须包含 drill，防止误写业务库。")
    return target


def _mysql_args(url: URL) -> tuple[list[str], dict[str, str]]:
    args = ["-h", url.host or "127.0.0.1", "-P", str(url.port or 3306), "-u", url.username or "", url.database or ""]
    env = dict(os.environ)
    if url.password:
        env["MYSQL_PWD"] = url.password
    return args, env


def run_restore_drill(settings: Settings) -> dict[str, object]:
    target_raw = os.getenv("STUDYHUB_RESTORE_DRILL_DATABASE_URL", "").strip()
    if not target_raw:
        raise RuntimeError("未配置 STUDYHUB_RESTORE_DRILL_DATABASE_URL，恢复演练拒绝执行。")
    target = require_isolated_restore_target(settings.resolved_database_url, target_raw)
    root = settings.private_dir / "backups" / "production-encrypted"
    candidates = sorted(root.glob("studyhub-production-*.sql.gz.age"), key=lambda path: path.stat().st_mtime, reverse=True)
    if not candidates:
        raise RuntimeError("没有可用于恢复演练的加密生产备份。")
    backup = candidates[0]
    identity = Path(
        os.getenv(
            "STUDYHUB_BACKUP_AGE_IDENTITY_FILE",
            settings.private_dir / "backups" / "keys" / "production.agekey",
        )
    )
    _verify_encrypted_backup(backup, identity)
    mysql = _require_program("mysql")
    args, env = _mysql_args(target)
    with subprocess.Popen(
        [_require_program("age"), "--decrypt", "--identity", str(identity), str(backup)],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    ) as decrypt:
        assert decrypt.stdout is not None
        with subprocess.Popen([_require_program("gzip"), "-dc"], stdin=decrypt.stdout, stdout=subprocess.PIPE, stderr=subprocess.PIPE) as unzip:
            decrypt.stdout.close()
            assert unzip.stdout is not None
            with subprocess.Popen([mysql, *args], stdin=unzip.stdout, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env) as restore:
                unzip.stdout.close()
                _stdout, restore_stderr = restore.communicate()
                if restore.returncode != 0:
                    raise RuntimeError(f"恢复演练导入失败：{restore_stderr.decode(errors='replace').strip()}")
            unzip_stderr = unzip.stderr.read().decode(errors="replace") if unzip.stderr else ""
            if unzip.wait() != 0:
                raise RuntimeError(f"恢复演练解压失败：{unzip_stderr.strip()}")
        decrypt_stderr = decrypt.stderr.read().decode(errors="replace") if decrypt.stderr else ""
        if decrypt.wait() != 0:
            raise RuntimeError(f"恢复演练解密失败：{decrypt_stderr.strip()}")

    query = "SELECT COUNT(*) FROM information_schema.tables WHERE table_schema = DATABASE()"
    result = subprocess.run([mysql, *args, "--batch", "--skip-column-names", "-e", query], env=env, capture_output=True, text=True, check=False)
    if result.returncode != 0:
        raise RuntimeError(f"恢复演练验收查询失败：{result.stderr.strip()}")
    table_count = int(result.stdout.strip() or "0")
    if table_count < 10:
        raise RuntimeError(f"恢复演练表数量异常：{table_count}")
    return {"backupFile": str(backup), "targetDatabase": target.database, "tableCount": table_count, "verified": True}


def main() -> int:
    parser = argparse.ArgumentParser(description="StudyHub encrypted database backup automation")
    parser.add_argument("command", choices=("backup", "restore-drill"))
    args = parser.parse_args()
    settings = get_settings()
    payload = run_backup(settings) if args.command == "backup" else run_restore_drill(settings)
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
