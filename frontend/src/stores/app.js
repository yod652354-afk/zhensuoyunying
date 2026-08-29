import { defineStore } from 'pinia'
import { routes } from '../router/index.js'

export const useAppStore = defineStore('app', {
  state: () => ({
    menuRoutes: routes.filter((r) => r.meta?.title && !r.meta?.public),
  }),
})