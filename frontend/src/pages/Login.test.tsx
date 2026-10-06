import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, describe, expect, test, vi } from 'vitest'
import { Login } from './Login'
import { ApiError, api } from '../api/client'
import { useAuthStore } from '../store/auth'

function Ekran() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return (
    <QueryClientProvider client={queryClient}>
      <MemoryRouter>
        <Login />
      </MemoryRouter>
    </QueryClientProvider>
  )
}

beforeEach(() => {
  useAuthStore.getState().clear()
  vi.restoreAllMocks()
})

describe('Login', () => {
  test('başarılı girişte auth store doldurulur', async () => {
    const user = userEvent.setup()
    vi.spyOn(api, 'post').mockResolvedValue({ user_id: 1, customer_id: 2, is_staff: false })
    render(<Ekran />)

    await user.type(screen.getByLabelText('E-posta'), 'test@example.com')
    await user.type(screen.getByLabelText('Parola'), 'parola123')
    await user.click(screen.getByRole('button', { name: 'Giriş Yap' }))

    await waitFor(() =>
      expect(useAuthStore.getState().user).toEqual({
        userId: 1,
        customerId: 2,
        email: 'test@example.com',
        isStaff: false,
      }),
    )
    expect(api.post).toHaveBeenCalledWith('/api/v1/auth/login', { email: 'test@example.com', password: 'parola123' })
  })

  test('başarısız girişte hata ERİŞİLEBİLİR şekilde gösterilir, store BOŞ kalır', async () => {
    const user = userEvent.setup()
    vi.spyOn(api, 'post').mockRejectedValue(new ApiError(401, 'e-posta veya parola yanlış'))
    render(<Ekran />)

    await user.type(screen.getByLabelText('E-posta'), 'test@example.com')
    await user.type(screen.getByLabelText('Parola'), 'yanlis')
    await user.click(screen.getByRole('button', { name: 'Giriş Yap' }))

    const uyari = await screen.findByRole('alert')
    expect(uyari).toHaveTextContent('e-posta veya parola yanlış')
    expect(useAuthStore.getState().user).toBeNull()
  })

  test('is_staff=true dönerse auth store\'da isStaff=true olarak saklanır', async () => {
    const user = userEvent.setup()
    vi.spyOn(api, 'post').mockResolvedValue({ user_id: 9, customer_id: 1, is_staff: true })
    render(<Ekran />)

    await user.type(screen.getByLabelText('E-posta'), 'personel@example.com')
    await user.type(screen.getByLabelText('Parola'), 'parola123')
    await user.click(screen.getByRole('button', { name: 'Giriş Yap' }))

    await waitFor(() => expect(useAuthStore.getState().user?.isStaff).toBe(true))
  })

  test('kayıt sayfasına bağlantı var', () => {
    render(<Ekran />)
    expect(screen.getByRole('link', { name: 'Kayıt olun' })).toHaveAttribute('href', '/kayit')
  })
})
