// @vitest-environment happy-dom
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import { nextTick } from 'vue'
import ElementPlus from 'element-plus'
import * as api from '@/api/coverage'
import CoverageTaskFormDialog from './CoverageTaskFormDialog.vue'
import type { CoverageTask, CoverageTaskCreatePayload } from '@/types/coverage'

vi.mock('@/api/coverage', () => ({
  listCodeRepos: vi.fn(),
  listRepoBranches: vi.fn(),
  listRepoServices: vi.fn(),
  createCodeRepo: vi.fn(),
  updateCodeRepo: vi.fn(),
  deleteCodeRepo: vi.fn(),
}))

function mountDialog(task: CoverageTask | null = null) {
  return mount(CoverageTaskFormDialog, {
    props: { modelValue: true, task },
    global: { plugins: [ElementPlus], stubs: { teleport: true } },
  })
}

// script setup 内部状态，测试中通过 vm 访问
type Vm = {
  form: Record<string, any>
  handleSubmit: () => Promise<void>
}

function fillBasic(vm: Vm): void {
  vm.form.name = 'order-runtime'
  vm.form.repo_url = 'https://git.example.com/demo/order.git'
  vm.form.branch = 'master'
  vm.form.services = [{ name: 'order', module: '', path: 'services/order' }]
}

describe('CoverageTaskFormDialog 采集模式', () => {
  it('默认单元测试模式，不展示运行时配置', async () => {
    const wrapper = mountDialog()
    await nextTick()
    expect(wrapper.text()).toContain('采集模式')
    expect(wrapper.find('.rt-host-input').exists()).toBe(false)
    expect(wrapper.find('.svc-host-input').exists()).toBe(false)
  })

  it('切换到运行时模式后展示 agent 配置', async () => {
    const wrapper = mountDialog()
    ;(wrapper.vm as unknown as Vm).form.collection_mode = 'runtime'
    await nextTick()
    expect(wrapper.find('.rt-host-input').exists()).toBe(true)
    expect(wrapper.find('.svc-host-input').exists()).toBe(true)
    expect(wrapper.text()).toContain('output=tcpserver')
  })

  it('单元测试模式提交时不带 runtime_config 和 agent 字段', async () => {
    const wrapper = mountDialog()
    const vm = wrapper.vm as unknown as Vm
    fillBasic(vm)
    await nextTick()
    await vm.handleSubmit()

    const [payload, isEdit] = wrapper.emitted('submit')![0] as [CoverageTaskCreatePayload, boolean]
    expect(isEdit).toBe(false)
    expect(payload.collection_mode).toBe('unittest')
    expect(payload.runtime_config).toBeUndefined()
    expect(payload.services[0]).not.toHaveProperty('agent_host')
  })

  it('运行时模式提交时带上全局和服务级 agent 配置', async () => {
    const wrapper = mountDialog()
    const vm = wrapper.vm as unknown as Vm
    fillBasic(vm)
    vm.form.collection_mode = 'runtime'
    vm.form.runtime_host = ' 10.0.1.100 '
    vm.form.runtime_port = 6301
    vm.form.runtime_reset = true
    vm.form.services = [
      { name: 'order', path: 'services/order', agent_host: '10.0.1.200', agent_port: 6400 },
      { name: 'user', path: 'services/user' },
    ]
    await nextTick()
    await vm.handleSubmit()

    const [payload] = wrapper.emitted('submit')![0] as [CoverageTaskCreatePayload, boolean]
    expect(payload.collection_mode).toBe('runtime')
    expect(payload.runtime_config).toEqual({ host: '10.0.1.100', port: 6301, reset: true })
    expect(payload.services[0]).toMatchObject({ agent_host: '10.0.1.200', agent_port: 6400 })
    expect(payload.services[1].agent_host).toBeUndefined()
  })

  it('运行时模式下未配置任何 agent 地址时校验失败', async () => {
    const wrapper = mountDialog()
    const vm = wrapper.vm as unknown as Vm
    fillBasic(vm)
    vm.form.collection_mode = 'runtime'
    await nextTick()

    await expect(vm.handleSubmit()).rejects.toBeTruthy()
    expect(wrapper.emitted('submit')).toBeUndefined()
  })

  it('编辑运行时任务时回填配置', async () => {
    const task = {
      id: 1,
      name: 'order-runtime',
      repo_url: 'https://git.example.com/demo/order.git',
      branch: 'release',
      collection_mode: 'runtime',
      runtime_config: { host: '10.0.1.100', port: 6301, reset: true },
      services: [{ name: 'order', path: 'services/order', agent_host: '10.0.1.200' }],
    } as unknown as CoverageTask
    const wrapper = mountDialog(task)
    const vm = wrapper.vm as unknown as Vm
    await nextTick()

    expect(vm.form.collection_mode).toBe('runtime')
    expect(vm.form.runtime_host).toBe('10.0.1.100')
    expect(vm.form.runtime_port).toBe(6301)
    expect(vm.form.runtime_reset).toBe(true)
    expect(wrapper.find('.rt-host-input').exists()).toBe(true)

    await vm.handleSubmit()
    const [, isEdit] = wrapper.emitted('submit')![0] as [CoverageTaskCreatePayload, boolean]
    expect(isEdit).toBe(true)
  })
})

describe('CoverageTaskFormDialog 代码源下拉', () => {
  beforeEach(() => {
    vi.mocked(api.listCodeRepos).mockResolvedValue([
      {
        id: 7,
        project_id: 1,
        name: 'test_java_project',
        repo_url: 'https://github.com/zhaojiafeng2021/test_java_project.git',
        default_branch: 'demo-webapp',
        created_at: '',
        updated_at: '',
      },
    ])
    vi.mocked(api.listRepoBranches).mockResolvedValue([
      { name: 'main', commit_sha: 'aaaaaaaaaa' },
      { name: 'demo-webapp', commit_sha: 'bbbbbbbbbb' },
    ])
    vi.mocked(api.listRepoServices).mockResolvedValue([
      { name: 'demo-webapp', path: '.', build_tool: 'maven' },
    ])
  })

  it('默认选中第一个代码源和默认分支，并自动发现服务', async () => {
    const wrapper = mount(CoverageTaskFormDialog, {
      props: { modelValue: true, task: null, projectId: 1 },
      // ElSelect 的下拉层依赖真实 Teleport，stub 掉会在 happy-dom 中触发递归更新
      attachTo: document.body,
      global: { plugins: [ElementPlus] },
    })
    await flushPromises()
    const vm = wrapper.vm as unknown as Vm & { discoveredServices: unknown[] }
    expect(vm.form.repo_id).toBe(7)
    expect(vm.form.branch).toBe('demo-webapp')
    expect(api.listRepoServices).toHaveBeenCalledWith(1, 7, 'demo-webapp')
    expect(vm.discoveredServices).toHaveLength(1)

    vm.form.name = 'demo-runtime'
    vm.form.services = [{ name: 'demo-webapp', module: '', path: '.' }]
    await nextTick()
    await vm.handleSubmit()
    const [payload] = wrapper.emitted('submit')![0] as [CoverageTaskCreatePayload, boolean]
    expect(payload.repo_id).toBe(7)
    expect(payload.repo_url).toBeUndefined()
    expect(payload.branch).toBe('demo-webapp')
  })
})
