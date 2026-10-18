import { createRouter, createWebHistory } from 'vue-router'
import { useAuthStore } from '@/stores/auth'

const router = createRouter({
  history: createWebHistory(),
  routes: [
    {
      path: '/login',
      name: 'login',
      component: () => import('@/views/LoginView.vue'),
      meta: { public: true },
    },
    {
      path: '/',
      component: () => import('@/layouts/MainLayout.vue'),
      redirect: '/dashboard',
      children: [
        {
          path: 'dashboard',
          name: 'dashboard',
          component: () => import('@/views/DashboardView.vue'),
          meta: { title: '审核工作台', icon: 'DataBoard' },
        },
        {
          path: 'create',
          name: 'create',
          component: () => import('@/views/CreateTaskView.vue'),
          meta: { title: '发起审核任务', icon: 'Upload', operatorOnly: true },
        },
        {
          path: 'tasks/:code',
          name: 'task',
          component: () => import('@/views/TaskObjectView.vue'),
          meta: { title: '任务详情', hidden: true },
        },
      ],
    },
    { path: '/:pathMatch(.*)*', redirect: '/dashboard' },
  ],
})

router.beforeEach((to) => {
  const auth = useAuthStore()
  if (!to.meta.public && !auth.isAuthenticated) {
    return { name: 'login', query: { redirect: to.fullPath } }
  }
  if (to.name === 'login' && auth.isAuthenticated) {
    return { name: 'dashboard' }
  }
  // 发起任务页仅经办人可进
  if (to.meta.operatorOnly && !auth.canCreate) {
    return { name: 'dashboard' }
  }
  return true
})

export default router
