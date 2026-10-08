"""Live localhost playtests of the reference game's real command path.

Run with the environment containing Evennia, all contribs, psutil and Playwright.
Only the evidence/ subdirectory of a run is safe to publish as an artifact.
"""

import argparse
import json
import re
import sys
import threading
import traceback

from playtesting.client import ClientError
from playtesting.host import Host, HostError
from playtesting.session import Session


def interactive(session):
    """Persistent request/response JSONL, with sequenced unsolicited events."""
    output_lock = threading.Lock()
    finished = threading.Event()

    def emit(value):
        with output_lock:
            print(json.dumps(value, default=str), flush=True)

    def events():
        published = 0
        while not finished.wait(0.05):
            for event in session.host.evidence.after(published):
                emit({"event": "transcript", **event})
                published = event["seq"]

    emit(
        {"event": "ready", "run_id": session.host.run_id, "actors": list(session.host.credentials)}
    )
    pump = threading.Thread(target=events, daemon=True)
    pump.start()
    try:
        for line in sys.stdin:
            request = {}
            try:
                request = json.loads(line)
                if not isinstance(request, dict):
                    request = {}
                    raise ValueError("A request must be a JSON object.")
                handle_request(session, request, emit)
                if request.get("op") == "quit":
                    return
            except (ValueError, KeyError, ClientError, re.error) as exc:
                emit({"id": request.get("id"), "ok": False, "error": str(exc)})
    finally:
        finished.set()
        pump.join(timeout=2)


def handle_request(session, request, emit):
    operation = request["op"]
    if "id" not in request:
        raise ValueError("Every request needs an id.")
    if operation == "quit":
        emit({"id": request["id"], "ok": True})
        return
    if operation == "send":
        result = session.send(request["actor"], request["command"])
    elif operation == "read":
        result = session.host.evidence.after(request.get("after", 0), request.get("actor"))
    elif operation == "expect":
        client = session.connect(request["actor"])
        result = client.expect(
            request["pattern"], request.get("after", 0), request.get("timeout")
        ).group(0)
    elif operation == "snapshot":
        result = session.snapshot()
    elif operation == "disconnect":
        session.disconnect(request["actor"])
        result = None
    else:
        raise ValueError(f"Unknown operation: {operation}")
    emit({"id": request["id"], "ok": True, "result": result})


def run_host(args, profile):
    try:
        host = Host(profile, args.startup_timeout, args.action_timeout, args.shutdown_timeout)
    except (HostError, OSError) as exc:
        print(f"Playtest environment: {exc}", file=sys.stderr)
        return 2
    session = Session(host)
    print(f"Playtest {profile}: {host.directory}", file=sys.stderr, flush=True)
    code = 0
    results = []
    try:
        host.start()
        if args.mode == "interactive":
            interactive(session)
        else:
            from playtesting.scenarios import run_rp

            results.extend(run_rp(session, smoke=profile == "normal"))
            if args.browser and profile == "deterministic":
                from playtesting.browser import run_browser

                results.extend(run_browser(session, args.browser_timeout))
            if not results:
                raise HostError("No playtest cases executed")
            if any(not result["passed"] for result in results):
                code = 1
    except AssertionError as exc:
        code = 1
        results.append({"name": "assertion", "passed": False, "error": str(exc)})
        traceback.print_exc(file=sys.stderr)
    except Exception as exc:
        code = 2
        results.append({"name": "environment/protocol", "passed": False, "error": str(exc)})
        traceback.print_exc(file=sys.stderr)
    finally:
        session.close()
        try:
            host.stop()
        except Exception as exc:
            code = 2
            results.append({"name": "cleanup", "passed": False, "error": str(exc)})
            traceback.print_exc(file=sys.stderr)
        server_log = host.artifacts / "server.log"
        if server_log.is_file() and any(
            marker in server_log.read_text(encoding="utf-8") for marker in ("Traceback", "[EE]")
        ):
            code = max(code, 1)
            results.append(
                {
                    "name": "server log errors",
                    "passed": False,
                    "error": "Unexpected server exception; see server.log",
                }
            )
        host.evidence.write(
            "results.json",
            {
                "exit_code": code,
                "cases": results,
                "case_count": len(results),
                "passed_count": sum(result["passed"] for result in results),
                "partial": args.mode == "interactive" or not args.browser or args.profile != "both",
            },
        )
        report = "# Live playtest\n\n" + "\n".join(
            f"- {'PASS' if case['passed'] else 'FAIL'} {case['name']}: {case.get('error', '')}"
            for case in results
        )
        (host.artifacts / "results.md").write_text(
            host.evidence.clean(report) + "\n", encoding="utf-8"
        )
        if args.mode == "run":
            print(
                f"Playtest {profile}: {sum(case['passed'] for case in results)}/{len(results)} cases passed; exit {code}",
                file=sys.stderr,
                flush=True,
            )
    return code


def main(argv=None):
    if not __debug__:
        raise HostError("Playtests require assertions; do not run Python with -O.")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("run", "interactive"))
    parser.add_argument("--suite", choices=("rp",), default="rp")
    parser.add_argument("--profile", choices=("both", "deterministic", "normal"))
    parser.add_argument("--browser", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--startup-timeout", type=float, default=180)
    parser.add_argument("--action-timeout", type=float, default=15)
    parser.add_argument("--browser-timeout", type=float, default=30)
    parser.add_argument("--shutdown-timeout", type=float, default=30)
    args = parser.parse_args(argv)
    args.profile = args.profile or ("normal" if args.mode == "interactive" else "both")
    if args.mode == "interactive" and args.profile == "both":
        parser.error("interactive uses one persistent host; choose normal or deterministic")
    if any(
        getattr(args, name) <= 0
        for name in ("startup_timeout", "action_timeout", "browser_timeout", "shutdown_timeout")
    ):
        parser.error("timeouts must be positive")
    profiles = ("deterministic", "normal") if args.profile == "both" else (args.profile,)
    codes = [run_host(args, profile) for profile in profiles]
    return max(codes)


if __name__ == "__main__":
    sys.exit(main())
