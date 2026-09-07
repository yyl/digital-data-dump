"""Client for Workflowy's full node export endpoint."""

import json
from typing import Any, Dict, List, Optional

import requests

from ..config import Config


class WorkflowyAPIError(RuntimeError):
    """Raised when Workflowy cannot provide a valid complete export."""


class WorkflowyRateLimitError(WorkflowyAPIError):
    """Raised when Workflowy's one-export-per-minute limit is reached."""


class WorkflowyAPIClient:
    """Fetch and validate a complete Workflowy node export."""

    def __init__(
        self,
        api_key: Optional[str] = None,
        session: Optional[requests.Session] = None,
    ):
        self.api_key = api_key if api_key is not None else Config.WORKFLOWY_API_KEY
        self.api_base = Config.WORKFLOWY_API_BASE.rstrip("/")
        self.session = session or requests.Session()

    def export_all_nodes(self) -> List[Dict[str, Any]]:
        """Return fully validated, database-ready nodes from one export."""
        try:
            response = self.session.get(
                f"{self.api_base}/nodes-export",
                headers={"Authorization": f"Bearer {self.api_key}"},
                timeout=(10, 120),
            )
        except requests.RequestException as exc:
            raise WorkflowyAPIError(f"Workflowy export request failed: {exc}") from exc

        if response.status_code == 429:
            retry_after = response.headers.get("Retry-After")
            suffix = f" Retry after {retry_after} seconds." if retry_after else ""
            raise WorkflowyRateLimitError(
                "Workflowy allows one complete node export per minute." + suffix
            )

        try:
            response.raise_for_status()
        except requests.RequestException as exc:
            raise WorkflowyAPIError(f"Workflowy export failed: HTTP {response.status_code}") from exc

        try:
            payload = response.json()
        except ValueError as exc:
            raise WorkflowyAPIError("Workflowy export returned invalid JSON.") from exc

        if not isinstance(payload, dict) or not isinstance(payload.get("nodes"), list):
            raise WorkflowyAPIError("Workflowy export must be an object containing a nodes list.")

        seen_ids: set[str] = set()
        return [self._normalize_node(node, seen_ids) for node in payload["nodes"]]

    @staticmethod
    def _normalize_node(node: Any, seen_ids: set[str]) -> Dict[str, Any]:
        if not isinstance(node, dict):
            raise WorkflowyAPIError("Workflowy export contains a non-object node.")

        node_id = node.get("id")
        if not isinstance(node_id, str) or not node_id:
            raise WorkflowyAPIError("Workflowy export contains a node without a valid id.")
        if node_id in seen_ids:
            raise WorkflowyAPIError(f"Workflowy export contains duplicate node id {node_id!r}.")
        seen_ids.add(node_id)

        parent_id = node.get("parent_id")
        if parent_id is not None and not isinstance(parent_id, str):
            raise WorkflowyAPIError(f"Node {node_id!r} has an invalid parent_id.")
        if not isinstance(node.get("name"), str):
            raise WorkflowyAPIError(f"Node {node_id!r} has an invalid name.")
        if node.get("note") is not None and not isinstance(node.get("note"), str):
            raise WorkflowyAPIError(f"Node {node_id!r} has an invalid note.")
        if isinstance(node.get("priority"), bool) or not isinstance(node.get("priority"), (int, float)):
            raise WorkflowyAPIError(f"Node {node_id!r} has an invalid priority.")
        if not isinstance(node.get("completed"), bool):
            raise WorkflowyAPIError(f"Node {node_id!r} has an invalid completed value.")

        timestamps: Dict[str, Optional[float]] = {}
        for key in ("createdAt", "modifiedAt", "completedAt"):
            value = node.get(key)
            if key == "completedAt" and value is None:
                timestamps[key] = None
            elif isinstance(value, bool) or not isinstance(value, (int, float)):
                raise WorkflowyAPIError(f"Node {node_id!r} has an invalid {key}.")
            else:
                timestamps[key] = float(value)

        data = node.get("data", {})
        if not isinstance(data, dict):
            raise WorkflowyAPIError(f"Node {node_id!r} has invalid data.")
        layout_mode = data.get("layoutMode")
        if layout_mode is not None and not isinstance(layout_mode, str):
            raise WorkflowyAPIError(f"Node {node_id!r} has invalid data.layoutMode.")

        return {
            "id": node_id,
            "parent_id": parent_id,
            "name": node["name"],
            "note": node.get("note"),
            "priority": float(node["priority"]),
            "layout_mode": layout_mode,
            "completed": node["completed"],
            "created_at": timestamps["createdAt"],
            "modified_at": timestamps["modifiedAt"],
            "completed_at": timestamps["completedAt"],
            "raw_json": json.dumps(node, sort_keys=True, separators=(",", ":")),
        }
