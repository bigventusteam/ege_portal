"""
`activation_request` JSON dosyasının ortak doğrulaması.

Hem ödemeli abonelik çevrimdışı aktivasyonu
(app/services/offline_activation.py) hem deneme lisansı üretimi
(app/services/trial.py) AYNI dosyayı, AYNI kurallarla doğrular — kod TEK
yerde, biri değişince diğeri unutulmasın diye.

## Neyi, neden doğruluyoruz

`activation_request` dosyasını müşteri yükler, içeriği elle değiştirilebilir.
İlk taslak yalnızca `fingerprint.components`'in boş olmadığını kontrol
ediyordu. Bir müşteri `instance_id`/`machine_id`'yi silip yalnızca
`{"hostname": "<hash>"}` gönderirse ne olurdu: `ege_lisans.fingerprint.
fingerprint_matches`, lisanstaki bileşenler arasında hiç ÇAPA (`instance_id`,
`machine_id`) yoksa "en az `min_match` (varsayılan 2, ama
`min(min_match, len(components))` olduğu için TEK bileşenli bir lisansta
1'e düşer) bileşen eşleşsin" kuralına düşüyor — yani tek bir imzalı lisans,
aynı `hostname`'e sahip SINIRSIZ kurulumda geçerli olurdu (hostname zaten
biricik değil, birçok makinede aynı olabilir).

Düzeltme iki katmanlı:
- `instance_id` HER ZAMAN zorunlu. `ege_lisans.fingerprint._instance_id()`
  ürün tarafından üretilip `data_dir`'e KALICI yazılır — bulunamama diye bir
  durumu yok (en kötü ihtimalle `"unknown"` literal'i döner, o da yine
  hash'lenip 64-hex olarak activation_request'e girer). `instance_id` bir
  ÇAPA bileşenidir (`DEFAULT_ANCHOR_COMPONENTS`); lisansta bulunması,
  `fingerprint_matches`'i k-of-n (zayıf) yoluna DÜŞMEDEN doğrudan "tüm çapa
  bileşenleri eşleşmeli" kuralına sokar — açığı bu kapatıyor.
- `machine_id` ZORUNLU TUTULMADI (EGE lider'in önerisi). Sebep:
  `ege_lisans.fingerprint._machine_id()` bazı ortamlarda (machine-id
  dosyası olmayan minimal Docker imajları, registry erişim izni olmayan
  kısıtlı Windows ortamları, `/etc/machine-id` bulunmayan bazı Linux
  dağıtımları) MEŞRU biçimde `None` döner — ürünün kendi
  `activation_request()`'i bu durumda `machine_id`'yi hiç içermez.
  `machine_id`'yi zorunlu tutmak bu meşru kurulumları reddederdi.
  Güvenlik açısından sorun değil: `instance_id` tek başına zaten bir çapa
  olduğu için k-of-n açığını kapatmaya yetiyor.

Ayrıca: yalnızca BİLİNEN bileşen adları (`instance_id`, `machine_id`, `mac`,
`hostname`) kabul edilir, değerler 64 karakter küçük harf hex (sha256 hex
digest biçimi — `ege_lisans.fingerprint.component_hash`'in ürettiği biçim)
olmalıdır; aksi hâlde 422. Dosya boyutu da 16 KB ile sınırlı.

## İkinci bir yol — "unknown" instance_id

`instance_id`'yi zorunlu tutmak tek başına yetmiyordu: `ege_lisans.
fingerprint._instance_id()`, `instance_file` OKUNAMAZ/YAZILAMAZSA sabit
`"unknown"` döner. Veri dizinini kasıtlı olarak salt-okunur yapan (ya da hiç
bağlamayan) bir müşteri, HER kurulumda aynı `hash(product|instance_id|
"unknown")` değerini üretir — bu da yazılamayan veri dizinine sahip HER
kurulumda geçerli, sınırsız kopyalanabilir bir lisansla sonuçlanırdı. Bu,
`ege_lisans` tarafında da (worker_1, "unknown" artık üretilmeyecek) ayrıca
düzeltiliyor; burada — kütüphane tarafı henüz güncellenmemiş sürümlere karşı
da çalışsın diye — bağımsız bir savunma katmanı var: gelen `instance_id`, o
ürün için bilinen "unknown" hash'iyle (`ege_lisans.fingerprint.
component_hash(product, "instance_id", "unknown")` — İTHAL EDİLİYOR,
kopyalanmıyor) birebir karşılaştırılır; eşleşirse 422.

Çapraz-müşteri instance_id çarpışma kontrolü (aynı instance_id başka bir
müşterinin kaydında varsa) BURADA yapılmaz — o, "aynı fingerprint hangi
tablo(lar)da aranır" sorusu her çağıranın (abonelik `Activation`'ları mı,
deneme `TrialActivation`'ları mı, ikisi birden mi) kendi işi olduğu için
`offline_activation.py`/`trial.py`'de ayrı ayrı yapılıyor.
"""
from __future__ import annotations

import json
import re

from ege_lisans.fingerprint import component_hash

MAX_ACTIVATION_REQUEST_BYTES = 16 * 1024
KNOWN_FINGERPRINT_COMPONENTS = {"instance_id", "machine_id", "mac", "hostname"}
REQUIRED_FINGERPRINT_COMPONENTS = {"instance_id"}
_HEX64_RE = re.compile(r"^[0-9a-f]{64}$")
_BILINMEYEN_KURULUM_DEGERI = "unknown"


class InvalidActivationRequestError(Exception):
    def __init__(self, filename: str, reason: str):
        self.filename = filename
        self.reason = reason
        super().__init__(f"'{filename}': {reason}")


def parse_activation_request(filename: str, raw: bytes) -> dict:
    """`raw` bir `activation_request` JSON dosyasının ham baytları.
    Geçerliyse ayrıştırılmış `dict`'i döner, aksi hâlde
    `InvalidActivationRequestError` fırlatır (çağıran genelde bunu 422'ye
    çevirir)."""
    if len(raw) > MAX_ACTIVATION_REQUEST_BYTES:
        raise InvalidActivationRequestError(
            filename, f"dosya çok büyük ({len(raw)} bayt > {MAX_ACTIVATION_REQUEST_BYTES} bayt)"
        )

    try:
        data = json.loads(raw)
    except json.JSONDecodeError as e:
        raise InvalidActivationRequestError(filename, "geçerli bir JSON değil") from e

    if not isinstance(data, dict):
        raise InvalidActivationRequestError(filename, "JSON bir nesne (obje) olmalı")

    product = data.get("product")
    if not isinstance(product, str) or not product:
        raise InvalidActivationRequestError(filename, "'product' alanı eksik/boş")

    fingerprint = data.get("fingerprint")
    components = fingerprint.get("components") if isinstance(fingerprint, dict) else None
    if not isinstance(components, dict) or not components:
        raise InvalidActivationRequestError(filename, "'fingerprint.components' eksik/boş")

    bilinmeyen = set(components) - KNOWN_FINGERPRINT_COMPONENTS
    if bilinmeyen:
        raise InvalidActivationRequestError(filename, f"bilinmeyen parmak izi bileşeni: {sorted(bilinmeyen)}")

    eksik_zorunlu = REQUIRED_FINGERPRINT_COMPONENTS - set(components)
    if eksik_zorunlu:
        raise InvalidActivationRequestError(filename, f"zorunlu bileşen eksik: {sorted(eksik_zorunlu)}")

    for ad, deger in components.items():
        if not isinstance(deger, str) or not _HEX64_RE.fullmatch(deger):
            raise InvalidActivationRequestError(
                filename, f"'{ad}' değeri geçerli bir sha256 hex (64 küçük harf hex karakter) değil"
            )

    kotu_instance_id = component_hash(product, "instance_id", _BILINMEYEN_KURULUM_DEGERI)
    if components["instance_id"] == kotu_instance_id:
        raise InvalidActivationRequestError(
            filename, "kurulum kimliği okunamadı, lisans veri dizininin yazılabilir olduğundan emin olun"
        )

    return data
