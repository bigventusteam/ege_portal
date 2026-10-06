import { useEffect } from 'react'
import { api } from '../api/client'
import { useAuthStore } from '../store/auth'
import type { MeResponse } from '../types'

/**
 * Sayfa açılışında oturumu HttpOnly çerezden kurar: `GET /api/v1/auth/me`.
 * 401 → oturum yok (herkese açık sayfalar normal açılır; bu yolun 401'i
 * /giris'e yönlendirmez, bkz. api/client.ts). Ağ hatasında da güvenli
 * taraf seçilir: oturum yok sayılır.
 */
export function OturumYukleyici() {
  const setUser = useAuthStore((s) => s.setUser)
  const clear = useAuthStore((s) => s.clear)

  useEffect(() => {
    let iptal = false
    api
      .get<MeResponse>('/api/v1/auth/me')
      .then((me) => {
        if (!iptal) setUser({ userId: me.user_id, customerId: me.customer_id, email: me.email, isStaff: me.is_staff })
      })
      .catch(() => {
        if (!iptal) clear()
      })
    return () => {
      iptal = true
    }
  }, [setUser, clear])

  return null
}
