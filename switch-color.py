import json
import subprocess
import sys
import time
from pathlib import Path
from urllib.request import urlopen


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
# Configuration
# =========================

PROJECT_ROOT = Path(__file__).resolve().parent
ACTIVE_CONFIG = PROJECT_ROOT / "nginx" / "active.conf"

APP_PORT = 555
APP_URL = "http://127.0.0.1"

SERVICES = {
    "blue": "app-blue",
    "green": "app-green",
}


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
    """Check the target application directly inside its container."""

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

    heading(f"VERIFYING LIVE VERSION: {expected_version.upper()}")

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

    raise RuntimeError(
        "Live version verification failed."
    )


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
    """Validate configuration before reloading Nginx."""

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

    success("Nginx reload command completed.")


# =========================
# Rollback
# =========================

def rollback(previous_config):
    """Restore the previous routing configuration."""

    heading("ROLLBACK STARTED")

    ACTIVE_CONFIG.write_text(
        previous_config,
        encoding="utf-8",
    )

    validate_and_reload_nginx()

    success("Rollback configuration restored.")


# =========================
# Blue-Green Deployment
# =========================

def deploy(version):
    """Deploy the requested blue or green application."""

    if version not in SERVICES:
        raise ValueError(
            "Choose either: blue or green."
        )

    if not ACTIVE_CONFIG.exists():
        raise FileNotFoundError(
            f"Missing Nginx config: {ACTIVE_CONFIG}"
        )

    previous_config = ACTIVE_CONFIG.read_text(
        encoding="utf-8"
    )

    config_changed = False

    heading(f"STARTING {version.upper()} DEPLOYMENT")

    info(f"Target service: {SERVICES[version]}")
    info(f"Application port: {APP_PORT}")

    try:
        # Step 1: Check Docker Compose service status.
        heading("STEP 1: CHECKING DOCKER SERVICE")

        run_command([
            "docker", "compose", "ps", "--all",
            SERVICES[version],
        ])

        success("Docker Compose service checked.")

        # Step 2: Verify application health.
        heading("STEP 2: CHECKING APPLICATION HEALTH")

        check_target_health(SERVICES[version])

        # Step 3: Update Nginx routing configuration.
        heading("STEP 3: SWITCHING TRAFFIC")

        write_active_config(version)
        config_changed = True

        # Step 4: Validate configuration and reload Nginx.
        heading("STEP 4: APPLYING NGINX CONFIGURATION")

        validate_and_reload_nginx()

        # Step 5: Verify the live application version.
        heading("STEP 5: VERIFYING DEPLOYMENT")

        verify_live_version(version)

        # Deployment completed successfully.
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

        if config_changed:
            try:
                rollback(previous_config)

            except Exception as rollback_err:
                error(f"ROLLBACK ERROR: {rollback_err}")

                warning(
                    "Check Nginx and the active configuration "
                    "manually."
                )

        sys.exit(1)

# =========================
# Detect Current Version
# =========================
def detect_current_version():

    try:

        with urlopen(APP_URL + "/", timeout=3) as response:
            payload = json.loads(
                response.read().decode("utf-8")
            )
    
        actual_version = payload.get("version")

        if actual_version not in SERVICES:
            raise RuntimeError(
                f"Unknown active application version: {actual_version}"
            )
        
        return actual_version

    except Exception as err:
        warning(f"Could not detect active version: {err}")
        raise RuntimeError(
            "Cannot safely determine the current deployment."
        ) from err

# =========================
# Auto-Switch Deployment Version
# =========================
def auto_switch():
    current_version = detect_current_version()

    target_version = (
        "green" if current_version == "blue" else "blue"
    )

    heading("AUTOMATIC BLUE-GREEN DEPLOYMENT")
    info(f"Current version: {current_version}")
    info(f"Target version: {target_version}")

    deploy(target_version)

# =========================
# Main Entry Point
# =========================

if __name__ == "__main__":
    # if len(sys.argv) != 2:
    #     print(
    #         f"{Colors.YELLOW}"
    #         "Usage: python deploy.py blue|green|auto"
    #         f"{Colors.RESET}"
    #     )
    #     sys.exit(2)

    try:
        if len(sys.argv) == 1:
            auto_switch()
        elif len(sys.argv) == 2:
            version = sys.argv[1].lower()
            deploy(version)
        else:
            error("Usage: python3 switch-color.py [blue|green]")
            sys.exit(2)

    except (ValueError, FileNotFoundError) as err:
        error(str(err))
        sys.exit(1)