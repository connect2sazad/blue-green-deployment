
import json
import subprocess
import sys
import time
from pathlib import Path
from urllib.request import Request, urlopen


# =========================
# Configuration
# =========================

PROJECT_ROOT = Path(__file__).resolve().parent
ACTIVE_CONFIG = PROJECT_ROOT / "nginx" / "active.conf"

APP_PORT = 555
APP_URL = "http://127.0.0.1"
METRICS_URL = "http://127.0.0.1:9101/record"

SERVICES = {
    "blue": "app-blue",
    "green": "app-green",
}


# =========================
# Console Colors
# =========================

class Colors:
    RESET = "\033[0m"
    BOLD = "\033[1m"

    RED = "\033[91m"
    GREEN = "\033[92m"
    YELLOW = "\033[93m"
    BLUE = "\033[94m"
    CYAN = "\033[96m"
    MAGENTA = "\033[95m"
    GRAY = "\033[90m"


# =========================
# Console Helpers
# =========================

def info(message):
    print(f"{Colors.BLUE}ℹ {message}{Colors.RESET}")


def success(message):
    print(f"{Colors.GREEN}✓ {message}{Colors.RESET}")


def warning(message):
    print(f"{Colors.YELLOW}⚠ {message}{Colors.RESET}")


def error(message):
    print(f"{Colors.RED}✗ {message}{Colors.RESET}")


def heading(message):
    print(
        f"\n{Colors.BOLD}{Colors.MAGENTA}"
        f"{'=' * 50}\n"
        f"{message}\n"
        f"{'=' * 50}"
        f"{Colors.RESET}"
    )


# =========================
# Deployment Metrics
# =========================

def record_deployment_metrics(
    version,
    result,
    duration_seconds,
    active_version=None,
    rollback_result=None,
):
    """Send a deployment event to the persistent metrics exporter."""

    payload = {
        "version": version,
        "result": result,
        "duration_seconds": duration_seconds,
        "active_version": active_version,
        "rollback_result": rollback_result,
    }

    request = Request(
        METRICS_URL,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    try:
        with urlopen(request, timeout=2) as response:
            if response.status != 204:
                warning(
                    "Metrics exporter returned an unexpected status."
                )

        success("Deployment metrics recorded.")

    except Exception as err:
        # A metrics outage must not change the deployment result.
        warning(f"Could not record deployment metrics: {err}")


# =========================
# Run Shell Commands
# =========================

def run_command(args, check=True):
    """Run a command from the project directory."""

    print(
        f"\n{Colors.CYAN}{Colors.BOLD}"
        f"> {' '.join(args)}"
        f"{Colors.RESET}"
    )

    result = subprocess.run(
        args,
        cwd=PROJECT_ROOT,
        text=True,
        capture_output=True,
    )

    if result.stdout:
        print(
            f"{Colors.GRAY}"
            f"{result.stdout.strip()}"
            f"{Colors.RESET}"
        )

    if result.stderr:
        color = (
            Colors.RED
            if result.returncode != 0
            else Colors.YELLOW
        )

        print(f"{color}{result.stderr.strip()}{Colors.RESET}")

    if check and result.returncode != 0:
        raise RuntimeError(
            f"Command failed: {' '.join(args)}"
        )

    return result


# =========================
# Health Check
# =========================

def check_target_health(service):
    """Check the target application from inside its container."""

    heading(f"HEALTH CHECK: {service}")

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
                service, "node", "-e", check_code,
            ],
            check=False,
        )

        if result.returncode == 0:
            success(f"{service} is responding successfully.")
            return

        warning(
            f"Health check {attempt}/10 failed; retrying..."
        )

        time.sleep(2)

    raise RuntimeError(
        f"{service} did not become healthy."
    )


# =========================
# Verify Live Version
# =========================

def verify_live_version(expected_version):
    """Verify the version served through Nginx."""

    heading(
        f"VERIFYING LIVE VERSION: {expected_version.upper()}"
    )

    for attempt in range(1, 11):
        try:
            with urlopen(APP_URL + "/", timeout=3) as response:
                payload = json.loads(
                    response.read().decode("utf-8")
                )

            actual_version = payload.get("version")

            if actual_version == expected_version:
                success(
                    f"Deployment verified: {actual_version}"
                )
                return

            warning(
                f"Attempt {attempt}/10: expected "
                f"{expected_version}, received {actual_version}"
            )

        except Exception as err:
            warning(f"Attempt {attempt}/10: {err}")

        time.sleep(1)

    raise RuntimeError("Live version verification failed.")


# =========================
# Update Nginx Config
# =========================

def write_active_config(version):
    """Atomically update the Nginx upstream configuration."""

    service = SERVICES[version]

    config = (
        "upstream active_app {\n"
        f"    server {service}:{APP_PORT};\n"
        "}\n"
    )

    temporary_file = ACTIVE_CONFIG.with_name(
        "active.conf.temp"
    )

    temporary_file.write_text(
        config,
        encoding="utf-8",
    )

    temporary_file.replace(ACTIVE_CONFIG)

    success(
        f"Nginx configuration updated for {version.upper()}."
    )


# =========================
# Validate and Reload Nginx
# =========================

def validate_and_reload_nginx():
    """Validate configuration and apply the Nginx changes."""

    heading("VALIDATING NGINX CONFIGURATION")

    run_command([
        "docker", "compose", "exec", "-T",
        "nginx", "nginx", "-t",
    ])

    success("Nginx configuration validation passed.")

    heading("RELOADING NGINX")

    run_command([
        "docker", "compose", "up",
        "-d",
        "--force-recreate",
        "--no-deps",
        "nginx",
    ])

    success("Nginx configuration applied.")


# =========================
# Rollback
# =========================

def rollback(previous_config):
    """Restore the previous routing configuration."""

    heading("ROLLBACK STARTED")

    temporary_file = ACTIVE_CONFIG.with_name(
        "active.conf.rollback"
    )

    temporary_file.write_text(
        previous_config,
        encoding="utf-8",
    )

    temporary_file.replace(ACTIVE_CONFIG)

    validate_and_reload_nginx()

    success("Rollback configuration restored.")


# =========================
# Detect Current Version
# =========================

def detect_current_version():
    """Detect the currently served version through Nginx."""

    try:
        with urlopen(APP_URL + "/", timeout=3) as response:
            payload = json.loads(
                response.read().decode("utf-8")
            )

        actual_version = payload.get("version")

        if actual_version not in SERVICES:
            raise RuntimeError(
                f"Unknown active application version: "
                f"{actual_version}"
            )

        return actual_version

    except Exception as err:
        warning(f"Could not detect active version: {err}")

        raise RuntimeError(
            "Cannot safely determine the current deployment."
        ) from err


# =========================
# Blue-Green Deployment
# =========================

def deploy(version):
    """Deploy a version and record the outcome and duration."""

    if version not in SERVICES:
        raise ValueError("Choose either: blue or green.")

    start_time = time.monotonic()

    deployment_result = "failure"
    rollback_result = None
    config_changed = False
    previous_config = None

    heading(f"STARTING {version.upper()} DEPLOYMENT")

    info(f"Target service: {SERVICES[version]}")
    info(f"Application port: {APP_PORT}")

    try:
        if not ACTIVE_CONFIG.exists():
            raise FileNotFoundError(
                f"Missing Nginx config: {ACTIVE_CONFIG}"
            )

        previous_config = ACTIVE_CONFIG.read_text(
            encoding="utf-8"
        )

        # Step 1: Check Docker service status.
        heading("STEP 1: CHECKING DOCKER SERVICE")

        run_command([
            "docker", "compose", "ps", "--all",
            SERVICES[version],
        ])

        success("Docker Compose service checked.")

        # Step 2: Check target application health.
        heading("STEP 2: CHECKING APPLICATION HEALTH")

        check_target_health(SERVICES[version])

        # Step 3: Switch Nginx routing.
        heading("STEP 3: SWITCHING TRAFFIC")

        write_active_config(version)
        config_changed = True

        # Step 4: Validate and apply configuration.
        heading("STEP 4: APPLYING NGINX CONFIGURATION")

        validate_and_reload_nginx()

        # Step 5: Verify the live application version.
        heading("STEP 5: VERIFYING DEPLOYMENT")

        verify_live_version(version)

        deployment_result = "success"

        print(
            f"\n{Colors.GREEN}{Colors.BOLD}"
            f"{'=' * 50}\n"
            f"✓ SUCCESS: Traffic is now routed to "
            f"{version.upper()}.\n"
            f"{'=' * 50}"
            f"{Colors.RESET}"
        )

    except Exception as err:
        print(
            f"\n{Colors.RED}{Colors.BOLD}"
            f"✗ DEPLOYMENT FAILED: {err}"
            f"{Colors.RESET}"
        )

        if config_changed and previous_config is not None:
            try:
                rollback(previous_config)
                rollback_result = "success"

            except Exception as rollback_err:
                rollback_result = "failure"

                error(f"ROLLBACK ERROR: {rollback_err}")

                warning(
                    "Check Nginx and the active configuration "
                    "manually."
                )

    finally:
        duration = time.monotonic() - start_time

        # Report the version only if it can be verified.

        try:
            current_version = detect_current_version()
            active_version = 1 if current_version == "green" else 0 if current_version == "blue" else -1
        except Exception:
            warning(
                "Active version is unknown; preserving "
                "the previous exporter gauge."
            )

        record_deployment_metrics(
            version=version,
            result=deployment_result,
            duration_seconds=duration,
            active_version=active_version,
            rollback_result=rollback_result,
        )

    if deployment_result == "failure":
        sys.exit(1)


# =========================
# Prepare New Deployment Version
# =========================

def prepare_new_version(target_version):
    """Build and start the target application."""

    service = SERVICES[target_version]

    heading(f"PREPARING {target_version.upper()} DEPLOYMENT")

    info(f"Building and starting {service}...")

    run_command([
        "docker", "compose",
        "up", "-d",
        "--build",
        service,
    ])

    success(f"{service} has been started.")


# =========================
# Auto-Switch Deployment Version
# =========================

def auto_switch():
    """Detect the active version and deploy the other version."""

    current_version = detect_current_version()

    target_version = (
        "green" if current_version == "blue" else "blue"
    )

    heading("AUTOMATIC BLUE-GREEN DEPLOYMENT")

    info(f"Current version: {current_version}")
    info(f"Target version: {target_version}")

    prepare_new_version(target_version)
    deploy(target_version)


# =========================
# Main Entry Point
# =========================

if __name__ == "__main__":
    try:
        if len(sys.argv) == 1:
            auto_switch()

        elif len(sys.argv) == 2:
            version = sys.argv[1].lower()

            if version == "auto":
                auto_switch()
            else:
                deploy(version)

        else:
            error(
                "Usage: python3 switch-color.py [blue|green|auto]"
            )
            sys.exit(2)

    except (ValueError, FileNotFoundError) as err:
        error(str(err))
        sys.exit(1)

    except Exception as err:
        error(f"DEPLOYMENT ERROR: {err}")
        sys.exit(1)
