// 覆盖率任务进度 WebSocket 客户端
// 特性：
// - 自动重连（指数退避，最大 5 次后降级到轮询）
// - 客户端 ping 保活（25s 一次，配合服务端 30s 空闲超时）
// - 降级轮询：WS 连接失败 5 次后改用 setInterval 轮询 listRunReports
import { buildCoverageWsUrl, listRunReports } from '@/api/coverage'
import type { JavaCoverageReport, WsMessage } from '@/types/coverage'

export interface ProgressHandlers {
  onMessage: (msg: WsMessage) => void
  onPollingReports?: (reports: JavaCoverageReport[]) => void
  onStateChange?: (state: 'connecting' | 'open' | 'reconnecting' | 'polling' | 'closed') => void
}

const MAX_RETRY = 5
const PING_INTERVAL_MS = 25_000
const POLLING_INTERVAL_MS = 5_000

export class CoverageProgressClient {
  private taskId: number
  private runId: number | null = null
  private handlers: ProgressHandlers

  private ws: WebSocket | null = null
  private retryCount = 0
  private pingTimer: number | null = null
  private reconnectTimer: number | null = null
  private pollingTimer: number | null = null
  private stopped = false

  constructor(taskId: number, handlers: ProgressHandlers) {
    this.taskId = taskId
    this.handlers = handlers
  }

  /** 建立连接（如果已有连接则先断开） */
  connect(runId?: number): void {
    this.runId = runId ?? this.runId
    this.stopped = false
    this._cleanupWs()
    this._open()
  }

  /** 主动断开（组件卸载时调用） */
  disconnect(): void {
    this.stopped = true
    this._cleanupWs()
    this._stopPolling()
    this.handlers.onStateChange?.('closed')
  }

  /** 外部控制：切换 runId（新一轮 trigger 后调用） */
  setRunId(runId: number): void {
    this.runId = runId
  }

  // ─── 内部实现 ───

  private _open(): void {
    if (this.stopped) return
    this.handlers.onStateChange?.(this.retryCount === 0 ? 'connecting' : 'reconnecting')

    const url = buildCoverageWsUrl(this.taskId)
    let ws: WebSocket
    try {
      ws = new WebSocket(url)
    } catch (e) {
      console.error('[CoverageWS] construct failed', e)
      this._scheduleReconnect()
      return
    }
    this.ws = ws

    ws.onopen = () => {
      console.info('[CoverageWS] open', url)
      this.retryCount = 0
      this.handlers.onStateChange?.('open')
      this._startPing()
    }
    ws.onmessage = (ev) => {
      try {
        const msg = JSON.parse(ev.data) as WsMessage
        // snapshot 时把 run_id 同步回来，供降级轮询使用
        if (msg.type === 'snapshot' && msg.run_id) {
          this.runId = msg.run_id
        }
        this.handlers.onMessage(msg)
      } catch (e) {
        console.warn('[CoverageWS] bad message', ev.data, e)
      }
    }
    ws.onerror = (ev) => {
      console.warn('[CoverageWS] error', ev)
    }
    ws.onclose = (ev) => {
      console.info('[CoverageWS] close', ev.code, ev.reason)
      this._stopPing()
      if (this.stopped) return
      this._scheduleReconnect()
    }
  }

  private _startPing(): void {
    this._stopPing()
    this.pingTimer = window.setInterval(() => {
      if (this.ws && this.ws.readyState === WebSocket.OPEN) {
        try {
          this.ws.send(JSON.stringify({ type: 'ping' }))
        } catch (e) {
          console.warn('[CoverageWS] ping send failed', e)
        }
      }
    }, PING_INTERVAL_MS)
  }

  private _stopPing(): void {
    if (this.pingTimer !== null) {
      window.clearInterval(this.pingTimer)
      this.pingTimer = null
    }
  }

  private _scheduleReconnect(): void {
    if (this.stopped) return
    if (this.retryCount >= MAX_RETRY) {
      console.warn(`[CoverageWS] retry ${MAX_RETRY} times exhausted, fallback to polling`)
      this._startPolling()
      return
    }
    // 指数退避：1s, 2s, 4s, 8s, 16s
    const delay = Math.min(1000 * 2 ** this.retryCount, 16_000)
    this.retryCount += 1
    this.handlers.onStateChange?.('reconnecting')
    this.reconnectTimer = window.setTimeout(() => {
      this.reconnectTimer = null
      this._open()
    }, delay)
  }

  private _startPolling(): void {
    if (this.pollingTimer !== null) return
    this.handlers.onStateChange?.('polling')
    const tick = async () => {
      if (this.stopped || this.runId == null) return
      try {
        const reports = await listRunReports(this.runId)
        this.handlers.onPollingReports?.(reports)
      } catch (e) {
        console.warn('[CoverageWS] polling failed', e)
      }
    }
    void tick()
    this.pollingTimer = window.setInterval(tick, POLLING_INTERVAL_MS)
  }

  private _stopPolling(): void {
    if (this.pollingTimer !== null) {
      window.clearInterval(this.pollingTimer)
      this.pollingTimer = null
    }
  }

  private _cleanupWs(): void {
    this._stopPing()
    if (this.reconnectTimer !== null) {
      window.clearTimeout(this.reconnectTimer)
      this.reconnectTimer = null
    }
    if (this.ws) {
      try {
        this.ws.onopen = this.ws.onmessage = this.ws.onerror = this.ws.onclose = null
        this.ws.close()
      } catch {
        // ignore
      }
      this.ws = null
    }
  }
}
