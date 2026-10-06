import { useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { useMutation } from '@tanstack/react-query'
import { api, hataGoster } from '../api/client'
import { useAuthStore } from '../store/auth'
import { strings } from '../strings'
import type { TokenYaniti } from '../types'

export function Login() {
  const navigate = useNavigate()
  const setUser = useAuthStore((s) => s.setUser)
  const [email, setEmail] = useState('')
  const [parola, setParola] = useState('')

  const mutation = useMutation({
    mutationFn: () => api.post<TokenYaniti>('/api/v1/auth/login', { email, password: parola }),
    onSuccess: (data) => {
      setUser({ userId: data.user_id, customerId: data.customer_id, email, isStaff: data.is_staff })
      navigate('/')
    },
  })

  return (
    <div className="ege-card" style={{ maxWidth: 400, margin: '40px auto' }}>
      <h1>{strings.giris.baslik}</h1>
      {mutation.isError && (
        <div className="ege-alert ege-alert-err" role="alert">
          {hataGoster(mutation.error)}
        </div>
      )}
      <form
        onSubmit={(e) => {
          e.preventDefault()
          mutation.mutate()
        }}
      >
        <div className="ege-field">
          <label htmlFor="giris-eposta">{strings.giris.eposta}</label>
          <input
            id="giris-eposta"
            type="email"
            required
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            autoComplete="email"
          />
        </div>
        <div className="ege-field">
          <label htmlFor="giris-parola">{strings.giris.parola}</label>
          <input
            id="giris-parola"
            type="password"
            required
            value={parola}
            onChange={(e) => setParola(e.target.value)}
            autoComplete="current-password"
          />
        </div>
        <button type="submit" className="ege-btn" disabled={mutation.isPending}>
          {mutation.isPending ? strings.giris.gonderiliyor : strings.giris.gonder}
        </button>
      </form>
      <p style={{ marginTop: 16, fontSize: 14 }}>
        {strings.giris.hesapYok} <Link to="/kayit">{strings.giris.kayitLink}</Link>
      </p>
    </div>
  )
}
