import httpx


class ESClient:
    """Async HTTP client for Elasticsearch. No elasticsearch-py dependency."""

    def __init__(self, base_url: str, username: str, password: str, verify_ssl: bool = True):
        self._base_url = base_url.rstrip("/")
        self._auth = (username, password) if username else None
        self._verify_ssl = verify_ssl

    def _build_url(self, path: str) -> str:
        return f"{self._base_url}{path}"

    async def request(self, method: str, path: str, **kwargs) -> dict:
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

    async def cat_indices(self) -> list[dict]:
        return await self.get("/_cat/indices", params={"format": "json", "bytes": "b"})

    async def cat_shards(self) -> list[dict]:
        return await self.get("/_cat/shards", params={"format": "json", "bytes": "b"})

    async def cat_nodes(self) -> list[dict]:
        return await self.get("/_cat/nodes", params={"format": "json"})

    async def cluster_settings(self) -> dict:
        return await self.get("/_cluster/settings", params={"include_defaults": "false"})

    async def index_health(self, index: str) -> dict:
        return await self.get(f"/_cluster/health/{index}", params={"timeout": "5s"})

    async def set_index_settings(self, index: str, settings: dict) -> dict:
        return await self.put(f"/{index}/_settings", json={"settings": settings})

    async def shrink_index(self, source: str, target: str, settings: dict) -> dict:
        return await self.post(f"/{source}/_shrink/{target}", json={"settings": settings})

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
                "h": "health,status,index,pri,rep,docs.count,store.size,pri.store.size",
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
