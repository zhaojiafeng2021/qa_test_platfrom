<template>
  <div ref="editorContainer" class="json-editor"></div>
</template>

<script setup lang="ts">
import { ref, onMounted, onBeforeUnmount, watch } from 'vue'
import * as monaco from 'monaco-editor'

const props = defineProps<{
  modelValue: string
  readonly?: boolean
  height?: string
}>()

const emit = defineEmits<{
  (e: 'update:modelValue', value: string): void
}>()

const editorContainer = ref<HTMLDivElement>()
let editor: monaco.editor.IStandaloneCodeEditor | null = null

onMounted(() => {
  if (!editorContainer.value) return

  editor = monaco.editor.create(editorContainer.value, {
    value: props.modelValue,
    language: 'json',
    theme: 'vs',
    readOnly: props.readonly,
    minimap: { enabled: false },
    scrollBeyondLastLine: false,
    fontSize: 13,
    lineNumbers: 'on',
    automaticLayout: true,
    formatOnPaste: true,
    formatOnType: true,
    tabSize: 2,
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
    // Auto format
    setTimeout(() => {
      editor?.getAction('editor.action.formatDocument')?.run()
    }, 100)
  }
})

watch(() => props.readonly, (newVal) => {
  if (editor) {
    editor.updateOptions({ readOnly: newVal })
  }
})

onBeforeUnmount(() => {
  editor?.dispose()
})
</script>

<style scoped>
.json-editor {
  width: 100%;
  height: v-bind('props.height || "300px"');
  border: 1px solid #dcdfe6;
  border-radius: 4px;
  overflow: hidden;
}
</style>
