/**
 * 时区工具函数
 * 
 * 后端返回 UTC 时间字符串（无时区后缀或带 Z 后缀），
 * 需要统一转换为北京时间（UTC+8）展示。
 */

/**
 * 将后端返回的时间字符串确保为 UTC 解析
 * 兼容两种格式：
 *   - 无时区后缀: "2026-08-06T10:00:00" → 追加 Z
 *   - 已带 Z 后缀: "2026-08-06T10:00:00Z" → 原样使用
 */
export function parseUTC(value: string): Date {
  const s = value.endsWith('Z') ? value : `${value}Z`
  return new Date(s)
}

/** 格式化日期时间为北京时间，如 "2026/08/06 18:00:00" */
export function formatDateTime(value?: string | null): string {
  if (!value) return '-'
  return parseUTC(value).toLocaleString('zh-CN', { hour12: false })
}

/** 格式化日期为北京时间，如 "2026/08/06" */
export function formatDate(value?: string | null): string {
  if (!value) return '-'
  return parseUTC(value).toLocaleDateString('zh-CN')
}

/** 格式化时间为北京时间，如 "18:00:00" */
export function formatTime(value?: string | null): string {
  if (!value) return '-'
  return parseUTC(value).toLocaleTimeString('zh-CN', { hour12: false })
}

/** 格式化日期时间（短格式），如 "2026/08/06 18:00" */
export function formatDateTimeShort(value?: string | null): string {
  if (!value) return '-'
  return parseUTC(value).toLocaleString('zh-CN', {
    year: 'numeric', month: '2-digit', day: '2-digit',
    hour: '2-digit', minute: '2-digit', hour12: false,
  })
}

/** 仅格式化日期（短格式），如 "2026/08/06" */
export function formatDateShort(value?: string | null): string {
  if (!value) return '-'
  return parseUTC(value).toLocaleDateString('zh-CN', {
    year: 'numeric', month: '2-digit', day: '2-digit',
  })
}

/** 仅格式化时间（短格式），如 "18:00" */
export function formatTimeShort(value?: string | null): string {
  if (!value) return '-'
  return parseUTC(value).toLocaleTimeString('zh-CN', {
    hour: '2-digit', minute: '2-digit', hour12: false,
  })
}
