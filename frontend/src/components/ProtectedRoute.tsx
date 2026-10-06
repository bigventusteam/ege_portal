import type { ReactNode } from 'react'
import { Navigate } from 'react-router-dom'
import { useAuthStore } from '../store/auth'
import { strings } from '../strings'

export function ProtectedRoute({ children }: { children: ReactNode }) {
  const user = useAuthStore((s) => s.user)
  const durum = useAuthStore((s) => s.durum)
  // /auth/me henüz dönmediyse yönlendirme YAPMA — yenilemede oturumu açık
  // kullanıcı bir an /giris'e atılmasın.
  if (durum === 'bilinmiyor') return <p>{strings.genel.oturumKontrol}</p>
  if (!user) return <Navigate to="/giris" replace />
  return <>{children}</>
}
