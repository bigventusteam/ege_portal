import { useState } from 'react'
import { NavLink, Outlet, useNavigate } from 'react-router-dom'
import { api } from '../api/client'
import { useAuthStore } from '../store/auth'
import { strings } from '../strings'

export function Layout() {
  const user = useAuthStore((s) => s.user)
  const clear = useAuthStore((s) => s.clear)
  const navigate = useNavigate()
  const [cikisYapiliyor, setCikisYapiliyor] = useState(false)

  async function cikisYap() {
    setCikisYapiliyor(true)
    try {
      await api.post('/api/v1/auth/logout')
    } catch {
      // Çerez zaten geçersizse logout çağrısı başarısız olabilir — yine de
      // yerel durumu temizleyip çıkış yaptırıyoruz, kullanıcı takılı kalmasın.
    } finally {
      clear()
      setCikisYapiliyor(false)
      navigate('/giris')
    }
  }

  return (
    <div>
      <header className="ege-topbar">
        <strong>{strings.nav.baslik}</strong>
        <nav className="ege-nav">
          <NavLink to="/" end>
            {strings.nav.urunler}
          </NavLink>
          {user && (
            <>
              <NavLink to="/aboneliklerim">{strings.nav.aboneliklerim}</NavLink>
              <NavLink to="/aktivasyon">{strings.nav.aktivasyon}</NavLink>
              <NavLink to="/indirmeler">{strings.nav.indirmeler}</NavLink>
              <NavLink to="/deneme">{strings.nav.deneme}</NavLink>
              {user.isStaff && <NavLink to="/personel/bekleyen-siparisler">{strings.nav.personel}</NavLink>}
            </>
          )}
          {user ? (
            <button className="ege-btn ege-btn-outline" onClick={cikisYap} disabled={cikisYapiliyor}>
              {cikisYapiliyor ? strings.genel.cikisYapiliyor : strings.nav.cikisYap}
            </button>
          ) : (
            <>
              <NavLink to="/giris">{strings.nav.girisYap}</NavLink>
              <NavLink to="/kayit">{strings.nav.kayitOl}</NavLink>
            </>
          )}
        </nav>
      </header>
      <main className="ege-container">
        <Outlet />
      </main>
    </div>
  )
}
