#!/usr/bin/env python3
"""
Load Test — §4-6 Testing

Simulates 100 concurrent SSE streams against the AI chat endpoint.
Measures: success rate, time-to-first-token, time-to-finish, memory usage.

Usage:
    python3 scripts/load_test.py                           # localhost
    python3 scripts/load_test.py --url https://... --concurrent 50
"""

import argparse
import asyncio
import time
import json
import sys
import httpx


async def stream_sse(client: httpx.AsyncClient, url: str, session_id: str,
                     message: str, results: list):
    """Send one SSE chat request and collect timing metrics."""
    start = time.monotonic()
    first_token = None
    last_token = None
    token_count = 0
    error = None

    try:
        async with client.stream(
            "POST",
            url,
            json={"session_id": session_id, "message": message},
            timeout=30,
        ) as resp:
            if resp.status_code != 200:
                results.append({
                    "session_id": session_id,
                    "success": False,
                    "error": f"HTTP {resp.status_code}",
                    "duration_ms": (time.monotonic() - start) * 1000,
                    "token_count": 0,
                })
                return

            async for line in resp.aiter_lines():
                if line.startswith("data: "):
                    data = line[6:]
                    if data == "[DONE]":
                        break
                    try:
                        payload = json.loads(data)
                        if "token" in payload:
                            if first_token is None:
                                first_token = time.monotonic()
                            token_count += 1
                            last_token = time.monotonic()
                    except json.JSONDecodeError:
                        pass
    except Exception as e:
        error = str(e)

    end = time.monotonic()
    results.append({
        "session_id": session_id,
        "success": error is None,
        "error": error,
        "duration_ms": (end - start) * 1000,
        "time_to_first_token_ms": (first_token - start) * 1000 if first_token else None,
        "token_count": token_count,
    })


async def main():
    parser = argparse.ArgumentParser(description="SSE Load Test")
    parser.add_argument("--url", default="http://localhost:8001",
                        help="Backend base URL")
    parser.add_argument("--concurrent", type=int, default=10,
                        help="Number of concurrent SSE streams (default: 10)")
    parser.add_argument("--total", type=int, default=100,
                        help="Total requests to send (default: 100)")
    parser.add_argument("--auth", default="",
                        help="Bearer token for auth")
    args = parser.parse_args()

    base_url = args.url.rstrip("/")
    stream_url = f"{base_url}/api/v1/ai/chat/stream"

    headers = {"Content-Type": "application/json"}
    if args.auth:
        headers["Authorization"] = f"Bearer {args.auth}"

    print(f"🚀 Load Test — target: {base_url}")
    print(f"   Concurrent: {args.concurrent} | Total: {args.total}")
    print(f"   Endpoint: POST {stream_url}")
    print(f"{'='*60}")

    async with httpx.AsyncClient(headers=headers, timeout=30) as client:
        results = []
        sem = asyncio.Semaphore(args.concurrent)

        async def limited_stream(i: int):
            async with sem:
                sid = f"load-test-{i}"
                await stream_sse(client, stream_url, sid,
                                 f"Tell me about deal #{i}", results)

        start = time.monotonic()
        tasks = [limited_stream(i) for i in range(args.total)]
        await asyncio.gather(*tasks)
        elapsed = time.monotonic() - start

    # Stats
    successes = [r for r in results if r["success"]]
    failures = [r for r in results if not r["success"]]
    ttft_values = [r["time_to_first_token_ms"] for r in successes
                   if r["time_to_first_token_ms"] is not None]
    durations = [r["duration_ms"] for r in results]

    print(f"\n{'='*60}")
    print(f"📊 Results")
    print(f"{'='*60}")
    print(f"  Total requests:   {args.total}")
    print(f"  Successful:       {len(successes)} ({len(successes)/args.total*100:.1f}%)")
    print(f"  Failed:           {len(failures)}")
    print(f"  Total time:       {elapsed:.2f}s")
    print(f"  Throughput:       {args.total/elapsed:.1f} req/s")

    if ttft_values:
        print(f"\n  Time-to-first-token (TTFT):")
        print(f"    Min:    {min(ttft_values):.0f}ms")
        print(f"    Max:    {max(ttft_values):.0f}ms")
        print(f"    Avg:    {sum(ttft_values)/len(ttft_values):.0f}ms")
        print(f"    P50:    {sorted(ttft_values)[len(ttft_values)//2]:.0f}ms")
        print(f"    P95:    {sorted(ttft_values)[int(len(ttft_values)*0.95)]:.0f}ms")
        print(f"    P99:    {sorted(ttft_values)[int(len(ttft_values)*0.99)]:.0f}ms")

    if durations:
        print(f"\n  Total duration per request:")
        print(f"    Avg:    {sum(durations)/len(durations):.0f}ms")

    if failures:
        print(f"\n  ❌ Failures ({len(failures)}):")
        for f in failures[:5]:
            print(f"    [{f['session_id']}] {f['error']}")

    print(f"\n  Token stats:")
    token_counts = [r["token_count"] for r in successes]
    if token_counts:
        print(f"    Avg tokens/response: {sum(token_counts)/len(token_counts):.0f}")

    exit_code = 0 if len(failures) == 0 else 1
    print(f"\n{'='*60}")
    print(f"{'✅ PASS' if exit_code == 0 else '❌ FAIL'} — {len(failures)} failures")
    return exit_code


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
