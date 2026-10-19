# HookFlow

**Reliable Webhook Delivery Platform | Güvenilir Webhook Teslimat Platformu**

HookFlow is a webhook management and delivery API built with FastAPI, SQLAlchemy, and Python. It provides webhook registration, event management, HTTP delivery attempts, retry handling, and delivery history tracking.

HookFlow, FastAPI, SQLAlchemy ve Python kullanılarak geliştirilmiş bir webhook yönetim ve teslimat API'sidir. Webhook kaydı, olay yönetimi, HTTP teslimat denemeleri, yeniden deneme mekanizması ve teslimat geçmişinin takibini sağlar.

---

## 🇹🇷 Türkçe

### Proje Hakkında

Webhook'lar, bir uygulamada meydana gelen olayların başka bir sisteme HTTP istekleri aracılığıyla iletilmesini sağlar. Ancak hedef sistemin yanıt vermemesi, bağlantı hataları veya HTTP hataları teslimatın başarısız olmasına neden olabilir.

**HookFlow'un amacı**, webhook teslimat sürecini yönetilebilir, izlenebilir ve test edilebilir bir API üzerinden sunmaktır.

Proje geliştirme aşamasındadır. Mevcut sürüm, temel webhook yaşam döngüsünü ve senkron teslimat denemelerini kapsar.

### Özellikler

- **Webhook yönetimi:** Webhook oluşturma ve kayıtlı webhook'ları listeleme.
- **Olay yönetimi:** Webhook'lara olay türü ve JSON payload ile olay gönderme.
- **HTTP teslimatı:** Oluşturulan olayları kayıtlı hedef URL'ye iletme.
- **Yeniden deneme mekanizması:** Başarısız teslimatlarda en fazla 3 deneme ve denemeler arasında artan bekleme süreleri.
- **Teslimat geçmişi:** Deneme numarası, durum, HTTP yanıt kodu, yanıt gövdesi, hata mesajı ve süre bilgilerini kaydetme.
- **URL doğrulaması:** HTTPS zorunluluğu, URL kimlik bilgilerinin reddedilmesi, izin verilmeyen portların engellenmesi ve yerel/genel olmayan IP adreslerinin reddedilmesi.
- **Veri kalıcılığı:** SQLAlchemy üzerinden veritabanı işlemleri.
- **Şema yönetimi:** Alembic ile veritabanı migration altyapısı.
- **API dokümantasyonu:** FastAPI tarafından oluşturulan Swagger UI.
- **Otomatik kalite kontrolleri:** Pytest ve Ruff.
- **CI:** GitHub Actions üzerinden otomatik test ve kod kalitesi kontrolleri.

### Teknolojiler

| Teknoloji | Kullanım amacı |
|---|---|
| Python 3.10+ | Ana programlama dili |
| FastAPI | REST API geliştirme |
| SQLAlchemy 2 | ORM ve veritabanı işlemleri |
| Pydantic | İstek ve yanıt doğrulaması |
| SQLite | Yerel geliştirme veritabanı |
| PostgreSQL driver | PostgreSQL bağlantı desteği |
| Alembic | Veritabanı migration yönetimi |
| HTTPX | HTTP webhook teslimatı |
| Pytest | Otomatik testler |
| Ruff | Lint ve kod biçimlendirme kontrolleri |
| GitHub Actions | Sürekli entegrasyon (CI) |

### API Uç Noktaları

| Metot | Uç nokta | Açıklama |
|---|---|---|
| `GET` | `/health` | Servis durumunu kontrol eder. |
| `POST` | `/webhooks` | Yeni webhook oluşturur. |
| `GET` | `/webhooks` | Kayıtlı webhook'ları listeler. |
| `POST` | `/webhooks/{webhook_id}/events` | Olay oluşturur ve teslimat sürecini başlatır. |
| `GET` | `/webhooks/{webhook_id}/events` | Webhook'a ait olayları listeler. |
| `GET` | `/webhooks/{webhook_id}/events/{event_id}/deliveries` | Bir olayın teslimat geçmişini listeler. |

### Kurulum

**Gereksinimler**

- Python 3.10 veya üzeri
- pip
- Git

**1. Depoyu klonlayın**

```bash
git clone https://github.com/sssamet/hookflow.git
cd hookflow
```

**2. Sanal ortam oluşturun**

Windows PowerShell:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
```

**3. Bağımlılıkları yükleyin**

```bash
python -m pip install --upgrade pip
pip install -r requirements.txt
pip install pytest ruff
```

**4. Ortam değişkenlerini hazırlayın**

```powershell
Copy-Item .env.example .env
```

Gerekirse `.env` dosyasındaki ayarları kendi ortamınıza göre düzenleyin. Gerçek gizli bilgileri `.env` dosyasıyla birlikte Git'e göndermeyin.

**5. API'yi çalıştırın**

```bash
uvicorn app.main:app --reload
```

Varsayılan yerel adres:

`http://127.0.0.1:8000`

Swagger UI:

`http://127.0.0.1:8000/docs`

ReDoc:

`http://127.0.0.1:8000/redoc`

### Örnek Kullanım

Yeni bir webhook oluşturun:

```http
POST /webhooks
Content-Type: application/json
```

```json
{
  "name": "Example Webhook",
  "target_url": "https://example.com/webhook"
}
```

Bir olay oluşturun:

```http
POST /webhooks/{webhook_id}/events
Content-Type: application/json
```

```json
{
  "event_type": "user.created",
  "payload": {
    "user_id": 123,
    "email": "user@example.com"
  }
}
```

Yanıtta oluşturulan olay ve son teslimat denemesinin bilgileri döndürülür. Teslimat geçmişi ilgili endpoint üzerinden ayrıca görüntülenebilir.

> Örnek hedef URL'nin gerçekten webhook kabul etmesi gerekir. Gerçek teslimat sonuçları hedef sunucunun yanıtına ve ağ koşullarına bağlıdır.

### Testler ve Kod Kalitesi

Testleri çalıştırın:

```bash
python -m pytest -q
```

Lint kontrolü:

```bash
ruff check app tests
```

Kod biçimlendirme kontrolü:

```bash
ruff format --check app tests
```

GitHub Actions yapılandırması, push ve pull request işlemlerinde bu kontrolleri otomatik çalıştırmak üzere hazırlanmıştır.

### Güvenlik Notları

HookFlow, hedef URL'lerin doğrulanması için temel korumalar içerir. HTTP yerine HTTPS gerektirir, URL içine gömülü kullanıcı adı ve parola bilgilerini reddeder ve yerel ya da genel olmayan IP adreslerine yönelik hedefleri engellemeye çalışır.

**Önemli:** DNS çözümlemesi ile gerçek bağlantı arasında DNS rebinding gibi riskler oluşabileceğinden mevcut URL doğrulaması tek başına üretim seviyesinde SSRF koruması olarak değerlendirilmemelidir. Üretim kullanımı öncesinde bağlantı anında IP doğrulaması, güvenli DNS/bağlantı yönetimi, egress ağ politikaları, kimlik doğrulama, oran sınırlama, sır yönetimi ve kapsamlı güvenlik testleri gereklidir.

Mevcut teslimat mekanizması senkron çalışır. Yüksek hacimli üretim ortamları için kuyruk tabanlı asenkron işleme, kalıcı görev yönetimi, gözlemlenebilirlik ve kontrollü tekrar denemeleri ayrıca geliştirilmelidir.

### Geliştirme Yol Haritası

- [x] Temel FastAPI uygulaması
- [x] Webhook oluşturma ve listeleme
- [x] Olay oluşturma ve listeleme
- [x] HTTP teslimat denemeleri ve yeniden deneme mekanizması
- [x] Teslimat geçmişi
- [x] Temel URL doğrulaması
- [x] Otomatik API testleri
- [x] Ruff yapılandırması
- [x] GitHub Actions CI iş akışı
- [ ] Kuyruk tabanlı asenkron teslimat
- [ ] API anahtarı ve webhook imzası doğrulaması
- [ ] Gelişmiş SSRF koruması
- [ ] Oran sınırlama ve güvenlik politikaları
- [ ] Gelişmiş loglama ve metrikler
- [ ] Docker tabanlı dağıtım
- [ ] Daha kapsamlı entegrasyon ve hata senaryosu testleri

### Lisans

Lisans henüz belirlenmemiştir. Lisans dosyası eklenene kadar proje için açık kaynak lisansı varsayılmamalıdır.

---

## 🇬🇧 English

### About the Project

Webhooks allow applications to notify external systems about events through HTTP requests. Delivery can fail because of unavailable target services, network errors, or unsuccessful HTTP responses.

**HookFlow aims to make webhook delivery manageable, observable, and testable** through a dedicated API.

The project is under active development. The current implementation covers the core webhook lifecycle and synchronous delivery attempts.

### Features

- **Webhook management:** Create and list webhook registrations.
- **Event management:** Create events with event types and JSON payloads.
- **HTTP delivery:** Send events to registered target URLs.
- **Retry mechanism:** Up to three delivery attempts with increasing delays between retries.
- **Delivery history:** Record attempt numbers, statuses, HTTP response codes, response bodies, error messages, and durations.
- **Target URL validation:** Require HTTPS, reject embedded URL credentials and disallowed ports, and reject localhost and non-public IP addresses.
- **Database persistence:** Database access through SQLAlchemy.
- **Schema migrations:** Alembic migration infrastructure.
- **API documentation:** Interactive Swagger UI generated by FastAPI.
- **Automated quality checks:** Pytest and Ruff.
- **Continuous integration:** GitHub Actions workflow for automated testing and code quality checks.

### Technology Stack

| Technology | Purpose |
|---|---|
| Python 3.10+ | Core programming language |
| FastAPI | REST API framework |
| SQLAlchemy 2 | ORM and database access |
| Pydantic | Request and response validation |
| SQLite | Local development database |
| PostgreSQL driver | PostgreSQL connectivity |
| Alembic | Database migrations |
| HTTPX | HTTP webhook delivery |
| Pytest | Automated testing |
| Ruff | Linting and formatting checks |
| GitHub Actions | Continuous integration |

### API Endpoints

| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/health` | Check service health. |
| `POST` | `/webhooks` | Register a new webhook. |
| `GET` | `/webhooks` | List registered webhooks. |
| `POST` | `/webhooks/{webhook_id}/events` | Create an event and initiate delivery. |
| `GET` | `/webhooks/{webhook_id}/events` | List events for a webhook. |
| `GET` | `/webhooks/{webhook_id}/events/{event_id}/deliveries` | Retrieve an event's delivery history. |

### Installation

**Requirements**

- Python 3.10 or newer
- pip
- Git

**1. Clone the repository**

```bash
git clone https://github.com/sssamet/hookflow.git
cd hookflow
```

**2. Create a virtual environment**

Windows PowerShell:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
```

**3. Install dependencies**

```bash
python -m pip install --upgrade pip
pip install -r requirements.txt
pip install pytest ruff
```

**4. Configure environment variables**

```powershell
Copy-Item .env.example .env
```

Adjust the settings in `.env` if necessary. Never commit real secrets or credentials.

**5. Start the API**

```bash
uvicorn app.main:app --reload
```

Local base URL:

`http://127.0.0.1:8000`

Swagger UI:

`http://127.0.0.1:8000/docs`

ReDoc:

`http://127.0.0.1:8000/redoc`

### Example Usage

Register a webhook:

```http
POST /webhooks
Content-Type: application/json
```

```json
{
  "name": "Example Webhook",
  "target_url": "https://example.com/webhook"
}
```

Create an event:

```http
POST /webhooks/{webhook_id}/events
Content-Type: application/json
```

```json
{
  "event_type": "user.created",
  "payload": {
    "user_id": 123,
    "email": "user@example.com"
  }
}
```

The response includes the created event and the latest delivery attempt. Delivery history can be retrieved through the corresponding endpoint.

> The example target must actually accept webhook requests. Delivery results depend on the target server's response and network conditions.

### Testing and Code Quality

Run the test suite:

```bash
python -m pytest -q
```

Run lint checks:

```bash
ruff check app tests
```

Check formatting:

```bash
ruff format --check app tests
```

The GitHub Actions workflow is configured to run these checks automatically on pushes and pull requests.

### Security Considerations

HookFlow implements baseline target URL validation. It requires HTTPS, rejects embedded URL credentials, and attempts to block localhost and non-public IP addresses.

**Important:** DNS rebinding and time-of-check/time-of-use issues mean that the current URL validation alone must not be considered production-grade SSRF protection. Before production use, additional safeguards are needed, including connection-time IP validation, safe DNS and connection handling, egress network policies, authentication, rate limiting, secret management, and comprehensive security testing.

The current delivery mechanism is synchronous. High-volume production deployments would require additional work on asynchronous queue-based processing, durable task management, observability, and controlled retries.

### Roadmap

- [x] Core FastAPI application
- [x] Webhook registration and listing
- [x] Event creation and listing
- [x] HTTP delivery attempts and retry handling
- [x] Delivery history
- [x] Baseline target URL validation
- [x] Automated API tests
- [x] Ruff configuration
- [x] GitHub Actions CI workflow
- [ ] Queue-based asynchronous delivery
- [ ] API key and webhook signature verification
- [ ] Advanced SSRF protection
- [ ] Rate limiting and security policies
- [ ] Enhanced logging and metrics
- [ ] Docker-based deployment
- [ ] More comprehensive integration and failure-scenario tests

### License

A license has not yet been selected. The project should not be assumed to be open source until a license is added.
