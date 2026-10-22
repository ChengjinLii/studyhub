from __future__ import annotations

import csv
import io
import json
import math
import socket
import subprocess

from studyhub_agent.serving.config import VLLM_VERSION, ServingConfig, command, environment, model_identity


def gpu_snapshot() -> list[dict]:
    result = subprocess.run(
        [
            "nvidia-smi",
            "--query-gpu=index,uuid,name,driver_version,memory.total,memory.free,utilization.gpu",
            "--format=csv,noheader,nounits",
        ],
        capture_output=True,
        text=True,
        check=True,
        timeout=10,
    )
    rows = []
    for fields in csv.reader(io.StringIO(result.stdout), skipinitialspace=True):
        index, uuid, name, driver, total, free, utilization = (value.strip() for value in fields)
        rows.append(
            {
                "index": index,
                "uuid": uuid,
                "name": name,
                "driver": driver,
                "total_mib": int(total),
                "free_mib": int(free),
                "utilization": int(utilization),
            }
        )
    result = subprocess.run(
        ["nvidia-smi", "--query-compute-apps=gpu_uuid,pid", "--format=csv,noheader,nounits"],
        capture_output=True,
        text=True,
        check=True,
        timeout=10,
    )
    apps = list(csv.reader(io.StringIO(result.stdout), skipinitialspace=True))
    for row in rows:
        row["pids"] = [int(pid) for uuid, pid in apps if uuid.strip() == row["uuid"]]
    return rows


def select_gpus(config, rows):
    selected = []
    for selector in config.gpus:
        found = next((row for row in rows if selector in {row["index"], row["uuid"]}), None)
        if found is None:
            raise ValueError(f"找不到 GPU {selector}")
        selected.append(found)
    if len({row["uuid"] for row in selected}) != len(selected):
        raise ValueError("不同 GPU 标识指向同一张物理卡")
    return selected


def port_available(config):
    family = socket.AF_INET6 if ":" in config.host else socket.AF_INET
    with socket.socket(family, socket.SOCK_STREAM) as sock:
        try:
            sock.bind((config.host, config.port))
        except OSError:
            return False
    return True


def preflight(config: ServingConfig, *, inspect_runtime=True) -> dict:
    issues, warnings, report = [], [], {"base_url": config.base_url, "required_vllm": VLLM_VERSION}
    try:
        report["model"] = model_identity(config)
    except (OSError, ValueError, KeyError) as exc:
        issues.append({"code": "model_files", "detail": str(exc)})
    try:
        selected = select_gpus(config, gpu_snapshot())
        report["gpus"] = selected
        for row in selected:
            requested = math.ceil(row["total_mib"] * config.gpu_memory_utilization)
            if report.get("model"):
                # This is only a weight-size floor, not a prediction of KV/activation/graph usage.
                weights_mib = math.ceil(
                    sum(report["model"]["shards"].values()) / (1024**2 * config.tensor_parallel_size)
                )
                if requested <= weights_mib:
                    issues.append({"code": "weight_budget", "gpu": row["index"], "weight_floor_mib": weights_mib})
            if row["free_mib"] < requested + config.reserve_memory_mib:
                issues.append(
                    {
                        "code": "gpu_memory",
                        "gpu": row["index"],
                        "required_free_mib": requested + config.reserve_memory_mib,
                    }
                )
            if not config.allow_shared_gpu and (row["pids"] or row["utilization"] > 5):
                issues.append({"code": "gpu_busy", "gpu": row["index"]})
            if int(row["driver"].split(".")[0]) < 580:
                warnings.append(
                    "旧驱动：CUDA 13 构建通常要求 R580；CUDA 12 构建或官方容器兼容模式需单独验证，不能只看显存。"
                )
        if config.allow_shared_gpu:
            warnings.append("已显式允许共享 GPU；预检不是显存隔离，其他进程增长仍可能导致 OOM。")
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        issues.append({"code": "gpu_inspection", "detail": type(exc).__name__})
    if not port_available(config):
        issues.append({"code": "port_busy"})
    if config.prefix_caching:
        warnings.append("Qwen3.5 的 Mamba align 前缀缓存按官方说明仍需专项验证，不与规则上下文压缩混为一谈。")
    if inspect_runtime:
        try:
            query = subprocess.run(
                [
                    str(config.runtime_python),
                    "-c",
                    "import json,importlib.metadata as m; "
                    "print(json.dumps({n:m.version(n) for n in ('vllm','torch','transformers')}))",
                ],
                capture_output=True,
                text=True,
                check=True,
                timeout=30,
                env=environment(config),
            )
            report["runtime"] = json.loads(query.stdout)
            if report["runtime"]["vllm"] != VLLM_VERSION:
                issues.append({"code": "runtime_version", "expected": VLLM_VERSION})
            help_result = subprocess.run(
                command(config)[:5] + ["--help=all"],
                capture_output=True,
                text=True,
                timeout=60,
                env=environment(config) | {"CUDA_VISIBLE_DEVICES": ""},
            )
            flags = {item.split("=")[0] for item in command(config)[5:] if item.startswith("--")}
            missing = sorted(flag for flag in flags if flag not in help_result.stdout)
            if help_result.returncode or missing:
                issues.append({"code": "runtime_flags", "missing": missing})
        except (OSError, ValueError, KeyError, subprocess.SubprocessError) as exc:
            issues.append({"code": "runtime_unavailable", "detail": type(exc).__name__})
    report.update(ok=not issues, issues=issues, warnings=list(dict.fromkeys(warnings)))
    return report
