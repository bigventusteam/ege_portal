import { create } from 'zustand'
import { persist } from 'zustand/middleware'

/**
 * Bu store GÜVENLİK SINIRI DEĞİL — yalnız arayüzün "oturum açık mı, kime
 * ait" göstergesi. Gerçek doğrulama HER ZAMAN backend'deki HttpOnly oturum
 * çerezidir (bkz. api/client.ts başlık yorumu); burada SIR/token hiç
 * TUTULMAZ, yalnız görüntü amaçlı `userId`/`customerId`/`email` — bunlar
 * localStorage'da görünse bile başlı başına bir yetki vermez (çerez
 * olmadan hiçbir API isteği oturum gerektiren bir uca geçemez). Çerez
 * sunucu tarafında süresi dolmuş/geçersizse ilk API çağrısı 401 döner ve
 * `api/client.ts::onSessionExpired` bu store'u temizler (bkz. main.tsx).
 *
 * `isStaff` de AYNI şekilde yalnız GÖSTERİM amaçlı (Personel menüsünü
 * göster/gizle, yetkisiz rotada 404 göster) — gerçek yetki kontrolü HER
 * personel ucunda backend'deki `require_staff`dir (bkz. StaffRoute.tsx).
 */
export interface OturumKullanicisi {
  userId: number
  customerId: number
  email: string
  isStaff: boolean
}

interface AuthState {
  user: OturumKullanicisi | null
  setUser: (user: OturumKullanicisi) => void
  clear: () => void
}

export const useAuthStore = create<AuthState>()(
  persist(
    (set) => ({
      user: null,
      setUser: (user) => set({ user }),
      clear: () => set({ user: null }),
    }),
    { name: 'ege-portal-auth' },
  ),
)
