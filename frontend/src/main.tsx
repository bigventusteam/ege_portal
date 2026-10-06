import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { BrowserRouter } from 'react-router-dom'
import App from './App'
import './index.css'
import { onSessionExpired } from './api/client'
import { useAuthStore } from './store/auth'

// Oturum çerezi geçersiz/süresi dolmuşsa (herhangi bir API 401 dönerse —
// giriş/kayıt denemesi HARİÇ, bkz. api/client.ts) yerel "oturum açık"
// göstergesini temizle ve giriş sayfasına yönlendir.
onSessionExpired(() => {
  useAuthStore.getState().clear()
  if (window.location.pathname !== '/giris') window.location.assign('/giris')
})

const queryClient = new QueryClient({
  defaultOptions: { queries: { retry: false } },
})

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <App />
      </BrowserRouter>
    </QueryClientProvider>
  </StrictMode>,
)
