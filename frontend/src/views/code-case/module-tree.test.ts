import { describe, it, expect } from 'vitest'
import { pruneEmptyModules, countModules, collectSubtreeIds } from './module-tree'
import type { CodeModuleTreeNode } from '@/types/code-case'

let seq = 0

/** 构造测试节点：direct 为直属用例数，children 自动累计出 total_case_count */
function node(
  name: string,
  direct: number,
  children: CodeModuleTreeNode[] = [],
  id = ++seq,
): CodeModuleTreeNode {
  const total = direct + children.reduce((s, c) => s + c.total_case_count, 0)
  return {
    id,
    parent_id: null,
    name,
    level: 1,
    full_path: name,
    sort_order: 0,
    case_count: direct,
    total_case_count: total,
    children,
  }
}

const names = (nodes: CodeModuleTreeNode[]): string[] => nodes.map(n => n.name)

describe('pruneEmptyModules', () => {
  it('丢弃自身与子孙都无用例的层级', () => {
    const tree = [node('空模块', 0), node('有用例', 1)]
    expect(names(pruneEmptyModules(tree))).toEqual(['有用例'])
  })

  it('整棵空子树一并丢弃（对应真实数据里的支付中心）', () => {
    const tree = [
      node('支付中心', 0, [
        node('支付渠道', 0, [node('支付宝', 0), node('微信支付', 0)]),
        node('对账', 0, [node('日结对账', 0)]),
      ]),
      node('积分商城', 1),
    ]
    const kept = pruneEmptyModules(tree)
    expect(names(kept)).toEqual(['积分商城'])
    expect(countModules(tree)).toBe(7)
    expect(countModules(kept)).toBe(1)
  })

  it('父级自身为空但子孙有用例时保留父级以撑住层级', () => {
    const tree = [node('父', 0, [node('空子', 0), node('有用例子', 2)])]
    const kept = pruneEmptyModules(tree)
    expect(names(kept)).toEqual(['父'])
    expect(names(kept[0].children)).toEqual(['有用例子'])
  })

  it('父级有直属用例时，空的子层级依然被剪掉', () => {
    const tree = [node('父', 3, [node('空子', 0)])]
    const kept = pruneEmptyModules(tree)
    expect(names(kept)).toEqual(['父'])
    expect(kept[0].children).toEqual([])
  })

  it('keepId 指向的空层级保留，且保留其祖先链', () => {
    const target = node('新建空模块', 0, [], 999)
    const tree = [node('外层', 0, [node('中层', 0, [target])])]
    const kept = pruneEmptyModules(tree, 999)
    expect(names(kept)).toEqual(['外层'])
    expect(names(kept[0].children)).toEqual(['中层'])
    expect(names(kept[0].children[0].children)).toEqual(['新建空模块'])
  })

  it('keepId 不匹配任何节点时不影响剪枝结果', () => {
    const tree = [node('空模块', 0), node('有用例', 1)]
    expect(names(pruneEmptyModules(tree, 12345))).toEqual(['有用例'])
  })

  it('不修改传入的原始树（返回新对象）', () => {
    const tree = [node('父', 1, [node('空子', 0)])]
    const before = JSON.stringify(tree)
    pruneEmptyModules(tree)
    expect(JSON.stringify(tree)).toBe(before)
  })

  it('空数组与缺失 children 字段都能安全处理', () => {
    expect(pruneEmptyModules([])).toEqual([])
    const noChildren = { ...node('孤立', 1) } as CodeModuleTreeNode
    // @ts-expect-error 模拟后端未返回 children 的情况
    delete noChildren.children
    expect(names(pruneEmptyModules([noChildren]))).toEqual(['孤立'])
  })
})

describe('collectSubtreeIds', () => {
  it('返回自身 + 全部子孙的 ID', () => {
    const leaf = node('叶', 1, [], 30)
    const mid = node('中', 0, [leaf], 20)
    const root = node('根', 0, [mid], 10)
    expect(collectSubtreeIds([root], 10).sort()).toEqual([10, 20, 30])
  })

  it('从中间层级取时只含该子树', () => {
    const a = node('a', 1, [], 41)
    const b = node('b', 1, [], 42)
    const parent = node('p', 0, [a, b], 40)
    const sibling = node('s', 1, [], 50)
    expect(collectSubtreeIds([parent, sibling], 40).sort()).toEqual([40, 41, 42])
    expect(collectSubtreeIds([parent, sibling], 50)).toEqual([50])
  })

  it('叶子节点返回单个 ID', () => {
    expect(collectSubtreeIds([node('叶', 1, [], 60)], 60)).toEqual([60])
  })

  it('ID 不存在时返回空数组', () => {
    expect(collectSubtreeIds([node('x', 1, [], 70)], 999)).toEqual([])
  })

  it('空树返回空数组', () => {
    expect(collectSubtreeIds([], 1)).toEqual([])
  })
})

describe('countModules', () => {
  it('统计包含所有层级的节点数', () => {
    const tree = [node('a', 0, [node('b', 0, [node('c', 0)])]), node('d', 0)]
    expect(countModules(tree)).toBe(4)
  })

  it('空树为 0', () => {
    expect(countModules([])).toBe(0)
  })
})
