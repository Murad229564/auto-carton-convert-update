"""
Delivery Date সংক্রান্ত সব লজিক এখানে।

Default নিয়ম: order input date + 7 days। সেই ডেট যদি শুক্রবার হয় অথবা BD সরকারি
ছুটির দিন হয়, তাহলে একদিন একদিন করে এগিয়ে প্রথম এমন দিন খোঁজা হয় যেটা শুক্রবারও না,
ছুটির দিনও না।

উদাহরণ: আজ ৭ তারিখ হলে ডিফল্ট ডেট হবে ১৪ তারিখ। ১৪ তারিখ যদি শুক্রবার বা ছুটির দিন
হয়, তাহলে ১৫ তারিখ হবে (১৫ তারিখও শুক্রবার/ছুটি হলে ১৬ তারিখ, এভাবে এগোতে থাকবে)।

Manual override নিয়ম: ব্যবহারকারী নিজে থেকে ডেট বসাতে চাইলে, সেই ডেট অবশ্যই
current date + 4 days বা তার পরে হতে হবে — না হলে reject করা হবে।

সরকারি ছুটির তালিকা 'holidays' প্যাকেজ (PyPI) থেকে অটো আসে, তাই সার্ভার অনলাইনে
থাকলে প্রতি বছর হাতে আপডেট করা লাগে না। প্যাকেজ যা মিস করে সেটুকু
config.CUSTOM_EXTRA_HOLIDAYS_2026-এ ম্যানুয়ালি যোগ করা যায়।
"""
from datetime import date, timedelta

import holidays as holidays_pkg

from config import CUSTOM_EXTRA_HOLIDAYS_2026, DELIVERY_DATE_FORMAT

FRIDAY = 4  # Python: Monday=0 ... Friday=4


def _bd_holiday_set(year: int) -> set:
    """সেই বছরের BD সরকারি ছুটি 'holidays' প্যাকেজ থেকে + ম্যানুয়াল extra মিলিয়ে রিটার্ন করে।"""
    pkg_holidays = set(d.isoformat() for d in holidays_pkg.Bangladesh(years=[year, year + 1]))
    extra = set(CUSTOM_EXTRA_HOLIDAYS_2026) if year == 2026 else set()
    return pkg_holidays | extra


def is_bd_holiday(d: date) -> bool:
    return d.isoformat() in _bd_holiday_set(d.year)


def get_default_delivery_date(today: date = None) -> date:
    """order input date + 7 days থেকে শুরু করে শুক্রবার/ছুটি এড়িয়ে প্রথম workable day রিটার্ন করে।"""
    today = today or date.today()
    candidate = today + timedelta(days=7)
    while candidate.weekday() == FRIDAY or is_bd_holiday(candidate):
        candidate += timedelta(days=1)
    return candidate


def format_delivery_date(d: date) -> str:
    return d.strftime(DELIVERY_DATE_FORMAT)


def validate_manual_delivery_date(date_str: str, today: date = None):
    """Manual delivery date ভ্যালিড কিনা চেক করে (ফরম্যাট: YYYY-MM-DD, HTML date input থেকে আসে)।
    Returns (is_valid: bool, error_message: str|None, parsed_date: date|None)"""
    today = today or date.today()
    try:
        parsed = date.fromisoformat(date_str)
    except (ValueError, TypeError):
        return False, "Delivery Date ফরম্যাট সঠিক না (YYYY-MM-DD হতে হবে)", None

    min_allowed = today + timedelta(days=4)
    if parsed < min_allowed:
        return False, (
            f"Delivery Date কমপক্ষে {min_allowed.isoformat()} বা তার পরে হতে হবে "
            f"(আজকের তারিখ থেকে ন্যূনতম ৪ দিন পর)"
        ), None

    return True, None, parsed
