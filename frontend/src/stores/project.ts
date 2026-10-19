/**
 * 项目状态管理
 */
import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import * as projectApi from '@/api/project'

interface Project {
  id: number
  code: string
  name: string
  description?: string
  icon?: string
  color?: string
  status: string
  created_at: string
  updated_at: string
}

export const useProjectStore = defineStore('project', () => {
  // 当前项目
  const currentProject = ref<Project | null>(null)

  // 项目列表
  const projects = ref<Project[]>([])

  // 计算属性
  const currentProjectId = computed(() => currentProject.value?.id)
  const currentProjectCode = computed(() => currentProject.value?.code)

  /**
   * 通过项目代码加载项目信息
   */
  const loadProjectByCode = async (code: string) => {
    try {
      // 如果已经加载了该项目，直接返回
      if (currentProject.value?.code === code) {
        return currentProject.value
      }

      // 先从项目列表中查找
      let project = projects.value.find(p => p.code === code)

      // 如果列表中没有，则加载所有项目
      if (!project) {
        projects.value = await projectApi.getProjects()
        project = projects.value.find(p => p.code === code)
      }

      if (project) {
        currentProject.value = project
        return project
      }

      throw new Error('Project not found')
    } catch (error) {
      console.error('Failed to load project:', error)
      throw error
    }
  }

  /**
   * 设置当前项目
   */
  const setCurrentProject = (project: Project) => {
    currentProject.value = project
  }

  /**
   * 清除当前项目
   */
  const clearCurrentProject = () => {
    currentProject.value = null
    projects.value = []
  }

  /**
   * 加载项目列表
   */
  const loadProjects = async () => {
    try {
      projects.value = await projectApi.getProjects()
      return projects.value
    } catch (error) {
      console.error('Failed to load projects:', error)
      throw error
    }
  }

  return {
    currentProject,
    projects,
    currentProjectId,
    currentProjectCode,
    loadProjectByCode,
    setCurrentProject,
    clearCurrentProject,
    loadProjects
  }
})
