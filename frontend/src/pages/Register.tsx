import { useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { useMutation } from '@tanstack/react-query'
import { api, hataGoster } from '../api/client'
import { useAuthStore } from '../store/auth'
import { strings } from '../strings'
import type { TokenYaniti } from '../types'

export function Register() {
  const navigate = useNavigate()
  const setUser = useAuthStore((s) => s.setUser)
  const [kurumAdi, setKurumAdi] = useState('')
  const [email, setEmail] = useState('')
  const [parola, setParola] = useState('')
  const [parolaTekrar, setParolaTekrar] = useState('')
  const [yerelHata, setYerelHata] = useState<string | null>(null)

  const mutation = useMutation({
    mutationFn: () =>
      api.post<TokenYaniti>('/api/v1/auth/register', { customer_name: kurumAdi, email, password: parola }),
    onSuccess: (data) => {
      setUser({ userId: data.user_id, customerId: data.customer_id, email, isStaff: data.is_staff })
      navigate('/')
    },
  })

  function gonder(e: React.FormEvent) {
    e.preventDefault()
    if (parola !== parolaTekrar) {
      setYerelHata(strings.kayit.parolaUyusmuyor)
      return
    }
    setYerelHata(null)
    mutation.mutate()
  }

  const hataMetni = yerelHata ?? (mutation.isError ? hataGoster(mutation.error) : null)

  return (
    <div className="ege-card" style={{ maxWidth: 400, margin: '40px auto' }}>
      <h1>{strings.kayit.baslik}</h1>
      {hataMetni && (
        <div className="ege-alert ege-alert-err" role="alert">
          {hataMetni}
        </div>
      )}
      <form onSubmit={gonder}>
        <div className="ege-field">
          <label htmlFor="kayit-kurum">{strings.kayit.kurumAdi}</label>
          <input id="kayit-kurum" type="text" required value={kurumAdi} onChange={(e) => setKurumAdi(e.target.value)} />
        </div>
        <div className="ege-field">
          <label htmlFor="kayit-eposta">{strings.kayit.eposta}</label>
          <input
            id="kayit-eposta"
            type="email"
            required
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            autoComplete="email"
          />
        </div>
        <div className="ege-field">
          <label htmlFor="kayit-parola">{strings.kayit.parola}</label>
          <input
            id="kayit-parola"
            type="password"
            required
            value={parola}
            onChange={(e) => setParola(e.target.value)}
            autoComplete="new-password"
          />
        </div>
        <div className="ege-field">
          <label htmlFor="kayit-parola-tekrar">{strings.kayit.parolaTekrar}</label>
          <input
            id="kayit-parola-tekrar"
            type="password"
            required
            value={parolaTekrar}
            onChange={(e) => setParolaTekrar(e.target.value)}
            autoComplete="new-password"
          />
        </div>
        <button type="submit" className="ege-btn" disabled={mutation.isPending}>
          {mutation.isPending ? strings.kayit.gonderiliyor : strings.kayit.gonder}
        </button>
      </form>
      <p style={{ marginTop: 16, fontSize: 14 }}>
        {strings.kayit.hesapVar} <Link to="/giris">{strings.kayit.girisLink}</Link>
      </p>
    </div>
  )
}
