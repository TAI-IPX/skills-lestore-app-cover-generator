"""
通用AI生图客户端 — 零外部依赖。
通过环境变量配置后端，兼容 OpenAI 及 OpenAI 兼容 API。

配置方式 (.env):
  IMAGE_API=openai
  IMAGE_BASE_URL=https://api.openai.com
  IMAGE_API_KEY=sk-xxx
  IMAGE_MODEL=gpt-image-2
"""

import json
import os
import ssl
import urllib.request
import urllib.error


def _env(key, default=""):
    return os.environ.get(key, default)


def _download(url, path):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    ctx = ssl.create_default_context()
    with urllib.request.urlopen(req, timeout=300, context=ctx) as resp:
        with open(path, "wb") as f:
            f.write(resp.read())


# ═══════════════════════════════════════════════════
# OpenAI DALL-E
# ═══════════════════════════════════════════════════

def _openai_generate(prompt, output_path, api_key, model, base_url, size, quality, fmt="jpeg"):
    body = {"model": model, "prompt": prompt, "n": 1, "size": size, "output_format": fmt}
    if quality:
        body["quality"] = quality

    endpoint = f"{base_url.rstrip('/')}/v1/images/generations"
    req = urllib.request.Request(
        endpoint,
        data=json.dumps(body).encode(),
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        },
    )
    ctx = ssl.create_default_context()
    with urllib.request.urlopen(req, timeout=300, context=ctx) as resp:
        result = json.loads(resp.read().decode())

    url = result["data"][0]["url"]
    _download(url, output_path)
    return url


# ═══════════════════════════════════════════════════
# Replicate
# ═══════════════════════════════════════════════════

def _replicate_generate(prompt, output_path, api_key, model):
    # model: "black-forest-labs/flux-1.1-pro" 或 "black-forest-labs/flux-dev"
    body = {
        "version": model,
        "input": {"prompt": prompt, "aspect_ratio": "16:9"},
    }

    # Create prediction
    req = urllib.request.Request(
        "https://api.replicate.com/v1/predictions",
        data=json.dumps(body).encode(),
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        },
    )
    ctx = ssl.create_default_context()
    with urllib.request.urlopen(req, timeout=30, context=ctx) as resp:
        prediction = json.loads(resp.read().decode())

    # Poll until done
    import time
    poll_url = prediction["urls"]["get"]
    for _ in range(60):
        req = urllib.request.Request(
            poll_url,
            headers={"Authorization": f"Bearer {api_key}"},
        )
        with urllib.request.urlopen(req, timeout=10, context=ctx) as resp:
            status = json.loads(resp.read().decode())

        if status["status"] == "succeeded":
            url = status["output"][0] if isinstance(status["output"], list) else status["output"]
            _download(url, output_path)
            return url
        elif status["status"] == "failed":
            raise RuntimeError(f"Replicate failed: {status.get('error', 'unknown')}")
        time.sleep(2)

    raise TimeoutError("Replicate timed out")


# ═══════════════════════════════════════════════════
# Fal.ai
# ═══════════════════════════════════════════════════

def _fal_generate(prompt, output_path, api_key, model):
    body = {"prompt": prompt, "image_size": "landscape_16_9"}

    req = urllib.request.Request(
        f"https://fal.run/{model}",
        data=json.dumps(body).encode(),
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Key {api_key}",
        },
    )
    ctx = ssl.create_default_context()
    with urllib.request.urlopen(req, timeout=300, context=ctx) as resp:
        result = json.loads(resp.read().decode())

    url = result["images"][0]["url"]
    _download(url, output_path)
    return url


# ═══════════════════════════════════════════════════
# CLI
# ═══════════════════════════════════════════════════

BACKENDS = {
    "openai": _openai_generate,
    "replicate": _replicate_generate,
    "fal": _fal_generate,
}


def main():
    import argparse

    parser = argparse.ArgumentParser(description="通用AI生图工具")
    parser.add_argument("--prompt", required=True, help="中文prompt")
    parser.add_argument("--output", required=True, help="输出图片路径")
    parser.add_argument("--api", default=None, help="覆盖 IMAGE_API 环境变量")
    parser.add_argument("--key", default=None, help="覆盖 IMAGE_API_KEY")
    parser.add_argument("--model", default=None, help="覆盖 IMAGE_MODEL")
    parser.add_argument("--size", default="1792x1024", help="图片尺寸")
    parser.add_argument("--quality", default="low", help="质量: low/medium/high/auto")
    parser.add_argument("--format", default="jpeg", help="输出格式: png/jpeg")

    args = parser.parse_args()

    api = args.api or _env("IMAGE_API") or _env("IMAGE_PROVIDER")
    key = args.key or _env("IMAGE_API_KEY")
    model = args.model or _env("IMAGE_MODEL", "dall-e-3")
    base_url = _env("IMAGE_BASE_URL", "https://api.openai.com")

    if not api:
        print("❌ 未配置生图后端。请在 .env 中设置 IMAGE_API。")
        print("   支持: openai / replicate / fal")
        print("   IMAGE_API=openai")
        print("   IMAGE_API_KEY=sk-xxx")
        exit(1)

    if not key:
        print("❌ 未配置 API Key。请在 .env 中设置 IMAGE_API_KEY。")
        exit(1)

    fn = BACKENDS.get(api.lower())
    if not fn:
        print(f"❌ 不支持的后端: {api}，支持: {', '.join(BACKENDS.keys())}")
        exit(1)

    os.makedirs(os.path.dirname(args.output) or ".", exist_ok=True)

    print(f"🎨 生成中... (后端={api}, 模型={model})")

    try:
        kwargs = {"prompt": args.prompt, "output_path": args.output, "api_key": key, "model": model}
        if api == "openai":
            kwargs["base_url"] = base_url
            kwargs["size"] = args.size
            kwargs["quality"] = args.quality
            kwargs["fmt"] = args.format
        url = fn(**kwargs)
        print(f"✅ 已保存: {args.output}")
        print(json.dumps({"url": url, "local_path": args.output}))
    except Exception as e:
        print(f"❌ 生图失败: {e}")
        exit(1)


if __name__ == "__main__":
    main()
