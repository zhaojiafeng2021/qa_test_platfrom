<template>
  <div class="code-editor-wrap">
    <div v-if="!readonly" class="code-editor-toolbar">
      <el-button size="small" text @click="formatCode">格式化</el-button>
    </div>
    <div ref="editorContainer" class="code-editor"></div>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted, onBeforeUnmount, watch } from 'vue'
import { ElButton } from 'element-plus'
import * as monaco from 'monaco-editor'

const props = defineProps<{
  modelValue: string
  language?: string
  readonly?: boolean
  height?: string
}>()

const emit = defineEmits<{
  (e: 'update:modelValue', value: string): void
}>()

const editorContainer = ref<HTMLDivElement>()
let editor: monaco.editor.IStandaloneCodeEditor | null = null

/** 归一化语言到 Monaco 支持的标识（javascript / python）。 */
function monacoLang(lang?: string): string {
  const l = (lang || 'javascript').toLowerCase()
  if (l === 'js' || l === 'node' || l === 'nodejs') return 'javascript'
  if (l === 'py' || l === 'python3') return 'python'
  return l
}

onMounted(() => {
  if (!editorContainer.value) return

  editor = monaco.editor.create(editorContainer.value, {
    value: props.modelValue,
    language: monacoLang(props.language),
    theme: 'vs',
    readOnly: props.readonly,
    minimap: { enabled: false },
    scrollBeyondLastLine: false,
    fontSize: 13,
    lineNumbers: 'on',
    automaticLayout: true,
    tabSize: 2,
    suggestOnTriggerCharacters: true,
    quickSuggestions: true,
  })

  editor.onDidChangeModelContent(() => {
    if (editor) {
      emit('update:modelValue', editor.getValue())
    }
  })
})

watch(() => props.modelValue, (newValue) => {
  if (editor && editor.getValue() !== newValue) {
    editor.setValue(newValue)
  }
})

watch(() => props.language, (newVal) => {
  const model = editor?.getModel()
  if (model) {
    monaco.editor.setModelLanguage(model, monacoLang(newVal))
  }
})

watch(() => props.readonly, (newVal) => {
  if (editor) {
    editor.updateOptions({ readOnly: newVal })
  }
})

/** 触发 Monaco 内置格式化（JS/JSON 有内置格式器；Python 缩进规范化）。 */
async function formatCode() {
  if (!editor) return
  editor.focus()
  await editor.getAction('editor.action.formatDocument')?.run()
}

onBeforeUnmount(() => {
  editor?.dispose()
})
</script>

<style scoped>
.code-editor-wrap {
  width: 100%;
  border: 1px solid #dcdfe6;
  border-radius: 4px;
  overflow: hidden;
}
.code-editor-toolbar {
  display: flex;
  justify-content: flex-end;
  padding: 2px 6px;
  background: #f5f7fa;
  border-bottom: 1px solid #ebeef5;
}
.code-editor {
  width: 100%;
  height: v-bind('props.height || "240px"');
  overflow: hidden;
}
</style>
