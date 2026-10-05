import { useEffect, useState } from 'react'
import { fetchMcpTools } from '../lib/api'
import type { McpToolsResponse } from '../lib/types'

export function ClaudeTab() {
  const [tools, setTools] = useState<McpToolsResponse | null>(null)
  const [copied, setCopied] = useState(false)

  useEffect(() => {
    fetchMcpTools()
      .then(setTools)
      .catch(() =>
        setTools({
          status: 'offline',
          phase: 'P5',
          tools: [],
          note: 'API /mcp/tools indisponible — démarrez uvicorn.',
        }),
      )
  }, [])

  const configJson = JSON.stringify(
    tools?.claude_desktop || {
      mcpServers: {
        'ob-scanner': {
          command: '/workspace/ob-scanner-v2/.venv/bin/python',
          args: ['-m', 'app.mcp.server'],
          cwd: '/workspace/ob-scanner-v2/backend',
        },
      },
    },
    null,
    2,
  )

  const onCopy = async () => {
    try {
      await navigator.clipboard.writeText(configJson)
      setCopied(true)
      setTimeout(() => setCopied(false), 2000)
    } catch {
      /* ignore */
    }
  }

  const ready = tools?.status === 'ready'

  return (
    <div className="mx-auto max-w-3xl px-4 py-8">
      <div className="mb-2 flex items-center gap-2">
        <span
          className={
            ready
              ? 'rounded-full border border-emerald-800 bg-emerald-950/50 px-3 py-0.5 text-[11px] text-emerald-300'
              : 'rounded-full border border-zinc-700 px-3 py-0.5 text-[11px] text-zinc-500'
          }
        >
          {ready ? 'MCP prêt' : `Phase ${tools?.phase || 'P5'}`}
        </span>
        <span className="text-[11px] text-zinc-600">transport stdio · lecture / scan local</span>
      </div>
      <h2 className="text-xl font-semibold">Claude / MCP</h2>
      <p className="mt-2 text-sm text-zinc-500">
        Branchez Claude Desktop (ou Claude Code) sur le serveur MCP local. Aucun ordre n&apos;est
        passé — uniquement listage, stats, scan cache et graphiques SVG.
      </p>

      <h3 className="mt-6 text-sm font-medium text-zinc-300">Outils exposés</h3>
      <ul className="mt-2 space-y-1.5 text-sm">
        {(tools?.tools || []).map((t) => (
          <li
            key={t.name}
            className="rounded-lg border border-zinc-800 bg-zinc-900/50 px-3 py-2"
          >
            <div className="flex flex-wrap items-baseline gap-2">
              <code className="text-blue-300">{t.name}</code>
              <span className="text-zinc-600">({(t.args || []).join(', ')})</span>
            </div>
            {t.description && (
              <p className="mt-0.5 text-xs text-zinc-500">{t.description}</p>
            )}
          </li>
        ))}
        {!tools?.tools?.length && (
          <li className="text-zinc-500">Chargement du catalogue…</li>
        )}
      </ul>
      {tools?.note && <p className="mt-2 text-xs text-zinc-600">{tools.note}</p>}

      <h3 className="mt-6 text-sm font-medium text-zinc-300">Claude Desktop — snippet</h3>
      <p className="mt-1 text-xs text-zinc-500">
        Fichier de config (macOS){' '}
        <code className="text-zinc-400">~/Library/Application Support/Claude/claude_desktop_config.json</code>
        — fusionnez la clé <code className="text-zinc-400">mcpServers</code>.
      </p>
      <div className="relative mt-2">
        <pre className="overflow-x-auto rounded-xl border border-zinc-800 bg-zinc-950 p-4 text-xs text-zinc-400">
          {configJson}
        </pre>
        <button
          type="button"
          onClick={onCopy}
          className="absolute right-2 top-2 rounded-md border border-zinc-700 bg-zinc-900 px-2 py-1 text-[11px] text-zinc-300 hover:border-blue-500"
        >
          {copied ? 'Copié' : 'Copier'}
        </button>
      </div>

      <h3 className="mt-6 text-sm font-medium text-zinc-300">Test manuel</h3>
      <pre className="mt-2 overflow-x-auto rounded-xl border border-zinc-800 bg-zinc-950 p-4 text-xs text-zinc-400">
{`cd /workspace/ob-scanner-v2
.venv/bin/python scripts/mcp_smoke.py
# ou stdio :
.venv/bin/python -m app.mcp.server   # cwd=backend, PYTHONPATH=backend`}
      </pre>
    </div>
  )
}
