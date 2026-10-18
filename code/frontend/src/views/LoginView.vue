<template>
  <div class="login-wrap">
    <el-card class="login-card">
      <div class="brand">
        <div class="logo">贷</div>
        <div>
          <h1>境外贷款单据智能审核平台</h1>
          <p>Overseas Loan Document Review</p>
        </div>
      </div>

      <el-form :model="form" @submit.prevent="onSubmit">
        <el-form-item>
          <el-input v-model="form.username" size="large" placeholder="用户名"
            :prefix-icon="User" />
        </el-form-item>
        <el-form-item>
          <el-input v-model="form.password" size="large" type="password" show-password
            placeholder="密码" :prefix-icon="Lock" @keyup.enter="onSubmit" />
        </el-form-item>
        <el-button type="primary" size="large" style="width: 100%" :loading="loading"
          @click="onSubmit">登 录</el-button>
      </el-form>

      <div class="hint">
        <p>演示账号（点击填入）：</p>
        <el-space wrap>
          <el-tag v-for="a in accounts" :key="a.u" class="acc" @click="fill(a)">
            {{ a.label }}
          </el-tag>
        </el-space>
      </div>
    </el-card>
  </div>
</template>

<script setup lang="ts">
import { reactive, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { User, Lock } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import { api } from '@/api'
import { useAuthStore } from '@/stores/auth'

const router = useRouter()
const route = useRoute()
const auth = useAuthStore()

const form = reactive({ username: '', password: '' })
const loading = ref(false)

const accounts = [
  { u: 'reviewer', p: 'reviewer123', label: '审核人员 reviewer' },
  { u: 'operator', p: 'operator123', label: '业务经办人 operator' },
]
function fill(a: { u: string; p: string }) {
  form.username = a.u
  form.password = a.p
}

async function onSubmit() {
  if (!form.username || !form.password) {
    ElMessage.warning('请输入用户名和密码')
    return
  }
  loading.value = true
  try {
    const resp = await api.login(form.username, form.password)
    auth.setAuth(resp.access_token, resp.role, resp.display_name)
    ElMessage.success(`欢迎，${resp.display_name}`)
    const redirect = (route.query.redirect as string) || '/dashboard'
    router.push(redirect)
  } catch {
    /* 错误已在拦截器统一提示 */
  } finally {
    loading.value = false
  }
}
</script>

<style scoped>
.login-wrap {
  height: 100%;
  display: flex;
  align-items: center;
  justify-content: center;
  background: linear-gradient(135deg, #1a2b4a 0%, #3b6fd4 100%);
}
.login-card {
  width: 420px;
  padding: 12px 8px;
}
.brand {
  display: flex;
  align-items: center;
  gap: 14px;
  margin-bottom: 24px;
}
.logo {
  width: 48px;
  height: 48px;
  border-radius: 12px;
  background: var(--navy);
  color: #fff;
  font-size: 24px;
  font-weight: 700;
  display: flex;
  align-items: center;
  justify-content: center;
}
.brand h1 {
  margin: 0;
  font-size: 18px;
}
.brand p {
  margin: 2px 0 0;
  color: var(--muted);
  font-size: 12px;
}
.hint {
  margin-top: 18px;
  font-size: 12px;
  color: var(--muted);
}
.hint p {
  margin: 0 0 8px;
}
.acc {
  cursor: pointer;
}
</style>
