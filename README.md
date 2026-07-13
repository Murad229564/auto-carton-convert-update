# AutoCarton PO Converter

PO PDF আপলোড করলে সিস্টেম নিজে থেকে:
1. "Purchase Order Details" টেবিল থেকে সব লাইন-আইটেম বের করে
2. Measurement থেকে Length/Width/Height আলাদা করে
3. আপনার Order Upload Template (In-House বা General) format-এ বসায়
4. Raw + Mapped — দুটো Excel ফাইল একটা .zip-এ ডাউনলোড দেয়

এটা ডাটা-ড্রিভেন — মানে PDF-এর ফরম্যাট (কলাম/টেবিল স্ট্রাকচার) একই থাকলে
Qty, Measurement, EWO, Style, PO নম্বর — এসব যত পরিবর্তনই হোক, ঠিকভাবে বের হবে।

## ফাইল স্ট্রাকচার
```
webapp/
  app.py              -> Flask সার্ভার (main entry point)
  extractor.py         -> PDF থেকে ডাটা বের করার লজিক
  builder.py            -> Excel বানানোর লজিক (raw + mapped)
  templates/index.html   -> আপলোড পেজ (UI)
  template_files/          -> আপনার আসল template_inhouse.xlsx ও template_general.xlsx
  requirements.txt          -> প্রয়োজনীয় Python লাইব্রেরি
```

## লোকালি চালানো (নিজের কম্পিউটারে টেস্ট করতে)
```bash
pip install -r requirements.txt
python app.py
```
তারপর ব্রাউজারে যান: http://localhost:5000

## ফ্রি-তে অনলাইনে হোস্ট করা (Render.com)
1. এই পুরো `webapp` ফোল্ডারটা একটা নতুন GitHub রিপোতে push করুন
   (আপনার আগের GitHub Pages প্রজেক্টগুলোর মতোই, শুধু এবার এটা GitHub Pages না —
   Render.com-এ "Web Service" হিসেবে ডিপ্লয় হবে যেহেতু এখানে Python কোড চলে)
2. https://render.com -এ ফ্রি অ্যাকাউন্ট বানান, GitHub দিয়ে লগইন করুন
3. "New +" → "Web Service" → আপনার রিপো সিলেক্ট করুন
4. Settings:
   - Build Command: `pip install -r requirements.txt`
   - Start Command: `gunicorn app:app`
   - Instance Type: Free
5. Deploy চাপুন — কয়েক মিনিটে একটা পাবলিক URL পাবেন
   (যেমন: `https://autocarton-po.onrender.com`) — এটা যেকোনো ডিভাইস থেকে খোলা যাবে

বিকল্প (Render slow লাগলে): PythonAnywhere.com-এর ফ্রি প্ল্যানেও এটা চালানো যায়,
প্রসেস প্রায় একই।

## ভবিষ্যতে নতুন Customer/ফরম্যাট যোগ করা
- `extractor.py`-তে `extract_detail_rows()` ফাংশনটা এই একটা নির্দিষ্ট
  টেবিল-লেআউট (EWO No, Style No, Carton Type... ইত্যাদি হেডিং) খোঁজে।
- অন্য customer-এর PDF-এর কলাম/হেডিং যদি ভিন্ন হয়, তাহলে ওই customer-এর
  জন্য এই ফাংশনের একটা আলাদা ভার্সন বানাতে হবে (profile অনুযায়ী), এবং
  `app.py`-তে `profile` ভ্যালু দিয়ে কোনটা ব্যবহার হবে ঠিক করা যাবে।
- আমাকে সেই customer-এর একটা sample PDF দিলে আমি সেই profile-টা বানিয়ে
  একইভাবে যোগ করে দিতে পারব।

## দুইটা আলাদা প্রসেসিং মেথড
Upload page-এ একটা dropdown আছে, প্রতিবার আপলোডের আগে বেছে নিতে হয়:

1. **Rule-Based (এখন সচল)** — শুধু Epyllion Style Limited-এর এই নির্দিষ্ট
   PDF টেবিল-ফরম্যাটের জন্য কাজ করে। কোনো API খরচ নেই, সম্পূর্ণ ফ্রি।
   ভবিষ্যতে আরেকটা বায়ারের ফরম্যাট যোগ করতে চাইলে `extractor.py`-তে
   একটা নতুন profile ফাংশন লিখে দিতে হবে (সেই বায়ারের sample PDF দিলে
   আমি সেটা বানিয়ে দিতে পারব)।

2. **AI-Based (শীঘ্রই আসছে, এখন disabled)** — `ai_extractor.py` ফাইলে
   কোড রেডি আছে কিন্তু এখনো `app.py`-তে সক্রিয় করা হয়নি। এটা যেকোনো
   বায়ারের ভিন্ন ফরম্যাটের PDF থেকেও ডাটা বুঝে বের করতে পারবে, কিন্তু
   একটা AI API (Claude বা Google Gemini) key লাগবে এবং সামান্য খরচ হবে।
   যখন এটা চালু করতে চাইবেন বলবেন — Gemini API-এর একটা উদার ফ্রি
   টায়ার আছে (দৈনিক প্রায় ১,০০০+ request, ক্রেডিট কার্ড ছাড়াই),
   সেটা দিয়েও শুরু করা যায় যদি Claude API-এর খরচ এড়াতে চান।

## Delivery Place — এখন কিভাবে কাজ করে
- config.py-তে DELIVERY_ADDRESSES ডিকশনারিতে আপনার দেওয়া delivery_place.xlsx-এর
  ৩৭টা Customer-এর ঠিকানা বসানো হয়েছে (Customer name -> Delivery address name)।
- Upload page-এ Customer সিলেক্ট করলেই, ওই Customer-এর জন্য যে ঠিকানাগুলো
  লিস্টে আছে সেগুলো Delivery Address ফিল্ডে dropdown আকারে দেখাবে —
  সেখান থেকে সিলেক্ট করে দিলেই হবে, ম্যানুয়ালি আলাদা করে ঠিকানা লেখার দরকার নেই।
- যে Customer-এর জন্য এখনো কোনো ঠিকানা লিস্ট করা নেই, তার ক্ষেত্রে ফিল্ডটা
  ঐচ্ছিক থাকবে এবং চাইলে ম্যানুয়ালি টাইপ করে দেওয়া যাবে।
- নতুন Customer/ঠিকানা যোগ করতে চাইলে শুধু config.py-তে DELIVERY_ADDRESSES-এ
  একটা লাইন যোগ করে দিলেই হবে, অন্য কোনো কোড বদলাতে হবে না।

## এখনো যা নিয়ে আলোচনা বাকি
- Delivery Date-এ শুধু PDF-এর "Delivery Start Date" বসছে; দরকার হলে
  বলুন, End Date বা অন্য কোনো নিয়মে বদলে দেব

## Rule-Based সিস্টেমে Must-have vs Optional ফিল্ড
- **Must-have** (এগুলো ছাড়া WARNINGS.txt-এ সতর্কতা আসবে): Item Name,
  PO Number, EWO No, Style No, Length, Width, Height, Ply, Quantity
- **Optional** (না থাকলে স্বয়ংক্রিয়ভাবে N/A বসবে): Pack Type, Reference,
  Color, Size, Delivery Date

প্রতিবার প্রসেসের zip ফাইলে একটা `WARNINGS.txt` থাকবে (যদি কোনো
must-have field মিসিং থাকে) — সেটা দেখে বুঝবেন কোন রো manually চেক
করা দরকার।
