<template>
  <pre class="json-view" v-html="html"></pre>
</template>

<script setup lang="ts">
import { computed } from 'vue'

/**
 * 只读 JSON 展示：语法高亮（key/string/number/boolean/null 分色），自动格式化缩进。
 * 相比纯 <pre> 文本更易读；非 JSON 内容（如 HTML 错误页）原样转义展示，不做高亮。
 * 轻量实现（无 Monaco），适合在执行详情等列表/折叠面板里多实例渲染。
 */
const props = defineProps<{ value: unknown }>()

function escapeHtml(text: string): string {
  return text
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
}

// 归一化为字符串：对象美化缩进；字符串尝试 parse 后美化，失败原样返回。
function toText(v: unknown): { text: string; isJson: boolean } {
  if (v === null || v === undefined) return { text: '', isJson: false }
  if (typeof v === 'string') {
    try {
      return { text: JSON.stringify(JSON.parse(v), null, 2), isJson: true }
    } catch {
      return { text: v, isJson: false }
    }
  }
  try {
    return { text: JSON.stringify(v, null, 2), isJson: true }
  } catch {
    return { text: String(v), isJson: false }
  }
}

const html = computed(() => {
  const { text, isJson } = toText(props.value)
  const escaped = escapeHtml(text)
  if (!isJson) return escaped
  // 先转义再套色，避免 XSS：spans 只包裹我们自己识别的 token。
  return escaped.replace(
    /("(\\u[a-zA-Z0-9]{4}|\\[^u]|[^\\"])*"(\s*:)?|\b(true|false)\b|\bnull\b|-?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?)/g,
    (match) => {
      let cls = 'jv-num'
      if (/^"/.test(match)) {
        cls = /:$/.test(match) ? 'jv-key' : 'jv-str'
      } else if (/^(true|false)$/.test(match)) {
        cls = 'jv-bool'
      } else if (match === 'null') {
        cls = 'jv-null'
      }
      return `<span class="${cls}">${match}</span>`
    },
  )
})
</script>

<style scoped>
.json-view {
  background: #f7f8fa;
  border: 1px solid #ebeef5;
  border-radius: 4px;
  padding: 8px 10px;
  font-family: 'SFMono-Regular', Consolas, 'Liberation Mono', Menlo, monospace;
  font-size: 12px;
  line-height: 1.6;
  color: #303133;
  max-height: 320px;
  overflow: auto;
  margin: 0;
  white-space: pre-wrap;
  word-break: break-all;
}

.json-view :deep(.jv-key) { color: #c41d7f; }
.json-view :deep(.jv-str) { color: #2f9e44; }
.json-view :deep(.jv-num) { color: #1971c2; }
.json-view :deep(.jv-bool) { color: #e8590c; font-weight: 600; }
.json-view :deep(.jv-null) { color: #868e96; font-style: italic; }
</style>
