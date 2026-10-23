# Öğretici örnekler

Windows'ta repo kökünde çalışın. `bat` blokları CMD komutlarıdır; yeni
CMD penceresinde önce `call .venv\Scripts\activate.bat` çalıştırın.
`python` blokları [README](../README.md) içindeki `main` importunu ve gizli parola
girişini yaptığınız **aynı Python konsolunda** çalıştırılır. Python konsolundan
çıkmak için `exit()` yazın; yeniden açtığınızda kimlik bilgilerini tekrar girin.
Python'a verilen `examples/yaml` gibi yollar Windows'ta da geçerlidir.

Bu örnekler gerçek Jira verisi içermez. Önce `python -m jira_test explore` ile test projenizi
keşfedin, sonra örnekleri bir çalışma dizinine kopyalayıp kimlik ve kuralları değiştirin.
Hiçbir örnek kaynak projeye yazmaz; oluşturulan test kayıtları otomatik silinmez.

## Kimlik sözlüğü

| Örnek kimliği | Değiştirmeniz gereken kavram |
|---|---|
| `10001` | Task issue türü |
| `10002` | Subtask issue türü |
| `customfield_10010` | Tek seçim |
| `customfield_10011` | Sayısal alan |
| `customfield_10012` | Özel metin alanı |
| `customfield_10013` | Çoklu seçim |
| `customfield_10099` | Python adaptörü için özel eklenti alanı |
| `20001` / `20002` | Birinci / İkinci seçenek ID'leri |
| `31` / `41` | Workflow geçiş ID'leri |
| `10000` / `10003` / `10004` | Başlangıç / hedef status ID'leri |

Bu kimlikler demo amaçlıdır, Jira varsayılan kimlikleri değildir. Katalog örneklerinde
`fixture.catalog` yolunu güncelleyin veya `--catalog` ile override edin. Hata mesajlarını
Jira dilinize uyarlayın; `required` ve `minimum` örnek metin parçalarıdır.

## YAML örnekleri

Her satır bağımsız bir senaryodur. Ortak çalıştırma biçimi:

```python
main(["validate", "--suite", "my-scenarios"])
main(
    [
        "run",
        "--suite",
        "my-scenarios/09_edit_text.yaml",
        "--config",
        "config.local.yaml",
        "--test-project",
        "AUTOTEST",
    ]
)
```

| No | Dosya | Amaç / önkoşul | Beklenen sonuç |
|---|---|---|---|
| 01 | find_field | Summary create metadata gözlemi | Alan kimliği katalogda doğrulanır |
| 02 | task_field | Task özel metin alanı keşfedilmiş | Task alanı bulunur |
| 03 | subtask_field | Subtask özel metin alanı keşfedilmiş | Subtask alanı bulunur |
| 04 | allowed_options | Seçim alanı ve 20001 seçeneği | Seçenek ID'si bulunur |
| 05 | required_metadata | Summary API zorunluluk bilgisi | Metadata required=true |
| 06 | create_missing_required | Summary zorunlu | Hata + yeni kayıt oluşmaması |
| 07 | create_valid | Oluşturma yetkisi ve diğer gerekli alanlar | Task oluşturulur; açıklama kalıcıdır |
| 08 | optional_empty | Description opsiyonel, boş API değeri null | Oluşturma kabul edilir |
| 09 | edit_text | Description edit ekranında | Düzenleme ve kalıcı metin |
| 10 | number_boundary | Kabul edilen minimum değer 0 | Sınır değeri kaydedilir |
| 11 | change_select | İkinci etiketi, 20002 ID'si | Seçim değişikliği kalıcıdır |
| 12 | change_multiselect | İki seçenek, API liste sırası uyumlu | İki seçim kaydedilir |
| 13 | available_transition | Başlangıçta 31 geçişi açık | Kullanılabilirlik true |
| 14 | valid_transition | 31 ekranında metin alanı; hedef 10003 | Alan değeriyle geçiş gerçekleşir |
| 15 | transition_missing_field | Geçiş alanı zorunlu; başlangıç 10000 | Hata ve statü/kayıt değişmemesi |
| 16 | conditional_transition | Onaylandı değeri 41 koşulunu sağlıyor | Hedef 10004'e geçilir |
| 17 | create_subtask | Parent ve subtask oluşturma izinleri | Yeni subtask oluşturulur |
| 18 | subtask_required | Subtask summary zorunlu | Hata ve subtask oluşmaması |
| 19 | edit_subtask | Description düzenlenebilir | Subtask açıklaması kaydedilir |
| 20 | reject_subtask_edit | Negatif sayıyı edit sırasında reddeden kural | Beklenen ret ve kayıt değişmemesi |

Her dosyanın başındaki yorumlar ilgili önkoşulu tekrar belirtir. İlk beş örnek yalnız
katalog sorgularıdır; canlı bağlantı gerektirmez. `demo-catalog.json` bunlar için
sentetik veri sağlar:

```bat
python -m jira_test run --suite examples/yaml/05_required_metadata.yaml --catalog examples/demo-catalog.json
```

## Python örnekleri

```python
import subprocess
import sys

subprocess.call(
    [
        sys.executable,
        "-m",
        "pytest",
        "examples/python/test_01_components.py",
        "--jira-config",
        "config.local.yaml",
    ]
)
```

1. **test_01_components:** doğrudan UI komponentleri ve REST sonucu; Task/description gerekir.
2. **test_02_parametrized:** üç sayısal değeri bağımsız fixture'larda sınar; sayısal alan gerekir.
3. **test_03_parent_subtask:** parent ilişkisi ve subtask düzenlemesini kontrol eder.
4. **test_04_custom_adapter:** hayali eklenti widget adaptörünü gösterir; şemayı gerçek eklentinize uyarlayın.

## Sık hatalar

- **Unknown context / blocked:** ilgili statü, issue türü veya ekran henüz keşfedilmemiştir.
- **No adapter:** eklenti widget'ı için registry adaptörü gerekir.
- **Field not editable:** yanlış ekran/statü veya locator; kullanıcı yetkisini de kontrol edin.
- **Cannot verify create identity:** gerçek formun project/type/parent kontrol locator'larını uyarlayın.
- **API HTTP 400:** fixture'ın zorunlu alanları veya API değer biçimi eksik; default_fields'i inceleyin.
- **Validation error not observed:** hata metni/lokasyonu uyuşmuyor veya iş kuralı gerçekten çalışmıyor.
- **Timeout:** beklenen UI durumuna ulaşılmadı; bu sonuç iş kuralı reddi değildir.

Yeni bir YAML dosyası eklemek için en yakın örneği kopyalayın, benzersiz `id` verin,
fixture ve assertion'ları değiştirin, offline validate çalıştırın, sonra yalnız o dosyayı
canlı ortamda çalıştırın.
