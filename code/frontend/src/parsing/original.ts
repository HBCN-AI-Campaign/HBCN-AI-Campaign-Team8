import { useAuthStore } from '@/stores/auth'

export function originalUrl(file: string) {
  return file.startsWith('uploads/')
    ? '/' + file.split('/').map(encodeURIComponent).join('/')
    : `/pdf/${encodeURIComponent(file)}`
}

export function originalHeaders(): Record<string, string> {
  const { token } = useAuthStore.getState()
  return token ? { Authorization: `Bearer ${token}` } : {}
}

export async function fetchOriginal(file: string) {
  const response = await fetch(originalUrl(file), { headers: originalHeaders() })
  if (!response.ok) throw Error(`原件不可访问（${response.status}），请检查登录或材料归属`)
  return response.blob()
}
