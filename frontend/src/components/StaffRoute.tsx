import type { ReactNode } from 'react'
import { Navigate } from 'react-router-dom'
import { NotFound } from '../pages/NotFound'
import { useAuthStore } from '../store/auth'

/** `ProtectedRoute`'tan AYRI: oturum yoksa aynı şekilde /giris'e yönlendirir,
 * ama oturum VAR ve personel DEĞİLSE (`isStaff=false`) sessizce bir 404
 * sayfası gösterir — "bu rota var ama senin için değil" yerine "bu rota
 * hiç yok" (yetkisiz bir kullanıcıya personel rotalarının VARLIĞINI bile
 * belirtmemek için, 2026-10-05 havale/EFT işaretleme görevi). Gerçek yetki
 * kontrolü HER ZAMAN backend'deki `require_staff`dir — bu bileşen yalnız
 * bir UX kısayolu, güvenlik sınırı DEĞİL. */
export function StaffRoute({ children }: { children: ReactNode }) {
  const user = useAuthStore((s) => s.user)
  if (!user) return <Navigate to="/giris" replace />
  if (!user.isStaff) return <NotFound />
  return <>{children}</>
}
