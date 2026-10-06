import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, describe, expect, test, vi } from 'vitest'
import { Register } from './Register'
import { ApiError, api } from '../api/client'
import { useAuthStore } from '../store/auth'

function Ekran() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return (
    <QueryClientProvider client={queryClient}>
      <MemoryRouter>
        <Register />
      </MemoryRouter>
    </QueryClientProvider>
  )
}

beforeEach(() => {
  useAuthStore.getState().clear()
  vi.restoreAllMocks()
})

async function formuDoldur(user: ReturnType<typeof userEvent.setup>, parola = 'parola123', tekrar = 'parola123') {
  await user.type(screen.getByLabelText('Kurum adı'), 'Test Belediyesi')
  await user.type(screen.getByLabelText('E-posta'), 'test@example.com')
  await user.type(screen.getByLabelText('Parola'), parola)
  await user.type(screen.getByLabelText('Parola (tekrar)'), tekrar)
  await user.click(screen.getByRole('button', { name: 'Kayıt Ol' }))
}

describe('Register', () => {
  test('parolalar eşleşmiyorsa API HİÇ ÇAĞRILMAZ, yerel hata gösterilir', async () => {
    const user = userEvent.setup()
    vi.spyOn(api, 'post')
    render(<Ekran />)

    await formuDoldur(user, 'parola123', 'baskaParola')

    expect(await screen.findByRole('alert')).toHaveTextContent('Parolalar eşleşmiyor.')
    expect(api.post).not.toHaveBeenCalled()
  })

  test('başarılı kayıtta auth store doldurulur', async () => {
    const user = userEvent.setup()
    vi.spyOn(api, 'post').mockResolvedValue({ user_id: 5, customer_id: 9, is_staff: false })
    render(<Ekran />)

    await formuDoldur(user)

    await waitFor(() =>
      expect(useAuthStore.getState().user).toEqual({
        userId: 5,
        customerId: 9,
        email: 'test@example.com',
        isStaff: false,
      }),
    )
    expect(api.post).toHaveBeenCalledWith('/api/v1/auth/register', {
      customer_name: 'Test Belediyesi',
      email: 'test@example.com',
      password: 'parola123',
    })
  })

  test('e-posta zaten kayıtlıysa backend hatası gösterilir', async () => {
    const user = userEvent.setup()
    vi.spyOn(api, 'post').mockRejectedValue(new ApiError(409, 'bu e-posta zaten kayıtlı'))
    render(<Ekran />)

    await formuDoldur(user)

    expect(await screen.findByRole('alert')).toHaveTextContent('bu e-posta zaten kayıtlı')
  })
})
