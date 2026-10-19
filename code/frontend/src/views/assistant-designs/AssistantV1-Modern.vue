<template>
  <div class="assistant-v1">
    <!-- 顶部导航栏 -->
    <header class="top-bar">
      <div class="top-bar-left">
        <div class="brand">
          <div class="brand-icon">
            <el-icon><MagicStick /></el-icon>
          </div>
          <span class="brand-text">慧眼助手</span>
        </div>
        <el-select v-model="taskCode" placeholder="关联任务" clearable class="task-selector">
          <el-option label="FOL LN-008 · 华为技术有限公司" value="FOL_LN_008" />
          <el-option label="FOL LN-009 · 中兴通讯股份" value="FOL_LN_009" />
        </el-select>
      </div>
      <div class="top-bar-right">
        <el-switch v-model="darkMode" :active-icon="Moon" :inactive-icon="Sunny" />
        <el-button text :icon="User">审核员</el-button>
        <el-button text :icon="ArrowLeft" @click="$router.push('/')">返回</el-button>
      </div>
    </header>

    <div class="main-shell">
      <!-- 左侧：会话列表 -->
      <aside class="session-sidebar">
        <el-button type="primary" :icon="Plus" class="new-session-btn">新建会话</el-button>
        <el-input :prefix-icon="Search" placeholder="搜索会话..." class="search-input" />

        <div class="session-groups">
          <div class="session-group">
            <div class="group-title">📌 今日会话</div>
            <div class="session-item active">
              <span class="session-dot"></span>
              <div class="session-info">
                <div class="session-name">单据LN-008审核</div>
                <div class="session-meta">3条消息 · 2分钟前</div>
              </div>
            </div>
            <div class="session-item">
              <span class="session-dot"></span>
              <div class="session-info">
                <div class="session-name">制裁名单核查</div>
                <div class="session-meta">5条消息 · 1小时前</div>
              </div>
            </div>
          </div>

          <div class="session-group">
            <div class="group-title">📅 本周会话</div>
            <div class="session-item">
              <span class="session-dot"></span>
              <div class="session-info">
                <div class="session-name">汇率核验</div>
                <div class="session-meta">12条消息 · 昨天</div>
              </div>
            </div>
          </div>
        </div>

        <div class="sidebar-footer">
          <span class="status-dot online"></span>
          <span class="status-text">模型已连接</span>
        </div>
      </aside>

      <!-- 中间：对话区域 -->
      <main class="chat-area">
        <!-- 欢迎界面 -->
        <div class="welcome-screen">
          <div class="welcome-icon">
            <el-icon><MagicStick /></el-icon>
          </div>
          <h2>让审核工作更快一步</h2>
          <p>我可以帮你解释不通过项、检索法规证据、执行专项审核技能</p>

          <div class="prompt-cards">
            <div class="prompt-card">
              <el-icon class="prompt-icon"><DocumentChecked /></el-icon>
              <div class="prompt-content">
                <div class="prompt-title">解释不通过项</div>
                <div class="prompt-desc">为什么单据被驳回</div>
              </div>
            </div>
            <div class="prompt-card">
              <el-icon class="prompt-icon"><Search /></el-icon>
              <div class="prompt-content">
                <div class="prompt-title">检索法规证据</div>
                <div class="prompt-desc">查找相关业务规则</div>
              </div>
            </div>
            <div class="prompt-card">
              <el-icon class="prompt-icon"><Edit /></el-icon>
              <div class="prompt-content">
                <div class="prompt-title">起草复核意见</div>
                <div class="prompt-desc">生成审核报告草稿</div>
              </div>
            </div>
          </div>
        </div>

        <!-- 消息流 (这里是示例,真实场景下根据 messages 循环) -->
        <!-- 用户消息示例 -->
        <div v-if="false" class="message-container user-message">
          <div class="message-bubble user-bubble">
            <div class="message-header">
              <span class="message-author">你</span>
              <span class="message-time">刚刚</span>
            </div>
            <div class="message-content">
              为什么单据 LN-008 被驳回？
            </div>
          </div>
          <div class="message-avatar user-avatar">我</div>
        </div>

        <!-- 助手消息示例 -->
        <div v-if="false" class="message-container assistant-message">
          <div class="message-avatar assistant-avatar">
            <el-icon><MagicStick /></el-icon>
          </div>
          <div class="message-bubble assistant-bubble">
            <div class="message-header">
              <span class="message-author">慧眼助手</span>
              <span class="streaming-badge">正在生成...</span>
            </div>

            <!-- 执行步骤折叠面板 -->
            <el-collapse v-model="activeSteps" class="execution-steps">
              <el-collapse-item name="steps">
                <template #title>
                  <div class="steps-header">
                    <el-icon class="is-loading"><Loading /></el-icon>
                    <div class="steps-info">
                      <div class="steps-title">慧眼正在处理</div>
                      <div class="steps-subtitle">已调用 2 次证据检索</div>
                    </div>
                    <el-icon class="steps-arrow"><ArrowRight /></el-icon>
                  </div>
                </template>
                <div class="steps-content">
                  <div class="step-item completed">
                    <el-icon class="step-icon"><CircleCheck /></el-icon>
                    <div class="step-info">
                      <div class="step-label">正在读取任务材料</div>
                      <div class="step-detail">已加载提款申请书、合同等 5 份单据</div>
                    </div>
                  </div>
                  <div class="step-item running">
                    <el-icon class="step-icon is-loading"><Loading /></el-icon>
                    <div class="step-info">
                      <div class="step-label">正在检索知识库</div>
                      <div class="step-detail">找到 3 条相关证据</div>
                    </div>
                  </div>
                  <div class="step-item pending">
                    <span class="step-dot"></span>
                    <div class="step-info">
                      <div class="step-label">组织审核建议</div>
                      <div class="step-detail">正在整合材料、规则和知识库依据</div>
                    </div>
                  </div>
                </div>
              </el-collapse-item>
            </el-collapse>

            <!-- 回答内容 -->
            <div class="message-content">
              <p>根据任务材料和规则检查结果，单据 LN-008 被驳回的主要原因：</p>
              <ul>
                <li><strong>贷款用途不符（R001）</strong>：提款申请书中用途为"设备采购"，但合同约定用途为"项目建设"</li>
                <li><strong>金额超限（R003）</strong>：申请提款金额 500 万美元，超过合同约定的单次提款上限 300 万美元</li>
              </ul>
            </div>

            <!-- 证据引用 -->
            <div class="citations">
              <div class="citations-label">🏷️ 证据引用</div>
              <div class="citations-list">
                <el-tag type="info" effect="plain">R001 贷款用途</el-tag>
                <el-tag type="info" effect="plain">提款申请书 · p.3</el-tag>
                <el-tag type="success" effect="plain">业务规则 · 相关度 89%</el-tag>
              </div>
            </div>

            <!-- 操作按钮 -->
            <div class="message-actions">
              <el-button text :icon="CopyDocument">复制</el-button>
              <el-button text :icon="Refresh">重新生成</el-button>
            </div>
          </div>
        </div>

        <!-- 输入区域 -->
        <div class="composer">
          <el-input
            v-model="userInput"
            type="textarea"
            :rows="2"
            placeholder="描述你想核对的规则、材料或风险..."
            class="composer-input"
          />
          <div class="composer-actions">
            <div class="composer-hint">受控只读 · 结论由审核人员确认</div>
            <el-button type="primary" circle :icon="Promotion" class="send-btn"></el-button>
          </div>
        </div>
      </main>

      <!-- 右侧：审核技能面板 -->
      <aside class="skill-sidebar">
        <div class="skill-header">
          <span class="skill-title">审核技能</span>
          <el-button text @click="skillStoreVisible = true">✨ 浏览全部</el-button>
        </div>

        <div class="skill-section">
          <div class="section-title">📋 常用技能</div>
          <div class="skill-card">
            <div class="skill-icon-wrap">
              <el-icon><Ship /></el-icon>
            </div>
            <div class="skill-info">
              <div class="skill-name">提单验真</div>
              <div class="skill-desc">核验海运提单关键信息</div>
            </div>
            <el-button size="small" type="primary">立即使用</el-button>
          </div>

          <div class="skill-card">
            <div class="skill-icon-wrap">
              <el-icon><Lock /></el-icon>
            </div>
            <div class="skill-info">
              <div class="skill-name">制裁名单筛查</div>
              <div class="skill-desc">检查借款人、收款人</div>
            </div>
            <el-button size="small" type="primary">立即使用</el-button>
          </div>

          <div class="skill-card">
            <div class="skill-icon-wrap">
              <el-icon><Coin /></el-icon>
            </div>
            <div class="skill-info">
              <div class="skill-name">汇率换算</div>
              <div class="skill-desc">核对币种与汇率折算</div>
            </div>
            <el-button size="small" type="primary">立即使用</el-button>
          </div>
        </div>

        <div class="skill-section">
          <div class="section-title">🔥 热门技能</div>
          <div class="skill-stats">
            <div class="stat-item">
              <span class="stat-name">汇率换算</span>
              <span class="stat-count">本周 89 次</span>
            </div>
            <div class="stat-item">
              <span class="stat-name">节假日核验</span>
              <span class="stat-count">本周 67 次</span>
            </div>
          </div>
        </div>
      </aside>
    </div>

    <!-- 技能商店 Dialog -->
    <el-dialog v-model="skillStoreVisible" title="审核技能商店" fullscreen>
      <div class="skill-store">
        <div class="store-header">
          <el-input :prefix-icon="Search" placeholder="搜索技能..." class="store-search" />
          <el-radio-group v-model="activeCategory" class="store-tabs">
            <el-radio-button label="all">全部</el-radio-button>
            <el-radio-button label="doc">单据核验</el-radio-button>
            <el-radio-button label="risk">风险识别</el-radio-button>
            <el-radio-button label="law">法规检索</el-radio-button>
            <el-radio-button label="data">数据处理</el-radio-button>
          </el-radio-group>
        </div>

        <el-row :gutter="20" class="store-grid">
          <el-col :xs="24" :sm="12" :md="8" :lg="6">
            <el-card shadow="hover" class="store-skill-card">
              <div class="skill-cover" style="background: linear-gradient(135deg, #3b82f6, #1e3a8a)">
                <el-icon class="cover-icon"><Ship /></el-icon>
              </div>
              <div class="skill-card-body">
                <div class="skill-tags">
                  <el-tag size="small" type="info">#单据核验</el-tag>
                  <el-badge value="推荐" type="success" />
                </div>
                <h3 class="skill-card-title">提单验真</h3>
                <p class="skill-card-desc">核验海运提单的真实性，检测伪造或篡改</p>
                <div class="skill-usage">
                  <el-icon><TrendCharts /></el-icon>
                  <span>本周使用 67 次</span>
                </div>
                <div class="skill-card-actions">
                  <el-button text size="small">查看详情</el-button>
                  <el-button type="primary" size="small">立即运行</el-button>
                </div>
              </div>
            </el-card>
          </el-col>

          <el-col :xs="24" :sm="12" :md="8" :lg="6">
            <el-card shadow="hover" class="store-skill-card">
              <div class="skill-cover" style="background: linear-gradient(135deg, #f59e0b, #dc2626)">
                <el-icon class="cover-icon"><Lock /></el-icon>
              </div>
              <div class="skill-card-body">
                <div class="skill-tags">
                  <el-tag size="small" type="warning">#风险识别</el-tag>
                  <el-badge value="新上架" type="success" />
                </div>
                <h3 class="skill-card-title">制裁名单筛查</h3>
                <p class="skill-card-desc">检查借款人/担保人是否在国际制裁名单中</p>
                <div class="skill-usage">
                  <el-badge value="新" type="success" />
                  <span>新上架</span>
                </div>
                <div class="skill-card-actions">
                  <el-button text size="small">查看详情</el-button>
                  <el-button type="primary" size="small">立即运行</el-button>
                </div>
              </div>
            </el-card>
          </el-col>

          <!-- 更多卡片... -->
        </el-row>
      </div>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { ref } from 'vue'
import { useRouter } from 'vue-router'
import {
  ArrowLeft, ArrowRight, CircleCheck, Coin, CopyDocument, DocumentChecked,
  Edit, Loading, Lock, MagicStick, Moon, Plus, Promotion, Refresh,
  Search, Ship, Sunny, TrendCharts, User
} from '@element-plus/icons-vue'

const router = useRouter()
const taskCode = ref('')
const darkMode = ref(false)
const userInput = ref('')
const activeSteps = ref(['steps'])
const skillStoreVisible = ref(false)
const activeCategory = ref('all')
</script>

<style scoped>
/* V1 版本：现代简洁风格 */
.assistant-v1 {
  display: flex;
  flex-direction: column;
  height: 100vh;
  background: #f8fafc;
}

/* 顶部导航栏 */
.top-bar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 12px 24px;
  background: #ffffff;
  border-bottom: 1px solid #e2e8f0;
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.05);
}

.top-bar-left, .top-bar-right {
  display: flex;
  align-items: center;
  gap: 16px;
}

.brand {
  display: flex;
  align-items: center;
  gap: 10px;
}

.brand-icon {
  display: grid;
  place-items: center;
  width: 36px;
  height: 36px;
  border-radius: 8px;
  background: linear-gradient(135deg, #3b82f6, #1e3a8a);
  color: white;
  font-size: 20px;
}

.brand-text {
  font-size: 18px;
  font-weight: 700;
  color: #1e293b;
}

.task-selector {
  width: 260px;
}

/* 主体布局 */
.main-shell {
  display: grid;
  grid-template-columns: 260px 1fr 300px;
  flex: 1;
  min-height: 0;
  gap: 1px;
  background: #e2e8f0;
}

/* 左侧会话列表 */
.session-sidebar {
  display: flex;
  flex-direction: column;
  background: #ffffff;
  padding: 16px;
  overflow-y: auto;
}

.new-session-btn {
  width: 100%;
  margin-bottom: 12px;
}

.search-input {
  margin-bottom: 16px;
}

.session-groups {
  flex: 1;
  overflow-y: auto;
}

.session-group {
  margin-bottom: 20px;
}

.group-title {
  font-size: 12px;
  font-weight: 600;
  color: #64748b;
  margin-bottom: 8px;
  padding: 0 8px;
}

.session-item {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 10px 12px;
  border-radius: 8px;
  cursor: pointer;
  transition: all 0.2s;
  margin-bottom: 4px;
}

.session-item:hover {
  background: #f1f5f9;
}

.session-item.active {
  background: #dbeafe;
  border-left: 3px solid #3b82f6;
}

.session-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: #cbd5e1;
  flex-shrink: 0;
}

.active .session-dot {
  background: #3b82f6;
}

.session-info {
  flex: 1;
  min-width: 0;
}

.session-name {
  font-size: 13px;
  font-weight: 600;
  color: #1e293b;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.session-meta {
  font-size: 11px;
  color: #94a3b8;
  margin-top: 2px;
}

.sidebar-footer {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 12px;
  border-top: 1px solid #e2e8f0;
  margin-top: auto;
  font-size: 12px;
  color: #64748b;
}

.status-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: #94a3b8;
}

.status-dot.online {
  background: #10b981;
  box-shadow: 0 0 0 2px #d1fae5;
}

/* 中间对话区域 */
.chat-area {
  display: flex;
  flex-direction: column;
  background: #ffffff;
  overflow-y: auto;
  padding: 24px;
}

.welcome-screen {
  max-width: 700px;
  margin: 60px auto;
  text-align: center;
}

.welcome-icon {
  width: 64px;
  height: 64px;
  margin: 0 auto 20px;
  border-radius: 12px;
  background: linear-gradient(135deg, #3b82f6, #1e3a8a);
  color: white;
  display: grid;
  place-items: center;
  font-size: 32px;
}

.welcome-screen h2 {
  font-size: 28px;
  font-weight: 700;
  color: #1e293b;
  margin: 0 0 12px;
}

.welcome-screen p {
  font-size: 15px;
  color: #64748b;
  line-height: 1.6;
  margin: 0 0 32px;
}

.prompt-cards {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 16px;
  margin-top: 32px;
}

.prompt-card {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 12px;
  padding: 24px 16px;
  border: 1px solid #e2e8f0;
  border-radius: 12px;
  background: #ffffff;
  cursor: pointer;
  transition: all 0.3s;
}

.prompt-card:hover {
  border-color: #3b82f6;
  box-shadow: 0 8px 24px rgba(59, 130, 246, 0.12);
  transform: translateY(-4px);
}

.prompt-icon {
  width: 48px;
  height: 48px;
  border-radius: 10px;
  background: #dbeafe;
  color: #3b82f6;
  display: grid;
  place-items: center;
  font-size: 24px;
}

.prompt-content {
  text-align: center;
}

.prompt-title {
  font-size: 14px;
  font-weight: 600;
  color: #1e293b;
  margin-bottom: 4px;
}

.prompt-desc {
  font-size: 12px;
  color: #64748b;
}

/* 消息流 */
.message-container {
  display: flex;
  gap: 12px;
  margin-bottom: 24px;
  max-width: 800px;
}

.user-message {
  flex-direction: row-reverse;
  margin-left: auto;
}

.assistant-message {
  margin-right: auto;
}

.message-avatar {
  width: 36px;
  height: 36px;
  border-radius: 50%;
  display: grid;
  place-items: center;
  flex-shrink: 0;
  font-size: 14px;
  font-weight: 600;
}

.user-avatar {
  background: #dbeafe;
  color: #3b82f6;
}

.assistant-avatar {
  background: #f1f5f9;
  color: #3b82f6;
  font-size: 20px;
}

.message-bubble {
  flex: 1;
  padding: 16px;
  border-radius: 12px;
}

.user-bubble {
  background: #dbeafe;
  color: #1e293b;
  border-top-right-radius: 4px;
}

.assistant-bubble {
  background: #ffffff;
  border: 1px solid #e2e8f0;
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.04);
  border-top-left-radius: 4px;
}

.message-header {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 12px;
}

.message-author {
  font-size: 12px;
  font-weight: 600;
  color: #475569;
}

.message-time {
  font-size: 11px;
  color: #94a3b8;
}

.streaming-badge {
  font-size: 11px;
  color: #3b82f6;
}

.message-content {
  font-size: 14px;
  line-height: 1.7;
  color: #334155;
}

.message-content p {
  margin: 0 0 12px;
}

.message-content ul {
  margin: 0;
  padding-left: 20px;
}

.message-content li {
  margin-bottom: 8px;
}

/* 执行步骤 */
.execution-steps {
  margin-bottom: 16px;
  border: 1px solid #e2e8f0;
  border-radius: 8px;
  background: #f8fafc;
}

.steps-header {
  display: flex;
  align-items: center;
  gap: 12px;
  width: 100%;
}

.steps-info {
  flex: 1;
}

.steps-title {
  font-size: 13px;
  font-weight: 600;
  color: #334155;
}

.steps-subtitle {
  font-size: 11px;
  color: #64748b;
  margin-top: 2px;
}

.steps-arrow {
  color: #94a3b8;
  transition: transform 0.3s;
}

.steps-content {
  padding: 12px 0;
}

.step-item {
  display: flex;
  align-items: flex-start;
  gap: 12px;
  padding: 8px 0;
}

.step-icon {
  font-size: 16px;
  color: #10b981;
}

.step-icon.is-loading {
  color: #3b82f6;
}

.step-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: #cbd5e1;
  margin-top: 4px;
}

.step-info {
  flex: 1;
}

.step-label {
  font-size: 12px;
  font-weight: 600;
  color: #475569;
}

.step-detail {
  font-size: 11px;
  color: #64748b;
  margin-top: 2px;
}

/* 证据引用 */
.citations {
  margin-top: 16px;
  padding-top: 16px;
  border-top: 1px solid #e2e8f0;
}

.citations-label {
  font-size: 11px;
  font-weight: 600;
  color: #64748b;
  margin-bottom: 8px;
}

.citations-list {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

/* 操作按钮 */
.message-actions {
  display: flex;
  gap: 8px;
  margin-top: 12px;
}

/* 输入区域 */
.composer {
  margin-top: auto;
  padding-top: 16px;
  border-top: 1px solid #e2e8f0;
}

.composer-input {
  margin-bottom: 8px;
}

.composer-actions {
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.composer-hint {
  font-size: 11px;
  color: #94a3b8;
}

.send-btn {
  width: 40px;
  height: 40px;
}

/* 右侧技能面板 */
.skill-sidebar {
  background: #ffffff;
  padding: 16px;
  overflow-y: auto;
}

.skill-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 16px;
}

.skill-title {
  font-size: 15px;
  font-weight: 700;
  color: #1e293b;
}

.skill-section {
  margin-bottom: 24px;
}

.section-title {
  font-size: 12px;
  font-weight: 600;
  color: #64748b;
  margin-bottom: 12px;
}

.skill-card {
  display: flex;
  flex-direction: column;
  gap: 8px;
  padding: 12px;
  border: 1px solid #e2e8f0;
  border-radius: 8px;
  margin-bottom: 12px;
  transition: all 0.2s;
}

.skill-card:hover {
  border-color: #3b82f6;
  box-shadow: 0 4px 12px rgba(59, 130, 246, 0.08);
}

.skill-icon-wrap {
  width: 40px;
  height: 40px;
  border-radius: 8px;
  background: #dbeafe;
  color: #3b82f6;
  display: grid;
  place-items: center;
  font-size: 20px;
}

.skill-info {
  flex: 1;
}

.skill-name {
  font-size: 13px;
  font-weight: 600;
  color: #1e293b;
  margin-bottom: 4px;
}

.skill-desc {
  font-size: 11px;
  color: #64748b;
  line-height: 1.4;
}

.skill-stats {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.stat-item {
  display: flex;
  justify-content: space-between;
  padding: 8px 12px;
  background: #f8fafc;
  border-radius: 6px;
  font-size: 12px;
}

.stat-name {
  color: #475569;
}

.stat-count {
  color: #f59e0b;
  font-weight: 600;
}

/* 技能商店 */
.skill-store {
  padding: 24px;
}

.store-header {
  display: flex;
  gap: 16px;
  margin-bottom: 24px;
}

.store-search {
  width: 300px;
}

.store-tabs {
  flex: 1;
}

.store-grid {
  margin-top: 24px;
}

.store-skill-card {
  margin-bottom: 20px;
  border-radius: 12px;
  overflow: hidden;
  transition: all 0.3s;
}

.store-skill-card:hover {
  transform: translateY(-8px);
  box-shadow: 0 12px 28px rgba(0, 0, 0, 0.12);
}

.skill-cover {
  height: 140px;
  display: grid;
  place-items: center;
  position: relative;
}

.cover-icon {
  font-size: 48px;
  color: rgba(255, 255, 255, 0.9);
}

.skill-card-body {
  padding: 16px;
}

.skill-tags {
  display: flex;
  gap: 8px;
  align-items: center;
  margin-bottom: 12px;
}

.skill-card-title {
  font-size: 16px;
  font-weight: 700;
  color: #1e293b;
  margin: 0 0 8px;
}

.skill-card-desc {
  font-size: 13px;
  color: #64748b;
  line-height: 1.5;
  margin: 0 0 12px;
}

.skill-usage {
  display: flex;
  align-items: center;
  gap: 4px;
  font-size: 12px;
  color: #f59e0b;
  margin-bottom: 12px;
}

.skill-card-actions {
  display: flex;
  gap: 8px;
  justify-content: space-between;
}

/* 响应式 */
@media (max-width: 1200px) {
  .main-shell {
    grid-template-columns: 240px 1fr;
  }
  .skill-sidebar {
    display: none;
  }
}

@media (max-width: 768px) {
  .main-shell {
    grid-template-columns: 1fr;
  }
  .session-sidebar {
    display: none;
  }
  .prompt-cards {
    grid-template-columns: 1fr;
  }
}
</style>
