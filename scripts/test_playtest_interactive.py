"""Exercise the real persistent JSONL CLI across multiple actors and requests."""

import json
import queue
import subprocess
import sys
import threading
import time

from playtesting.host import HIDDEN, ROOT


def main():
    diagnostics = ROOT / ".playtest-runs" / "interactive-smoke.log"
    diagnostics.parent.mkdir(exist_ok=True)
    with diagnostics.open("w", encoding="utf-8") as log:
        process = subprocess.Popen(
            [sys.executable, str(ROOT / "scripts/playtest.py"), "interactive"],
            cwd=ROOT,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=log,
            text=True,
            encoding="utf-8",
            bufsize=1,
            **HIDDEN,
        )
        received = queue.Queue()
        events = []

        def read():
            try:
                for line in process.stdout:
                    received.put(json.loads(line))
            except Exception as exc:
                received.put({"reader_error": str(exc)})
            finally:
                received.put({"event": "eof"})

        reader = threading.Thread(target=read, daemon=True)
        reader.start()

        def wait(key, value, timeout=45):
            deadline = time.monotonic() + timeout
            while True:
                remaining = deadline - time.monotonic()
                assert remaining > 0, f"JSONL timeout waiting for {key}={value}"
                message = received.get(timeout=remaining)
                if message.get("event") == "transcript":
                    events.append(message)
                elif message.get(key) == value:
                    return message
                elif message.get("event") == "eof" or "reader_error" in message:
                    raise AssertionError(f"JSONL runner stopped: {message}; see {diagnostics}")

        def request(identity, operation, **arguments):
            process.stdin.write(json.dumps({"id": identity, "op": operation, **arguments}) + "\n")
            process.stdin.flush()
            return wait("id", identity)

        try:
            ready = wait("event", "ready", timeout=360)
            assert ready["actors"] == ["alice", "bob", "staff", "browser", "browser-observer"]
            first = request(1, "send", actor="alice", command="look")
            assert first["ok"] and "Playtest telnet laboratory" in first["result"]["output"]
            second = request(2, "send", actor="bob", command="ooc JSONL multi-actor greeting")
            assert second["ok"]
            observed = request(
                3,
                "expect",
                actor="alice",
                pattern="JSONL multi-actor greeting",
                after=first["result"]["through"],
                timeout=5,
            )
            assert observed["ok"], observed
            state = request(4, "snapshot")
            assert state["ok"] and len(state["result"]["actors"]) == 5
            assert request(5, "disconnect", actor="bob")["ok"]
            assert request(6, "send", actor="bob", command="+sheet")["ok"]
            invalid = request(7, "send", actor="unknown", command="look")
            assert not invalid["ok"]
            history = request(8, "read", actor="alice", after=first["result"]["through"])
            assert history["ok"] and any(
                "JSONL multi-actor greeting" in event["plain"] for event in history["result"]
            )
            assert request(9, "quit")["ok"]
            assert [event["seq"] for event in events] == sorted({event["seq"] for event in events})
            assert events, "No unsolicited transcript events"
        finally:
            process.stdin.close()  # EOF also requests normal host cleanup on assertion failure.
            process.wait(timeout=360)
            reader.join(timeout=3)
            process.stdout.close()
    assert process.returncode == 0, diagnostics.read_text(encoding="utf-8")[-4000:]
    print("Live JSONL smoke: 9 requests, two player sessions, staff snapshot and reconnect passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
