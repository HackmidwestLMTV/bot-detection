"""Run Red/Blue once or consume Person 1's lab command queue."""
import argparse
import asyncio
import json
import logging
import os
from pathlib import Path
from uuid import uuid4

from strands.types.exceptions import EventLoopException
from engine.agents.blue import run_blue
from engine.agents.common import load_settings, make_model
from engine.agents.hooks import RequestBudget
from engine.agents.lab_client import LabClient
from engine.agents.red import run_red
from engine.calibrate import ROOT, load_traces
from engine.worker_state import WorkerState


def error_data(exc):
    while isinstance(exc, EventLoopException):
        exc = exc.original_exception
    return {"error_type": type(exc).__name__}


async def execute(command, client, model_factory, budget, state, *, traces_dir, round_number=None,
                  approval_timeout=180, output=print):
    run_id, kind = command["run_id"], command["kind"]
    number = state.claim(run_id, kind, round_number=round_number)
    if number is None:
        output(json.dumps({"status": "duplicate_skipped", "run_id": run_id}))
        return True
    before = budget.calls
    try:
        if kind == "red":
            # Legacy residuals remain useful as synthetic attacks, never current human evidence.
            traces, rejected = load_traces(traces_dir, None, None) if number >= 3 else ([], [])
            if rejected:
                raise ValueError("resolve invalid team recordings before using transplantation")
            report = await run_red(model_factory(), client, run_id=run_id, round_number=number, traces=traces, budget=budget)
        else:
            report = await asyncio.wait_for(run_blue(model_factory(), client, run_id=run_id, round_number=number,
                budget=budget, approval_timeout=approval_timeout), timeout=600 + approval_timeout * 3)
        state.finish(run_id, "completed")
        output(json.dumps({"status": "completed", "run_id": run_id, "model_calls": budget.calls - before,
                           "report": report.model_dump()}))
        return True
    except asyncio.CancelledError:
        state.finish(run_id, "interrupted")
        raise
    except Exception as exc:
        state.finish(run_id, "failed")
        error = error_data(exc)
        try:
            client.event(run_id, "error", error, agent=kind)
        except Exception:
            pass
        output(json.dumps({"status": "failed", "run_id": run_id, **error}))
        return False


async def consume(client, model_factory, state, *, traces_dir, interval=1, min_interval_s=3,
                  approval_timeout=180, stop=None, output=print):
    budget = RequestBudget(max_calls=float("inf"), min_interval_s=min_interval_s)
    failures = 0
    while stop is None or not stop.is_set():
        try:
            command = client.next_command()
            failures = 0
        except Exception as exc:
            failures += 1
            output(json.dumps({"status": "poll_failed", **error_data(exc)}))
            await asyncio.sleep(min(30, interval * 2 ** min(failures, 5)))
            continue
        if command is None:
            await asyncio.sleep(interval)
            continue
        try:
            await execute(command, client, model_factory, budget, state, traces_dir=traces_dir,
                          approval_timeout=approval_timeout, output=output)
        except (KeyError, TypeError, ValueError) as exc:
            output(json.dumps({"status": "invalid_command", **error_data(exc)}))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--once", choices=["red", "blue"])
    mode.add_argument("--check-api", action="store_true", help="Read-only API check; no model calls")
    parser.add_argument("--round", type=int, help="Explicit round for --once; otherwise persisted per agent")
    parser.add_argument("--traces", type=Path)
    parser.add_argument("--state", type=Path)
    parser.add_argument("--approval-timeout", type=float, default=180)
    args = parser.parse_args(argv)
    if (args.round is not None and (not args.once or args.round < 1)) or not 1 <= args.approval_timeout <= 1800:
        parser.error("--round requires --once and a positive number; approval timeout must be 1–1800 seconds")
    logging.disable(logging.CRITICAL)
    client, state = None, None
    try:
        from dotenv import load_dotenv
        load_dotenv(ROOT / ".env", override=False)
        traces_dir = args.traces or Path(os.environ.get("HUMAN_TRACES_DIR", ROOT / "contracts/fixtures/human_traces"))
        state_path = args.state or Path(os.environ.get("WORKER_STATE_PATH", ROOT / "engine/.state/worker.sqlite3"))
        base = os.environ.get("API_BASE", "http://127.0.0.1:8001")
        key = os.environ.get("LAB_KEY", "dev" if base == "http://127.0.0.1:8001" else "")
        client = LabClient(base, key, allow_internal_http=os.environ.get("LAB_ALLOW_INTERNAL_HTTP") == "1")
        if args.check_api:
            from engine.scorer import validate_variant
            variant = client.active_variant()
            validate_variant(variant)
            print(json.dumps({"status": "ready", "variant": variant["id"], "humans": len(client.human_features()),
                              "forgeries": len(client.forgeries()), "model_calls": 0}))
            return 0
        settings = load_settings()
        state = WorkerState(state_path)
        factory = lambda: make_model(settings, request_timeout=60)
        if args.once:
            success = asyncio.run(execute({"run_id": "run_" + uuid4().hex, "kind": args.once}, client, factory,
                RequestBudget(max_calls=30, min_interval_s=settings.min_interval_s), state, traces_dir=traces_dir,
                round_number=args.round, approval_timeout=args.approval_timeout))
            return 0 if success else 1
        asyncio.run(consume(client, factory, state, traces_dir=traces_dir,
                            min_interval_s=settings.min_interval_s, approval_timeout=args.approval_timeout))
        return 0
    except KeyboardInterrupt:
        print(json.dumps({"status": "stopped"}))
        return 0
    except Exception as exc:
        print(json.dumps({"status": "failed", **error_data(exc)}))
        return 1
    finally:
        if state is not None:
            state.close()
        if client is not None:
            client.close()


if __name__ == "__main__":
    raise SystemExit(main())
