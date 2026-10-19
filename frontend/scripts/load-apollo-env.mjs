/**
 * 构建/启动前从 Apollo 拉取前端配置，写入 frontend/.env.local。
 *
 * 设计
 * ====
 * - Vite 是「构建时」注入 import.meta.env，运行时无法直接读 Apollo。
 *   因此在 dev/build 之前跑本脚本，把 Apollo 里的 VITE_* 配置落到 .env.local，
 *   Vite 自动加载 .env.local 且优先级高于 .env（即 Apollo 覆盖默认值）。
 *   key 与之前 .env 完全一致（如 VITE_API_BASE_URL）。
 *   仅在设置了 APOLLO_URL 时才写 .env.local，避免覆盖本地开发者的文件。
 * - Apollo 连接信息由部署平台（Zadig / K8s）通过环境变量注入，命名与后端一致：
 *     APOLLO_URL   Apollo 配置服务地址，必填才启用
 *     APP_NAME     作为 Apollo AppId（默认回退）
 *     DEPLOY_ENV   作为 Apollo cluster（默认回退）
 *   可选覆盖：
 *     APOLLO_APP_ID / APOLLO_CLUSTER / APOLLO_NAMESPACE(逗号分隔) / APOLLO_SECRET / APOLLO_TIMEOUT
 *
 * 容错
 * ====
 * - 未设置 APOLLO_URL 时直接跳过（本地开发用现有 .env），不报错、退出码 0。
 * - Apollo 拉取失败时打印告警并跳过，绝不阻塞 dev/build。
 * - 只写入 VITE_ 前缀的 key（Vite 只会暴露这些给客户端，避免把后端密钥打进前端产物）。
 */
import { createHmac } from 'node:crypto'
import { writeFileSync } from 'node:fs'
import { resolve, dirname } from 'node:path'
import { fileURLToPath } from 'node:url'

const __dirname = dirname(fileURLToPath(import.meta.url))
// 写入 .env.local：Vite 自动加载且优先级高于 .env（Apollo 覆盖默认值）。
// 仅在启用 Apollo 时写入，未启用时不动该文件（保护开发者本地覆盖）。
const OUT_FILE = resolve(__dirname, '..', '.env.local')

function sign(timestamp, pathWithQuery, secret) {
  const stringToSign = `${timestamp}\n${pathWithQuery}`
  return createHmac('sha1', secret).update(stringToSign).digest('base64')
}

function authHeaders(appId, secret, path) {
  if (!secret) return {}
  const timestamp = String(Date.now())
  return {
    Authorization: `Apollo ${appId}:${sign(timestamp, path, secret)}`,
    Timestamp: timestamp,
  }
}

async function fetchNamespace(baseUrl, appId, cluster, namespace, secret, timeoutMs) {
  const path = `/configs/${encodeURIComponent(appId)}/${encodeURIComponent(cluster)}/${encodeURIComponent(namespace)}`
  const url = `${baseUrl}${path}`
  const controller = new AbortController()
  const timer = setTimeout(() => controller.abort(), timeoutMs)
  try {
    const resp = await fetch(url, { headers: authHeaders(appId, secret, path), signal: controller.signal })
    if (!resp.ok) throw new Error(`HTTP ${resp.status}`)
    const data = await resp.json()
    const configs = data && data.configurations
    return configs && typeof configs === 'object' ? configs : {}
  } finally {
    clearTimeout(timer)
  }
}

async function main() {
  const baseUrl = (process.env.APOLLO_URL || '').trim().replace(/\/+$/, '')
  if (!baseUrl) {
    console.log('[apollo] APOLLO_URL 未设置，跳过 Apollo，使用现有 .env（不改动 .env.local）')
    return
  }

  const appId = (process.env.APOLLO_APP_ID || process.env.APP_NAME || 'qa-platform').trim()
  const cluster = (process.env.APOLLO_CLUSTER || process.env.DEPLOY_ENV || 'default').trim()
  const namespaces = (process.env.APOLLO_NAMESPACE || 'application')
    .split(',')
    .map((s) => s.trim())
    .filter(Boolean)
  const secret = (process.env.APOLLO_SECRET || '').trim()
  const timeoutMs = Number(process.env.APOLLO_TIMEOUT || '5') * 1000

  console.log(`[apollo] loading url=${baseUrl} app_id=${appId} cluster=${cluster} namespaces=${JSON.stringify(namespaces)}`)

  const merged = {}
  for (const namespace of namespaces) {
    try {
      const configs = await fetchNamespace(baseUrl, appId, cluster, namespace, secret, timeoutMs)
      Object.assign(merged, configs)
      console.log(`[apollo] namespace '${namespace}' 拉取 ${Object.keys(configs).length} 个 key`)
    } catch (err) {
      console.warn(`[apollo] WARN 命名空间 '${namespace}' 拉取失败，已跳过: ${err && err.message}`)
    }
  }

  // 只保留 VITE_ 前缀（其余是后端配置，不应打进前端产物）
  const lines = []
  const kept = []
  for (const [key, value] of Object.entries(merged)) {
    if (!key.startsWith('VITE_')) continue
    const safe = String(value).replace(/\n/g, '\\n')
    lines.push(`${key}=${safe}`)
    kept.push(key)
  }
  writeFileSync(OUT_FILE, lines.join('\n') + (lines.length ? '\n' : ''))
  console.log(`[apollo] 写入 ${OUT_FILE}，共 ${kept.length} 个 VITE_ key: ${JSON.stringify(kept.sort())}`)
}

main().catch((err) => {
  // 兜底：绝不因 Apollo 阻塞构建（不改动 .env.local，保留已有值）
  console.warn(`[apollo] WARN 未预期错误，已跳过: ${err && err.message}`)
})
