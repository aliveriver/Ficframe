from __future__ import annotations

import json
import socket
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, Callable

import httpx

from .comfyui import ComfyUIError, is_comfyui_install_path, normalize_comfyui_base_url
from .providers import EndpointConfig, build_url, llm_runtime_path, safe_url, vlm_runtime_path


COMFYUI_CLI_PORT = 8188
COMFYUI_DESKTOP_DEFAULT_PORT = 8000
COMFYUI_DESKTOP_PORT_SPAN = 1000


def test_provider_connection(
    source: dict[str, Any],
    *,
    logger: Any,
    comfyui_test: Callable[[str, str], dict[str, Any]],
) -> dict[str, Any]:
    """探测 provider 的模型列表及实际 LLM/VLM 端点。"""
    base_url = str(source.get("base_url") or "").strip().rstrip("/")
    api_key = str(source.get("api_key") or "").strip()
    if not base_url:
        raise ValueError("请先填写请求地址")
    provider_name = str(source.get("provider") or "openai").lower()
    if provider_name == "comfyui":
        return comfyui_test(base_url, api_key)
    if not api_key:
        raise ValueError("请先填写 API key")

    headers = {"Authorization": f"Bearer {api_key}"}
    started = time.perf_counter()
    model_url = build_url(base_url, "models")
    kind = str(source.get("kind") or "").lower()
    model_name = str(source.get("active_model") or "").strip()
    try:
        with httpx.Client(timeout=15.0, follow_redirects=True) as client:
            response = client.get(model_url, headers=headers)
            latency_ms = int((time.perf_counter() - started) * 1000)
            if response.status_code < 400:
                data = response.json() if response.headers.get("content-type", "").startswith("application/json") else {}
                count = len(data.get("data", [])) if isinstance(data, dict) and isinstance(data.get("data"), list) else None
                probe = probe_runtime_endpoint(client, base_url, api_key, kind, provider_name, model_name, logger=logger)
                runtime_ok = bool(probe.get("ok", True))
                suffix = ""
                if probe.get("tested"):
                    suffix = f"；正式端点 {probe.get('path')} {'可达' if runtime_ok else '不可达'}"
                    if not runtime_ok and probe.get("message"):
                        suffix += f"：{probe.get('message')}"
                result = {
                    "ok": runtime_ok,
                    "status_code": probe.get("status_code") if probe.get("tested") else response.status_code,
                    "latency_ms": int((time.perf_counter() - started) * 1000),
                    "message": f"/models 可达{f'，模型数 {count}' if count is not None else ''}{suffix}",
                }
                logger.info(
                    "provider test completed source_id=%s kind=%s provider=%s models_status=%s runtime_path=%s runtime_status=%s ok=%s latency_ms=%s url=%s",
                    source.get("id"), kind, provider_name, response.status_code, probe.get("path", ""),
                    probe.get("status_code", ""), runtime_ok, result["latency_ms"], safe_url(model_url),
                )
                return result
            if response.status_code not in {404, 405}:
                result = {
                    "ok": False,
                    "status_code": response.status_code,
                    "latency_ms": latency_ms,
                    "message": response.text[:500] or response.reason_phrase,
                }
                logger.warning("provider test http_error source_id=%s status=%s latency_ms=%s message=%s", source.get("id"), response.status_code, latency_ms, result["message"])
                return result

            fallback = client.get(base_url, headers=headers)
            result = {
                "ok": fallback.status_code < 500,
                "status_code": fallback.status_code,
                "latency_ms": int((time.perf_counter() - started) * 1000),
                "message": "服务可达，但该供应商可能不支持 /models" if fallback.status_code < 500 else fallback.text[:500],
            }
            logger.info("provider test fallback source_id=%s status=%s latency_ms=%s ok=%s", source.get("id"), fallback.status_code, result["latency_ms"], result["ok"])
            return result
    except (httpx.HTTPError, ValueError) as exc:
        logger.warning("provider test exception source_id=%s error=%s", source.get("id"), exc)
        return {
            "ok": False,
            "status_code": None,
            "latency_ms": int((time.perf_counter() - started) * 1000),
            "message": str(exc),
        }


def test_comfyui_connection(
    base_url: str,
    api_key: str = "",
    *,
    discover_endpoints: Callable[[str], tuple[str, ...]],
) -> dict[str, Any]:
    headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
    started = time.perf_counter()
    from_install_path = is_comfyui_install_path(base_url)
    try:
        candidates = discover_endpoints(base_url) if from_install_path else (normalize_comfyui_base_url(base_url),)
    except ComfyUIError as exc:
        return {"ok": False, "status_code": None, "latency_ms": int((time.perf_counter() - started) * 1000), "message": str(exc)}
    errors: list[str] = []
    detected: list[tuple[str, int]] = []
    last_status: int | None = None
    timeout = 2.0 if from_install_path else 15.0
    with httpx.Client(timeout=timeout, follow_redirects=True) as client:
        for candidate in candidates:
            try:
                response = client.get(build_url(candidate, "system_stats"), headers=headers)
            except httpx.HTTPError as exc:
                errors.append(f"{candidate}: {exc}")
                continue
            last_status = response.status_code
            if response.status_code >= 400:
                errors.append(f"{candidate}: HTTP {response.status_code}")
            elif from_install_path:
                detected.append((candidate, response.status_code))
            else:
                return {"ok": True, "status_code": response.status_code, "latency_ms": int((time.perf_counter() - started) * 1000), "message": "ComfyUI 服务可达", "resolved_base_url": candidate}
    latency_ms = int((time.perf_counter() - started) * 1000)
    if len(detected) == 1:
        candidate, status_code = detected[0]
        return {"ok": True, "status_code": status_code, "latency_ms": latency_ms, "message": f"安装目录不是 API 地址；已自动检测到 ComfyUI 服务 {candidate}，请保存该地址", "resolved_base_url": candidate}
    if len(detected) > 1:
        return {"ok": True, "status_code": detected[0][1], "latency_ms": latency_ms, "message": "检测到多个 ComfyUI 服务，请选择与当前 Desktop 窗口一致的地址后保存。", "detected_base_urls": [candidate for candidate, _ in detected]}
    if from_install_path:
        return {"ok": False, "status_code": None, "latency_ms": latency_ms, "message": "填写的是 ComfyUI 安装目录，不是 API 地址，且未检测到正在运行的本机 ComfyUI 服务。请先启动 ComfyUI，再填写启动日志或 Desktop 设置中显示的 http://127.0.0.1:端口。"}
    return {"ok": False, "status_code": last_status, "latency_ms": latency_ms, "message": errors[-1] if errors else "ComfyUI 服务不可达"}


def discover_local_comfyui_endpoints(base_path: str) -> tuple[str, ...]:
    host, start_port = desktop_comfyui_server_target(base_path)
    ports = set(range(start_port, min(65535, start_port + COMFYUI_DESKTOP_PORT_SPAN) + 1))
    ports.add(COMFYUI_CLI_PORT)
    with ThreadPoolExecutor(max_workers=64) as executor:
        checks = executor.map(lambda port: (port, local_tcp_port_open(host, port)), sorted(ports))
        open_ports = [port for port, is_open in checks if is_open]
    return tuple(f"http://{host}:{port}" for port in open_ports)


def desktop_comfyui_server_target(base_path: str) -> tuple[str, int]:
    host = "127.0.0.1"
    port = COMFYUI_DESKTOP_DEFAULT_PORT
    settings_path = Path(base_path) / "user" / "default" / "comfy.settings.json"
    try:
        settings = json.loads(settings_path.read_text(encoding="utf-8"))
        launch_args = settings.get("Comfy.Server.LaunchArgs") if isinstance(settings, dict) else None
        if isinstance(launch_args, dict):
            if str(launch_args.get("listen") or host).strip() in {"0.0.0.0", "::", "localhost", "127.0.0.1"}:
                host = "127.0.0.1"
            configured_port = int(launch_args.get("port") or port)
            if 1 <= configured_port <= 65535:
                port = configured_port
    except (OSError, json.JSONDecodeError, TypeError, ValueError):
        pass
    return host, port


def local_tcp_port_open(host: str, port: int) -> bool:
    try:
        with socket.create_connection((host, port), timeout=0.05):
            return True
    except OSError:
        return False


def probe_runtime_endpoint(client: httpx.Client, base_url: str, api_key: str, kind: str, provider_name: str, model_name: str, *, logger: Any) -> dict[str, Any]:
    if kind not in {"llm", "vlm"} or not model_name:
        return {"tested": False, "ok": True}
    endpoint = EndpointConfig(api_key=api_key, base_url=base_url, model=model_name, provider=provider_name)
    path = vlm_runtime_path(endpoint) if kind == "vlm" else llm_runtime_path(endpoint)
    url = build_url(base_url, path)
    started = time.perf_counter()
    try:
        response = client.post(url, headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}, json=build_runtime_probe_payload(kind, path, model_name))
    except httpx.HTTPError as exc:
        logger.warning("provider runtime probe exception kind=%s provider=%s url=%s error=%s", kind, provider_name, safe_url(url), exc)
        return {"tested": True, "ok": False, "path": path, "status_code": None, "message": str(exc)}
    latency_ms = int((time.perf_counter() - started) * 1000)
    ok = response.status_code < 400
    logger.info("provider runtime probe kind=%s provider=%s path=%s status=%s latency_ms=%s ok=%s url=%s", kind, provider_name, path, response.status_code, latency_ms, ok, safe_url(url))
    return {"tested": True, "ok": ok, "path": path, "status_code": response.status_code, "latency_ms": latency_ms, "message": response.text[:300] if not ok else ""}


def build_runtime_probe_payload(kind: str, path: str, model_name: str) -> dict[str, Any]:
    if path == "chat/completions":
        return {"model": model_name, "messages": [{"role": "system", "content": "Return one short word."}, {"role": "user", "content": "ping"}], "max_tokens": 4}
    return {"model": model_name, "input": [{"role": "system", "content": [{"type": "input_text", "text": "Return one short word."}]}, {"role": "user", "content": [{"type": "input_text", "text": "ping"}]}]}
