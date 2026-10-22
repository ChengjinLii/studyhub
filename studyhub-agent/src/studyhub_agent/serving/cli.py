from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import httpx

from studyhub_agent.runtime.policy import PolicyInfraError
from studyhub_agent.serving.checks import preflight
from studyhub_agent.serving.config import VLLM_VERSION, command, load_config, model_identity
from studyhub_agent.serving.probe import ProbeError, smoke
from studyhub_agent.serving.supervisor import ServingError, supervise


def main(argv=None):
    parser = argparse.ArgumentParser(description="StudyHub 独立本地 Qwen3.5 模型服务")
    parser.add_argument("action", choices=("plan", "check", "run", "probe"))
    parser.add_argument("--config", type=Path, required=True, help="TOML 配置，路径相对配置文件解析")
    args = parser.parse_args(argv)
    try:
        config = load_config(args.config)
        if args.action == "plan":
            value = {
                "command": command(config),
                "base_url": config.base_url,
                "required_vllm": VLLM_VERSION,
                "model": model_identity(config),
                "gpus": config.gpus,
                "note": "仅预览，不启动进程、不创建目录、不访问 GPU。密钥只由指定环境变量提供。",
            }
        elif args.action == "check":
            value = preflight(config)
        elif args.action == "probe":
            value = smoke(config)
        else:
            value = supervise(config)
        print(json.dumps(value, ensure_ascii=False, indent=2))
        return 0 if value.get("ok", True) else 2
    except (
        OSError,
        ValueError,
        KeyError,
        ImportError,
        ServingError,
        ProbeError,
        PolicyInfraError,
        httpx.HTTPError,
    ) as exc:
        # Never dump pydantic inputs or upstream response bodies that may contain secrets.
        code = str(exc) if isinstance(exc, (ServingError, ProbeError)) else type(exc).__name__
        print(json.dumps({"ok": False, "error": code}, ensure_ascii=False), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
