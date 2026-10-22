"""Small consumer example; only the installed hbcn_assistant package is needed.

Supply the site root and a reviewer JWT through environment variables.
Persist session/request/run IDs in the calling module, never model credentials.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys

import httpx
from hbcn_assistant import AssistantClient, AssistantRunError


def output(value: dict) -> None:
    print(json.dumps(value, ensure_ascii=False), flush=True)


def parser() -> argparse.ArgumentParser:
    cli = argparse.ArgumentParser(description=__doc__)
    actions = cli.add_subparsers(dest="action", required=True)
    create = actions.add_parser("create", help="Create once, then persist session_id; no automatic retry")
    create.add_argument("--task", required=True)
    create.add_argument("--title", default="工作流审核辅助")
    ask = actions.add_parser("ask", help="Submit with your persisted idempotency key, then wait")
    ask.add_argument("--session", type=int, required=True)
    ask.add_argument("--request-id", required=True)
    ask.add_argument("--content", required=True)
    ask.add_argument("--skill")
    ask.add_argument("--timeout", type=float, default=280)
    resume = actions.add_parser("resume", help="Read an existing run only; never submit a question")
    resume.add_argument("--session", type=int, required=True)
    resume.add_argument("--run", required=True)
    resume.add_argument("--after-id", type=int, default=0)
    resume.add_argument("--timeout", type=float, default=280)
    return cli


async def invoke(args: argparse.Namespace, site: str, jwt: str) -> None:
    async with AssistantClient(site, jwt) as assistant:
        await assistant.contract()
        if args.action == "create":
            room = await assistant.create_session(args.task, title=args.title)
            output({"session_id": room["id"], "task_code": room["task_code"]})
            return
        if args.action == "ask":
            run = await assistant.start_run(
                args.session, args.content,
                client_message_id=args.request_id, skill_id=args.skill,
            )
            run_id = run["id"]
            cursor = 0
        else:
            run_id, cursor = args.run, args.after_id
        # Output before waiting so a caller can persist the run for recovery.
        output({"session_id": args.session, "run_id": run_id})
        message = await assistant.wait(
            args.session, run_id, after_id=cursor, timeout=args.timeout,
        )
        output({"session_id": args.session, "run_id": run_id,
                "status": "completed", "message": message})


def main() -> int:
    args = parser().parse_args()
    site = os.environ.get("HBCN_ASSISTANT_SITE", "").strip()
    jwt = os.environ.get("HBCN_ASSISTANT_REVIEWER_JWT", "").strip()
    if not site or not jwt:
        output({"error": "configuration", "required_env": [
            "HBCN_ASSISTANT_SITE", "HBCN_ASSISTANT_REVIEWER_JWT",
        ]})
        return 1
    try:
        asyncio.run(invoke(args, site, jwt))
    except httpx.HTTPStatusError as exc:
        output({"error": "http", "status_code": exc.response.status_code})
        return 1
    except AssistantRunError as exc:
        output({"error": "run", "run_id": exc.run_id, "status": exc.status})
        return 1
    except TimeoutError:
        output({"error": "wait_timeout", "recovery": "resume the saved run; it was not cancelled"})
        return 1
    except (httpx.RequestError, RuntimeError, ValueError, KeyError):
        # Avoid leaking the URL, JWT or upstream error body into caller logs.
        output({"error": "request_or_contract", "recovery": "read the saved run or retry the same request key"})
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
