<template>
  <div v-if="visible" class="help-guide-overlay" @click="close">
    <div class="help-guide-panel" @click.stop>
      <div class="guide-header">
        <h3>{{ title }}</h3>
        <button class="guide-close" @click="close">
          <el-icon><Close /></el-icon>
        </button>
      </div>
      <div class="guide-body">
        <slot></slot>
      </div>
      <div class="guide-footer">
        <el-checkbox v-model="dontShowAgain">不再显示此提示</el-checkbox>
        <el-button type="primary" @click="close">知道了</el-button>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { Close } from '@element-plus/icons-vue'

const props = defineProps<{
  guideKey: string
  title: string
}>()

const visible = ref(false)
const dontShowAgain = ref(false)

onMounted(() => {
  const storageKey = `qa-guide-dismissed-${props.guideKey}`
  if (!localStorage.getItem(storageKey)) {
    visible.value = true
  }
})

function close() {
  if (dontShowAgain.value) {
    const storageKey = `qa-guide-dismissed-${props.guideKey}`
    localStorage.setItem(storageKey, '1')
  }
  visible.value = false
}
</script>

<style scoped>
.help-guide-overlay {
  position: fixed;
  inset: 0;
  background: rgba(15, 25, 41, 0.55);
  backdrop-filter: blur(4px);
  z-index: 2000;
  display: flex;
  align-items: center;
  justify-content: center;
  animation: fade-in 0.25s ease;
}

@keyframes fade-in {
  from {
    opacity: 0;
  }
  to {
    opacity: 1;
  }
}

.help-guide-panel {
  background: #fff;
  border-radius: 12px;
  box-shadow: 0 8px 32px rgba(59, 123, 245, 0.13);
  width: 620px;
  max-width: 92vw;
  max-height: 85vh;
  display: flex;
  flex-direction: column;
  animation: slide-up 0.3s ease;
}

@keyframes slide-up {
  from {
    opacity: 0;
    transform: translateY(30px);
  }
  to {
    opacity: 1;
    transform: translateY(0);
  }
}

.guide-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 18px 22px;
  border-bottom: 1px solid var(--line);
}

.guide-header h3 {
  font-size: 17px;
  font-weight: 700;
  color: var(--txt);
}

.guide-close {
  background: none;
  border: 0;
  color: var(--txt3);
  font-size: 20px;
  padding: 4px 8px;
  border-radius: 6px;
  cursor: pointer;
  transition: all 0.15s;
}

.guide-close:hover {
  background: var(--line2);
  color: var(--txt);
}

.guide-body {
  padding: 24px;
  overflow-y: auto;
  flex: 1;
}

.guide-footer {
  padding: 16px 22px;
  border-top: 1px solid var(--line);
  display: flex;
  align-items: center;
  justify-content: space-between;
}
</style>
