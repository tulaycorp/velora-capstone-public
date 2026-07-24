from __future__ import annotations

import argparse
import json
import os
import sys
import uuid
from urllib.parse import urlparse

import httpx


REQUIRED_OUTPUT_FIELDS = {
    "title",
    "description",
    "tags",
    "seo_title",
    "seo_description",
    "seo_keywords",
    "attributes",
    "warnings",
}


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Run one non-applying OpenRouter staging canary against a saved "
            "non-sensitive fixture product."
        )
    )
    parser.add_argument("--api-base-url", required=True)
    parser.add_argument("--product-id", required=True)
    parser.add_argument("--expected-model")
    parser.add_argument(
        "--bearer-token-env",
        default="VELORA_STAGING_BEARER_TOKEN",
    )
    parser.add_argument("--timeout-seconds", type=float, default=120.0)
    parser.add_argument(
        "--execute",
        action="store_true",
        help="Required because this command performs a paid provider request.",
    )
    return parser


def _validated_base_url(value: str) -> str:
    normalized = value.strip().rstrip("/")
    parsed = urlparse(normalized)
    if parsed.scheme != "https" and parsed.hostname not in {
        "127.0.0.1",
        "localhost",
    }:
        raise ValueError("The staging API URL must use HTTPS.")
    return normalized


def main() -> int:
    args = _parser().parse_args()
    api_base_url = _validated_base_url(args.api_base_url)
    if not args.execute:
        print(
            "Dry run only: add --execute to perform one paid, non-applying "
            "generation request."
        )
        return 0

    bearer_token = os.environ.get(args.bearer_token_env, "").strip()
    if not bearer_token:
        raise RuntimeError(
            f"Missing bearer token in environment variable {args.bearer_token_env}."
        )

    headers = {"Authorization": f"Bearer {bearer_token}"}
    with httpx.Client(
        base_url=api_base_url,
        headers=headers,
        timeout=args.timeout_seconds,
    ) as client:
        capabilities = client.get("/ai/capabilities")
        capabilities.raise_for_status()
        capability_payload = capabilities.json()
        if capability_payload.get("enabled") is not True:
            raise RuntimeError("AI generation is not enabled in staging.")
        if (
            args.expected_model
            and capability_payload.get("model") != args.expected_model
        ):
            raise RuntimeError("Staging AI model does not match --expected-model.")

        product_response = client.get(f"/products/{args.product_id}")
        product_response.raise_for_status()
        product = product_response.json()

        generation_response = client.post(
            f"/products/{args.product_id}/ai-generations",
            json={
                "client_request_id": f"staging-canary-{uuid.uuid4()}",
                "expected_product_revision": product["revision"],
                "regenerate_fields": [],
            },
        )
        generation_response.raise_for_status()
        generation = generation_response.json()

    if generation.get("status") != "completed":
        raise RuntimeError(
            "Staging AI canary did not complete successfully: "
            f"{generation.get('error_code') or generation.get('status')}"
        )
    output = generation.get("output")
    if not isinstance(output, dict) or not REQUIRED_OUTPUT_FIELDS.issubset(output):
        raise RuntimeError("Staging AI canary returned an incomplete output contract.")

    print(
        json.dumps(
            {
                "generation_id": generation["id"],
                "model": capability_payload.get("model"),
                "source_product_revision": generation[
                    "source_product_revision"
                ],
                "status": generation["status"],
                "warning_count": len(generation.get("warnings") or []),
                "applied": False,
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (RuntimeError, ValueError, httpx.HTTPError) as exc:
        print(f"AI staging canary failed: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
