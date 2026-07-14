"""
সব fixed configuration এক জায়গায় — Customer/Buyer লিস্ট এবং BD সরকারি ছুটির তালিকা।
নতুন Customer/Buyer যোগ করতে চাইলে শুধু নিচের লিস্টে একটা লাইন যোগ করুন, কোথাও
কোড পরিবর্তন করার দরকার নেই।

গুরুত্বপূর্ণ: BD_HOLIDAYS_2026 লিস্টটা প্রতি বছর নতুন করে বসাতে হবে (সরকার প্রতি
বছর নতুন করে ছুটির তালিকা প্রকাশ করে)। প্রতিটা এন্ট্রি "YYYY-MM-DD" ফরম্যাটে।
"""
import re

# ---------------------------------------------------------------------------
# IN-HOUSE customer এবং buyer লিস্ট (case-sensitive — ERP-এর সাথে হুবহু মিলতে হবে)
# ---------------------------------------------------------------------------
CUSTOMERS = {
    "IN-HOUSE": [
        "Epyllion Style Limited",
        "Epyllion Knitwears Limited",
        "Dekko Knitwears Limited",
        "Dazzling Dresses Ltd.",
    ],
    # আপাতত OUT-HOUSE-এর কোনো fixed customer লিস্ট নেই — PDF থেকে auto নেওয়া হবে,
    # অথবা চাইলে এখানে যোগ করে দিতে পারবেন (IN-HOUSE-এর মতো একই ফরম্যাটে)
    # OUT-HOUSE কাস্টমার লিস্ট — নতুন কাস্টমার যোগ হলে এখানে যোগ করুন
    "OUT-HOUSE": [
        "GoodEarth Apparels ltd.",
        "Barnali Textile and Printing Industries (Pvt) Ltd.",
        "Barnali Collections Limited",
        "Modele de Capital Ind Ltd.",
    ],
}

BUYERS = [
    "MARKS & SPENCER SCM LTD.",
    "C&A BUYING GMBH & CO. KG",
    "S.OLIVER",
    "Celio",
    "Next",
    "Calvin Klein",
    "Original Marines",
    "Target Australia",
    "Tommy Hilfiger",
    "Tommy Jeans",
    "American Eagle",
    "Hultafors Group AB",
    "Primark",
    "Aditya Birla",
    "Carhartt",
    "Varner",
    "Express",
    "Country Road",
    "Puma",
    "Lands` End",
    "Ralph Lauren",
    "Stanley Stella",
    "G-Star",
    "Klattermusen",
    "Bonds",
    "Pointer",
    "VISTULA",
]
# এই লিস্টটা এখন থেকে সব মডিউল (Carton, Thermal, ভবিষ্যতের যেকোনো মডিউল)
# শেয়ার করবে — নতুন কোনো buyer যোগ করলে এখানে একবার যোগ করলেই সব মডিউলের
# ড্রপডাউনে দেখা যাবে। কোনো মডিউলে সেই buyer-এর PDF ফরম্যাট এখনো যাচাই করা না
# থাকলে, ওই মডিউলের own "VERIFIED" সাব-লিস্টে না থাকায় প্রসেসিং ব্লক হবে না,
# শুধু Warnings শীটে একটা নোট যোগ হবে (দেখুন thermal_config.py-তে উদাহরণ)।

# ---------------------------------------------------------------------------
# Buyer/Customer Aliases — PDF-এ প্রায়ই সংক্ষিপ্ত বা একটু ভিন্ন বানানে নাম থাকে
# (যেমন PDF-এ 'M&S' কিন্তু আমাদের ক্যানোনিকাল লিস্টে 'MARKS & SPENCER SCM LTD.')।
# এখানে PDF-ভ্যারিয়েন্ট -> আমাদের ক্যানোনিকাল নাম ম্যাপ করে দিলে সিস্টেম অটোমেটিক
# ক্যানোনিকাল নামটাই বসিয়ে দেবে (ফিল্ড অটো-লক হয়ে যাবে) এবং মিসম্যাচ এরর আসবে না।
#
# নতুন কোনো buyer/customer PDF-এ ভিন্ন নামে দেখলে শুধু এখানে একটা লাইন যোগ করুন —
# key-এর case/স্পেসিং নিয়ে চিন্তার দরকার নেই (মিলানো হয় case-insensitive ভাবে)।
# ---------------------------------------------------------------------------
# ---------------------------------------------------------------------------
# যেসব buyer-এর Carton PDF ফরম্যাট আসলেই টেস্ট করে নিশ্চিত হওয়া গেছে —
# নতুন buyer-এর PDF যাচাই করে নিশ্চিত হওয়ার পর এখানে যোগ করুন (BUYERS
# লিস্টে যেভাবে বানান লেখা আছে হুবহু সেভাবেই)। এই লিস্টে না থাকা buyer
# ব্লক হবে না, শুধু আউটপুটে একটা সতর্কতা (warning) যোগ হবে।
# ---------------------------------------------------------------------------
CARTON_VERIFIED_BUYERS = [
    "Tommy Jeans",
    "Target Australia",
    "American Eagle",
    "Hultafors Group AB",
    "Primark",
    "Aditya Birla",
]

BUYER_ALIASES = {
    "M&S": "MARKS & SPENCER SCM LTD.",
    "MARKS & SPENCER": "MARKS & SPENCER SCM LTD.",
    "C&A": "C&A BUYING GMBH & CO. KG",
}

CUSTOMER_ALIASES = {
    "DEKKO KNITWEARS LTD.": "Dekko Knitwears Limited",
}

# ---------------------------------------------------------------------------
# Item Name Aliases — কিছু buyer-এর PDF-এ item name আমাদের ERP-এর নামের থেকে
# ভিন্ন থাকে (যেমন Bonds-এর PDF-এ 'Pal Box' থাকে, কিন্তু আমাদের ERP-এ ওটাকে
# 'Palbox Carton' নামে ঢুকাতে হয়)। এখানে ম্যাপ করা থাকলে ফাইনাল Mapped
# Template (Sheet1)-এ সঠিক ERP নামটাই বসবে — Raw Data/PO Details শীটে অবশ্য
# PDF-এর আসল নামটাই (অপরিবর্তিত) থাকবে, রেফারেন্সের জন্য।
# ---------------------------------------------------------------------------
ITEM_NAME_ALIASES = {
    "Pal Box": "Palbox Carton",
    "Pal Box Cover Top": "Palbox Top",
    "Carton Corner Support": "Divider",
}


def _norm_key(s):
    return re.sub(r'\s+', ' ', str(s or '')).strip().upper()


def resolve_alias(name, alias_map):
    """name-এর normalize (case/বাড়তি-স্পেস উপেক্ষা করে) key দিয়ে alias_map-এ
    খোঁজে; মিল পেলে ক্যানোনিকাল নামটা রিটার্ন করে, না পেলে input অপরিবর্তিত
    রিটার্ন করে (alias না থাকলে কোনো ক্ষতি হয় না)।"""
    if not name:
        return name
    key = _norm_key(name)
    for k, v in alias_map.items():
        if _norm_key(k) == key:
            return v
    return name

# ---------------------------------------------------------------------------
# Customer-wise Delivery Address — আপনার দেওয়া delivery_place.xlsx থেকে বসানো হয়েছে
# (Customer name -> Delivery address name(s), ফাইলে যে অর্ডারে ছিল সেই অর্ডারেই)।
# নতুন সারি যোগ করতে চাইলে শুধু নিচে একটা key/value যোগ করুন, কোথাও কোড বদলাতে হবে না।
# ---------------------------------------------------------------------------
DELIVERY_ADDRESSES = {
    'Renaissance Apparels Limited': ['Renaissance Apparels Limited (RAL)', 'Southern Garments Ltd (SGL)'],
    'SQ Celcius Limited': ['SQ Celcius Limited (Unit-2)'],
    'Ventura (HK) Trading Limited': ['Ventura Latherware Mfy. (BD) Ltd.'],
    'Sterling Styles Limited': ['Sterling Styles Ltd.-Factory', 'Aspire Garments Limited', 'TECH MAX LIMITED'],
    'Four Design Private Limited': ['Four Design (Pvt) Limited'],
    'Genesis Fashions Ltd.': ['Genesis Fashion Ltd.'],
    'Evergreen Products Factory (BD) Limited': ['Uttara EPZ, Nilphamari'],
    'Midland Knitwear Limited': ['Midland Knitwear Limited'],
    'International Knitwear & Apparels Ltd. (Unit-2)': ['Esses Fashions Limited', 'International Knitwear & Apparels Ltd.', 'NDIL-2 STORE', 'CFDL-5 STORE', 'NDIL-1 STORE'],
    'Norp Knit Industries Ltd.': ['Prudent Fashions Ltd.', 'Norp Knit (Unit-2)', 'Norp Knit (NU)'],
    'Epyllion Style Limited': ['Epyllion Knitwear Limited-Extention (Highway Unit)', 'Epyllion Style Limited', 'Epyllion Style Limited - Extension', 'Epyllion Knitwears Limited'],
    'Columbia Garments Limited': ['Columbia Apperals Limited'],
    'Shanta Expressions Ltd.': ['Contept Knitting Ltd.'],
    'Creative Designers Ltd.': ['Tunic Apparels Ltd.'],
    'Young 4 Ever Textiles Limited': ['Young 4 Ever Textiles Ltd'],
    'Kenpark Bangladesh Apparel (Pvt.) Limited': ['Kenpark Bangladesh Apparel (Pvt.) Limited- U-5', 'Kenpark Bangladesh Apparel (Pvt.) Limited- U-2', 'Kenpark Bangladesh Apparel (Pvt.) Limited-U-3', 'Kenpark Bangladesh Apparel (Pvt.) Limited'],
    'Epyllion Knitwears Limited': ['Epyllion Knitwear Limited-Extention (Highway Unit)', 'Epyllion Style Ltd.', 'Dazzling Dresses Ltd.', 'Epyllion Knitwears Ltd.', 'Dekko Knitwears Ltd.', 'Epyllion Style Ltd.-Extension'],
    'Dekko Knitwears Limited': [
        'Dekko Knitwears Ltd.',
        'Epyllion Knitwears Ltd.',
        'Dazzling Dresses Ltd.',
        'Epyllion Style Ltd.',
        'Epyllion Knitex Ltd.',
        'Epyllion Fabrics Ltd.',
        'Nina Kabbo',
        'Epyllion Style Ltd.-Extension',
        'Epyllion Knitwears Limited-Madanpur (Highway Unit)',
    ],
    # OUT-HOUSE কাস্টমার — ডেলিভারি নিজের ঠিকানাতেই হয় (Epyllion-এর কোনো ইউনিটে না)
    'GoodEarth Apparels ltd.': ['GoodEarth Apparels ltd.'],
    'Barnali Textile and Printing Industries (Pvt) Ltd.': [
        'Barnali Textile and Printing (Pvt) Ltd.',
        'SONIA FINE KNIT LIMITED',
    ],
    'Barnali Collections Limited': [
        'Barnali Collection (Pvt.) Ltd.',
        'Barnali Textile and Printing Industries (Pvt) Ltd.',
    ],
    'Modele de Capital Ind Ltd.': [
        'Modele de Capital Ind Ltd.',
        'Modele de Capital Ltd. (Dying Section)',
        'Goumati Knit Wears Ltd.',
    ],
    'Impress Fashion Limited': ['Impress Fashion Ltd.'],
    'Dazzling Dresses Ltd.': ['Dazzling Dresses Ltd.', 'Epyllion Style Limited'],
    'Eurotex Knitwear Ltd.': ['Bally Cotton Knitdress Ltd.', 'Consist Apparel Ltd'],
    'Brandix Apparel Ltd.': ['Brandix Apparel Bangladesh Ltd'],
    'Comfit Composite Knit Limited': ['Comfit Composite Knit Ltd. (Unit-3)', 'Comfit Composite Knit Limited, Unit-02', 'Urmi group'],
    'Pioneer Knitwears (BD) Ltd.': ['Pioneer Knitwears (BD) Ltd.-Mymensingh'],
    'PRUDENT FASHION LTD.': ['Norp Knit Industries Ltd. (U-2)'],
    'Sky Trade Global Limited': ['Unimas Sportswear Ltd.'],
    'Pretty Sweaters Ltd.': ['D & S Pretty Fashion Ltd.'],
    'ISHAYAT FASHIONS LTD': ['Sharmin Fashions Ltd.', 'Sharaf Apparels'],
    'Columbia Apparels Limited': ['Columbia Garments Limited.'],
    'Divine Fabrics Ltd.': ['Divine Fabrics LTD'],
    'Barnali Textile and Printing Industries (Pvt) Ltd.': ['Barnali Textile and Printing (Pvt) Ltd.'],
    'Integra Apparels BD Ltd.': ['TSR APPARELS LTD.', 'Integra Design Ltd'],
    'Toshrifa Industries Limited': ['Tosrifa Industries Ltd.'],
    'Fakir Fashion Limited': ['Fakir Fashion Ltd.'],
    'Triple Apparels Limited': ['Triple Apparels Limited', 'HANDZ CLOTHING  BD LTD.', 'AJ Super Garments Ltd', 'BRICKLAND COMPOSITE LIMITED', 'Kimberly Design', 'EAGLE TEXTILES', 'SHAFI PROCESSING IND LTD', 'JAAS Garments Limited', 'NASSA COMPLEX', 'RUMA IMPORT & EXPORT LTD', 'TEMAKAW FASHION LTD'],
    'Everbright Sweater Ltd.': ['Everbright Sweater Ltd.'],
    'Mohsin Knitwears Ltd.': ['MOHSIN KNITWEAS LTD'],
    'Interstoff Apparels Ltd.': ['Interstoff Apparels Ltd.', 'South East Textiles (PVT.) Ltd.', 'Interstoff Clothing Ltd.'],
}

# ---------------------------------------------------------------------------
# BD সরকারি ছুটি — এখন 'holidays' Python প্যাকেজ (PyPI: holidays) থেকে অটো আসে,
# তাই প্রতি বছর হাতে আপডেট করা লাগবে না (date_logic.py-তে ব্যবহার হয়)।
# প্যাকেজ যদি কোনো নির্বাহী আদেশে ঘোষিত বাড়তি ছুটি (Durga Puja, Buddha Purnima,
# National Mourning Day ইত্যাদি) ধরতে না পারে, সেগুলো এখানে ম্যানুয়ালি যোগ করে দিন:
# ফরম্যাট: "YYYY-MM-DD"
# ---------------------------------------------------------------------------
CUSTOM_EXTRA_HOLIDAYS_2026 = [
    "2026-05-01",  # Buddha Purnima (May Day-এর সাথে একই দিন)
    "2026-08-15",  # National Mourning Day
    "2026-09-04",  # Janmashtami
    "2026-10-20", "2026-10-21",  # Durga Puja
]

# ---------------------------------------------------------------------------
# Template-এর Delivery Date কলামে যে ফরম্যাটে ডেট বসবে (Python strftime ফরম্যাট)
# উদাহরণ: "17-Jul-2026". আগে যেভাবে ছিল সেভাবেই রাখা হয়েছে — অন্য ফরম্যাট চাইলে
# এখানে শুধু এই একটা লাইন বদলালেই সব জায়গায় বদলে যাবে।
# ---------------------------------------------------------------------------
DELIVERY_DATE_FORMAT = "%d-%b-%Y"

