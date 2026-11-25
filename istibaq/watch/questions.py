"""The fixed list of questions residents ask, in Arabic and English."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Question:
    topic: str   # fines, bills, helplines, banks, government
    lang: str    # "ar" or "en"
    text: str
    maps: bool = False  # also ask Google Maps (Places)
    ad_prone: bool = False  # one of the five where scam ads show most: the only ones the paid Google check asks


QUESTIONS: tuple[Question, ...] = (
    # Fines
    Question("fines", "en", "pay abu dhabi police traffic fine", ad_prone=True),
    Question("fines", "ar", "دفع مخالفات المرور شرطة أبوظبي"),
    Question("fines", "en", "abu dhabi traffic fines 50% discount"),
    Question("fines", "ar", "خصم المخالفات المرورية أبوظبي"),
    # Bills
    Question("bills", "en", "pay ADDC electricity bill online", ad_prone=True),
    Question("bills", "ar", "دفع فاتورة الكهرباء والماء أبوظبي"),
    Question("bills", "en", "darb toll top up abu dhabi"),
    # Helplines
    Question("helplines", "en", "abu dhabi police customer service number", maps=True, ad_prone=True),
    Question("helplines", "ar", "رقم مساعدة شرطة أبوظبي", maps=True),
    Question("helplines", "en", "aman service report fraud abu dhabi"),
    # Banks
    Question("banks", "en", "FAB online banking login"),
    Question("banks", "en", "ADCB update card details"),
    Question("banks", "ar", "تحديث بيانات البطاقة بنك أبوظبي الأول"),
    Question("banks", "en", "emirates nbd customer care", maps=True, ad_prone=True),
    # Government services
    Question("government", "en", "TAMM login"),
    Question("government", "ar", "تطبيق تم خدمات حكومة أبوظبي"),
    Question("government", "en", "ICP emirates id renewal fee payment"),
    Question("government", "ar", "تجديد الهوية الإماراتية دفع الرسوم"),
    Question("government", "en", "emirates post parcel customs fee"),
    Question("government", "en", "uae visa renewal fee payment online", ad_prone=True),
)
