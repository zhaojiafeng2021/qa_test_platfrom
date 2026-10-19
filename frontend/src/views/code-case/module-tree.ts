import type { CodeModuleTreeNode } from '@/types/code-case'

/**
 * 剪掉整棵子树都没有有效用例的层级。
 *
 * 依据后端 `get_tree`：`total_case_count` = 自身直属用例 + 全部子孙用例，
 * 且统计时已排除软删除（`is_deleted`）的用例。所以 `total_case_count === 0`
 * 即代表该层级连同子孙都没有任何可展示的用例。
 *
 * @param nodes    原始模块树
 * @param keepId   需要保留的层级 ID（通常是当前选中项）。即使它为空也保留，
 *                 并保留其祖先链，避免选中项凭空消失、或新建的空模块看起来像创建失败。
 */
export function pruneEmptyModules(
  nodes: CodeModuleTreeNode[],
  keepId: number | null = null,
): CodeModuleTreeNode[] {
  return nodes.reduce<CodeModuleTreeNode[]>((acc, n) => {
    const children = pruneEmptyModules(n.children || [], keepId)
    // children.length 非空说明子孙里有需要保留的节点，此时父级必须留下来撑住层级
    if (n.total_case_count > 0 || children.length > 0 || n.id === keepId) {
      acc.push({ ...n, children })
    }
    return acc
  }, [])
}

/** 统计树中节点总数（含各层子孙） */
export function countModules(nodes: CodeModuleTreeNode[]): number {
  return nodes.reduce((sum, n) => sum + 1 + countModules(n.children || []), 0)
}

/**
 * 取指定层级自身 + 全部子孙的 ID，用于「按层级筛用例时包含子层级」。
 * 对应后端 `collect_subtree_ids` / 列表接口的 `include_children=true`：
 * 节点展示的是 total_case_count（含子孙），筛选口径必须一致，否则点父级会得到空列表。
 * 找不到该 ID 时返回空数组。
 */
export function collectSubtreeIds(
  nodes: CodeModuleTreeNode[],
  moduleId: number,
): number[] {
  for (const n of nodes) {
    if (n.id === moduleId) {
      const gather = (x: CodeModuleTreeNode): number[] =>
        [x.id, ...(x.children || []).flatMap(gather)]
      return gather(n)
    }
    const hit = collectSubtreeIds(n.children || [], moduleId)
    if (hit.length) return hit
  }
  return []
}
