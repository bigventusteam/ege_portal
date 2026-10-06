import { render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { beforeEach, describe, expect, test, vi } from 'vitest'
import { OturumYukleyici } from './OturumYukleyici'
import { ProtectedRoute } from './ProtectedRoute'
import { ApiError, api } from '../api/client'
import { useAuthStore } from '../store/auth'

function KorumaliEkran() {
  return (
    <MemoryRouter initialEntries={['/aboneliklerim']}>
      <OturumYukleyici />
      <Routes>
        <Route path="/giris" element={<h1>Giriş Yap</h1>} />
        <Route
          path="/aboneliklerim"
          element={
            <ProtectedRoute>
              <h1>Aboneliklerim</h1>
            </ProtectedRoute>
          }
        />
      </Routes>
    </MemoryRouter>
  )
}

beforeEach(() => {
  vi.restoreAllMocks()
  useAuthStore.setState({ user: null, durum: 'bilinmiyor' })
  localStorage.clear()
})

describe('OturumYukleyici + ProtectedRoute', () => {
  test('oturum /auth/me yanıtından kurulur, korumalı sayfa açılır (localStorage kullanılmaz)', async () => {
    vi.spyOn(api, 'get').mockResolvedValue({
      user_id: 5, customer_id: 9, customer_name: 'Belediye', email: 'a@b.com', is_staff: true,
    })
    render(<KorumaliEkran />)

    expect(await screen.findByRole('heading', { name: 'Aboneliklerim' })).toBeInTheDocument()
    expect(api.get).toHaveBeenCalledWith('/api/v1/auth/me')
    expect(useAuthStore.getState().user).toEqual({ userId: 5, customerId: 9, email: 'a@b.com', isStaff: true })
    expect(localStorage.length).toBe(0)
  })

  test('/auth/me dönene kadar yönlendirme yapılmaz, bekleme mesajı görünür', () => {
    vi.spyOn(api, 'get').mockReturnValue(new Promise(() => {}))
    render(<KorumaliEkran />)
    expect(screen.getByText('Oturum kontrol ediliyor…')).toBeInTheDocument()
    expect(screen.queryByRole('heading', { name: 'Giriş Yap' })).not.toBeInTheDocument()
  })

  test('/auth/me 401 dönerse oturum yok sayılır ve /giris’e gidilir', async () => {
    vi.spyOn(api, 'get').mockRejectedValue(new ApiError(401, 'oturum gerekli'))
    render(<KorumaliEkran />)
    expect(await screen.findByRole('heading', { name: 'Giriş Yap' })).toBeInTheDocument()
    await waitFor(() => expect(useAuthStore.getState().durum).toBe('hazir'))
    expect(useAuthStore.getState().user).toBeNull()
  })
})
