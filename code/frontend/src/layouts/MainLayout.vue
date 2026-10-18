<template>
  <el-container class="layout">
    <el-container>
      <el-header class="header">
        <!-- 无侧边栏：顶栏左侧显示品牌，点击回工作台 -->
        <div class="crumb">
          <span class="brand-link" @click="router.push({ name: 'dashboard' })">
            <span class="logo-sm">贷</span> 境外贷款单据审核平台
          </span>
        </div>
        <div class="right">
          <el-tag :type="roleTag.type" effect="dark">{{ roleTag.label }}</el-tag>
          <span class="uname">{{ auth.displayName }}</span>
          <el-dropdown @command="onCommand">
            <el-avatar :size="32" style="cursor: pointer; background: var(--blue)">
              {{ auth.displayName?.slice(0, 1) }}
            </el-avatar>
            <template #dropdown>
              <el-dropdown-menu>
                <el-dropdown-item command="logout">退出登录</el-dropdown-item>
              </el-dropdown-menu>
            </template>
          </el-dropdown>
        </div>
      </el-header>

      <el-main class="main">
        <router-view />
      </el-main>
    </el-container>
  </el-container>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { useRouter } from 'vue-router'
import { useAuthStore } from '@/stores/auth'

const router = useRouter()
const auth = useAuthStore()

const roleTag = computed(() => {
  const map: Record<string, { label: string; type: any }> = {
    reviewer: { label: '审核人员', type: 'success' },
    operator: { label: '业务经办人', type: 'warning' },
  }
  return map[auth.role] || { label: '未知', type: 'info' }
})

function onCommand(cmd: string) {
  if (cmd === 'logout') {
    auth.logout()
    router.push('/login')
  }
}
</script>

<style scoped>
.layout {
  height: 100%;
}
.header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  background: #fff;
  border-bottom: 1px solid #e2e8f0;
}
.crumb {
  font-weight: 600;
  display: flex;
  align-items: center;
  gap: 8px;
}
.logo-sm {
  width: 26px;
  height: 26px;
  border-radius: 7px;
  background: var(--blue);
  color: #fff;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  font-weight: 700;
  font-size: 14px;
}
.brand-link {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  cursor: pointer;
}
.right {
  display: flex;
  align-items: center;
  gap: 12px;
}
.uname {
  font-size: 13px;
  color: var(--muted);
}
.main {
  background: var(--bg);
  padding: 20px;
}
</style>
