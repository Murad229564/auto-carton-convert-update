"""Customer / Buyer / PO Number / Delivery Address সংক্রান্ত validation।

দুই ধরনের ম্যাচিং আলাদা নিয়মে চলে:
1) আমাদের ইনপুট vs config.py-এর ফিক্সড লিস্ট (Customer/Buyer) —
   এটা 100% case-sensitive, এমনকি কমা/দাঁড়ি পর্যন্ত হুবহু মিলতে হবে।
2) আমাদের ইনপুট vs PDF থেকে বের করা তথ্য (PO Number/Customer/Buyer) —
   এটা case-insensitive (capitalisation-এ পার্থক্য থাকলেও চলবে, কনটেন্ট
   একই হলেই হবে) — কারণ PDF-এর টেক্সট এক্সট্র্যাকশনে case ভিন্ন হতে পারে।
"""
import re

from config import CUSTOMERS, BUYERS, DELIVERY_ADDRESSES


def validate_customer(customer_type, customer_name):
    """Customer নাম আবশ্যক — ফাঁকা রাখা যাবে না, আর অবশ্যই ওই customer_type-এর
    ফিক্সড লিস্টের সাথে case-sensitive মিলতে হবে।"""
    if not customer_name or not customer_name.strip():
        return "Customer নাম আবশ্যক — এই ফিল্ড খালি রাখা যাবে না।"
    allowed = CUSTOMERS.get(customer_type, [])
    if allowed and customer_name not in allowed:
        return (
            f"Customer নাম '{customer_name}' {customer_type} লিস্টের সাথে "
            f"হুবহু (case-sensitive) মিলছে না। লিস্ট থেকে সিলেক্ট করুন।"
        )
    return None


def validate_buyer_in_list(buyer_name, allowed_buyers):
    """সাধারণ (module-independent) Buyer validation — যেকোনো allowed_buyers
    লিস্টের বিরুদ্ধে চেক করা যায়। এভাবে প্রতিটা মডিউল (Carton/Thermal/...)
    নিজের Buyer লিস্ট দিয়ে একই ফাংশন পুনরায় ব্যবহার করতে পারে।"""
    if not buyer_name or not buyer_name.strip():
        return "Buyer নাম আবশ্যক — এই ফিল্ড খালি রাখা যাবে না।"
    if buyer_name not in allowed_buyers:
        return (
            f"Buyer নাম '{buyer_name}' তালিকার সাথে হুবহু (case-sensitive) মিলছে না। "
            f"লিস্ট থেকে সিলেক্ট করুন।"
        )
    return None


def validate_buyer(buyer_name):
    """Carton মডিউলের জন্য ব্যাকওয়ার্ড-কম্প্যাটিবল shortcut (config.BUYERS ব্যবহার করে)।"""
    return validate_buyer_in_list(buyer_name, BUYERS)


def _normalize_for_pdf_match(s):
    """PDF-ম্যাচিং-এর জন্য শুধু case আর বাড়তি হোয়াইটস্পেস উপেক্ষা করা হয়,
    বাকি সব (কমা, দাঁড়ি ইত্যাদি) অক্ষত থাকে।"""
    return re.sub(r'\s+', ' ', str(s or '')).strip().lower()


def values_match_ci(a, b):
    return _normalize_for_pdf_match(a) == _normalize_for_pdf_match(b)


def validate_matches_pdf(label, input_value, pdf_value):
    """input_value (আমাদের ফর্মে দেওয়া) আর pdf_value (PDF থেকে বের করা) —
    এই দুটোর মিল case-insensitive ভাবে চেক করা হয়। PDF থেকে এই তথ্যটা বের
    করাই না গেলে (ফাঁকা), চেক স্কিপ হয়ে যায় (ভুলভাবে ব্লক করা এড়াতে)।"""
    if not pdf_value or not str(pdf_value).strip():
        return None
    if not input_value:
        return None
    if not values_match_ci(input_value, pdf_value):
        return (
            f"{label} '{input_value}' আপলোড করা PDF-এর {label} "
            f"('{pdf_value}') এর সাথে মিলছে না। (এখানে case না মিললেও চলবে, "
            f"কিন্তু আসল লেখাটা মিলতে হবে)"
        )
    return None


def validate_po_number(po_override, pdf_po_number):
    """PO Number ফাঁকা থাকলে PDF থেকে auto নেওয়া হবে।
    ম্যানুয়ালি দিলে PDF-এ পাওয়া PO Number-এর সাথে (case-insensitive) মিলতে হবে।"""
    if not po_override:
        return None
    return validate_matches_pdf('PO Number', po_override, pdf_po_number)


def validate_delivery_address(customer_name, delivery_address):
    """যে Customer-এর জন্য delivery address লিস্ট configure করা আছে
    (config.DELIVERY_ADDRESSES-এ), তার জন্য address দেওয়া বাধ্যতামূলক —
    কিন্তু লিস্টের বাইরে গিয়ে ম্যানুয়ালি নিজের ঠিকানা লিখলেও চলবে (শুধু
    ফাঁকা রাখা যাবে না)। এখনো যে Customer-এর কোনো address লিস্ট করা নেই,
    তার জন্য এই চেক স্কিপ হবে।"""
    allowed = DELIVERY_ADDRESSES.get(customer_name, [])
    if not allowed:
        return None  # এই Customer-এর জন্য এখনো address data যোগ করা হয়নি
    if not delivery_address or not delivery_address.strip():
        return "Delivery Address আবশ্যক — লিস্ট থেকে সিলেক্ট করুন অথবা নিজে টাইপ করুন।"
    return None
