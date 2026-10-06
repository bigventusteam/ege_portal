import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// vitest'in `test` ayarı BİLEREK burada DEĞİL, ayrı `vitest.config.ts`'de —
// `vite`den gelen `defineConfig` ile `vitest/config`den gelen `defineConfig`
// tipleri karışınca `tsc -b` tip hatası veriyor (mapEGE frontend'inde
// yaşanan AYNI sorun, bkz. o projenin vite.config.ts'deki not).
export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      // Backend `uvicorn.run(..., port=8002)` (bkz. app/main.py) — tüm
      // `/api/*` istekleri AYNI ORİJİNMİŞ gibi proxy'lenir, böylece tarayıcı
      // cross-origin görmez ve oturum çerezi (HttpOnly, SameSite=Strict)
      // CORS/credentials karmaşası olmadan normal şekilde gönderilir/kabul
      // edilir (bkz. app/routers/auth.py).
      '/api': {
        target: 'http://localhost:8002',
        changeOrigin: true,
      },
    },
  },
  build: {
    // `app/main.py` bu klasörü (repo kökünde, `frontend/`den BİR ÜST)
    // `index.html`/`assets/` için tarar ve SPA'yı AYNI FastAPI sürecinden
    // sunar (mapEGE'nin geo_service/static deseninin AYNISI, bkz. deploy/
    // Dockerfile) — canlıda frontend ayrı bir origin DEĞİLDİR, SameSite=
    // Strict çerez ve Origin doğrulama middleware'i bunu VARSAYAR.
    outDir: '../static',
    emptyOutDir: true,
  },
})
