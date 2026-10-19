/**
 * 性能监控工具
 */

export class PerformanceMonitor {
  private marks: Map<string, number> = new Map()

  /**
   * 开始计时
   */
  start(label: string): void {
    this.marks.set(label, performance.now())
  }

  /**
   * 结束计时并输出结果
   */
  end(label: string): number {
    const startTime = this.marks.get(label)
    if (!startTime) {
      console.warn(`[性能] 未找到标记: ${label}`)
      return 0
    }

    const duration = performance.now() - startTime
    this.marks.delete(label)

    // 根据耗时设置不同颜色
    const style = duration < 100 ? 'color: #67C23A' :
                  duration < 500 ? 'color: #E6A23C' :
                  'color: #F56C6C'

    console.log(`%c[性能] ${label}: ${duration.toFixed(2)}ms`, style)
    return duration
  }

  /**
   * 测量异步函数执行时间
   */
  async measure<T>(label: string, fn: () => Promise<T>): Promise<T> {
    this.start(label)
    try {
      const result = await fn()
      this.end(label)
      return result
    } catch (error) {
      this.end(label)
      throw error
    }
  }

  /**
   * 测量同步函数执行时间
   */
  measureSync<T>(label: string, fn: () => T): T {
    this.start(label)
    try {
      const result = fn()
      this.end(label)
      return result
    } catch (error) {
      this.end(label)
      throw error
    }
  }
}

// 全局单例
export const perfMonitor = new PerformanceMonitor()

/**
 * 监控 Vue computed 性能
 */
export function logComputedTime(name: string, fn: () => any) {
  const start = performance.now()
  const result = fn()
  const duration = performance.now() - start

  if (duration > 10) {
    console.warn(`[Computed 慢] ${name}: ${duration.toFixed(2)}ms`)
  }

  return result
}
