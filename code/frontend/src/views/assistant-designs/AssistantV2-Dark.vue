<template>
  <div class="assistant-v2 dark-theme">
    <!-- 顶部栏 -->
    <header class="app-header">
      <div class="header-left">
        <div class="logo">
          <div class="logo-icon">
            <el-icon><MagicStick /></el-icon>
          </div>
          <span class="logo-text">慧眼</span>
        </div>
        <el-divider direction="vertical" />
        <el-select v-model="taskCode" placeholder="选择任务" clearable size="small" class="task-picker">
          <el-option label="FOL LN-008 · 华为技术" value="FOL_LN_008" />
          <el-option label="FOL LN-009 · 中兴通讯" value="FOL_LN_009" />
        </el-select>
      </div>
      <div class="header-right">
        <el-button text size="small">审核员</el-button>
        <el-button text size="small" :icon="ArrowLeft" @click="$router.push('/')">返回</el-button>
      </div>
    </header>

    <!-- 主容器 -->
    <div class="app-container">
      <!-- 左侧：会话 -->
      <aside class="sessions-panel">
        <div class="panel-header">
          <el-button type="primary" :icon="Plus" size="small" class="new-btn">新会话</el-button>
        </div>

        <div class="sessions-list">
          <div class="session-card active">
            <div class="session-indicator"></div>
            <div class="session-content">
              <div class="session-title">单据LN-008审核</div>
              <div class="session-info">
                <span>3 条</span>
                <span class="dot">·</span>
                <span>2 分钟前</span>
              </div>
            </div>
          </div>

          <div class="session-card">
            <div class="session-indicator"></div>
            <div class="session-content">
              <div class="session-title">制裁名单核查</div>
              <div class="session-info">
                <span>5 条</span>
                <span class="dot">·</span>
                <span>1 小时前</span>
              </div>
            </div>
          </div>

          <div class="session-card">
            <div class="session-indicator"></div>
            <div class="session-content">
              <div class="session-title">汇率核验任务</div>
              <div class="session-info">
                <span>12 条</span>
                <span class="dot">·</span>
                <span>昨天</span>
              </div>
            </div>
          </div>
        </div>

        <div class="panel-footer">
          <div class="status-indicator">
            <span class="status-light active"></span>
            <span class="status-text">GPT-4 在线</span>
          </div>
        </div>
      </aside>

      <!-- 中间：对话 -->
      <main class="chat-panel">
        <!-- 欢迎屏幕 -->
        <div class="welcome-view">
          <div class="welcome-header">
            <div class="welcome-avatar">
              <el-icon><MagicStick /></el-icon>
            </div>
            <h1 class="welcome-title">让审核工作更快一步</h1>
            <p class="welcome-subtitle">解析单据、验证规则、检索证据，为你提供专业的审核辅助</p>
          </div>

          <div class="quick-prompts">
            <div class="prompt-chip">
              <el-icon><DocumentChecked /></el-icon>
              <span>梳理风险点</span>
            </div>
            <div class="prompt-chip">
              <el-icon><Search /></el-icon>
              <span>解释不通过项</span>
            </div>
            <div class="prompt-chip">
              <el-icon><FolderOpened /></el-icon>
              <span>核对材料字段</span>
            </div>
          </div>

          <div class="features-grid">
            <div class="feature-card">
              <el-icon class="feature-icon"><Reading /></el-icon>
              <div class="feature-title">知识库检索</div>
              <div class="feature-desc">查找业务规则、法规条款和历史案例</div>
            </div>
            <div class="feature-card">
              <el-icon class="feature-icon"><DataLine /></el-icon>
              <div class="feature-title">智能分析</div>
              <div class="feature-desc">对比单据字段，识别不一致和风险</div>
            </div>
            <div class="feature-card">
              <el-icon class="feature-icon"><DocumentCopy /></el-icon>
              <div class="feature-title">证据引用</div>
              <div class="feature-desc">每个结论都标注材料来源和页码</div>
            </div>
          </div>
        </div>

        <!-- 消息示例 (v-if="false" 表示默认隐藏,实际使用时根据数据渲染) -->
        <div v-if="false" class="messages-flow">
          <!-- 用户消息 -->
          <div class="message user-msg">
            <div class="msg-content">
              <div class="msg-text">为什么单据 LN-008 被驳回？</div>
            </div>
            <div class="msg-avatar user">我</div>
          </div>

          <!-- 助手消息 -->
          <div class="message assistant-msg">
            <div class="msg-avatar assistant">
              <el-icon><MagicStick /></el-icon>
            </div>
            <div class="msg-content">
              <!-- 执行轨迹 -->
              <div class="execution-trace">
                <div class="trace-header" @click="traceExpanded = !traceExpanded">
                  <el-icon class="trace-icon"><Loading class="spin" /></el-icon>
                  <div class="trace-title">
                    <div class="trace-main">执行中</div>
                    <div class="trace-sub">读取材料 → 检索知识库 → 生成建议</div>
                  </div>
                  <el-icon class="trace-toggle" :class="{ expanded: traceExpanded }"><ArrowRight /></el-icon>
                </div>
                <div v-show="traceExpanded" class="trace-body">
                  <div class="trace-step done">
                    <el-icon class="step-status"><CircleCheck /></el-icon>
                    <div class="step-text">
                      <div class="step-name">读取任务材料</div>
                      <div class="step-detail">已加载 5 份单据</div>
                    </div>
                  </div>
                  <div class="trace-step running">
                    <el-icon class="step-status spin"><Loading /></el-icon>
                    <div class="step-text">
                      <div class="step-name">检索知识库</div>
                      <div class="step-detail">找到 3 条证据</div>
                    </div>
                  </div>
                  <div class="trace-step pending">
                    <div class="step-status"></div>
                    <div class="step-text">
                      <div class="step-name">组织审核建议</div>
                    </div>
                  </div>
                </div>
              </div>

              <!-- 回答内容 -->
              <div class="msg-text">
                <p>单据 LN-008 被驳回的主要原因：</p>
                <ol>
                  <li><strong>贷款用途不符（R001）</strong><br>提款申请书用途为"设备采购"，但合同约定为"项目建设"</li>
                  <li><strong>金额超限（R003）</strong><br>申请金额 500 万美元，超过单次上限 300 万美元</li>
                </ol>
              </div>

              <!-- 引用 -->
              <div class="references">
                <div class="ref-label">证据来源</div>
                <div class="ref-tags">
                  <span class="ref-tag rule">R001 贷款用途</span>
                  <span class="ref-tag doc">提款申请书 · p.3</span>
                  <span class="ref-tag kb">业务规则 · 89%</span>
                </div>
              </div>

              <!-- 操作 -->
              <div class="msg-actions">
                <el-button text size="small" :icon="CopyDocument">复制</el-button>
                <el-button text size="small" :icon="Refresh">重新生成</el-button>
              </div>
            </div>
          </div>
        </div>

        <!-- 输入框 -->
        <div class="chat-input">
          <div class="input-wrapper">
            <el-input
              v-model="userInput"
              type="textarea"
              :rows="1"
              :autosize="{ minRows: 1, maxRows: 4 }"
              placeholder="描述你想核对的规则、材料或风险..."
              class="input-field"
            />
            <el-button type="primary" circle :icon="Promotion" class="send-btn"></el-button>
          </div>
          <div class="input-footer">
            <span class="input-hint">受控只读 · 结论由审核人员确认</span>
          </div>
        </div>
      </main>

      <!-- 右侧：技能 -->
      <aside class="skills-panel">
        <div class="panel-header">
          <span class="panel-title">审核技能</span>
          <el-button text size="small" @click="storeVisible = true">全部</el-button>
        </div>

        <div class="skills-group">
          <div class="group-label">常用</div>
          <div class="skill-item">
            <div class="skill-badge">
              <el-icon><Ship /></el-icon>
            </div>
            <div class="skill-text">
              <div class="skill-name">提单验真</div>
              <div class="skill-hint">核验提单关键信息</div>
            </div>
            <el-button size="small" type="primary" round>运行</el-button>
          </div>

          <div class="skill-item">
            <div class="skill-badge">
              <el-icon><Lock /></el-icon>
            </div>
            <div class="skill-text">
              <div class="skill-name">制裁筛查</div>
              <div class="skill-hint">检查制裁名单</div>
            </div>
            <el-button size="small" type="primary" round>运行</el-button>
          </div>

          <div class="skill-item">
            <div class="skill-badge">
              <el-icon><Coin /></el-icon>
            </div>
            <div class="skill-text">
              <div class="skill-name">汇率换算</div>
              <div class="skill-hint">核对币种折算</div>
            </div>
            <el-button size="small" type="primary" round>运行</el-button>
          </div>
        </div>

        <div class="skills-group">
          <div class="group-label">本周热门</div>
          <div class="hot-skill">
            <span class="hot-name">汇率换算</span>
            <span class="hot-count">89 次</span>
          </div>
          <div class="hot-skill">
            <span class="hot-name">节假日核验</span>
            <span class="hot-count">67 次</span>
          </div>
          <div class="hot-skill">
            <span class="hot-name">提单验真</span>
            <span class="hot-count">54 次</span>
          </div>
        </div>
      </aside>
    </div>

    <!-- 技能商店 -->
    <el-dialog v-model="storeVisible" title="审核技能商店" fullscreen class="skill-store-dialog">
      <div class="store-container">
        <div class="store-toolbar">
          <el-input :prefix-icon="Search" placeholder="搜索技能..." class="store-search" />
          <el-radio-group v-model="category" class="store-filters">
            <el-radio-button label="all">全部</el-radio-button>
            <el-radio-button label="doc">单据核验</el-radio-button>
            <el-radio-button label="risk">风险识别</el-radio-button>
            <el-radio-button label="law">法规检索</el-radio-button>
            <el-radio-button label="data">数据处理</el-radio-button>
          </el-radio-group>
        </div>

        <div class="store-grid">
          <div class="store-card">
            <div class="card-cover blue">
              <el-icon class="cover-icon"><Ship /></el-icon>
              <div class="cover-badge">推荐</div>
            </div>
            <div class="card-body">
              <div class="card-header">
                <h3 class="card-title">提单验真</h3>
                <el-tag size="small" effect="plain">#单据核验</el-tag>
              </div>
              <p class="card-desc">核验海运提单的真实性，检测伪造或篡改</p>
              <div class="card-meta">
                <span class="meta-item"><el-icon><TrendCharts /></el-icon> 本周 67 次</span>
              </div>
              <div class="card-actions">
                <el-button text size="small">详情</el-button>
                <el-button type="primary" size="small">立即运行</el-button>
              </div>
            </div>
          </div>

          <div class="store-card">
            <div class="card-cover orange">
              <el-icon class="cover-icon"><Lock /></el-icon>
              <div class="cover-badge new">新</div>
            </div>
            <div class="card-body">
              <div class="card-header">
                <h3 class="card-title">制裁名单筛查</h3>
                <el-tag size="small" effect="plain" type="warning">#风险识别</el-tag>
              </div>
              <p class="card-desc">检查借款人/担保人是否在国际制裁名单中</p>
              <div class="card-meta">
                <span class="meta-item"><el-badge value="新" type="success" /></span>
              </div>
              <div class="card-actions">
                <el-button text size="small">详情</el-button>
                <el-button type="primary" size="small">立即运行</el-button>
              </div>
            </div>
          </div>

          <div class="store-card">
            <div class="card-cover purple">
              <el-icon class="cover-icon"><Coin /></el-icon>
              <div class="cover-badge hot">热门</div>
            </div>
            <div class="card-body">
              <div class="card-header">
                <h3 class="card-title">汇率换算</h3>
                <el-tag size="small" effect="plain" type="info">#数据处理</el-tag>
              </div>
              <p class="card-desc">自动获取实时汇率，计算多币种金额</p>
              <div class="card-meta">
                <span class="meta-item"><el-icon><TrendCharts /></el-icon> 本周 89 次</span>
              </div>
              <div class="card-actions">
                <el-button text size="small">详情</el-button>
                <el-button type="primary" size="small">立即运行</el-button>
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
import {
  ArrowLeft, ArrowRight, CircleCheck, Coin, CopyDocument, DataLine,
  DocumentChecked, DocumentCopy, FolderOpened, Loading, Lock, MagicStick,
  Plus, Promotion, Reading, Refresh, Search, Ship, TrendCharts
} from '@element-plus/icons-vue'

const router = useRouter()
const taskCode = ref('')
const userInput = ref('')
const traceExpanded = ref(true)
const storeVisible = ref(false)
const category = ref('all')
</script>

<style scoped>
/* V2 版本：暗色专业风格 - 金融终端感 */
.assistant-v2.dark-theme {
  height: 100vh;
  background: #0f172a;
  color: #cbd5e1;
  display: flex;
  flex-direction: column;
}

/* 顶部栏 */
.app-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 12px 20px;
  background: #1e293b;
  border-bottom: 1px solid #334155;
}

.header-left, .header-right {
  display: flex;
  align-items: center;
  gap: 16px;
}

.logo {
  display: flex;
  align-items: center;
  gap: 10px;
}

.logo-icon {
  width: 32px;
  height: 32px;
  border-radius: 6px;
  background: linear-gradient(135deg, #3b82f6, #1e40af);
  color: white;
  display: grid;
  place-items: center;
  font-size: 18px;
}

.logo-text {
  font-size: 17px;
  font-weight: 700;
  color: #f1f5f9;
  letter-spacing: 1px;
}

.task-picker {
  width: 220px;
}

/* 主容器 */
.app-container {
  display: grid;
  grid-template-columns: 240px 1fr 280px;
  flex: 1;
  min-height: 0;
  gap: 1px;
  background: #1e293b;
}

/* 左侧会话面板 */
.sessions-panel {
  background: #1e293b;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

.panel-header {
  padding: 16px;
  border-bottom: 1px solid #334155;
}

.new-btn {
  width: 100%;
}

.sessions-list {
  flex: 1;
  overflow-y: auto;
  padding: 12px;
}

.session-card {
  display: flex;
  gap: 10px;
  padding: 12px;
  margin-bottom: 6px;
  border-radius: 8px;
  background: #0f172a;
  border: 1px solid transparent;
  cursor: pointer;
  transition: all 0.2s;
}

.session-card:hover {
  background: #1e293b;
  border-color: #475569;
}

.session-card.active {
  background: #1e3a8a;
  border-color: #3b82f6;
}

.session-indicator {
  width: 4px;
  height: 4px;
  border-radius: 50%;
  background: #64748b;
  margin-top: 8px;
  flex-shrink: 0;
}

.session-card.active .session-indicator {
  background: #3b82f6;
  box-shadow: 0 0 8px #3b82f6;
}

.session-content {
  flex: 1;
  min-width: 0;
}

.session-title {
  font-size: 13px;
  font-weight: 600;
  color: #e2e8f0;
  margin-bottom: 4px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.session-info {
  font-size: 11px;
  color: #64748b;
}

.dot {
  margin: 0 4px;
}

.panel-footer {
  padding: 12px 16px;
  border-top: 1px solid #334155;
}

.status-indicator {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 12px;
  color: #64748b;
}

.status-light {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: #64748b;
}

.status-light.active {
  background: #10b981;
  box-shadow: 0 0 8px #10b981;
}

/* 中间对话面板 */
.chat-panel {
  background: #0f172a;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

.welcome-view {
  flex: 1;
  overflow-y: auto;
  padding: 60px 40px;
  display: flex;
  flex-direction: column;
  align-items: center;
}

.welcome-header {
  text-align: center;
  max-width: 600px;
  margin-bottom: 40px;
}

.welcome-avatar {
  width: 72px;
  height: 72px;
  margin: 0 auto 24px;
  border-radius: 16px;
  background: linear-gradient(135deg, #3b82f6, #1e40af);
  display: grid;
  place-items: center;
  font-size: 36px;
  color: white;
  box-shadow: 0 8px 24px rgba(59, 130, 246, 0.3);
}

.welcome-title {
  font-size: 32px;
  font-weight: 700;
  color: #f1f5f9;
  margin: 0 0 16px;
  letter-spacing: 0.5px;
}

.welcome-subtitle {
  font-size: 15px;
  color: #94a3b8;
  line-height: 1.6;
  margin: 0;
}

.quick-prompts {
  display: flex;
  gap: 12px;
  margin-bottom: 40px;
}

.prompt-chip {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 10px 16px;
  border-radius: 20px;
  background: #1e293b;
  border: 1px solid #334155;
  color: #cbd5e1;
  font-size: 13px;
  cursor: pointer;
  transition: all 0.2s;
}

.prompt-chip:hover {
  background: #334155;
  border-color: #3b82f6;
  transform: translateY(-2px);
}

.features-grid {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 20px;
  max-width: 800px;
  width: 100%;
}

.feature-card {
  padding: 24px;
  border-radius: 12px;
  background: #1e293b;
  border: 1px solid #334155;
  text-align: center;
  transition: all 0.3s;
}

.feature-card:hover {
  border-color: #3b82f6;
  box-shadow: 0 8px 24px rgba(59, 130, 246, 0.15);
  transform: translateY(-4px);
}

.feature-icon {
  font-size: 32px;
  color: #3b82f6;
  margin-bottom: 16px;
}

.feature-title {
  font-size: 15px;
  font-weight: 600;
  color: #f1f5f9;
  margin-bottom: 8px;
}

.feature-desc {
  font-size: 12px;
  color: #64748b;
  line-height: 1.5;
}

/* 消息流 */
.messages-flow {
  flex: 1;
  overflow-y: auto;
  padding: 24px;
}

.message {
  display: flex;
  gap: 12px;
  margin-bottom: 24px;
  max-width: 900px;
}

.user-msg {
  flex-direction: row-reverse;
  margin-left: auto;
}

.assistant-msg {
  margin-right: auto;
}

.msg-avatar {
  width: 36px;
  height: 36px;
  border-radius: 50%;
  display: grid;
  place-items: center;
  flex-shrink: 0;
  font-size: 12px;
  font-weight: 600;
}

.msg-avatar.user {
  background: #1e3a8a;
  color: #93c5fd;
}

.msg-avatar.assistant {
  background: #1e293b;
  color: #3b82f6;
  font-size: 18px;
  border: 1px solid #334155;
}

.msg-content {
  flex: 1;
  padding: 16px;
  border-radius: 12px;
  background: #1e293b;
  border: 1px solid #334155;
}

.user-msg .msg-content {
  background: #1e3a8a;
  border-color: #1e40af;
}

.msg-text {
  font-size: 14px;
  line-height: 1.7;
  color: #cbd5e1;
}

.msg-text p {
  margin: 0 0 12px;
}

.msg-text ol, .msg-text ul {
  margin: 0;
  padding-left: 20px;
}

.msg-text li {
  margin-bottom: 10px;
}

.msg-text strong {
  color: #f1f5f9;
}

/* 执行轨迹 */
.execution-trace {
  margin-bottom: 16px;
  border-radius: 8px;
  background: #0f172a;
  border: 1px solid #334155;
  overflow: hidden;
}

.trace-header {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 12px;
  cursor: pointer;
}

.trace-icon {
  font-size: 20px;
  color: #3b82f6;
}

.trace-title {
  flex: 1;
}

.trace-main {
  font-size: 13px;
  font-weight: 600;
  color: #e2e8f0;
}

.trace-sub {
  font-size: 11px;
  color: #64748b;
  margin-top: 2px;
}

.trace-toggle {
  font-size: 14px;
  color: #64748b;
  transition: transform 0.3s;
}

.trace-toggle.expanded {
  transform: rotate(90deg);
}

.trace-body {
  padding: 0 12px 12px;
}

.trace-step {
  display: flex;
  gap: 12px;
  padding: 8px 0;
}

.step-status {
  font-size: 14px;
  color: #10b981;
  margin-top: 2px;
}

.step-status.spin {
  color: #3b82f6;
}

.trace-step.pending .step-status {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: #475569;
  border: 2px dashed #64748b;
  margin-top: 6px;
}

.step-text {
  flex: 1;
}

.step-name {
  font-size: 12px;
  font-weight: 600;
  color: #cbd5e1;
}

.step-detail {
  font-size: 11px;
  color: #64748b;
  margin-top: 2px;
}

.spin {
  animation: spin 1s linear infinite;
}

@keyframes spin {
  to { transform: rotate(360deg); }
}

/* 引用 */
.references {
  margin-top: 16px;
  padding-top: 16px;
  border-top: 1px solid #334155;
}

.ref-label {
  font-size: 11px;
  font-weight: 600;
  color: #64748b;
  margin-bottom: 8px;
}

.ref-tags {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.ref-tag {
  padding: 4px 10px;
  border-radius: 4px;
  font-size: 11px;
  border: 1px solid;
}

.ref-tag.rule {
  background: rgba(59, 130, 246, 0.1);
  border-color: #3b82f6;
  color: #93c5fd;
}

.ref-tag.doc {
  background: rgba(100, 116, 139, 0.1);
  border-color: #64748b;
  color: #94a3b8;
}

.ref-tag.kb {
  background: rgba(16, 185, 129, 0.1);
  border-color: #10b981;
  color: #6ee7b7;
}

/* 操作 */
.msg-actions {
  display: flex;
  gap: 8px;
  margin-top: 12px;
  padding-top: 12px;
  border-top: 1px solid #334155;
}

/* 输入框 */
.chat-input {
  padding: 16px 24px;
  border-top: 1px solid #334155;
  background: #1e293b;
}

.input-wrapper {
  display: flex;
  gap: 12px;
  align-items: flex-end;
}

.input-field {
  flex: 1;
}

.send-btn {
  width: 40px;
  height: 40px;
  flex-shrink: 0;
}

.input-footer {
  margin-top: 8px;
  text-align: center;
}

.input-hint {
  font-size: 11px;
  color: #475569;
}

/* 右侧技能面板 */
.skills-panel {
  background: #1e293b;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

.panel-title {
  font-size: 14px;
  font-weight: 700;
  color: #e2e8f0;
}

.skills-group {
  padding: 16px;
  border-bottom: 1px solid #334155;
}

.group-label {
  font-size: 11px;
  font-weight: 600;
  color: #64748b;
  margin-bottom: 12px;
  text-transform: uppercase;
  letter-spacing: 0.5px;
}

.skill-item {
  display: flex;
  gap: 10px;
  align-items: flex-start;
  padding: 12px;
  margin-bottom: 8px;
  border-radius: 8px;
  background: #0f172a;
  border: 1px solid #334155;
  transition: all 0.2s;
}

.skill-item:hover {
  border-color: #3b82f6;
  box-shadow: 0 4px 12px rgba(59, 130, 246, 0.1);
}

.skill-badge {
  width: 36px;
  height: 36px;
  border-radius: 8px;
  background: #1e3a8a;
  color: #3b82f6;
  display: grid;
  place-items: center;
  font-size: 18px;
  flex-shrink: 0;
}

.skill-text {
  flex: 1;
  min-width: 0;
}

.skill-name {
  font-size: 13px;
  font-weight: 600;
  color: #e2e8f0;
  margin-bottom: 2px;
}

.skill-hint {
  font-size: 11px;
  color: #64748b;
  line-height: 1.3;
}

.hot-skill {
  display: flex;
  justify-content: space-between;
  padding: 8px 12px;
  margin-bottom: 6px;
  border-radius: 6px;
  background: #0f172a;
  font-size: 12px;
}

.hot-name {
  color: #cbd5e1;
}

.hot-count {
  color: #f59e0b;
  font-weight: 600;
}

/* 技能商店 */
.skill-store-dialog :deep(.el-dialog__body) {
  padding: 0;
}

.store-container {
  padding: 24px;
  background: #0f172a;
  min-height: 100vh;
}

.store-toolbar {
  display: flex;
  gap: 16px;
  margin-bottom: 24px;
}

.store-search {
  width: 300px;
}

.store-filters {
  flex: 1;
}

.store-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(320px, 1fr));
  gap: 20px;
}

.store-card {
  border-radius: 12px;
  background: #1e293b;
  border: 1px solid #334155;
  overflow: hidden;
  transition: all 0.3s;
}

.store-card:hover {
  border-color: #3b82f6;
  box-shadow: 0 12px 28px rgba(59, 130, 246, 0.2);
  transform: translateY(-8px);
}

.card-cover {
  height: 140px;
  display: grid;
  place-items: center;
  position: relative;
}

.card-cover.blue {
  background: linear-gradient(135deg, #3b82f6, #1e40af);
}

.card-cover.orange {
  background: linear-gradient(135deg, #f59e0b, #dc2626);
}

.card-cover.purple {
  background: linear-gradient(135deg, #8b5cf6, #6d28d9);
}

.cover-icon {
  font-size: 48px;
  color: rgba(255, 255, 255, 0.95);
}

.cover-badge {
  position: absolute;
  top: 12px;
  right: 12px;
  padding: 4px 12px;
  border-radius: 12px;
  background: rgba(255, 255, 255, 0.2);
  backdrop-filter: blur(8px);
  font-size: 11px;
  font-weight: 600;
  color: white;
}

.card-body {
  padding: 16px;
}

.card-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 12px;
}

.card-title {
  font-size: 16px;
  font-weight: 700;
  color: #f1f5f9;
  margin: 0;
}

.card-desc {
  font-size: 13px;
  color: #94a3b8;
  line-height: 1.5;
  margin: 0 0 12px;
}

.card-meta {
  margin-bottom: 12px;
}

.meta-item {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  font-size: 12px;
  color: #f59e0b;
}

.card-actions {
  display: flex;
  gap: 8px;
  justify-content: space-between;
}

/* 响应式 */
@media (max-width: 1200px) {
  .app-container {
    grid-template-columns: 220px 1fr;
  }
  .skills-panel {
    display: none;
  }
}

@media (max-width: 768px) {
  .app-container {
    grid-template-columns: 1fr;
  }
  .sessions-panel {
    display: none;
  }
  .features-grid {
    grid-template-columns: 1fr;
  }
}
</style>
