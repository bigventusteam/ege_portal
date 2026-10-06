import { Navigate, Route, Routes } from 'react-router-dom'
import { Layout } from './components/Layout'
import { ProtectedRoute } from './components/ProtectedRoute'
import { StaffRoute } from './components/StaffRoute'
import { Login } from './pages/Login'
import { Register } from './pages/Register'
import { Plans } from './pages/Plans'
import { OrderSummary } from './pages/OrderSummary'
import { Subscriptions } from './pages/Subscriptions'
import { OfflineActivation } from './pages/OfflineActivation'
import { Downloads } from './pages/Downloads'
import { Trial } from './pages/Trial'
import { AdminPendingOrders } from './pages/AdminPendingOrders'

export default function App() {
  return (
    <Routes>
      <Route path="/giris" element={<Login />} />
      <Route path="/kayit" element={<Register />} />
      <Route element={<Layout />}>
        <Route path="/" element={<Plans />} />
        <Route
          path="/siparis"
          element={
            <ProtectedRoute>
              <OrderSummary />
            </ProtectedRoute>
          }
        />
        <Route
          path="/aboneliklerim"
          element={
            <ProtectedRoute>
              <Subscriptions />
            </ProtectedRoute>
          }
        />
        <Route
          path="/aktivasyon"
          element={
            <ProtectedRoute>
              <OfflineActivation />
            </ProtectedRoute>
          }
        />
        <Route
          path="/indirmeler"
          element={
            <ProtectedRoute>
              <Downloads />
            </ProtectedRoute>
          }
        />
        <Route
          path="/deneme"
          element={
            <ProtectedRoute>
              <Trial />
            </ProtectedRoute>
          }
        />
        <Route
          path="/personel/bekleyen-siparisler"
          element={
            <StaffRoute>
              <AdminPendingOrders />
            </StaffRoute>
          }
        />
      </Route>
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  )
}
