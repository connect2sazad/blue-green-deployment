import json
import re
import subprocess
import sys
import time
from pathlib import Path
from urllib.request import urlopen

PROJECT_ROOT = Path(__file__).resolve().parent;
ACTIVE_CONFIG = PROJECT_ROOT / "nginx" / "active.conf"
APP_PORT = 555
APP_URL = "http://127.0.0.1"

SERVICES = {
    "blue": "app-blue",
    "green": "app-green",
}

def run_command(args, check=True):
    """Run a command from project directory"""
    print(f"\n> {' '.join(args)}")

    result=subprocess.run(
        args,
        cwd=PROJECT_ROOT,
        text=True,
        capture_output=True,
    )

    if result.stdout:
        print(result.stdout.strip())

    if result.stderr:
        print(result.stderr.strip())

    if check and result.returncode != 0:
        raise RuntimeError(f"Command failed: {' '.join(args)}")

    return result

def check_target_health(service):
    """Check the target application directly inside its container."""
    print(f"\nChecking health of {service}...")

    check_code = (
        "require('http').get("
        f"'{APP_URL}:{APP_PORT}/', "
        "r => process.exit("
        "r.statusCode >= 200 && r.statusCode < 300 ? 0 : 1"
        ")).on('error', () => process.exit(1))"
    )

    for attempt in range(1, 11):
        result = run_command(
            [
                "docker", "compose", "exec", "-T",
                service, "node", "-e", check_code
            ],
            check=False,
        )

        if result.returncode == 0:
            print(f"{service} is responding successfully")
            return

        print(f"Health check {attempt}/10 failed; retrying...")
        time.sleep(2)

    raise RuntimeError(f"{service} did not become healthy.")

def verify_live_version(expected_version):
    """Verify the version served through Nginx."""
    print(f"\nVerifying live version: {expected_version}")

    for attempt in range(1,11):
        try:
            with urlopen(APP_URL+"/", timeout=3) as response:
                payload = json.loads(response.read().decode("utf-8"))

            actual_version = payload.get("version")

            if actual_version == expected_version:
                print(f"Deployment verified: {actual_version}")
                return

            print(
                f"Attempt {attempt}/10: expected "
                f"{expected_version}, received {actual_version}"
            )

        except Exception as err:
            print(f"Attempt {attempt}/10: {err}")

        time.sleep(1)

    raise RuntimeError("Live version verification failed.")

def write_active_config(version):
    """Atomically update the Nginx upstream configuration."""
    service = SERVICES[version]

    config = (
        "upstream active_app {\n"
        f"    server {service}:{APP_PORT};\n"
        "}\n"
    )

    temporary_file = ACTIVE_CONFIG.with_name('active.conf.temp')
    temporary_file.write_text(config, encoding="utf-8")
    temporary_file.replace(ACTIVE_CONFIG)

def validate_and_reload_nginx():
    """Validate configuration before reloading Nginx."""
    run_command([
        "docker", "compose", "exec", "-T",
        "nginx", "nginx", "-t",
    ])

    run_command([
        "docker", "compose", "exec", "-T",
        "nginx", "nginx", "-s", "reload",
    ])

def rollback(previous_config):
    """Restore the previous routing configuration."""
    print("\nDeployment failed. Attempting rollback...")

    ACTIVE_CONFIG.write_text(previous_config, encoding="utf-8")

    validate_and_reload_nginx()

    print("Rollback configuration restored.")

def deploy(version):
    if version not in SERVICES:
        raise ValueError(f"Choose either of: {SERVICES}")

    if not ACTIVE_CONFIG.exists():
        raise FileNotFoundError(f"Missing Nginx config: {ACTIVE_CONFIG}")

    previous_config = ACTIVE_CONFIG.read_text(encoding="utf-8")
    config_changed = False

    try:
        # Confirm Docker Compose can access the target.
        run_command([
            "docker", "compose", "ps", "--all", SERVICES[version]
        ])

        # Ensure the target responds before switching the traffic
        check_target_health(SERVICES[version])

        # Change routing, then validate and apply it.
        write_active_config(version)
        config_changed = True

        # validate nginx configuration and reload nginx
        validate_and_reload_nginx()

        # Confirm that Nginx now servers the requested version
        verify_live_version(version)

        print(f"\nSUCCESS: Traffic is now routed to {version.upper()}.")

    except Exception as err:
        print(f"\nERROR: {err}")

        if config_changed:
            try:
                rollback(previous_config)
            except Exception as rollback_err:
                print(f"ROLLBACK ERROR: {rollback_err}")
                print("Check Nginx and the active configuration manually.")

        sys.exit(1)

if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: python deploy.py blue|green")
        sys.exit(2)

    try:
        deploy(sys.argv[1].lower())
    except (ValueError, FileNotFoundError) as err:
        print(f"ERROR: {err}")
        sys.exit(1)