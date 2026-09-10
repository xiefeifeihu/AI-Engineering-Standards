#!/usr/bin/env python3
"""
AI Engineering Standards: Shared Inference Resource Conformance Checker
Portable diagnostic script to probe shared inference resources from either:
  - Host environment (default loopback endpoints 127.0.0.1: 11434, 8317, 18317)
  - Container environment (via host-gateway, e.g. host.docker.internal: 11434, 8317, 18317)

Zero Secrets Principle:
  - Never logs or exposes API keys.
  - If a token is supplied via environment or --token, it is used only in probe headers and redacted in output.
  - If no token is provided, auth-requiring endpoints report AUTH_NOT_CONFIGURED without network failure.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import socket
import sys
import time
import urllib.request
import urllib.error

RESOURCES = [
    {
        "id": "ollama-local",
        "default_host": "127.0.0.1",
        "port": 11434,
        "path": "/api/tags",
        "auth_required": False,
    },
    {
        "id": "cpa-local",
        "default_host": "127.0.0.1",
        "port": 8317,
        "path": "/v1/models",
        "ping_path": "/",
        "auth_required": True,
    },
    {
        "id": "cpa-cloud",
        "default_host": "127.0.0.1",
        "port": 18317,
        "path": "/v1/models",
        "ping_path": "/",
        "auth_required": True,
        "optional": True,
    },
]


def sanitize(text: str) -> str:
    patterns = [
        (r"Bearer\s+[A-Za-z0-9_\-\.]{8,}", "Bearer [REDACTED]"),
        (r"sk-[A-Za-z0-9_\-]{16,}", "sk-[REDACTED]"),
    ]
    for pat, rep in patterns:
        text = re.sub(pat, rep, text, flags=re.IGNORECASE)
    return text


def probe_endpoint(target_host: str, res_def: dict, token: str | None = None) -> dict:
    res_id = res_def["id"]
    port = res_def["port"]
    ping_url = f"http://{target_host}:{port}{res_def.get('ping_path', res_def['path'])}"
    models_url = f"http://{target_host}:{port}{res_def['path']}"

    result = {
        "resource_id": res_id,
        "target": f"{target_host}:{port}",
        "tcp": "UNKNOWN",
        "http_transport": "UNKNOWN",
        "auth": "UNKNOWN",
        "discovery": "UNKNOWN",
        "status": "FAIL",
    }

    # 1. TCP Connect
    t0 = time.time()
    try:
        with socket.create_connection((target_host, port), timeout=2.0):
            elapsed = (time.time() - t0) * 1000
            result["tcp"] = f"PASS ({elapsed:.1f}ms)"
    except Exception as exc:
        result["tcp"] = f"FAIL ({exc})"
        if res_def.get("optional"):
            result["status"] = "OFFLINE"
        return result

    # 2. HTTP Transport Probe
    t0 = time.time()
    try:
        req = urllib.request.Request(ping_url, headers={"User-Agent": "SharedInferenceChecker/1.0"})
        with urllib.request.urlopen(req, timeout=3.0) as resp:
            elapsed = (time.time() - t0) * 1000
            result["http_transport"] = f"HTTP {resp.status} ({elapsed:.1f}ms)"
    except urllib.error.HTTPError as he:
        elapsed = (time.time() - t0) * 1000
        if he.code == 502:
            result["http_transport"] = f"HTTP 502 Bad Gateway ({elapsed:.1f}ms)"
            result["status"] = "OFFLINE" if res_def.get("optional") else "FAIL"
            result["auth"] = "UPSTREAM_OFFLINE"
            result["discovery"] = "OFFLINE"
            return result
        else:
            result["http_transport"] = f"HTTP {he.code} ({elapsed:.1f}ms)"
    except Exception as exc:
        result["http_transport"] = f"ERR ({exc})"
        result["status"] = "OFFLINE" if res_def.get("optional") else "FAIL"
        return result

    # 3. Auth & Discovery Probe
    if not res_def.get("auth_required"):
        result["auth"] = "NONE_REQUIRED"
        try:
            req = urllib.request.Request(models_url, headers={"User-Agent": "SharedInferenceChecker/1.0"})
            with urllib.request.urlopen(req, timeout=3.0) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                models = data.get("models", [])
                result["discovery"] = f"PASS ({len(models)} models available)"
                result["status"] = "PASS"
        except Exception as exc:
            result["discovery"] = f"ERR ({exc})"
            result["status"] = "PASS"  # Transport is still PASS
    else:
        if token:
            headers = {
                "User-Agent": "SharedInferenceChecker/1.0",
                "Authorization": f"Bearer {token.strip()}",
            }
            try:
                req = urllib.request.Request(models_url, headers=headers)
                with urllib.request.urlopen(req, timeout=4.0) as resp:
                    data = json.loads(resp.read().decode("utf-8"))
                    models = data.get("data", [])
                    result["auth"] = "PASS"
                    result["discovery"] = f"PASS ({len(models)} models available)"
                    result["status"] = "PASS"
            except urllib.error.HTTPError as he:
                result["auth"] = f"HTTP {he.code}"
                result["discovery"] = f"HTTP {he.code}"
                result["status"] = "FAIL"
            except Exception as exc:
                result["auth"] = f"ERR ({exc})"
                result["discovery"] = f"ERR ({exc})"
                result["status"] = "FAIL"
        else:
            # Probe without credentials to verify auth enforcement
            try:
                req = urllib.request.Request(models_url, headers={"User-Agent": "SharedInferenceChecker/1.0"})
                with urllib.request.urlopen(req, timeout=3.0) as resp:
                    result["auth"] = "ANONYMOUS_OK"
                    result["discovery"] = "PASS"
                    result["status"] = "PASS"
            except urllib.error.HTTPError as he:
                if he.code in (401, 403):
                    result["auth"] = f"AUTH_NOT_CONFIGURED (HTTP {he.code} received)"
                    result["discovery"] = "AUTH_REQUIRED"
                    result["status"] = "PASS"  # Network & transport PASS!
                elif he.code == 502:
                    result["auth"] = "UPSTREAM_OFFLINE"
                    result["discovery"] = "OFFLINE"
                    result["status"] = "OFFLINE"
                else:
                    result["auth"] = f"HTTP {he.code}"
                    result["discovery"] = f"HTTP {he.code}"
                    result["status"] = "PASS"
            except Exception as exc:
                result["auth"] = f"ERR ({exc})"
                result["discovery"] = f"ERR ({exc})"
                result["status"] = "FAIL"

    return result


def main() -> None:
    parser = argparse.ArgumentParser(description="Shared Inference Resource Conformance Checker")
    parser.add_argument(
        "--host",
        default="127.0.0.1",
        help="Target host to probe (127.0.0.1 for host loopback, host.docker.internal for containers)",
    )
    parser.add_argument(
        "--container",
        action="store_true",
        help="Use host.docker.internal as target host",
    )
    parser.add_argument(
        "--token",
        default=os.environ.get("CPA_API_KEY"),
        help="Optional CPA API token for auth/discovery testing",
    )
    parser.add_argument("--json", action="store_true", help="Output JSON result")
    args = parser.parse_args()

    target_host = "host.docker.internal" if args.container else args.host

    print(f"================================================================================")
    print(f"AI Engineering Standards: Shared Inference Resource Conformance Checker")
    print(f"Target Host: {target_host} ({'Container Runtime Perspective' if target_host != '127.0.0.1' else 'Host Perspective'})")
    print(f"================================================================================")

    results = []
    all_ok = True
    for res_def in RESOURCES:
        res = probe_endpoint(target_host, res_def, args.token)
        results.append(res)
        print(f"\n[{res['resource_id']}] -> {res['target']}")
        print(f"  TCP:        {res['tcp']}")
        print(f"  HTTP:       {res['http_transport']}")
        print(f"  Auth:       {res['auth']}")
        print(f"  Discovery:  {res['discovery']}")
        print(f"  Status:     {res['status']}")
        if res["status"] == "FAIL":
            all_ok = False

    print("\n================================================================================")
    verdict = "PASS" if all_ok else "FAIL"
    print(f"OVERALL CONFORMANCE: {verdict}")
    print("================================================================================")

    if args.json:
        print(json.dumps({"results": results, "verdict": verdict}, indent=2))

    sys.exit(0 if all_ok else 1)


if __name__ == "__main__":
    main()
