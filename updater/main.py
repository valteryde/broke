"""
Broke Updater Sidecar

A minimal HTTP service that handles Docker operations for the main Broke app.
Only accessible on the internal Docker network (no host port mapping).

Endpoints:
    GET  /status  — health check
    POST /restart — pull latest image and recreate the target service
"""

import os
import logging

from flask import Flask, jsonify, request
import docker

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("updater")

# Configuration from environment
TARGET_IMAGE = os.environ.get("TARGET_IMAGE", "ghcr.io/valteryde/broke:latest")
COMPOSE_PROJECT = os.environ.get("COMPOSE_PROJECT", "broke")
TARGET_SERVICE = os.environ.get("TARGET_SERVICE", "broke-server")
PORT = int(os.environ.get("PORT", "9999"))

app = Flask(__name__)


def get_docker_client():
    """Connect to the Docker daemon via the mounted socket."""
    try:
        return docker.from_env()
    except PermissionError as e:
        logger.error("Permission denied accessing Docker socket. Solutions:")
        logger.error("1. Run container as root: add 'user: root' in docker-compose.yml")
        logger.error("2. Mount socket with proper permissions: /var/run/docker.sock:/var/run/docker.sock:rw")
        logger.error("3. Add container user to docker group")
        raise RuntimeError(f"Cannot access Docker socket: {e}") from e


def pull_and_restart(image=None):
    """Pull the latest image and recreate the target container."""
    target_image = image or TARGET_IMAGE
    client = get_docker_client()

    # Pull the latest image
    logger.info(f"Pulling image: {target_image}")
    client.images.pull(target_image)
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
        networks[net_name] = {
            "Aliases": net_config.get("Aliases", []),
        }

    # Stop and remove old container
    logger.info(f"Stopping container: {container_name}")
    container.stop(timeout=30)
    container.remove()
    logger.info("Old container removed")

    # Create and start new container with same config
    logger.info(f"Creating new container: {container_name}")
    new_container = client.containers.create(
        image=target_image,
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
            network.connect(new_container, aliases=endpoint_config.get("Aliases", []))
        except Exception as e:
            logger.warning(f"Could not connect to network {net_name}: {e}")

    new_container.start()
    logger.info(f"New container started: {new_container.short_id}")

    return {"success": True, "container_id": new_container.short_id}


@app.route("/status", methods=["GET"])
def status():
    """Health check endpoint."""
    try:
        client = get_docker_client()
        client.ping()
        return jsonify({"ok": True, "docker": True})
    except Exception as e:
        logger.error(f"Status check failed: {e}")
        return jsonify({"ok": False, "error": str(e)}), 500


@app.route("/restart", methods=["POST"])
def restart():
    """Pull latest image and recreate the target container."""
    try:
        data = request.get_json(silent=True) or {}
        image = data.get("image")
        result = pull_and_restart(image=image)
        return jsonify(result)
    except Exception as e:
        logger.error(f"Restart failed: {e}", exc_info=True)
        return jsonify({"error": str(e)}), 500


if __name__ == "__main__":
    logger.info(f"Updater sidecar starting on port {PORT}")
    logger.info(f"Target: project={COMPOSE_PROJECT}, service={TARGET_SERVICE}")
    logger.info(f"Image: {TARGET_IMAGE}")
    app.run(host="0.0.0.0", port=PORT)
