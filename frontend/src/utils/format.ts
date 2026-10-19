/**
 * 统一格式化工具
 */

/**
 * 格式化时间为北京时间 (UTC+8)
 * 后端返回的是 UTC 时间（无时区标记），前端统一加 Z 解析后转为北京时间显示
 * @param value ISO datetime string from backend (e.g. "2026-07-30T06:30:45")
 * @param style 'short' = "07-30 14:30", 'datetime' = "2026-07-30 14:30", 'full' = "2026-07-30 14:30:45"
 */
export function formatTime(value: string | null | undefined, style: 'short' | 'datetime' | 'full' = 'short'): string {
  if (!value) return '—'
  const iso = value.endsWith('Z') ? value : value + 'Z'
  const d = new Date(iso)
  if (isNaN(d.getTime())) return '—'

  // 转为北京时间 (UTC+8)
  const beijing = new Date(d.getTime() + 8 * 60 * 60 * 1000)
  const Y = beijing.getUTCFullYear()
  const M = String(beijing.getUTCMonth() + 1).padStart(2, '0')
  const D = String(beijing.getUTCDate()).padStart(2, '0')
  const h = String(beijing.getUTCHours()).padStart(2, '0')
  const m = String(beijing.getUTCMinutes()).padStart(2, '0')
  const s = String(beijing.getUTCSeconds()).padStart(2, '0')

  if (style === 'full') return `${Y}-${M}-${D} ${h}:${m}:${s}`
  if (style === 'datetime') return `${Y}-${M}-${D} ${h}:${m}`
  return `${M}-${D} ${h}:${m}`
}
