import { useState } from "react"
import { useClusterContext } from "@/context/ClusterContext"
import { useRestProxy } from "@/api/rest"

const METHODS = ["GET", "POST", "PUT", "DELETE"]

const PRESETS = [
  { label: "Cluster Health", method: "GET", path: "/_cluster/health" },
  { label: "Cat Indices", method: "GET", path: "/_cat/indices?format=json&bytes=b" },
  { label: "Cat Nodes", method: "GET", path: "/_cat/nodes?format=json" },
  { label: "Cat Shards", method: "GET", path: "/_cat/shards?format=json&bytes=b" },
  { label: "Cluster Settings", method: "GET", path: "/_cluster/settings?flat_settings=true" },
]

export default function Rest() {
  const { activeCluster } = useClusterContext()
  const proxy = useRestProxy(activeCluster?.id ?? null)
  const [method, setMethod] = useState("GET")
  const [path, setPath] = useState("/_cluster/health")
  const [body, setBody] = useState("")

  if (!activeCluster) {
    return <div className="flex items-center justify-center h-full text-eo-stone">Select a cluster</div>
  }

  // On a read-only cluster only read verbs are permitted; the backend rejects everything else with 403.
  const isReadVerb = method === "GET" || method === "HEAD"
  const writeBlocked = !!activeCluster.read_only && !isReadVerb

  const handleSubmit = () => {
    if (writeBlocked) return
    proxy.mutate({ method, path, body })
  }

  const handlePreset = (preset: (typeof PRESETS)[number]) => {
    setMethod(preset.method)
    setPath(preset.path)
    setBody("")
  }

  const responseText = proxy.data
    ? JSON.stringify(proxy.data, null, 2)
    : proxy.error
      ? `Error: ${proxy.error.message}`
      : ""

  return (
    <div className="flex flex-col h-full">
      {/* Request area */}
      <div className="p-4 border-b border-eo-border space-y-3">
        {/* Presets */}
        <div className="flex items-center gap-2">
          <span className="text-xs text-eo-muted font-mono">Presets:</span>
          {PRESETS.map((p) => (
            <button
              key={p.label}
              onClick={() => handlePreset(p)}
              className="px-2 py-1 text-[10px] font-mono text-eo-stone border border-eo-border rounded hover:text-eo-cream hover:border-eo-amber/40 transition-colors"
            >{p.label}</button>
          ))}
        </div>

        {/* Method + URL + Send */}
        <div className="flex items-center gap-2">
          <select
            value={method}
            onChange={(e) => setMethod(e.target.value)}
            className="bg-eo-bg border border-eo-border rounded px-2 py-2 text-sm font-mono text-eo-amber focus:border-eo-amber focus:outline-none"
          >
            {METHODS.map((m) => <option key={m} value={m}>{m}</option>)}
          </select>
          <input
            type="text"
            value={path}
            onChange={(e) => setPath(e.target.value)}
            onKeyDown={(e) => { if (e.key === "Enter") handleSubmit() }}
            className="flex-1 bg-eo-bg border border-eo-border rounded px-3 py-2 text-sm font-mono text-eo-cream placeholder:text-eo-muted focus:border-eo-amber focus:outline-none"
            placeholder="/_cluster/health"
          />
          <button
            onClick={handleSubmit}
            disabled={proxy.isPending || writeBlocked}
            title={writeBlocked ? "Cluster is read-only — only GET/HEAD requests are allowed" : undefined}
            className="px-4 py-2 bg-eo-amber text-eo-bg rounded text-sm font-semibold hover:bg-eo-light-amber transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
          >{proxy.isPending ? "Sending..." : "Send"}</button>
        </div>

        {writeBlocked && (
          <p className="text-xs text-eo-brick font-mono">
            This cluster is read-only. Only GET/HEAD requests are allowed.
          </p>
        )}

        {/* Body editor (for POST/PUT) */}
        {(method === "POST" || method === "PUT") && (
          <textarea
            value={body}
            onChange={(e) => setBody(e.target.value)}
            placeholder='{"index": {"number_of_replicas": 1}}'
            className="w-full h-24 bg-eo-bg border border-eo-border rounded px-3 py-2 text-xs font-mono text-eo-cream placeholder:text-eo-muted focus:border-eo-amber focus:outline-none resize-y"
          />
        )}
      </div>

      {/* Response area */}
      <div className="flex-1 overflow-auto p-4">
        {proxy.isPending && (
          <div className="text-eo-stone text-sm font-mono">Executing request...</div>
        )}
        {responseText && (
          <pre className="text-xs font-mono text-eo-cream whitespace-pre-wrap break-words leading-relaxed">
            {responseText}
          </pre>
        )}
        {!proxy.isPending && !responseText && (
          <div className="flex items-center justify-center h-full text-eo-muted text-sm">
            Send a request to see the response
          </div>
        )}
      </div>
    </div>
  )
}
