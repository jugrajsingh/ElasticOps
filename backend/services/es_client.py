import httpx


class ESClient:
    """Async HTTP client for Elasticsearch. No elasticsearch-py dependency.

    By default a short-lived ``httpx.AsyncClient`` is created per request (request-scoped use, the
    FastAPI dependency path). The background poller injects a pooled, long-lived client via
    ``pooled_client`` so a single ``httpx.AsyncClient`` is reused across its many cat_* requests,
    avoiding per-call connection churn. The injected client is owned (and closed) by the caller.
    """

    def __init__(
        self,
        base_url: str,
        username: str,
        password: str,
        verify_ssl: bool = True,
        pooled_client: httpx.AsyncClient | None = None,
    ):
        self._base_url = base_url.rstrip("/")
        self._auth = (username, password) if username else None
        self._verify_ssl = verify_ssl
        self._pooled_client = pooled_client

    def _build_url(self, path: str) -> str:
        return f"{self._base_url}{path}"

    async def request(self, method: str, path: str, **kwargs) -> dict:
        if self._pooled_client is not None:
            response = await self._pooled_client.request(method, self._build_url(path), auth=self._auth, **kwargs)
            response.raise_for_status()
            return response.json()
        async with httpx.AsyncClient(verify=self._verify_ssl, timeout=30.0) as client:
            response = await client.request(
                method,
                self._build_url(path),
                auth=self._auth,
                **kwargs,
            )
            response.raise_for_status()
            return response.json()

    async def get(self, path: str, **kwargs) -> dict:
        return await self.request("GET", path, **kwargs)

    async def put(self, path: str, **kwargs) -> dict:
        return await self.request("PUT", path, **kwargs)

    async def post(self, path: str, **kwargs) -> dict:
        return await self.request("POST", path, **kwargs)

    async def delete(self, path: str, **kwargs) -> dict:
        return await self.request("DELETE", path, **kwargs)

    async def cluster_health(self) -> dict:
        return await self.get("/_cluster/health")

    async def index_health(self, index: str) -> dict:
        return await self.get(f"/_cluster/health/{index}", params={"timeout": "5s"})

    async def set_index_settings(self, index: str, settings: dict) -> dict:
        return await self.put(f"/{index}/_settings", json={"settings": settings})

    async def shrink_index(self, source: str, target: str, settings: dict) -> dict:
        return await self.post(f"/{source}/_shrink/{target}", json={"settings": settings})

    async def split_index(self, source: str, target: str, settings: dict) -> dict:
        return await self.request("PUT", f"/{source}/_split/{target}", json={"settings": settings})

    async def update_aliases(self, actions: list[dict]) -> dict:
        return await self.request("POST", "/_aliases", json={"actions": actions})

    async def reindex_async(self, source: str, dest: str) -> dict:
        return await self.request(
            "POST",
            "/_reindex",
            params={"wait_for_completion": "false"},
            json={"source": {"index": source}, "dest": {"index": dest}},
        )

    async def delete_index(self, index: str) -> dict:
        return await self.request("DELETE", f"/{index}")

    async def create_index(
        self, index: str, settings: dict, *, mappings: dict | None = None, aliases: dict | None = None
    ) -> dict:
        body: dict = {"settings": settings}
        if mappings is not None:
            body["mappings"] = mappings
        if aliases is not None:
            body["aliases"] = aliases
        return await self.request("PUT", f"/{index}", json=body)

    async def get_index(self, index: str) -> dict:
        """Return ``index``'s definition (aliases, mappings, settings); ``{}`` if absent in the response."""
        resp = await self.get(f"/{index}")
        return resp.get(index, {})

    async def count(self, index: str) -> int:
        resp = await self.get(f"/{index}/_count")
        return int(resp["count"])

    async def cat_nodes_detailed(self) -> list[dict]:
        node_fields = "name,node.role,ip,disk.total,disk.used,disk.used_percent"
        node_fields += ",heap.max,heap.current,heap.percent,cpu,load_1m,segments.count,version"
        return await self.get(
            "/_cat/nodes",
            params={"format": "json", "bytes": "b", "h": node_fields},
        )

    async def cat_indices_detailed(self) -> list[dict]:
        return await self.get(
            "/_cat/indices",
            params={
                "format": "json",
                "bytes": "b",
                "h": "health,status,index,pri,rep,docs.count,docs.deleted,store.size,pri.store.size",
            },
        )

    async def cat_shards_detailed(self) -> list[dict]:
        return await self.get(
            "/_cat/shards",
            params={
                "format": "json",
                "bytes": "b",
                "h": "index,shard,prirep,state,docs,store,node,segments.count",
            },
        )

    async def cat_recovery_active(self) -> list[dict]:
        return await self.get(
            "/_cat/recovery",
            params={
                "format": "json",
                "bytes": "b",
                "active_only": "true",
                "h": "index,shard,source_node,target_node,bytes_total,bytes_recovered,bytes_percent",
            },
        )

    async def cluster_settings_full(self) -> dict:
        return await self.get("/_cluster/settings", params={"include_defaults": "true", "flat_settings": "true"})

    async def put_cluster_settings(self, body: dict) -> dict:
        return await self.request("PUT", "/_cluster/settings", json=body)

    async def proxy(self, method: str, path: str, body: dict | None = None) -> dict:
        kwargs: dict = {}
        if body is not None:
            kwargs["json"] = body
        return await self.request(method, path, **kwargs)

    async def reroute(self, commands: list[dict]) -> dict:
        return await self.request("POST", "/_cluster/reroute", json={"commands": commands})

    async def get_task(self, task_id: str) -> dict:
        return await self.request("GET", f"/_tasks/{task_id}")

    async def forcemerge_async(self, index: str, *, only_expunge_deletes: bool = False) -> dict:
        params: dict[str, str] = {"wait_for_completion": "false"}
        if only_expunge_deletes:
            params["only_expunge_deletes"] = "true"
        else:
            params["max_num_segments"] = "1"
        return await self.request("POST", f"/{index}/_forcemerge", params=params)

    async def cat_shards_on_node(self, node: str) -> list[dict]:
        rows = await self.cat_shards_detailed()
        return [r for r in rows if r.get("node") == node]
