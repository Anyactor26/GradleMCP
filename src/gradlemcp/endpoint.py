import httpx


def endpoint_status(config):
    result = {
        "public_url": config.public_url,
        "exposure_mode": config.exposure,
        "connection_status": "not_probed",
        "temporary": False,
        "diagnostic": "Configured URL is not proof of external reachability",
    }
    if config.exposure == "private":
        result["connection_status"] = "private"
    elif config.exposure == "ngrok" and config.tunnel_status_url:
        # Local operator-managed ngrok API only. Never configurable by API clients.
        try:
            with httpx.Client(timeout=2, follow_redirects=False, trust_env=False) as client:
                data = client.get(config.tunnel_status_url).raise_for_status().json()
            tunnels = [
                t for t in data.get("tunnels", []) if t.get("public_url", "").startswith("https://")
            ]
            if tunnels:
                result.update(
                    public_url=tunnels[0]["public_url"],
                    connection_status="connected",
                    temporary=True,
                )
            else:
                result["connection_status"] = "disconnected"
        except (httpx.HTTPError, ValueError, KeyError):
            result["connection_status"] = "disconnected"
    elif config.exposure in ("cloudflare", "custom"):
        result["diagnostic"] = "Operator-managed tunnel; connection not verified by GradleMCP"
    return result
