# Jira test otomasyonu

Jira Data Center projelerini keşfeden, YAML veya Python/pytest senaryolarıyla
kullanıcı davranışlarını Playwright üzerinden test eden araç.

## Kurulum

Python 3.11+ gerekir. Aşağıdaki komutları repo kökünde **Windows CMD** ile çalıştırın:

```bat
python -m venv .venv
call .venv\Scripts\activate.bat
python -m pip install -e ".[dev]"
if not exist config.local.yaml copy config.example.yaml config.local.yaml
```

macOS/Linux'ta ortamı `source .venv/bin/activate` ile açın; yapılandırma örneğini
`config.local.yaml` adıyla kopyalayın. Sonraki komutları sanal ortam açıkken çalıştırın.

`config.local.yaml` içinde Jira HTTPS adresini, kaynak proje ve **ayrı bir test
projesi** anahtarını ayarlayın. Projeler önceden oluşturulmuş olmalıdır.
Varsayılan tarayıcı kurulu Chrome'dur; Edge için `browser: edge` kullanın.
Firefox için `browser: firefox` ayarlayıp `python -m playwright install firefox`
çalıştırın. WebDriver gerekmez.

## Masaüstü arayüzü

```bat
python -m jira_test gui
```

Windows'ta `run-gui.bat` dosyasına çift tıklayarak da açabilirsiniz; Python'un
**Tcl/Tk and IDLE** bileşeni gerekir. Arayüzden bağlantı profili oluşturabilir,
Jira'yı keşfedebilir, test tasarlayıp çalıştırabilir ve sonuçları inceleyebilirsiniz.
**Çevrimdışı demo yükle** seçeneği Jira hesabı gerektirmez.

## Jira olmadan deneyin

```bat
python -m jira_test validate --suite examples/yaml
python -m jira_test query --catalog examples/demo-catalog.json --field summary --source api
python -m jira_test run --suite examples/yaml/05_required_metadata.yaml --catalog examples/demo-catalog.json
```

Bu örnekler sentetik katalog kullanır; Jira bağlantısı veya tarayıcı gerektirmez.
Windows'ta kurulum ve demo kontrollerini otomatik çalıştırmak için `run-demo.bat`
kullanın. Bu dosya ayrı bir `.venv-demo` ortamı oluşturur.

## Canlı Jira kullanımı

Terminalde `python` ile Python konsolunu açın. Aşağıdaki kodu **satır satır** girin;
kullanıcı adı ve parola sorularını yanıtladıktan sonra devam edin:

```python
import getpass
import os
from jira_test.cli import main

os.environ["JIRA_USERNAME"] = input("Jira kullanıcı adı: ")
os.environ["JIRA_PASSWORD"] = getpass.getpass("Jira parolası: ")
```

Kimlik bilgileri yalnız bu süreçte geçerlidir. Aşağıdaki komutları **aynı Python
konsolunda** çalıştırın; `DEMO` ve `AUTOTEST` değerlerini kendi projelerinizle değiştirin:

```python
# Bağlantıyı kontrol edin ve kaynak projeyi keşfedin.
main(["doctor", "--config", "config.local.yaml"])
main(["explore", "--config", "config.local.yaml", "--project", "DEMO"])

# Test projesindeki alan ve workflow kimliklerini bulun.
main(["explore", "--config", "config.local.yaml", "--project", "AUTOTEST",
      "--output", "artifacts/test-catalog"])

# Örnekleri yeni bir klasöre kopyalayın.
import shutil
shutil.copytree("examples/yaml", "my-scenarios")
```

`artifacts/explorer/catalog.html` ve `artifacts/test-catalog/catalog.html`
raporlarını açın. `my-scenarios` içindeki örnek kimlikleri ve kuralları test
projenize uyarlayın, ardından aynı konsolda doğrulayıp tek bir senaryo çalıştırın:

```python
main(["validate", "--suite", "my-scenarios"])
main(["run", "--suite", "my-scenarios/09_edit_text.yaml",
      "--config", "config.local.yaml", "--test-project", "AUTOTEST"])
```

Tüm senaryolar için `--suite` değerini `my-scenarios` yapın. Sonuçlar varsayılan
olarak `artifacts/test-results.json` ve `artifacts/junit.xml` dosyalarına yazılır.
CI'da `JIRA_USERNAME` ve `JIRA_PASSWORD` değişkenlerini secret store üzerinden
sağlayarak `python -m jira_test ...` komutlarını doğrudan kullanabilirsiniz.

## Önemli noktalar

- Keşif salt okunurdur; davranış testleri test projesinde kayıt oluşturup değiştirir.
  Test kayıtları otomatik silinmez.
- Kimlik bilgilerini dosyalara yazmayın. HTTPS ve TLS doğrulaması zorunludur.
- Jira Data Center 8.4+ hedeflenir. SSO/MFA ve CAPTCHA otomasyonu desteklenmez.
  Özel eklenti alanları için adaptör veya locator ayarı gerekebilir.

## Geliştirme ve belgeler

```bat
python -m pytest
python -m ruff check src tests examples/python
python -m mypy src/jira_test
```

- [Ayrıntılı kullanım ve YAML referansı](docs/usage.md)
- [Masaüstü arayüzü](docs/gui.md)
- [YAML ve Python örnekleri](examples/README.md)
- [Mimari ve komponent geliştirme](docs/architecture.md)
