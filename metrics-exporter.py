import json
import os
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

HOST = "0.0.0.0"
PORT = 9101
STATE_FILE = Path(os.getenv("METRICS_STATE_FILE", "/data/metrics.json"))
LOCK = threading.Lock()

BUCKETS = [0.1, 1, 5, 10, 30, 60, 120, 300]

def empty_state():
    return {
        "deployments": {},
        "duration": {},
        "active_version": -1,
        "last_timestamp": 0,
        "rollbacks": {},
    }

def load_state():
    try:
        return json.loads(STATE_FILE.read_text())
    except (OSError, ValueError):
        return empty_state()

state = load_state()

def save_state():
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    temporary = STATE_FILE.with_suffix(".tmp")
    temporary.write_text(json.dumps(state))
    temporary.replace(STATE_FILE)

def escape_label(value):
    return str(value).replace("\\", "\\\\").replace(
        "\n", "\\n"
    ).replace('"', '\\"')

def labels(**kwargs):
    return "{" + ",".join(
        f'{key}="{escape_label(value)}"'
        for key, value in kwargs.items()
    ) + "}"

def metrics_text():
    lines = [
        "# HELP blue_green_deployments_total Completed deployment attempts.",
        "# TYPE blue_green_deployments_total counter",
    ]

    for key, count in sorted(state["deployments"].items()):
        version, result = key.split("|", 1)
        lines.append(
            f"blue_green_deployments_total"
            f"{labels(version=version, result=result)} {count}"
        )

    lines += [
        "# HELP blue_green_deployment_duration_seconds Deployment duration in seconds.",
        "# TYPE blue_green_deployment_duration_seconds histogram",
    ]

    for version, values in sorted(state["duration"].items()):
        cumulative = 0
        for bucket in BUCKETS:
            cumulative += values.get(str(bucket), 0)
            lines.append(
                "blue_green_deployment_duration_seconds_bucket"
                f'{labels(version=version, le=bucket)} {cumulative}'
            )

        lines.append(
            "blue_green_deployment_duration_seconds_bucket"
            f'{labels(version=version, le="+Inf")} {values.get("count", 0)}'
        )
        lines.append(
            f"blue_green_deployment_duration_seconds_sum"
            f'{labels(version=version)} {values.get("sum", 0)}'
        )
        lines.append(
            f"blue_green_deployment_duration_seconds_count"
            f'{labels(version=version)} {values.get("count", 0)}'
        )

    lines += [
        "# HELP blue_green_active_version Active version: blue=0, green=1, unknown=-1.",
        "# TYPE blue_green_active_version gauge",
        f'blue_green_active_version {state["active_version"]}',
        "# HELP blue_green_last_deployment_timestamp_seconds Unix timestamp of the last completed attempt.",
        "# TYPE blue_green_last_deployment_timestamp_seconds gauge",
        f'blue_green_last_deployment_timestamp_seconds {state["last_timestamp"]}',
        "# HELP blue_green_rollbacks_total Rollback outcomes.",
        "# TYPE blue_green_rollbacks_total counter",
    ]

    for result, count in sorted(state["rollbacks"].items()):
        lines.append(
            f"blue_green_rollbacks_total"
            f'{labels(result=result)} {count}'
        )

    return "\n".join(lines) + "\n"


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path != "/metrics":
            self.send_error(404)
            return

        with LOCK:
            body = metrics_text().encode()

        self.send_response(200)
        self.send_header(
            "Content-Type", "text/plain; version=0.0.4; charset=utf-8"
        )
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        if self.path != "/record":
            self.send_error(404)
            return

        try:
            length = int(self.headers.get("Content-Length", "0"))
            event = json.loads(self.rfile.read(length))
            version = event.get("version")

            if version not in ("blue", "green"):
                raise ValueError("Invalid version")

            result = event.get("result")
            if result not in ("success", "failure"):
                raise ValueError("Invalid result")

            duration = float(event["duration_seconds"])
            if duration < 0:
                raise ValueError("Invalid duration")

            active = event.get("active_version")
            if active not in ("blue", "green", None):
                raise ValueError("Invalid active version")

            rollback = event.get("rollback_result")
            if rollback not in (None, "success", "failure"):
                raise ValueError("Invalid rollback result")

            with LOCK:
                key = f"{version}|{result}"
                state["deployments"][key] = (
                    state["deployments"].get(key, 0) + 1
                )

                values = state["duration"].setdefault(
                    version,
                    {"sum": 0, "count": 0, **{
                        str(b): 0 for b in BUCKETS
                    }},
                )
                values["sum"] += duration
                values["count"] += 1

                for bucket in BUCKETS:
                    if duration <= bucket:
                        values[str(bucket)] += 1

                if active is not None:
                    state["active_version"] = (
                        0 if active == "blue" else 1
                    )

                state["last_timestamp"] = time.time()

                if rollback is not None:
                    state["rollbacks"][rollback] = (
                        state["rollbacks"].get(rollback, 0) + 1
                    )

                save_state()

            self.send_response(204)
            self.end_headers()

        except (ValueError, KeyError, TypeError, OSError):
            self.send_error(400, "Invalid event or state write failed")

    def log_message(self, *_):
        pass


if __name__ == "__main__":
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    with LOCK:
        save_state()

    print(f"Metrics exporter listening on {HOST}:{PORT}")
    ThreadingHTTPServer((HOST, PORT), Handler).serve_forever()