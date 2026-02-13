"""
Broke Updater Sidecar

A minimal HTTP service that handles Docker operations for the main Broke app.
Only accessible on the internal Docker network (no host port mapping).

Endpoints:
    GET  /status  — health check
    POST /restart — pull latest image and recreate the target service
"""

import json
import os
import logging
from http.server import HTTPServer, BaseHTTPRequestHandler

import docker

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("updater")

# Configuration from environment
TARGET_IMAGE = os.environ.get("TARGET_IMAGE", "ghcr.io/valteryde/broke:latest")
COMPOSE_PROJECT = os.environ.get("COMPOSE_PROJECT", "broke")
TARGET_SERVICE = os.environ.get("TARGET_SERVICE", "broke-server")
PORT = int(os.environ.get("PORT", "9999"))


def get_docker_client():
    """Connect to the Docker daemon via the mounted socket."""
    return docker.from_env()


def pull_and_restart():
    """Pull the latest image and recreate the target container."""
    client = get_docker_client()

    # Pull the latest image
    logger.info(f"Pulling image: {TARGET_IMAGE}")
    client.images.pull(TARGET_IMAGE)
    logger.info("Image pulled successfully")

    # Find the target container by compose project + service labels
    containers = client.containers.list(
        filters={
            "label": [
                f"com.docker.compose.project={COMPOSE_PROJECT}",
                f"com.docker.compose.service={TARGET_SERVICE}",
            ]
        }
    )

    if not containers:
        raise RuntimeError(
            f"No container found for project={COMPOSE_PROJECT}, service={TARGET_SERVICE}"
        )

    container = containers[0]
    container_name = container.name
    logger.info(f"Found container: {container_name}")

    # Get current container configuration to preserve it
    attrs = container.attrs
    host_config = attrs["HostConfig"]
    networking = attrs["NetworkingConfig"] if "NetworkingConfig" in attrs else None
    env = attrs["Config"].get("Env", [])
    labels = attrs["Config"].get("Labels", {})
    ports = host_config.get("PortBindings", {})
    volumes = host_config.get("Binds", [])
    restart_policy = host_config.get("RestartPolicy", {"Name": "always"})

    # Collect connected networks
    networks = {}
    for net_name, net_config in attrs["NetworkSettings"]["Networks"].items():
        networks[net_name] = docker.types.EndpointConfig(
            aliases=net_config.get("Aliases"),
        )

    # Stop and remove old container
    logger.info(f"Stopping container: {container_name}")
    container.stop(timeout=30)
    container.remove()
    logger.info("Old container removed")

    # Create and start new container with same config
    logger.info(f"Creating new container: {container_name}")
    new_container = client.containers.create(
        image=TARGET_IMAGE,
        name=container_name,
        environment=env,
        labels=labels,
        ports=ports,
        volumes=volumes,
        restart_policy=restart_policy,
        detach=True,
        networking_config=networking,
    )

    # Connect to all the same networks
    for net_name, endpoint_config in networks.items():
        try:
            network = client.networks.get(net_name)
            network.connect(new_container, aliases=endpoint_config.get("Aliases"))
        except Exception as e:
            logger.warning(f"Could not connect to network {net_name}: {e}")

    new_container.start()
    logger.info(f"New container started: {new_container.short_id}")

    return {"success": True, "container_id": new_container.short_id}


class UpdateHandler(BaseHTTPRequestHandler):
    """HTTP request handler for the updater sidecar."""

    def _send_json(self, status_code, data):
        self.send_response(status_code)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps(data).encode())

    def do_GET(self):
        if self.path == "/status":
            try:
                client = get_docker_client()
                client.ping()
                self._send_json(200, {"ok": True, "docker": True})
            except Exception as e:
                self._send_json(500, {"ok": False, "error": str(e)})
        else:
            self._send_json(404, {"error": "Not found"})

    def do_POST(self):
        if self.path == "/restart":
            try:
                # Read optional body for image override
                content_length = int(self.headers.get("Content-Length", 0))
                if content_length > 0:
                    body = json.loads(self.rfile.read(content_length))
                    global TARGET_IMAGE
                    if "image" in body:
                        TARGET_IMAGE = body["image"]

                result = pull_and_restart()
                self._send_json(200, result)
            except Exception as e:
                logger.error(f"Restart failed: {e}", exc_info=True)
                self._send_json(500, {"error": str(e)})
        else:
            self._send_json(404, {"error": "Not found"})

    def log_message(self, format, *args):
        """Override to use our logger instead of stderr."""
        logger.info(f"{self.client_address[0]} - {format % args}")


if __name__ == "__main__":
    server = HTTPServer(("0.0.0.0", PORT), UpdateHandler)
    logger.info(f"Updater sidecar listening on port {PORT}")
    logger.info(f"Target: project={COMPOSE_PROJECT}, service={TARGET_SERVICE}")
    logger.info(f"Image: {TARGET_IMAGE}")
    server.serve_forever()
