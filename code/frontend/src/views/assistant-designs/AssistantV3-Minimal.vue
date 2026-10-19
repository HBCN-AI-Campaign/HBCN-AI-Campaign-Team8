<template>
  <div class="assistant-v3">
    <!-- 简洁顶栏 -->
    <nav class="top-nav">
      <div class="nav-brand">
        <span class="brand-logo">✨</span>
        <span class="brand-name">慧眼助手</span>
      </div>
      <div class="nav-actions">
        <el-button text size="small" @click="$router.push('/')">← 返回</el-button>
      </div>
    </nav>

    <!-- 单栏布局 -->
    <div class="main-view">
      <!-- 顶部：任务选择 + 技能快捷方式 -->
      <div class="control-bar">
        <el-select v-model="taskCode" placeholder="选择关联任务" clearable class="task-select">
          <el-option label="FOL LN-008 · 华为技术有限公司" value="FOL_LN_008" />
          <el-option label="FOL LN-009 · 中兴通讯股份" value="FOL_LN_009" />
        </el-select>
        <el-button @click="skillsDrawerVisible = true">审核技能</el-button>
        <el-button @click="sessionsDrawerVisible = true">会话列表</el-button>
      </div>

      <!-- 对话内容区 -->
      <div class="conversation-area">
        <!-- 欢迎卡片 -->
        <div class="welcome-card">
          <div class="welcome-emoji">🤖</div>
          <h1 class="welcome-heading">让审核工作更快一步</h1>
          <p class="welcome-text">我可以帮你解释不通过项、检索法规证据、执行专项审核技能</p>

          <div class="starter-prompts">
            <button class="starter-btn">
              <span class="starter-emoji">📋</span>
              <span class="starter-text">梳理风险点</span>
            </button>
            <button class="starter-btn">
              <span class="starter-emoji">🔍</span>
              <span class="starter-text">解释不通过项</span>
            </button>
            <button class="starter-btn">
              <span class="starter-emoji">📄</span>
              <span class="starter-text">核对材料字段</span>
            </button>
          </div>
        </div>

        <!-- 消息卡片示例 (v-if="false" 默认隐藏) -->
        <div v-if="false" class="message-cards">
          <!-- 用户消息 -->
          <div class="message-card user-card">
            <div class="card-header">
              <span class="author-badge">你</span>
              <span class="time-badge">刚刚</span>
            </div>
            <div class="card-body">
              为什么单据 LN-008 被驳回？
            </div>
          </div>

          <!-- 助手消息 -->
          <div class="message-card assistant-card">
            <div class="card-header">
              <span class="author-badge">慧眼助手</span>
              <span class="status-badge streaming">生成中...</span>
            </div>

            <!-- 步骤折叠 -->
            <details class="steps-accordion" open>
              <summary class="steps-summary">
                <span class="summary-icon">⚡</span>
                <span class="summary-text">执行步骤 (3 个)</span>
                <span class="summary-arrow">›</span>
              </summary>
              <div class="steps-list">
                <div class="step-row done">
                  <span class="step-bullet">✓</span>
                  <div class="step-content">
                    <div class="step-name">读取任务材料</div>
                    <div class="step-info">已加载 5 份单据</div>
                  </div>
                </div>
                <div class="step-row active">
                  <span class="step-bullet spinner">⏳</span>
                  <div class="step-content">
                    <div class="step-name">检索知识库</div>
                    <div class="step-info">找到 3 条证据</div>
                  </div>
                </div>
                <div class="step-row">
                  <span class="step-bullet">○</span>
                  <div class="step-content">
                    <div class="step-name">组织审核建议</div>
                  </div>
                </div>
              </div>
            </details>

            <div class="card-body">
              <p>单据 LN-008 被驳回的主要原因：</p>
              <ol class="reason-list">
                <li>
                  <strong>贷款用途不符（R001）</strong><br>
                  提款申请书用途为"设备采购"，但合同约定为"项目建设"
                </li>
                <li>
                  <strong>金额超限（R003）</strong><br>
                  申请金额 500 万美元，超过单次上限 300 万美元
                </li>
              </ol>
            </div>

            <!-- 证据标签 -->
            <div class="evidence-tags">
              <span class="tag-label">证据：</span>
              <span class="evidence-tag">R001 贷款用途</span>
              <span class="evidence-tag">提款申请书 · p.3</span>
              <span class="evidence-tag">业务规则 · 89%</span>
            </div>

            <!-- 卡片底部操作 -->
            <div class="card-footer">
              <button class="action-btn"><span>📋</span> 复制</button>
              <button class="action-btn"><span>🔄</span> 重新生成</button>
            </div>
          </div>
        </div>
      </div>

      <!-- 底部输入 -->
      <div class="input-zone">
        <div class="input-container">
          <textarea
            v-model="userInput"
            class="input-textarea"
            placeholder="描述你想核对的规则、材料或风险..."
            rows="2"
          ></textarea>
          <button class="send-button" :disabled="!userInput.trim()">
            <span>→</span>
          </button>
        </div>
        <div class="input-hint">受控只读 · 结论由审核人员确认</div>
      </div>
    </div>

    <!-- 左侧抽屉：会话列表 -->
    <el-drawer v-model="sessionsDrawerVisible" title="会话列表" direction="ltr" size="320px">
      <div class="drawer-content">
        <el-button type="primary" :icon="Plus" class="drawer-action">新建会话</el-button>

        <div class="sessions-list">
          <div class="session-group">
            <div class="group-heading">今日</div>
            <div class="session-row active">
              <div class="session-main">
                <div class="session-title">单据LN-008审核</div>
                <div class="session-meta">3 条消息 · 2 分钟前</div>
              </div>
            </div>
            <div class="session-row">
              <div class="session-main">
                <div class="session-title">制裁名单核查</div>
                <div class="session-meta">5 条消息 · 1 小时前</div>
              </div>
            </div>
          </div>

          <div class="session-group">
            <div class="group-heading">本周</div>
            <div class="session-row">
              <div class="session-main">
                <div class="session-title">汇率核验任务</div>
                <div class="session-meta">12 条消息 · 昨天</div>
              </div>
            </div>
          </div>
        </div>
      </div>
    </el-drawer>

    <!-- 右侧抽屉：审核技能 -->
    <el-drawer v-model="skillsDrawerVisible" title="审核技能" direction="rtl" size="360px">
      <div class="drawer-content">
        <el-button @click="storeVisible = true" class="drawer-action">✨ 浏览全部技能</el-button>

        <div class="skills-section">
          <div class="section-heading">常用技能</div>
          <div class="skill-grid">
            <div class="skill-box">
              <div class="skill-emoji">🚢</div>
              <div class="skill-label">提单验真</div>
              <button class="skill-run-btn">运行</button>
            </div>
            <div class="skill-box">
              <div class="skill-emoji">🔒</div>
              <div class="skill-label">制裁筛查</div>
              <button class="skill-run-btn">运行</button>
            </div>
            <div class="skill-box">
              <div class="skill-emoji">💱</div>
              <div class="skill-label">汇率换算</div>
              <button class="skill-run-btn">运行</button>
            </div>
            <div class="skill-box">
              <div class="skill-emoji">📅</div>
              <div class="skill-label">节假日核验</div>
              <button class="skill-run-btn">运行</button>
            </div>
          </div>
        </div>

        <div class="skills-section">
          <div class="section-heading">本周热门</div>
          <div class="hot-list">
            <div class="hot-row">
              <span class="hot-name">汇率换算</span>
              <span class="hot-count">89 次</span>
            </div>
            <div class="hot-row">
              <span class="hot-name">节假日核验</span>
              <span class="hot-count">67 次</span>
            </div>
            <div class="hot-row">
              <span class="hot-name">提单验真</span>
              <span class="hot-count">54 次</span>
            </div>
          </div>
        </div>
      </div>
    </el-drawer>

    <!-- 全屏技能商店 -->
    <el-dialog v-model="storeVisible" title="审核技能商店" fullscreen>
      <div class="store-view">
        <div class="store-search-bar">
          <el-input :prefix-icon="Search" placeholder="搜索技能..." class="search-box" />
          <el-radio-group v-model="category" class="category-tabs">
            <el-radio-button label="all">全部</el-radio-button>
            <el-radio-button label="doc">单据核验</el-radio-button>
            <el-radio-button label="risk">风险识别</el-radio-button>
            <el-radio-button label="law">法规检索</el-radio-button>
            <el-radio-button label="data">数据处理</el-radio-button>
          </el-radio-group>
        </div>

        <div class="store-catalog">
          <div class="catalog-card">
            <div class="catalog-cover blue-gradient">
              <span class="cover-emoji">🚢</span>
              <span class="cover-badge">推荐</span>
            </div>
            <div class="catalog-info">
              <h3 class="catalog-title">提单验真</h3>
              <p class="catalog-desc">核验海运提单的真实性，检测伪造或篡改</p>
              <div class="catalog-stats">
                <span class="stat-badge">📊 本周 67 次</span>
                <span class="stat-badge">#单据核验</span>
              </div>
              <div class="catalog-actions">
                <button class="catalog-btn detail">查看详情</button>
                <button class="catalog-btn primary">立即运行</button>
              </div>
            </div>
          </div>

          <div class="catalog-card">
            <div class="catalog-cover orange-gradient">
              <span class="cover-emoji">🔒</span>
              <span class="cover-badge new">新</span>
            </div>
            <div class="catalog-info">
              <h3 class="catalog-title">制裁名单筛查</h3>
              <p class="catalog-desc">检查借款人/担保人是否在国际制裁名单中</p>
              <div class="catalog-stats">
                <span class="stat-badge">🆕 新上架</span>
                <span class="stat-badge">#风险识别</span>
              </div>
              <div class="catalog-actions">
                <button class="catalog-btn detail">查看详情</button>
                <button class="catalog-btn primary">立即运行</button>
              </div>
            </div>
          </div>

          <div class="catalog-card">
            <div class="catalog-cover purple-gradient">
              <span class="cover-emoji">💱</span>
              <span class="cover-badge hot">热门</span>
            </div>
            <div class="catalog-info">
              <h3 class="catalog-title">汇率换算</h3>
              <p class="catalog-desc">自动获取实时汇率，计算多币种金额</p>
              <div class="catalog-stats">
                <span class="stat-badge">🔥 本周 89 次</span>
                <span class="stat-badge">#数据处理</span>
              </div>
              <div class="catalog-actions">
                <button class="catalog-btn detail">查看详情</button>
                <button class="catalog-btn primary">立即运行</button>
              </div>
            </div>
          </div>

          <div class="catalog-card">
            <div class="catalog-cover green-gradient">
              <span class="cover-emoji">📅</span>
            </div>
            <div class="catalog-info">
              <h3 class="catalog-title">节假日核验</h3>
              <p class="catalog-desc">检查提款日/还款日是否为借款国节假日</p>
              <div class="catalog-stats">
                <span class="stat-badge">📊 本周 54 次</span>
                <span class="stat-badge">#风险识别</span>
              </div>
              <div class="catalog-actions">
                <button class="catalog-btn detail">查看详情</button>
                <button class="catalog-btn primary">立即运行</button>
              </div>
            </div>
          </div>
        </div>
      </div>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { ref } from 'vue'
import { useRouter } from 'vue-router'
import { Plus, Search } from '@element-plus/icons-vue'

const router = useRouter()
const taskCode = ref('')
const userInput = ref('')
const sessionsDrawerVisible = ref(false)
const skillsDrawerVisible = ref(false)
const storeVisible = ref(false)
const category = ref('all')
</script>

<style scoped>
/* V3 版本：卡片式极简风格 - 强调内容，弱化边框 */
.assistant-v3 {
  height: 100vh;
  background: #fafbfc;
  display: flex;
  flex-direction: column;
}

/* 顶栏 */
.top-nav {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 16px 24px;
  background: white;
  border-bottom: 1px solid #e5e7eb;
}

.nav-brand {
  display: flex;
  align-items: center;
  gap: 12px;
}

.brand-logo {
  font-size: 28px;
}

.brand-name {
  font-size: 20px;
  font-weight: 700;
  color: #111827;
}

/* 主视图 */
.main-view {
  flex: 1;
  display: flex;
  flex-direction: column;
  overflow: hidden;
  max-width: 900px;
  margin: 0 auto;
  width: 100%;
  padding: 0 20px;
}

/* 控制栏 */
.control-bar {
  display: flex;
  gap: 12px;
  padding: 20px 0;
}

.task-select {
  flex: 1;
}

/* 对话区域 */
.conversation-area {
  flex: 1;
  overflow-y: auto;
  padding: 20px 0;
}

/* 欢迎卡片 */
.welcome-card {
  background: white;
  border-radius: 16px;
  padding: 48px 32px;
  text-align: center;
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.05);
}

.welcome-emoji {
  font-size: 64px;
  margin-bottom: 20px;
}

.welcome-heading {
  font-size: 32px;
  font-weight: 700;
  color: #111827;
  margin: 0 0 12px;
}

.welcome-text {
  font-size: 16px;
  color: #6b7280;
  margin: 0 0 32px;
  line-height: 1.6;
}

.starter-prompts {
  display: flex;
  gap: 12px;
  justify-content: center;
  flex-wrap: wrap;
}

.starter-btn {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 12px 20px;
  border: 1px solid #e5e7eb;
  border-radius: 24px;
  background: white;
  color: #374151;
  font-size: 14px;
  font-weight: 500;
  cursor: pointer;
  transition: all 0.2s;
}

.starter-btn:hover {
  border-color: #3b82f6;
  background: #eff6ff;
  transform: translateY(-2px);
  box-shadow: 0 4px 12px rgba(59, 130, 246, 0.15);
}

.starter-emoji {
  font-size: 18px;
}

/* 消息卡片 */
.message-cards {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.message-card {
  background: white;
  border-radius: 12px;
  padding: 20px;
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.05);
}

.user-card {
  margin-left: auto;
  max-width: 80%;
  background: #eff6ff;
  border: 1px solid #dbeafe;
}

.assistant-card {
  margin-right: auto;
  max-width: 100%;
  border: 1px solid #e5e7eb;
}

.card-header {
  display: flex;
  gap: 8px;
  align-items: center;
  margin-bottom: 12px;
}

.author-badge {
  font-size: 12px;
  font-weight: 600;
  color: #374151;
}

.time-badge {
  font-size: 11px;
  color: #9ca3af;
}

.status-badge {
  font-size: 11px;
  padding: 2px 8px;
  border-radius: 10px;
  background: #e5e7eb;
  color: #6b7280;
}

.status-badge.streaming {
  background: #dbeafe;
  color: #3b82f6;
}

.card-body {
  font-size: 15px;
  line-height: 1.7;
  color: #1f2937;
}

.card-body p {
  margin: 0 0 12px;
}

.reason-list {
  margin: 0;
  padding-left: 20px;
}

.reason-list li {
  margin-bottom: 12px;
}

.reason-list strong {
  color: #111827;
}

/* 步骤折叠 */
.steps-accordion {
  margin-bottom: 16px;
  border: 1px solid #e5e7eb;
  border-radius: 8px;
  background: #fafbfc;
  overflow: hidden;
}

.steps-summary {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 12px 16px;
  cursor: pointer;
  list-style: none;
  user-select: none;
}

.steps-summary::-webkit-details-marker {
  display: none;
}

.summary-icon {
  font-size: 18px;
}

.summary-text {
  flex: 1;
  font-size: 13px;
  font-weight: 600;
  color: #374151;
}

.summary-arrow {
  font-size: 16px;
  color: #9ca3af;
  transition: transform 0.2s;
}

details[open] .summary-arrow {
  transform: rotate(90deg);
}

.steps-list {
  padding: 0 16px 12px;
}

.step-row {
  display: flex;
  gap: 12px;
  padding: 8px 0;
}

.step-bullet {
  font-size: 16px;
  color: #9ca3af;
}

.step-row.done .step-bullet {
  color: #10b981;
}

.step-row.active .step-bullet {
  color: #3b82f6;
}

.spinner {
  animation: spin 1s linear infinite;
}

@keyframes spin {
  to { transform: rotate(360deg); }
}

.step-content {
  flex: 1;
}

.step-name {
  font-size: 13px;
  font-weight: 600;
  color: #374151;
}

.step-info {
  font-size: 12px;
  color: #6b7280;
  margin-top: 2px;
}

/* 证据标签 */
.evidence-tags {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  align-items: center;
  margin-top: 16px;
  padding-top: 16px;
  border-top: 1px solid #e5e7eb;
}

.tag-label {
  font-size: 12px;
  font-weight: 600;
  color: #6b7280;
}

.evidence-tag {
  padding: 4px 10px;
  border-radius: 6px;
  background: #f3f4f6;
  color: #374151;
  font-size: 12px;
  border: 1px solid #e5e7eb;
}

/* 卡片底部 */
.card-footer {
  display: flex;
  gap: 8px;
  margin-top: 12px;
  padding-top: 12px;
  border-top: 1px solid #e5e7eb;
}

.action-btn {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 6px 12px;
  border: 0;
  background: transparent;
  color: #6b7280;
  font-size: 13px;
  cursor: pointer;
  border-radius: 6px;
  transition: all 0.2s;
}

.action-btn:hover {
  background: #f3f4f6;
  color: #374151;
}

/* 输入区域 */
.input-zone {
  padding: 20px 0;
  background: white;
  border-top: 1px solid #e5e7eb;
}

.input-container {
  display: flex;
  gap: 12px;
  align-items: flex-end;
  padding: 12px;
  border: 2px solid #e5e7eb;
  border-radius: 12px;
  background: white;
  transition: border-color 0.2s;
}

.input-container:focus-within {
  border-color: #3b82f6;
  box-shadow: 0 0 0 3px rgba(59, 130, 246, 0.1);
}

.input-textarea {
  flex: 1;
  border: 0;
  outline: none;
  resize: none;
  font-size: 15px;
  color: #111827;
  font-family: inherit;
  line-height: 1.5;
}

.input-textarea::placeholder {
  color: #9ca3af;
}

.send-button {
  width: 40px;
  height: 40px;
  border: 0;
  border-radius: 10px;
  background: #3b82f6;
  color: white;
  font-size: 20px;
  cursor: pointer;
  flex-shrink: 0;
  transition: all 0.2s;
}

.send-button:hover:not(:disabled) {
  background: #2563eb;
  transform: scale(1.05);
}

.send-button:disabled {
  background: #e5e7eb;
  color: #9ca3af;
  cursor: not-allowed;
}

.input-hint {
  text-align: center;
  font-size: 11px;
  color: #9ca3af;
  margin-top: 8px;
}

/* 抽屉内容 */
.drawer-content {
  padding: 20px;
}

.drawer-action {
  width: 100%;
  margin-bottom: 20px;
}

.sessions-list {
  display: flex;
  flex-direction: column;
  gap: 20px;
}

.session-group {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.group-heading {
  font-size: 12px;
  font-weight: 600;
  color: #6b7280;
  text-transform: uppercase;
  letter-spacing: 0.5px;
  margin-bottom: 4px;
}

.session-row {
  padding: 12px;
  border-radius: 8px;
  background: #f9fafb;
  cursor: pointer;
  transition: all 0.2s;
}

.session-row:hover {
  background: #f3f4f6;
}

.session-row.active {
  background: #eff6ff;
  border: 2px solid #3b82f6;
}

.session-title {
  font-size: 14px;
  font-weight: 600;
  color: #111827;
  margin-bottom: 4px;
}

.session-meta {
  font-size: 12px;
  color: #6b7280;
}

/* 技能区域 */
.skills-section {
  margin-bottom: 24px;
}

.section-heading {
  font-size: 13px;
  font-weight: 600;
  color: #374151;
  margin-bottom: 12px;
}

.skill-grid {
  display: grid;
  grid-template-columns: repeat(2, 1fr);
  gap: 12px;
}

.skill-box {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 8px;
  padding: 16px;
  border: 1px solid #e5e7eb;
  border-radius: 12px;
  background: white;
  transition: all 0.2s;
  cursor: pointer;
}

.skill-box:hover {
  border-color: #3b82f6;
  box-shadow: 0 4px 12px rgba(59, 130, 246, 0.1);
  transform: translateY(-2px);
}

.skill-emoji {
  font-size: 32px;
}

.skill-label {
  font-size: 13px;
  font-weight: 600;
  color: #374151;
  text-align: center;
}

.skill-run-btn {
  padding: 4px 12px;
  border: 1px solid #3b82f6;
  border-radius: 12px;
  background: white;
  color: #3b82f6;
  font-size: 12px;
  font-weight: 600;
  cursor: pointer;
  transition: all 0.2s;
}

.skill-run-btn:hover {
  background: #3b82f6;
  color: white;
}

.hot-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.hot-row {
  display: flex;
  justify-content: space-between;
  padding: 10px 12px;
  border-radius: 6px;
  background: #f9fafb;
  font-size: 13px;
}

.hot-name {
  color: #374151;
}

.hot-count {
  color: #f59e0b;
  font-weight: 600;
}

/* 技能商店 */
.store-view {
  padding: 24px;
  background: #fafbfc;
  min-height: 100vh;
}

.store-search-bar {
  display: flex;
  gap: 16px;
  margin-bottom: 24px;
}

.search-box {
  width: 300px;
}

.category-tabs {
  flex: 1;
}

.store-catalog {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(300px, 1fr));
  gap: 20px;
}

.catalog-card {
  background: white;
  border-radius: 16px;
  overflow: hidden;
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.08);
  transition: all 0.3s;
}

.catalog-card:hover {
  box-shadow: 0 12px 28px rgba(0, 0, 0, 0.15);
  transform: translateY(-8px);
}

.catalog-cover {
  height: 140px;
  display: grid;
  place-items: center;
  position: relative;
}

.blue-gradient {
  background: linear-gradient(135deg, #3b82f6, #1e40af);
}

.orange-gradient {
  background: linear-gradient(135deg, #f59e0b, #dc2626);
}

.purple-gradient {
  background: linear-gradient(135deg, #8b5cf6, #6d28d9);
}

.green-gradient {
  background: linear-gradient(135deg, #10b981, #047857);
}

.cover-emoji {
  font-size: 56px;
  filter: drop-shadow(0 4px 8px rgba(0, 0, 0, 0.1));
}

.cover-badge {
  position: absolute;
  top: 12px;
  right: 12px;
  padding: 4px 12px;
  border-radius: 12px;
  background: rgba(255, 255, 255, 0.25);
  backdrop-filter: blur(8px);
  font-size: 11px;
  font-weight: 700;
  color: white;
  text-transform: uppercase;
}

.cover-badge.new {
  background: rgba(16, 185, 129, 0.9);
}

.cover-badge.hot {
  background: rgba(245, 158, 11, 0.9);
}

.catalog-info {
  padding: 20px;
}

.catalog-title {
  font-size: 18px;
  font-weight: 700;
  color: #111827;
  margin: 0 0 8px;
}

.catalog-desc {
  font-size: 14px;
  color: #6b7280;
  line-height: 1.5;
  margin: 0 0 16px;
}

.catalog-stats {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
  margin-bottom: 16px;
}

.stat-badge {
  padding: 4px 10px;
  border-radius: 6px;
  background: #f3f4f6;
  color: #374151;
  font-size: 12px;
  border: 1px solid #e5e7eb;
}

.catalog-actions {
  display: flex;
  gap: 8px;
}

.catalog-btn {
  flex: 1;
  padding: 10px;
  border: 1px solid #e5e7eb;
  border-radius: 8px;
  background: white;
  color: #374151;
  font-size: 14px;
  font-weight: 600;
  cursor: pointer;
  transition: all 0.2s;
}

.catalog-btn.detail:hover {
  background: #f9fafb;
  border-color: #d1d5db;
}

.catalog-btn.primary {
  background: #3b82f6;
  border-color: #3b82f6;
  color: white;
}

.catalog-btn.primary:hover {
  background: #2563eb;
  border-color: #2563eb;
}

/* 响应式 */
@media (max-width: 768px) {
  .main-view {
    padding: 0 16px;
  }
  .control-bar {
    flex-direction: column;
  }
  .starter-prompts {
    flex-direction: column;
  }
  .skill-grid {
    grid-template-columns: 1fr;
  }
}
</style>
