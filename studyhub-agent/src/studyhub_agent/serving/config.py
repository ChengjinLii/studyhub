from __future__ import annotations

import hashlib
import json
import os
import re
import tomllib
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from studyhub_agent.contracts.render import TEMPLATE_SHA256

VLLM_VERSION = "0.32.0"


class ServingConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)
    model_dir: Path
    runtime_python: Path
    state_dir: Path
    served_model_name: str = "Qwen/Qwen3.5-9B"
    host: Literal["127.0.0.1", "::1"] = "127.0.0.1"
    port: int = Field(default=30411, ge=1024, le=65535)
    gpus: list[str] = Field(default_factory=lambda: ["0"], min_length=1, max_length=8)
    tensor_parallel_size: int = Field(default=1, ge=1, le=8)
    max_model_len: int = Field(default=16384, ge=16384, le=262144)
    max_num_seqs: int = Field(default=4, ge=1, le=64)
    max_num_batched_tokens: int = Field(default=2048, ge=256, le=32768)
    gpu_memory_utilization: float = Field(default=0.5, ge=0.1, le=0.9)
    reserve_memory_mib: int = Field(default=4096, ge=1024)
    allow_shared_gpu: bool = False
    prefix_caching: bool = False
    enforce_eager: bool = False
    startup_timeout_s: int = Field(default=600, ge=1, le=3600)
    shutdown_timeout_s: int = Field(default=30, ge=1, le=120)
    poll_interval_s: float = Field(default=2.0, ge=0.1, le=30)
    api_key_env: str = "STUDYHUB_KNOWLEDGE_MODEL_API_KEY"

    @model_validator(mode="after")
    def coherent(self):
        if len(self.gpus) != self.tensor_parallel_size or len(set(self.gpus)) != len(self.gpus):
            raise ValueError("GPU 列表必须唯一且数量与 tensor_parallel_size 相同")
        if any(not re.fullmatch(r"(?:\d+|GPU-[a-fA-F0-9-]+)", value) for value in self.gpus):
            raise ValueError("GPU 使用物理编号或完整 UUID，不接受 MIG／环境内相对编号")
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", self.api_key_env):
            raise ValueError("api_key_env 必须是环境变量名，不能填写密钥")
        if not re.fullmatch(r"[A-Za-z0-9_./-]{1,120}", self.served_model_name):
            raise ValueError("模型服务标识无效")
        return self

    @property
    def base_url(self):
        return f"http://{'[' + self.host + ']' if ':' in self.host else self.host}:{self.port}"


def load_config(path: Path) -> ServingConfig:
    path = path.resolve()
    with path.open("rb") as stream:
        values = tomllib.load(stream)
    for key in ("model_dir", "runtime_python", "state_dir"):
        value = Path(values[key]).expanduser()
        values[key] = Path(os.path.abspath(path.parent / value)) if not value.is_absolute() else value
    # Do not resolve the interpreter symlink: a venv python must retain its own environment.
    values["model_dir"] = values["model_dir"].resolve()
    values["state_dir"] = values["state_dir"].resolve()
    return ServingConfig.model_validate(values)


def model_identity(config: ServingConfig) -> dict:
    path = config.model_dir
    metadata = json.loads((path / "config.json").read_text())
    if not isinstance(metadata, dict):
        raise ValueError("模型配置必须为 JSON 对象")
    if metadata.get("model_type") != "qwen3_5" or metadata.get("architectures") != ["Qwen3_5ForConditionalGeneration"]:
        raise ValueError("要求 Qwen3.5 dense 本地权重，不自动下载或修改模型配置")
    text_config = metadata.get("text_config")
    if not isinstance(text_config, dict) or type(text_config.get("max_position_embeddings")) is not int:
        raise ValueError("模型上下文配置无效")
    if config.max_model_len > text_config["max_position_embeddings"]:
        raise ValueError("服务窗口不能超过模型原始上下文，不自动启用 YaRN")
    files = (
        "config.json",
        "tokenizer.json",
        "tokenizer_config.json",
        "chat_template.jinja",
        "model.safetensors.index.json",
    )
    hashes = {name: hashlib.sha256((path / name).read_bytes()).hexdigest() for name in files}
    if hashes["chat_template.jinja"] != TEMPLATE_SHA256:
        raise ValueError("模型模板与 Agent 的固定模板不一致，请先执行模板验收")
    index = json.loads((path / "model.safetensors.index.json").read_text())
    weight_map = index.get("weight_map") if isinstance(index, dict) else None
    if not isinstance(weight_map, dict) or not weight_map or any(not isinstance(v, str) for v in weight_map.values()):
        raise ValueError("权重分片清单无效")
    shards = sorted(set(weight_map.values()))
    if any(Path(name).name != name or not name.endswith(".safetensors") for name in shards):
        raise ValueError("权重分片清单无效")
    if any(not (path / name).is_file() or (path / name).stat().st_size == 0 for name in shards):
        raise ValueError("本地权重分片缺失或为空")
    return {
        "sha256": hashes,
        "shards": {name: (path / name).stat().st_size for name in shards},
        "weight_hash_verified": False,
    }


def command(config: ServingConfig) -> list[str]:
    args = [
        str(config.runtime_python),
        "-m",
        "vllm.entrypoints.cli.main",
        "serve",
        str(config.model_dir),
        "--host",
        config.host,
        "--port",
        str(config.port),
        "--served-model-name",
        config.served_model_name,
        "--tokenizer",
        str(config.model_dir),
        "--chat-template",
        str(config.model_dir / "chat_template.jinja"),
        "--dtype",
        "bfloat16",
        "--tensor-parallel-size",
        str(config.tensor_parallel_size),
        "--max-model-len",
        str(config.max_model_len),
        "--max-num-seqs",
        str(config.max_num_seqs),
        "--max-num-batched-tokens",
        str(config.max_num_batched_tokens),
        "--gpu-memory-utilization",
        str(config.gpu_memory_utilization),
        "--language-model-only",
        "--enable-auto-tool-choice",
        "--tool-call-parser",
        "qwen3_coder",
        "--reasoning-parser",
        "qwen3",
        "--default-chat-template-kwargs",
        '{"enable_thinking":false}',
        "--generation-config",
        "vllm",
        "--enable-chunked-prefill",
        "--enable-prefix-caching" if config.prefix_caching else "--no-enable-prefix-caching",
        "--mamba-cache-mode",
        "align" if config.prefix_caching else "none",
        "--no-enable-log-requests",
        "--no-enable-log-outputs",
        "--no-trust-request-chat-template",
        "--shutdown-timeout",
        str(config.shutdown_timeout_s),
        "--seed",
        "20261022",
    ]
    if config.enforce_eager:
        args.append("--enforce-eager")
    else:
        args.extend(("--max-cudagraph-capture-size", str(config.max_num_seqs)))
    return args


def environment(config: ServingConfig, *, gpu_uuids=None) -> dict[str, str]:
    result = dict(os.environ)
    result.update(
        CUDA_VISIBLE_DEVICES=",".join(gpu_uuids or config.gpus),
        CUDA_DEVICE_ORDER="PCI_BUS_ID",
        HF_HUB_OFFLINE="1",
        TRANSFORMERS_OFFLINE="1",
        VLLM_NO_USAGE_STATS="1",
        DO_NOT_TRACK="1",
        VLLM_USE_RUST_FRONTEND="0",
        OMP_NUM_THREADS="4",
        TOKENIZERS_PARALLELISM="false",
        VLLM_CACHE_ROOT=str(config.state_dir / "cache"),
        XDG_CACHE_HOME=str(config.state_dir / "cache"),
        HF_HOME=str(config.state_dir / "cache" / "huggingface"),
        TRITON_CACHE_DIR=str(config.state_dir / "cache" / "triton"),
        TORCHINDUCTOR_CACHE_DIR=str(config.state_dir / "cache" / "inductor"),
        CUDA_CACHE_PATH=str(config.state_dir / "cache" / "cuda"),
        VLLM_LOGGING_LEVEL="INFO",
        NO_PROXY="127.0.0.1,localhost,::1",
        no_proxy="127.0.0.1,localhost,::1",
    )
    # The key never appears in argv, printed plans or the launch manifest.
    for name in (
        "PYTHONPATH",
        "PYTHONHOME",
        "STUDYHUB_DISABLE_DEEP_GEMM_WITHOUT_NVCC",
        "STUDYHUB_SGLANG_TORCH_FALLBACKS_WITHOUT_NVCC",
    ):
        result.pop(name, None)
    result["PYTHONNOUSERSITE"] = "1"
    result.pop("VLLM_API_KEY", None)
    if key := os.environ.get(config.api_key_env):
        result["VLLM_API_KEY"] = key
    return result
