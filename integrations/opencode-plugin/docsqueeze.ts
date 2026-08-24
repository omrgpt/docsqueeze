/**
 * docsqueeze auto-activation plugin for opencode.
 *
 * 1. Hooks `tool.execute.before` on the built-in `read` tool: when the target
 *    is a supported document (PDF, DOCX, XLSX, ...), runs the zero-dependency
 *    Python engine and transparently rewrites the read target to a compact
 *    text sidecar next to the source. Any failure falls back silently to
 *    native behavior.
 *
 * 2. Registers a `docsqueeze` tool for direct, targeted extraction
 *    (--pages / --sheets / budget / --full / JSON).
 *
 * Auto-discovered from .opencode/plugins/ - no config changes required.
 */

import { existsSync, writeFileSync } from "node:fs"
import { basename, dirname, extname, isAbsolute, join, resolve } from "node:path"
import { fileURLToPath } from "node:url"

import { tool } from "@opencode-ai/plugin"

const DOC_EXTENSIONS = new Set([
  ".pdf", ".docx", ".xlsx", ".pptx", ".odt", ".ods", ".odp", ".epub",
  ".rtf", ".html", ".htm", ".xml", ".csv", ".tsv", ".json", ".jsonl",
  ".ndjson", ".toml", ".ini", ".cfg", ".conf", ".eml", ".ipynb", ".db",
  ".sqlite", ".sqlite3", ".log",
])

const MAX_AUTO_TOKENS = 24000

const PLUGIN_DIR = dirname(fileURLToPath(import.meta.url))

function findEngine(): string | null {
  const candidates: string[] = []
  let dir = PLUGIN_DIR
  for (let i = 0; i < 6; i++) {
    candidates.push(
      join(dir, ".agents", "skills", "docsqueeze", "scripts", "docsqueeze.py"),
      join(dir, "docsqueeze-repo", "docsqueeze", "core.py"),
    )
    const parent = dirname(dir)
    if (parent === dir) break
    dir = parent
  }
  for (const c of candidates) {
    if (existsSync(c)) return c
  }
  return null
}

function pythonCandidates(): string[] {
  const env = process.env.DOCSQUEEZE_PYTHON
  const list: string[] = env ? [env] : []
  if (process.platform === "win32") list.push("python", "py")
  else list.push("python3", "python")
  return list
}

function toAbs(p: string, base: string): string {
  return isAbsolute(p) ? p : resolve(base, p)
}

type ShellFn = (
  strings: TemplateStringsArray,
  ...vals: unknown[]
) => { quiet(): any; nothrow(): any }

export const DocsqueezePlugin = async ({
  directory,
  $,
}: {
  directory: string
  $: ShellFn
}) => {
  const engine = findEngine()
  let pythonBin: string | null = null
  let runtimeVerified = false

  async function ensureRuntime(): Promise<boolean> {
    if (!engine) return false
    if (runtimeVerified && pythonBin) return true
    for (const bin of pythonCandidates()) {
      try {
        const probe = await $`${bin} -c "print(1)"`.quiet().nothrow()
        if ((probe.exitCode ?? 1) === 0 && String(probe.stdout ?? "").trim() === "1") {
          pythonBin = bin
          runtimeVerified = true
          return true
        }
      } catch {
        // try next candidate
      }
    }
    return false
  }

  async function runEngine(
    args: string[],
    timeoutMs = 120000,
  ): Promise<{ ok: boolean; stdout: string; stderr: string }> {
    if (!(await ensureRuntime()) || !pythonBin) {
      return { ok: false, stdout: "", stderr: "docsqueeze: no usable python runtime" }
    }
    try {
      const res = await $`${pythonBin} ${engine} ${args}`.quiet().nothrow().timeout(timeoutMs)
      const code = res.exitCode ?? 1
      const stdout = String(res.stdout ?? "")
      const stderr = String(res.stderr ?? "")
      if (code !== 0 && stdout.trim() === "") {
        return { ok: false, stdout, stderr }
      }
      return { ok: code === 0, stdout, stderr }
    } catch (e: unknown) {
      return { ok: false, stdout: "", stderr: String(e) }
    }
  }

  return {
    "tool.execute.before": async (
      input: { tool: string },
      output: { args: Record<string, unknown> },
    ) => {
      try {
        if (input.tool !== "read" || !engine) return
        const filePath = output.args?.filePath
        if (typeof filePath !== "string" || filePath.length === 0) return
        const ext = extname(filePath).toLowerCase()
        if (!DOC_EXTENSIONS.has(ext)) return
        if (basename(filePath).includes(".dsq.")) return

        const abs = toAbs(filePath, directory)
        if (!existsSync(abs)) return

        const result = await runEngine([
          abs,
          "--max-tokens",
          String(MAX_AUTO_TOKENS),
        ])
        if (!result.ok || result.stdout.trim() === "") return

        const sidecar = join(dirname(abs), `.${basename(abs)}.dsq.md`)
        writeFileSync(sidecar, result.stdout, { encoding: "utf-8", flag: "w" })
        output.args.filePath = sidecar
      } catch {
        // Silent fallback to native read behavior.
      }
    },

    tool: {
      docsqueeze: tool({
        description:
          "Read a document (PDF, DOCX, XLSX, PPTX, ODT/ODS/ODP, EPUB, RTF, HTML, XML, CSV, JSON, TOML, INI, EML, IPYNB, SQLite, logs, text) as token-efficient page/sheet/slide-anchored text within a token budget. Prefer pages/sheets for targeted lookups; use full only when explicitly needed.",
        args: {
          path: tool.schema.string().describe("Path to the document file"),
          pages: tool.schema.string().optional().describe("PDF page selection, e.g. '1-5,8'"),
          sheets: tool.schema
            .string()
            .optional()
            .describe("xlsx/ods sheet selection by name or index, e.g. 'Summary,3'"),
          max_tokens: tool.schema
            .number()
            .optional()
            .describe("token budget override (default 24000)"),
          full: tool.schema.boolean().optional().describe("disable truncation (expensive)"),
          json: tool.schema
            .boolean()
            .optional()
            .describe("wrap output in a JSON envelope with metadata"),
        },
        async execute(args, context) {
          const cliArgs: string[] = [toAbs(args.path, context.directory)]
          if (args.pages) cliArgs.push("--pages", args.pages)
          if (args.sheets) cliArgs.push("--sheets", args.sheets)
          if (typeof args.max_tokens === "number") {
            cliArgs.push("--max-tokens", String(args.max_tokens))
          }
          if (args.full) cliArgs.push("--full")
          if (args.json) cliArgs.push("--json")
          const result = await runEngine(cliArgs)
          if (!result.ok && result.stdout.trim() === "") {
            return `docsqueeze failed: ${result.stderr || "unknown error"}`
          }
          return result.stdout
        },
      }),
    },
  }
}

export default DocsqueezePlugin
