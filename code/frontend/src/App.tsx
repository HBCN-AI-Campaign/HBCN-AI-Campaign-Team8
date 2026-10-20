import { useEffect } from 'react'
import { RouterProvider } from 'react-router-dom'
import { ConfigProvider, App as AntdApp } from 'antd'
import zhCN from 'antd/locale/zh_CN'
import { router } from '@/router'
import { bindNavigate, bindMessage } from '@/api'

// 将 api 拦截器的导航回调绑定到 router 实例（替代 Vue 的 router.push）
bindNavigate((path) => router.navigate(path))

const theme = {
  token: {
    colorPrimary: '#3b6fd4',
    borderRadius: 8,
  },
}

/** 内层组件：拿到 antd App 的 message 实例并注入给 api 拦截器 */
function Bootstrap() {
  const { message } = AntdApp.useApp()
  useEffect(() => {
    bindMessage(message)
  }, [message])
  return <RouterProvider router={router} />
}

export default function App() {
  return (
    <ConfigProvider locale={zhCN} theme={theme}>
      <AntdApp>
        <Bootstrap />
      </AntdApp>
    </ConfigProvider>
  )
}
