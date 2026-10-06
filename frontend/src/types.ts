/** Backend yanıt şekilleri (bkz. app/schemas.py) — tek dosyada, sayfalar
 * arasında kopyalanmasın diye. Para alanları backend'de `Decimal`,
 * JSON'da STRING olarak gelir (ör. "12000.00") — istemci KENDİSİ
 * HESAPLAMAZ, yalnız olduğu gibi gösterir. */

export interface TokenYaniti {
  user_id: number
  customer_id: number
  is_staff: boolean
}

// `tier` yok: kademe yok, her lisans tam sürüm (backend app/models.py::TAM_SURUM_TIER).
export interface PlanItem {
  product_code: string
  product_name: string
}

export interface PlanPrice {
  months: number
  net: string
  vat_rate: string
  vat_amount: string
  total: string
  currency: string
}

export interface Plan {
  id: number
  code: string
  name: string
  items: PlanItem[]
  prices: PlanPrice[]
}

export interface MeResponse {
  user_id: number
  customer_id: number
  customer_name: string
  email: string
  is_staff: boolean
}

export interface TrialSettingsResponse {
  days: number
}

export interface OrderResponse {
  id: number
  customer_id: number
  plan_id: number
  months: number
  quantity: number
  net: string
  vat_rate: string
  vat_amount: string
  total: string
  currency: string
  status: string
  created_at: string
}

export interface SubscriptionPlanItemSummary {
  product_code: string
  product_name: string
}

export interface SubscriptionActivationSummary {
  product_code: string
  mode: string
  created_at: string
  last_seen_at: string | null
  revoked_at: string | null
}

export interface SubscriptionIssuedLicenseSummary {
  license_id: string
  issued_at: string
  expires_at: string
}

export interface SubscriptionResponse {
  id: number
  plan_id: number
  plan_code: string
  plan_name: string
  items: SubscriptionPlanItemSummary[]
  status: string
  current_period_end: string
  activations: SubscriptionActivationSummary[]
  issued_licenses: SubscriptionIssuedLicenseSummary[]
}

export interface LicenseDocumentResponse {
  payload: Record<string, unknown>
  signature: string
}

export interface AdminOrderResponse {
  id: number
  customer_id: number
  customer_name: string
  plan_id: number
  plan_name: string
  months: number
  net: string
  vat_rate: string
  vat_amount: string
  total: string
  currency: string
  status: string
  created_at: string
}

export interface MarkOrderPaidResponse {
  payment_id: number
  order_id: number
  order_status: string
  amount: string
  bank_reference: string
  received_at: string
  marked_by_user_id: number
}

export interface ReleaseResponse {
  id: number
  product_code: string
  product_name: string
  version: string
  package_type: string
  os: string
  arch: string
  file_name: string
  size_bytes: number
  sha256: string
  signed: boolean
  notes: string | null
  published_at: string
}
