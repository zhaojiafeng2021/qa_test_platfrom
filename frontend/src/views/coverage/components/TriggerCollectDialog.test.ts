// @vitest-environment happy-dom
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount, type VueWrapper } from '@vue/test-utils'
import ElementPlus from 'element-plus'
import * as api from '@/api/coverage'
import TriggerCollectDialog from './TriggerCollectDialog.vue'
import type { CoverageTask, RepoCommit, TriggerPayload } from '@/types/coverage'

vi.mock('@/api/coverage', () => ({
  listRepoCommits: vi.fn(),
}))

const COMMITS: RepoCommit[] = [
  { sha: 'a'.repeat(40), short_sha: 'aaaaaaa', author: 'dev', committed_at: '2026-10-22T10:00:00+08:00', subject: 'feat: order' },
  { sha: 'b'.repeat(40), short_sha: 'bbbbbbb', author: 'dev', committed_at: '2026-10-21T10:00:00+08:00', subject: 'fix: pay' },
]

function makeTask(patch: Partial<CoverageTask> = {}): CoverageTask {
  return {
    id: 1, project_id: 1, name: 't', repo_id: 7, repo_url: 'https://git.example.com/a.git',
    services: [{ name: 'order', path: 'services/order' }], branch: 'master',
    collection_mode: 'unittest', runtime_config: null, owner_id: 1, status: 'completed',
    created_at: '', updated_at: '', ...patch,
  }
}

type Vm = {
  source: string
  commitSha: string
  keyword: string
  filteredCommits: RepoCommit[]
  onOpen: () => void
  submit: () => void
}

const mounted: VueWrapper[] = []

async function mountDialog(task: CoverageTask, mismatchServices: string[] = []) {
  // 不 stub teleport：el-dialog + teleport stub 在 happy-dom 下会让 ElSelect 递归更新；弹窗内容渲染到 body
  const wrapper = mount(TriggerCollectDialog, {
    props: { modelValue: true, task, projectId: 1, mismatchServices },
    global: { plugins: [ElementPlus] },
    attachTo: document.body,
  })
  mounted.push(wrapper)
  const vm = wrapper.vm as unknown as Vm
  vm.onOpen()
  await flushPromises()
  return { wrapper, vm }
}

describe('TriggerCollectDialog', () => {
  beforeEach(() => {
    vi.mocked(api.listRepoCommits).mockReset().mockResolvedValue(COMMITS)
  })
  afterEach(() => {
    mounted.splice(0).forEach((w) => w.unmount())
  })

  it('默认选中分支最新提交并随触发提交', async () => {
    const { wrapper, vm } = await mountDialog(makeTask())
    expect(api.listRepoCommits).toHaveBeenCalledWith(1, 7, 'master')
    expect(vm.commitSha).toBe(COMMITS[0].sha)
    vm.submit()
    const [payload] = wrapper.emitted('confirm')![0] as [TriggerPayload]
    expect(payload).toEqual({ source: 'unittest', commit_sha: COMMITS[0].sha })
  })

  it('不在下拉列表中的 sha 不会提交', async () => {
    const { wrapper, vm } = await mountDialog(makeTask())
    vm.commitSha = 'c'.repeat(40)
    vm.submit()
    const [payload] = wrapper.emitted('confirm')![0] as [TriggerPayload]
    expect(payload.commit_sha).toBeUndefined()
  })

  it('按 sha 前缀或说明筛选，只在已加载列表中', async () => {
    const { vm } = await mountDialog(makeTask())
    vm.keyword = 'bbb'
    expect(vm.filteredCommits.map((c) => c.short_sha)).toEqual(['bbbbbbb'])
    vm.keyword = 'ORDER'
    expect(vm.filteredCommits.map((c) => c.short_sha)).toEqual(['aaaaaaa'])
    vm.keyword = 'zzz'
    expect(vm.filteredCommits).toEqual([])
  })

  it('运行时任务默认来源为运行时', async () => {
    const { vm } = await mountDialog(makeTask({
      collection_mode: 'runtime', runtime_config: { host: '10.0.0.1', port: 6300, reset: false },
    }))
    expect(vm.source).toBe('runtime')
  })

  it('未关联代码源时不请求提交列表，触发不带 commit', async () => {
    const { wrapper, vm } = await mountDialog(makeTask({ repo_id: null }))
    expect(api.listRepoCommits).not.toHaveBeenCalled()
    vm.submit()
    const [payload] = wrapper.emitted('confirm')![0] as [TriggerPayload]
    expect(payload).toEqual({ source: 'unittest' })
  })

  it('分支变更的服务提示将开新一轮', async () => {
    await mountDialog(makeTask(), ['order'])
    const text = document.body.textContent ?? ''
    expect(text).toContain('本次采集将开始新一轮')
    expect(text).toContain('涉及服务：order')
  })
})
