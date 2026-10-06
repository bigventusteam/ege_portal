import { render, screen } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { beforeEach, describe, expect, test } from 'vitest'
import { StaffRoute } from './StaffRoute'
import { useAuthStore } from '../store/auth'

function Ekran() {
  return (
    <MemoryRouter initialEntries={['/personel']}>
      <Routes>
        <Route path="/giris" element={<h1>Giriş Yap</h1>} />
        <Route
          path="/personel"
          element={
            <StaffRoute>
              <h1>Personel Sayfası</h1>
            </StaffRoute>
          }
        />
      </Routes>
    </MemoryRouter>
  )
}

beforeEach(() => {
  useAuthStore.getState().clear()
})

describe('StaffRoute', () => {
  test('oturum yoksa /giris’e yönlendirir', () => {
    render(<Ekran />)
    expect(screen.getByRole('heading', { name: 'Giriş Yap' })).toBeInTheDocument()
  })

  test('oturum var ama personel DEĞİLSE 404 gösterir, rota içeriğini SIZDIRMAZ', () => {
    useAuthStore.getState().setUser({ userId: 1, customerId: 2, email: 'a@b.com', isStaff: false })
    render(<Ekran />)
    expect(screen.getByText('404')).toBeInTheDocument()
    expect(screen.queryByText('Personel Sayfası')).not.toBeInTheDocument()
  })

  test('personel ise içeriği gösterir', () => {
    useAuthStore.getState().setUser({ userId: 1, customerId: 2, email: 'a@b.com', isStaff: true })
    render(<Ekran />)
    expect(screen.getByText('Personel Sayfası')).toBeInTheDocument()
  })
})
