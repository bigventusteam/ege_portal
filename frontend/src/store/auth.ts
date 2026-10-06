import { create } from 'zustand'

/**
 * Bu store GÜVENLİK SINIRI DEĞİL — yalnız arayüzün "oturum açık mı, kime
 * ait" göstergesi. Gerçek doğrulama HER ZAMAN backend'deki HttpOnly oturum
 * çerezidir (bkz. api/client.ts başlık yorumu); burada SIR/token hiç
 * TUTULMAZ.
 *
 * localStorage'a YAZILMAZ: sayfa her açıldığında oturum
 * `GET /api/v1/auth/me`'den kurulur (bkz. components/OturumYukleyici.tsx).
 * Eskiden persist ediliyordu; çerez geçerli ama localStorage silinmişse
 * kullanıcı "çıkış yapmış" görünüyor, tersi durumda da geçersiz bir oturum
 * ilk 401'e kadar "açık" görünüyordu.
 *
 * `durum`: 'bilinmiyor' iken /auth/me henüz dönmedi — korumalı sayfalar
 * bu sürede yönlendirme yapmaz, bekler (bkz. ProtectedRoute/StaffRoute).
 *
 * `isStaff` de yalnız GÖSTERİM amaçlı — gerçek yetki kontrolü HER personel
 * ucunda backend'deki `require_staff`dir (bkz. StaffRoute.tsx).
 */
export interface OturumKullanicisi {
  userId: number
  customerId: number
  email: string
  isStaff: boolean
}

export type OturumDurumu = 'bilinmiyor' | 'hazir'

interface AuthState {
  user: OturumKullanicisi | null
  durum: OturumDurumu
  setUser: (user: OturumKullanicisi) => void
  clear: () => void
}

export const useAuthStore = create<AuthState>()((set) => ({
  user: null,
  durum: 'bilinmiyor',
  setUser: (user) => set({ user, durum: 'hazir' }),
  clear: () => set({ user: null, durum: 'hazir' }),
}))
