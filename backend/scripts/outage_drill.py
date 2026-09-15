#!/usr/bin/env python3
"""
Provider Outage Drill — §4-6 Testing

Simulates a DeepSeek outage by temporarily breaking the provider config,
then verifies the fallback path works (Gemini). Restores DeepSeek after test.

Usage:
    python3 scripts/outage-drill.py              # run drill against localhost:8001
    python3 scripts/outage-drill.py --url https://nexus-crm.kinet-poc.com
"""

import argparse
import json
import sys
import time
import urllib.request
import urllib.error


def http_json(method: str, url: str, data: dict | None = None,
              headers: dict | None = None) -> tuple[int, dict | str]:
    """Low-dependency HTTP helper."""
    req = urllib.request.Request(
        url,
        data=json.dumps(data).encode() if data else None,
        headers=headers or {},
        method=method,
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            body = resp.read().decode()
            try:
                return resp.status, json.loads(body)
            except json.JSONDecodeError:
                return resp.status, body
    except urllib.error.HTTPError as e:
        body = e.read().decode()
        try:
            return e.code, json.loads(body)
        except json.JSONDecodeError:
            return e.code, body


def main():
    parser = argparse.ArgumentParser(description="Provider Outage Drill")
    parser.add_argument("--url", default="http://localhost:8001",
                        help="Backend base URL")
    parser.add_argument("--cron-key", default="",
                        help="Cron-API-Key if needed")
    args = parser.parse_args()

    base = args.url.rstrip("/")
    headers = {"Content-Type": "application/json"}
    if args.cron_key:
        headers["Cron-Api-Key"] = args.cron_key

    print(f"🔧 Provider Outage Drill — target: {base}")
    print(f"{'='*60}")

    # Step 1: Get auth token
    print("\n[1/5] Getting auth token...")
    status, body = http_json("POST", f"{base}/auth/login",
                             data={"email": "terrence@kinetix.com",
                                   "password": "..."})
    if status == 404:
        # Try test-token endpoint
        status, body = http_json("POST", f"{base}/api/v1/auth/test-token",
                                 data={"tenant_id": "ae6b27c7-8a77-4167-add7-3a498d59536a"})
        if status != 200:
            print(f"  ⚠️  Cannot get auth token (HTTP {status}). Using Cron-Api-Key.")
            auth_headers = headers
        else:
            access_token = body.get("access_token", body.get("token", ""))
            auth_headers = {**headers, "Authorization": f"Bearer {access_token}"}
            print(f"  ✅ Token acquired ({len(access_token)} chars)")
    else:
        access_token = body.get("access_token", "")
        auth_headers = {**headers, "Authorization": f"Bearer {access_token}"}
        print(f"  ✅ Token acquired ({len(access_token)} chars)")

    # Step 2: Test normal chat (baseline)
    print("\n[2/5] Baseline: send chat message (DeepSeek)...")
    status, body = http_json("POST", f"{base}/api/v1/ai/chat",
                             data={"session_id": "drill-test",
                                   "message": "Say hello in one word"},
                             headers=auth_headers)
    print(f"  HTTP {status} | Response: {str(body)[:100]}...")

    # Step 3: Simulate DeepSeek outage (if there's a kill-switch or config)
    print("\n[3/5] Seeking provider toggle endpoint...")
    # Check if there's a provider health toggle
    status, body = http_json("GET", f"{base}/api/v1/ai/providers/health",
                             headers=headers)
    print(f"  Provider health: {body}")

    # Try to disable DeepSeek
    status, body = http_json("POST", f"{base}/api/v1/ai/providers/deepseek/disable",
                             data={},
                             headers=auth_headers)
    if status == 404:
        print("  ⚠️  No provider disable endpoint — checking environment instead")
        status, body = http_json("GET", f"{base}/ai/rag/health",
                                 headers=auth_headers)
        print(f"  RAG health: {body}")
        print("  ℹ️  To simulate outage manually: unset DEEPSEEK_API_KEY and restart backend")
    elif status == 200:
        print("  ✅ DeepSeek disabled. Running fallback test...")

        # Step 4: Test fallback
        print("\n[4/5] Fallback test: send message (should route to Gemini)...")
        status, body = http_json("POST", f"{base}/api/v1/ai/chat",
                                 data={"session_id": "drill-test",
                                       "message": "Say hello in one word"},
                                 headers=auth_headers)
        if status == 200:
            print(f"  ✅ Fallback working! HTTP {status}")
        else:
            print(f"  ❌ Fallback FAILED: HTTP {status} — {str(body)[:200]}")

        # Restore DeepSeek
        print("\n[5/5] Restoring DeepSeek...")
        status, body = http_json("POST", f"{base}/api/v1/ai/providers/deepseek/enable",
                                 data={}, headers=auth_headers)
        print(f"  HTTP {status}")
    else:
        print(f"  ⚠️  Provider toggle not available (HTTP {status})")
        print("  ℹ️  Run manually: change DEFAULT_PROVIDER in backend/app/routers/ai.py to test fallback")

    print(f"\n{'='*60}")
    print("Drill complete. See notes above for manual steps if needed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
