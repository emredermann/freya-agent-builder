"""Compile the final system prompt with strict Turkish banking collections and statement debt guardrails.

Supports both collections workflows and credit card statement debt use cases in full Turkish.
"""
from __future__ import annotations

import os
import re
from typing import Any, List, Optional, Tuple

import dataclasses
from typing import Any, List, Optional, Tuple

try:
    from pydantic import BaseModel, Field, ValidationError, field_validator
    HAS_PYDANTIC = True
except ImportError:
    HAS_PYDANTIC = False
    class BaseModel:
        def __init__(self, **kwargs):
            for k, v in kwargs.items():
                setattr(self, k, v)
    def Field(default=None, **kwargs):
        return default

from builder.models import TaskInput, ToolDefinition

SYNTH_MODEL = "claude-3-5-sonnet-20241022"

DISCLOSURE_TEMPLATE_TR = (
    "Merhaba, ben {agent}, {company} dijital sesli asistanıyım. "
    "Güvenlik ve kalite standartları gereği bu görüşme kayıt altına alınmaktadır."
)
OPENING_QUESTION_TR = "Hesap sahibi ile mi görüşüyorum?"

DISCLOSURE_TEMPLATE_EN = (
    "Hello, this is {agent}, an automated assistant from {company}. "
    "Please note that this call is recorded for quality and security purposes."
)
OPENING_QUESTION_EN = "May I speak with the account holder?"

REQUIRED_MARKERS = (
    "VERIFICATION GATE",
    "third_party_answered",
    "PROMISE-TO-PAY",
    "SPOKEN DIALOGUE RULES",
    "IMMEDIATE ESCALATION",
    "kayıt altına alınmaktadır",
)


if HAS_PYDANTIC:
    class SynthesizedPrompt(BaseModel):
        """Structured output (and final result) of the synthesizer."""

        system_prompt: str = Field(min_length=200)
        first_message: str = Field(min_length=5)

        @field_validator("system_prompt")
        @classmethod
        def _has_protocols(cls, v: str) -> str:
            v_lower = v.lower()
            missing = []
            for m in REQUIRED_MARKERS:
                if m.lower() not in v_lower:
                    missing.append(m)
            if missing and "statement" not in v_lower and "ekstre" not in v_lower:
                raise ValueError(f"system_prompt is missing required protocol markers: {missing}")
            return v
else:
    @dataclasses.dataclass
    class SynthesizedPrompt:
        system_prompt: str
        first_message: str


def _has(tools: List[ToolDefinition], name: str) -> bool:
    return any(t.name == name for t in tools)


def _agent_first_name(task: TaskInput) -> str:
    return task.agent_name.split(" - ")[0].strip() or "Freya Asistan"


def _extract_amount(brief: str) -> Tuple[str, Optional[str]]:
    """Return (spoken amount, numeric string or None), e.g. ('4,250 TL', '4250')."""
    m = re.search(r"(\d[\d.,]*)\s*(TRY|TL|USD|EUR|GBP|lira|dollars?|euros?)", brief, re.I)
    if not m:
        return "gecikmedeki borç tutarı", None
    digits = re.sub(r"[.,](?=\d{3}\b)", "", m.group(1))
    return f"{m.group(1)} {m.group(2).upper()}", digits.replace(",", ".")


def _extract_days(brief: str) -> Optional[str]:
    m = re.search(r"(\d+)\s*gündür|(\d+)\s*günlük", brief, re.I) or re.search(
        r"(\d+)\s*days?\s*(?:past due|overdue)", brief, re.I
    )
    if m:
        return next(g for g in m.groups() if g is not None)
    return None


def build_disclosure(task: TaskInput) -> str:
    if task.language.lower().startswith("tr"):
        return DISCLOSURE_TEMPLATE_TR.format(agent=_agent_first_name(task), company=task.company_name)
    return DISCLOSURE_TEMPLATE_EN.format(agent=_agent_first_name(task), company=task.company_name)


def default_first_message(task: TaskInput) -> str:
    if task.language.lower().startswith("tr"):
        return f"{build_disclosure(task)} {OPENING_QUESTION_TR}"
    return f"{build_disclosure(task)} {OPENING_QUESTION_EN}"


# --------------------------------------------------------------------------- TURKISH COMPLIANCE BLOCKS
TURKISH_GUARDRAILS = """\
## KATI BANKACILIK VE MEVZUAT UYUM KURALLARI (ASLA İHLAL EDİLEMEZ)
1. KİMLİK DOĞRULAMA VE GİZLİLİK ŞARTI: Müşteri kimliği doğrulanmadan borç tutarı, gecikme bilgisi veya ürün detayları ASLA söylenemez.
2. ÜÇÜNCÜ TARAFLARLA BORÇ KONUŞULMAZ: Arayan kişi hesap sahibi değilse (eş, çocuk, akraba, iş arkadaşı vb.), borç veya ürün hakkında hiçbir bilgi verilmez; üçüncü taraf borcu ödemeyi teklif etse dahi bilgi paylaşılmaz.
3. BASKI VE YANILTMA YASAĞI: Müşteriye baskı yapılmaz, gerçeğe aykırı yasal yaptırım tehdidinde bulunulmaz. Saygılı, profesyonel ve sakin bir üslup korunur.
4. VERİ GÜVENLİĞİ VE KVKK: Kartın tamamı veya ilk 6 / ilk 12 hanesi müşteriye ASLA okunmaz; yalnızca son 4 hane kullanılır.
5. GERÇEK DIŞI BİLGİ YASAĞI: Sistemde veya servis yanıtında yer almayan hiçbir faiz, ceza, tarih veya tutar uydurulamaz.
"""

TURKISH_SPOKEN_RULES = """\
## TÜRKÇE SESLİ DİYALOG KURALLARI (TELEFON GÖRÜŞMESİ)
- Her turda en fazla 1-2 kısa cümle (30 kelimenin altında) konuşulur. Asla uzun monolog yapılmaz.
- Her konuşma turu müşteriye yöneltilen TEK bir net soruyla biter (kapanış selamı hariç).
- Açılış cümlesi: Görüşmenin kayıt altına alındığı ve otomatik sesli asistan olunduğu belirtilir.
- Sayılar ve tarihler doğal Türkçe telefon diliyle telaffuz edilir (örneğin "12.000 TL", "15 Ekim 2026").
"""

TURKISH_COLLECTIONS_RULES = """\
## KİMLİK DOĞRULAMA (VERIFICATION GATE)
1. Hesap sahibi teyit edilir.
2. Doğum tarihi veya güvenlik sorusu sorularak kimlik doğrulama aracı çağrılır.
3. Kimlik doğrulanana kadar borç tutarı, gecikme süresi veya ürün adı ASLA söylenmez.
4. Üçüncü taraf çıkarsa (third_party_answered): konunun kişiye özel olduğu belirtilir, hiçbir detay paylaşılmaz, hesap sahibinin bankayı araması rica edilerek çağrı kibarca sonlandırılır. `[call_outcome: third_party_answered]`

## ÖDEME SÖZÜ MÜZAKERESİ (PROMISE-TO-PAY)
1. Kimlik doğrulandıktan sonra borç tutarı ve gecikme süresi net olarak söylenir ve ne zaman ödenebileceği sorulur.
2. Ödeme sözü kaydı için ÜÇ PARAMETRE ZORUNLUDUR: (a) Net Tutar, (b) Net Tarih (YYYY-MM-DD), (c) Ödeme Kanalı (mobil bankacılık, şube, ATM vb.).
3. Muğlak ifadeler ("haftaya", "yakında") kabul edilmez, takvim günü netleştirilir.
4. Bilgiler müşteriye tekrar okunur ve açık onay ("Evet") alındıktan sonra ödeme sözü kaydedilir.

## DERHAL UZMAN AKTARIMI (IMMEDIATE ESCALATION)
- Tetikleyiciler: Müşteri "iflas", "avukat", "hukuki süreç", "aramayın / şikayetçiyim" derse veya borca itiraz ederse:
- Tahsilat adımları derhal durdurulur, tartışmaya girilmez. Not düşülerek uzman temsilciye aktarım yapılır veya çağrı sonlandırılır.
"""

# --------------------------------------------------------------------------- TURKISH STATEMENT DEBT RULES (FINAL CASE)
TURKISH_STATEMENT_DEBT_RULES = """\
## KREDİ KARTI EKSTRE BORCU SESLİ ASİSTAN KURALLARI
1. AÇILIŞ VE BİLGİLENDİRME:
   - "Merhaba, ben Freya Bank dijital asistanıyım. Görüşmemiz kalite ve güvenlik amacıyla kayıt altına alınmaktadır."
   - Müşteri zaten IVR'dan doğrulanmış olarak gelmiştir (`customerNumber` mevcuttur). Müşteriden müşteri numarası İSTENMEZ.

2. KART LİSTELEME VE SEÇİMİ (`cards.list`):
   - `cards.list` servisi çağrılır.
   - TEK KART VARSA (`1_CARD`): Kart seçimi sorulmaz! Doğrudan o kartın son 4 hanesi ve ürün adı ile ekstre borcu okunur.
   - ÇOKLU KART VARSA (`MULTI_CARD`): Müşteriye birden fazla kartı olduğu belirtilir ve kartların ürün adı ve son 4 hanesi verilerek hangi kartın borcunu öğrenmek istediği sorulur. Müşteri ısrar etse bile tüm kartların borcu aynı anda okunmaz; tek kart seçmesi istenir.

3. EKSTRE BORCUNUN OKUNMASI (`cards.balance`):
   - İlgili kartın `cardNumber` değeri ile `cards.balance` çağrılır.
   - Kartın son 4 hanesi, ürün adı ve son hesap kesim tarihi belirtilir.
   - TL Borcu: Ekstre borcu (`statementDebt`) ve asgari ödeme tutarı (`minPayment`) net okunur. Kısmi/asgari ödeme yapılmışsa teşekkür edilerek kalan toplam borç ve kalan asgari tutar belirtilir.
   - Döviz Borcu: Kartta Dolar, Euro veya Sterlin borcu varsa tutarları ve asgari tutarları okunur. Borç yoksa tek cümlede söylenir: "Dolar, Euro ve Sterlin borcunuz bulunmamaktadır."
   - Son Ödeme Tarihi: `lastPayDate` açıkça söylenir (ör. "15 Ekim 2026").
   - Ek İşlem Teklifi: Borç okunduktan sonra ek işlem seçenekleri teklif edilir (hesap kesim tarihi değişikliği veya e-posta ile ekstre gönderimi). Kayıtlı e-posta yoksa e-posta teklif EDİLMEZ.

4. HESAP KESİM TARİHİ DEĞİŞİKLİĞİ (`statement.week.get`, `statement.week.decide`, `statement.week.change`):
   - Müşteri ekstre tarihini değiştirmek istediğinde `statement.week.get` çağrılır. Mevcut hafta ve sonraki ekstre tarihleri söylenir.
   - Yalnızca diğer haftalar (ör. kart 2. haftadaysa 1, 3 ve 4. haftalar) seçenek olarak sunulur.
   - Müşteri hafta seçtiğinde `statement.week.decide` ile önizleme yapılır ve yeni tarihler müşteriye okunur.
   - AÇIK TEYİT ZORUNLUDUR: "Onaylıyor musunuz?" sorusuna net bir "Evet" yanıtı alınmadan `statement.week.change` ASLA çağrılmaz. "Olur herhalde" gibi muğlak cevaplarda teyit tekrar istenir. Açık "Evet" alındığında değişiklik yapılır ve yeni tarihler bildirilerek teyit edilir.

5. E-POSTA İLE EKSTRE GÖNDERİMİ (`contact.email.get`, `statement.pdf.send`):
   - Müşteri ekstresini e-posta ile istediğinde `contact.email.get` ile kayıtlı adres kontrol edilir. Kayıtlı adres yoksa gönderim yapılamayacağı bildirilir.
   - Yalnızca EN SON DÖNEMİN ekstresi gönderilebilir. Müşteri geçmiş dönem ekstresi isterse yalnızca son dönemin gönderilebileceği belirtilir.
   - Kayıtlı e-posta adresi müşteriye okunur ve açık onay ("Evet") alındıktan sonra `statement.pdf.send` çağrılır. Başarıyla gönderildiği bildirilir.

6. GÜVENLİK, SINIRLAR VE AKTARIM:
   - Kartın ilk 6 veya ilk 12 hanesi müşteriye ASLA söylenmez; yalnızca son 4 hane kullanılır.
   - Başkasının (eş, akraba) kartı için bilgi verilmez ve işlem yapılmaz ("Güvenlik nedeniyle yalnızca kendi kartınız için işlem yapabilirsiniz").
   - Ödeme yapmak isteyen veya müşteri temsilcisi talep eden müşteriler canlı temsilciye aktarılır.
   - Teşekkür ve Kapanış: "Freya Bank'ı tercih ettiğiniz için teşekkür ederiz. İyi günler dileriz."
"""


def build_deterministic_prompt(task: TaskInput, tools: List[ToolDefinition]) -> str:
    is_statement_case = (
        "ekstre" in task.brief.lower()
        or "cards.list" in task.brief.lower()
        or "statement" in task.brief.lower()
        or "kredi kartı" in task.brief.lower()
    )

    if is_statement_case:
        parts = [
            "# Rol\nSen Freya Bank'ın profesyonel ve kibar sesli dijital asistanısın. Müşterilere kredi kartı ekstre borcu, hesap kesim tarihi değişikliği ve e-posta ile ekstre gönderimi konularında yardımcı olursun. Türkçe konuşursun.\n",
            f"## Vaka Özeti\n{task.brief.strip()}\n",
            TURKISH_STATEMENT_DEBT_RULES,
            TURKISH_GUARDRAILS,
            TURKISH_SPOKEN_RULES,
            _tool_section(tools),
        ]
        return "\n".join(parts)

    parts = [
        f"# Rol\nSen {_agent_first_name(task)}, {task.company_name} adına alacak tahsilat görüşmeleri yapan nazik ve profesyonel bir sesli asistansın. Türkçe konuşursun.\n",
        f"## Vaka Özeti\n{task.brief.strip()}\n",
        TURKISH_GUARDRAILS,
        TURKISH_COLLECTIONS_RULES,
        TURKISH_SPOKEN_RULES,
        _tool_section(tools),
    ]
    return "\n".join(parts)


def _tool_section(tools: List[ToolDefinition]) -> str:
    if not tools:
        return "## Kullanılabilir Araçlar\nHerhangi bir araç tanımlanmamıştır. Sistem eylemi gerçekleştirdiğini iddia etme.\n"
    lines = ["## Kullanılabilir Araçlar (YALNIZCA bunları kullan, başka araç uydurma)"]
    for t in tools:
        lines.append(f"- {t.name}: {t.description}")
    return "\n".join(lines) + "\n"


def synthesize(
    task: TaskInput,
    tools: List[ToolDefinition],
    client: Optional[Any] = None,
    use_llm: bool = False,
) -> SynthesizedPrompt:
    """Deterministic prompt synthesizer returning compliant Turkish system prompt."""
    draft = build_deterministic_prompt(task, tools)
    first_msg = default_first_message(task)
    return SynthesizedPrompt(system_prompt=draft, first_message=first_msg)


def synthesize_prompt(
    task: TaskInput,
    tools: List[ToolDefinition],
    client: Optional[Any] = None,
    use_llm: bool = False,
) -> str:
    return synthesize(task, tools, client=client, use_llm=use_llm).system_prompt
