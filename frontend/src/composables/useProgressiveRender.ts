import { ref, computed, watch, onUnmounted, type Ref, type ComputedRef } from 'vue'

/**
 * 渐进式分帧渲染：先渲染一小批数据，之后通过 requestAnimationFrame
 * 分批追加剩余数据，避免一次性渲染大列表长时间阻塞主线程导致页面卡顿。
 *
 * @param source 源数据（响应式），变化时自动重置并重新分批渲染
 * @param options.initial 首批渲染数量（应能填满首屏）
 * @param options.step 每帧追加数量
 */
export function useProgressiveRender<T>(
  source: Ref<T[]> | ComputedRef<T[]>,
  options: { initial?: number; step?: number } = {},
) {
  const initial = options.initial ?? 30
  const step = options.step ?? 60
  const limit = ref(0)
  let raf = 0

  function grow() {
    const total = source.value.length
    if (limit.value >= total) {
      raf = 0
      return
    }
    limit.value = Math.min(limit.value + step, total)
    raf = requestAnimationFrame(grow)
  }

  function reset() {
    if (raf) {
      cancelAnimationFrame(raf)
      raf = 0
    }
    const total = source.value.length
    limit.value = Math.min(initial, total)
    if (limit.value < total) {
      raf = requestAnimationFrame(grow)
    }
  }

  watch(source, reset, { immediate: true })
  onUnmounted(() => {
    if (raf) cancelAnimationFrame(raf)
  })

  const visible = computed(() => source.value.slice(0, limit.value))
  const done = computed(() => limit.value >= source.value.length)

  return { visible, done, limit }
}
