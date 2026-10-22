# 🤖 vAvtoXabar Bot

**🇺🇿 [O'zbekcha](#-o'zbekcha) | 🇬🇧 [English](#-english)**

---

<a id="-o'zbekcha"></a>

# 🇺🇿 O'zbekcha

## 📖 Loyiha haqida

**vAvtoXabar Bot** – Telegram uchun avtomatik xabar yuborish boti. Foydalanuvchi o'z Telegram akkauntini bot orqali ulaydi, xabar matnini (yoki rasmini) tayyorlaydi, guruhlarni tanlaydi va belgilangan intervalda xabarlar tanlangan guruhlarga avtomatik yuborib turiladi.

Bot ikkita kutubxonaga tayanadi:

- **python-telegram-bot** – foydalanuvchi bilan muloqot qiluvchi bot qismi (menyu, tugmalar, to'lovlar, admin buyruqlari).
- **Telethon** – foydalanuvchining shaxsiy akkaunti nomidan guruhlarga xabar yuboruvchi qism.

Ma'lumotlar **SQLite** (`bot_data.db`) bazasida saqlanadi.

## ✨ Imkoniyatlari

### Foydalanuvchilar uchun

- 📱 Telegram akkauntni ulash (telefon raqam → kod → kerak bo'lsa 2 bosqichli parol)
- ✏️ Xabar turlari: **matn**, **rasm**, **rasm + matn** (rasm faqat Premium uchun)
- ⏰ Yuborish intervalini sozlash (tayyor tugmalar yoki qo'lda kiritish)
- 👥 Akkauntdagi guruhlar ro'yxatidan sahifalab tanlash (kanallar chiqarib tashlangan)
- ▶️ Yuborishni boshlash / ⏹️ to'xtatish
- 📊 Sessiya statistikasi va umumiy yuborilgan xabarlar soni
- 👑 Premium obuna (⭐ Telegram Stars yoki karta orqali to'lov)
- 🔗 Referral tizimi – taklif qilingan har bir foydalanuvchi uchun chegirma

### Admin uchun

- 💰 Foyda hisobi (naqd va Stars)
- 📢 Barcha foydalanuvchilarga broadcast (matn, rasm, video, fayl)
- 👑 Premium berish / olib tashlash
- ⛔ Bloklash / blokdan chiqarish
- ✅ Karta to'lovlarini tasdiqlash, bekor qilish yoki "yetarli emas" deb belgilash
- 📌 Barcha **bepul** foydalanuvchilar uchun navbatma-navbat yuboriladigan "admin xabari"
- 📈 Statistika kanalida avtomatik yangilanib turuvchi umumiy statistika

## 💎 Tariflar

| Imkoniyat | Oddiy (Free) | Premium |
|---|---|---|
| Minimal interval | 5 daqiqa | 2 daqiqa |
| Maksimal interval | 15 daqiqa | 15 daqiqa |
| Guruhlar soni | 5 ta | 30 ta |
| Sessiyadagi xabarlar | 100 ta | 1000 ta |
| Rasm yuborish | ❌ | ✅ |
| Xabar oxiridagi bot imzosi | Bor | Yo'q |
| Admin xabari (reklama) | Bor | Yo'q |
| Narxi (30 kun) | Bepul | ⭐ 40 Stars yoki 5 000 so'm |

> Qiymatlar `bot.py` boshidagi sozlamalar orqali o'zgartiriladi.

## 🎁 Referral tizimi

- Har bir foydalanuvchining shaxsiy havolasi bor: `https://t.me/<bot>?start=ref_<user_id>`
- Taklif qilingan odam majburiy kanalga obuna bo'lgach, taklif qiluvchiga **250 so'm** chegirma beriladi.
- Chegirma Premium narxidan ayriladi.
- Takliflar soni `5000 / 250 = 20` ga yetsa, Premium **bepul** faollashadi.

## 🔐 Majburiy obuna

Botdan foydalanish uchun foydalanuvchi sozlamalarda ko'rsatilgan kanalga (`REQUIRED_CHANNEL`) obuna bo'lishi shart. Akkaunt ulanganda esa majburiy bot(lar)ga (`REQUIRED_BOTS`) avtomatik `/start` yuboriladi.

## 🧭 Foydalanish tartibi

1. `/start` buyrug'ini yuboring va kanalga obuna bo'ling.
2. **👤 Profil → 🔗 Profil Ulash** orqali telefon raqamingizni yuboring.
3. Telegram yuborgan 5 xonali kodni kiriting (kerak bo'lsa 2 bosqichli parolni ham).
4. **⚙️ Sozlamalar** bo'limida:
   - **✏️ Xabar** – xabar matni/rasmini o'rnating,
   - **⏰ Interval** – yuborish oralig'ini tanlang,
   - **👥 Guruhlar** – xabar yuboriladigan guruhlarni belgilang.
5. **▶️ Yuborishni boshlash** tugmasini bosing.
6. To'xtatish uchun **⏹️ To'xtatish** tugmasini bosing.

## 🛠 O'rnatish

### Talablar

- Python 3.10+
- Telegram bot tokeni ([@BotFather](https://t.me/BotFather))
- Telegram `API_ID` va `API_HASH` ([my.telegram.org](https://my.telegram.org))

### Loyihani yuklab olish va kutubxonalarni o'rnatish

```bash
git clone https://github.com/YOUR_USERNAME/YOUR_REPO.git
cd YOUR_REPO
pip install -r requirements.txt
```

### Sozlash

Barcha shaxsiy ma'lumotlar kodda emas, **`.env`** faylida saqlanadi.

```bash
cp .env.example .env      # Windows: copy .env.example .env
```

So'ng `.env` faylini ochib, o'z qiymatlaringizni yozing:

| O'zgaruvchi | Majburiy | Ma'nosi |
|---|:---:|---|
| `BOT_TOKEN` | ✅ | Bot tokeni ([@BotFather](https://t.me/BotFather)) |
| `API_ID`, `API_HASH` | ✅ | Telethon uchun API ma'lumotlari ([my.telegram.org](https://my.telegram.org)) |
| `ADMIN_ID` | ✅ | Admin Telegram ID'si ([@userinfobot](https://t.me/userinfobot) orqali bilib oling) |
| `BOT_USERNAME` | | Botingiz username'i (`@`siz) – havolalar va xabar imzosida ishlatiladi |
| `ADMIN_USERNAME` | | Bloklangan foydalanuvchilarga ko'rsatiladigan admin username'i |
| `SHARE_TEXT` | | Referral havolasi ulashilganda qo'shiladigan matn |
| `REQUIRED_CHANNEL` | | Majburiy kanal (`@kanal`). Bo'sh bo'lsa, tekshirilmaydi |
| `REQUIRED_BOTS` | | Akkaunt ulanganda `/start` yuboriladigan botlar (vergul bilan) |
| `PAYMENTS_GROUP_ID` | | To'lov skrinshotlari tushadigan guruh ID'si |
| `NEW_MEMBERS_GROUP_ID` | | Yangi foydalanuvchilar haqida xabar guruhi (bo'sh = o'chiq) |
| `STATS_CHANNEL_ID` | | Statistika kanali ID'si (bo'sh = o'chiq) |
| `CARD_NUMBER`, `VISA_CARD_NUMBER` | | Karta orqali to'lov qabul qilinadigan kartalar |
| `PREMIUM_PRICE_STARS`, `PREMIUM_PRICE_MONEY`, `PREMIUM_DAYS` | | Premium narxi va muddati |
| `PREMIUM_MIN_INTERVAL`, `NON_PREMIUM_MIN_INTERVAL`, `MAX_INTERVAL` | | Interval chegaralari (daqiqa) |
| `PREMIUM_GROUP_LIMIT`, `NON_PREMIUM_GROUP_LIMIT` | | Guruhlar limiti |
| `PREMIUM_MESSAGE_LIMIT`, `NON_PREMIUM_MESSAGE_LIMIT` | | Sessiyadagi xabarlar limiti |
| `REFERRAL_DISCOUNT_PER_USER` | | Har bir taklif uchun chegirma (so'm) |

> 💡 Guruh yoki kanal ID'sini bilish uchun botni o'sha guruh/kanalga qo'shing (to'lovlar guruhida bot xabar yubora olishi kerak). Guruh ID'lari odatda `-100...` bilan boshlanadi.

> ⚠️ **Xavfsizlik:** `.env` faylini hech qachon GitHub'ga yuklamang (`.gitignore` uni avtomatik chiqarib tashlaydi). Agar token ommaga chiqib qolsa, uni darhol [@BotFather](https://t.me/BotFather) orqali yangilang.

### Ishga tushirish

```bash
python bot.py
```

Birinchi ishga tushirishda quyidagilar avtomatik yaratiladi:

```
bot_data.db       # SQLite ma'lumotlar bazasi
sessions/         # Telethon sessiya fayllari
user_images/      # Foydalanuvchilar rasmlari
admin_images/     # Admin xabari rasmlari
```

> 🔒 `sessions/` papkasi foydalanuvchilar akkauntlariga kirish imkonini beradi. Uni hech kimga bermang va repozitoriyga yuklamang.

## 👑 Admin buyruqlari

| Buyruq | Vazifasi |
|---|---|
| `/adminhelp` | Admin buyruqlari ro'yxati |
| `/stats` | Bot statistikasi |
| `/profit` | Bot foydasi |
| `/setprofit` | Foydani o'zgartirish (so'm yoki Stars) |
| `/broadcast` | Hammaga xabar yuborish |
| `/cancel_broadcast` | Broadcastni bekor qilish |
| `/see <user_id>` | Foydalanuvchi ma'lumotlari |
| `/entered` | Akkaunt ulagan foydalanuvchilar |
| `/active` | Hozir yuborayotgan foydalanuvchilar |
| `/pending` | Kutilayotgan to'lovlar |
| `/premusers` | Premium foydalanuvchilar |
| `/addprem <user_id> [kun]` | Premium qo'shish |
| `/removeprem <user_id>` | Premiumni olib tashlash |
| `/setadmsg` | Admin xabarini o'rnatish / o'chirish / almashtirish |
| `/ban <user_id>` | Bloklash |
| `/unban <user_id>` | Blokdan chiqarish |
| `/banned` | Bloklanganlar ro'yxati |
| `/reset <user_id>` | Foydalanuvchi ma'lumotlarini boshlang'ich holatga qaytarish |
| `/delete <user_id>` | Foydalanuvchini bazadan butunlay o'chirish |

## 💳 To'lov jarayoni

**⭐ Telegram Stars:** foydalanuvchi invoice orqali to'laydi va Premium avtomatik faollashadi.

**💰 Karta orqali:**

1. Foydalanuvchi to'lov summasini oladi va to'lov qiladi.
2. To'lov skrinshotini botga yuboradi.
3. Skrinshot admin guruhiga (`PAYMENTS_GROUP_ID`) tushadi.
4. Admin **✅ Tasdiqlash**, **❌ Bekor** yoki **⚠️ Yetarli emas** tugmasini bosadi.
5. "Yetarli emas" tanlansa, qolgan summa uchun yangi to'lov so'rovi yaratiladi.

## 🗄 Ma'lumotlar bazasi

| Jadval | Mazmuni |
|---|---|
| `users` | Foydalanuvchi sozlamalari, holati, Premium, referral, blok ma'lumotlari |
| `payments` | To'lovlar va ularning holati (`pending`, `confirmed`, `cancelled`, `insufficient`) |
| `profit` | Umumiy foyda (naqd va Stars) |
| `admin_message` | Bepul foydalanuvchilarga yuboriladigan admin xabari |

Yangi ustunlar kerak bo'lsa, bot ishga tushganda ular avtomatik qo'shiladi (oddiy migratsiya).

## ⚙️ Ichki ishlash prinsipi

- Har bir faol foydalanuvchi uchun alohida `asyncio` vazifasi (`send_scheduled_messages`) ishlaydi.
- Xabarlar guruhlarga ketma-ket yuboriladi, har bir xabardan keyin spamdan saqlanish uchun qisqa pauza qo'yiladi.
- Guruhga yozish taqiqlangan, maxfiy yoki bloklangan bo'lsa, u guruh avtomatik ro'yxatdan olib tashlanadi va foydalanuvchi ogohlantiriladi.
- Sessiya bekor qilingan bo'lsa, yuborish to'xtatiladi va foydalanuvchiga akkauntni qayta ulash kerakligi aytiladi.
- Bot qayta ishga tushganda faol foydalanuvchilarning yuborishi avtomatik davom ettiriladi.
- Premium muddati tugaganda rasmli xabarlar matnli xabarga o'tkaziladi.

## ⚠️ Muhim eslatmalar

- Avtomatik ommaviy xabar yuborish Telegram qoidalariga va guruh qoidalariga zid kelishi mumkin. Haddan tashqari tez yoki ko'p yuborish akkauntning cheklanishiga yoki bloklanishiga olib kelishi mumkin. Mas'uliyat foydalanuvchida.
- Kodda `target_groups` maydoni `eval()` orqali o'qiladi. Xavfsizroq variant – `json.loads()` / `json.dumps()` ishlatish.
- Sezgir ma'lumotlarni (token, API kalitlar, karta raqamlari) repozitoriyga yuklamang.

## 🤝 Hissa qo'shish

Takliflar va xatolar haqidagi xabarlar uchun *Issue* oching yoki *Pull Request* yuboring.

## 📄 Litsenziya

Loyiha **MIT litsenziyasi** ostida tarqatiladi. © 2026 Otabek Rustamov.

To'liq matn [LICENSE](LICENSE) faylida keltirilgan.

---

<a id="-english"></a>

# 🇬🇧 English

## 📖 About

**vAvtoXabar Bot** is a Telegram bot for automated message sending. A user connects their own Telegram account through the bot, prepares a message (text and/or image), picks target groups, and the bot then sends that message to the selected groups at a configured interval.

The project is built on two libraries:

- **python-telegram-bot** – the bot-facing side (menus, buttons, payments, admin commands).
- **Telethon** – the user-account side that actually sends messages to groups on the user's behalf.

All data is stored in an **SQLite** database (`bot_data.db`).

## ✨ Features

### For users

- 📱 Connect a Telegram account (phone number → code → 2FA password if enabled)
- ✏️ Message types: **text**, **image**, **image + text** (images are Premium-only)
- ⏰ Configurable send interval (preset buttons or manual input)
- 👥 Paginated group picker from the connected account (channels are excluded)
- ▶️ Start / ⏹️ stop sending
- 📊 Session statistics and total messages sent
- 👑 Premium subscription (⭐ Telegram Stars or card payment)
- 🔗 Referral system – discount for every invited user

### For the admin

- 💰 Profit tracking (cash and Stars)
- 📢 Broadcast to all users (text, photo, video, file)
- 👑 Grant / revoke Premium
- ⛔ Ban / unban users
- ✅ Confirm, cancel, or mark card payments as "insufficient"
- 📌 An "admin message" that is alternately sent for all **free** users
- 📈 Public stats message that auto-updates in a stats channel

## 💎 Plans

| Feature | Free | Premium |
|---|---|---|
| Minimum interval | 5 minutes | 2 minutes |
| Maximum interval | 15 minutes | 15 minutes |
| Group limit | 5 | 30 |
| Messages per session | 100 | 1000 |
| Image sending | ❌ | ✅ |
| Bot signature in message footer | Yes | No |
| Admin message (ad) | Yes | No |
| Price (30 days) | Free | ⭐ 40 Stars or 5,000 UZS |

> All values can be changed in the configuration block at the top of `bot.py`.

## 🎁 Referral system

- Every user has a personal link: `https://t.me/<bot>?start=ref_<user_id>`
- Once an invited person joins the required channel, the inviter gets a **250 UZS** discount.
- The discount is deducted from the Premium price.
- When invites reach `5000 / 250 = 20`, Premium is activated **for free**.

## 🔐 Mandatory subscription

To use the bot, a user must be subscribed to the channel set in `REQUIRED_CHANNEL`. When an account is connected, the bot also sends `/start` to every bot listed in `REQUIRED_BOTS`.

## 🧭 How to use

1. Send `/start` and subscribe to the required channel.
2. Go to **👤 Profil → 🔗 Profil Ulash** and send your phone number.
3. Enter the 5-digit code from Telegram (and your 2FA password if asked).
4. In **⚙️ Sozlamalar** (Settings):
   - **✏️ Xabar** – set the message text/image,
   - **⏰ Interval** – choose the sending interval,
   - **👥 Guruhlar** – select the target groups.
5. Press **▶️ Yuborishni boshlash** (Start sending).
6. Press **⏹️ To'xtatish** (Stop) to stop.

## 🛠 Installation

### Requirements

- Python 3.10+
- A Telegram bot token from [@BotFather](https://t.me/BotFather)
- Telegram `API_ID` and `API_HASH` from [my.telegram.org](https://my.telegram.org)

### Clone the project and install dependencies

```bash
git clone https://github.com/YOUR_USERNAME/YOUR_REPO.git
cd YOUR_REPO
pip install -r requirements.txt
```

### Configuration

All private settings live in a **`.env`** file, not in the code.

```bash
cp .env.example .env      # Windows: copy .env.example .env
```

Then open `.env` and fill in your own values:

| Variable | Required | Meaning |
|---|:---:|---|
| `BOT_TOKEN` | ✅ | Bot token from [@BotFather](https://t.me/BotFather) |
| `API_ID`, `API_HASH` | ✅ | Telegram API credentials for Telethon ([my.telegram.org](https://my.telegram.org)) |
| `ADMIN_ID` | ✅ | Admin's numeric Telegram ID (get it from [@userinfobot](https://t.me/userinfobot)) |
| `BOT_USERNAME` | | Your bot's username (without `@`) – used in links and the message footer |
| `ADMIN_USERNAME` | | Admin username shown to banned users |
| `SHARE_TEXT` | | Text added when users share their referral link |
| `REQUIRED_CHANNEL` | | Mandatory channel (`@channel`). Empty = no check |
| `REQUIRED_BOTS` | | Bots that get `/start` when an account is connected (comma separated) |
| `PAYMENTS_GROUP_ID` | | Group that receives payment screenshots |
| `NEW_MEMBERS_GROUP_ID` | | Group notified about new users (empty = off) |
| `STATS_CHANNEL_ID` | | Channel for the live statistics message (empty = off) |
| `CARD_NUMBER`, `VISA_CARD_NUMBER` | | Cards that accept manual payments |
| `PREMIUM_PRICE_STARS`, `PREMIUM_PRICE_MONEY`, `PREMIUM_DAYS` | | Premium price and duration |
| `PREMIUM_MIN_INTERVAL`, `NON_PREMIUM_MIN_INTERVAL`, `MAX_INTERVAL` | | Interval limits (minutes) |
| `PREMIUM_GROUP_LIMIT`, `NON_PREMIUM_GROUP_LIMIT` | | Group limits |
| `PREMIUM_MESSAGE_LIMIT`, `NON_PREMIUM_MESSAGE_LIMIT` | | Per-session message limits |
| `REFERRAL_DISCOUNT_PER_USER` | | Discount per invited user (UZS) |

> 💡 To get a group or channel ID, add the bot to that group/channel (the bot must be able to post in the payments group). Group IDs usually start with `-100...`.

> ⚠️ **Security:** never commit your `.env` file to GitHub (the included `.gitignore` already excludes it). If a token ever leaks, regenerate it right away via [@BotFather](https://t.me/BotFather).

### Run

```bash
python bot.py
```

On first launch the following are created automatically:

```
bot_data.db       # SQLite database
sessions/         # Telethon session files
user_images/      # Users' uploaded images
admin_images/     # Admin message images
```

> 🔒 The `sessions/` folder grants access to users' Telegram accounts. Never share it or commit it to a repository.

## 👑 Admin commands

| Command | Description |
|---|---|
| `/adminhelp` | List of admin commands |
| `/stats` | Bot statistics |
| `/profit` | Bot profit |
| `/setprofit` | Change profit (cash or Stars) |
| `/broadcast` | Send a message to everyone |
| `/cancel_broadcast` | Cancel broadcast mode |
| `/see <user_id>` | View user details |
| `/entered` | Users with a connected account |
| `/active` | Users currently sending |
| `/pending` | Pending payments |
| `/premusers` | Premium users |
| `/addprem <user_id> [days]` | Grant Premium |
| `/removeprem <user_id>` | Revoke Premium |
| `/setadmsg` | Set / delete / replace the admin message |
| `/ban <user_id>` | Ban a user |
| `/unban <user_id>` | Unban a user |
| `/banned` | List banned users |
| `/reset <user_id>` | Reset a user's data to defaults |
| `/delete <user_id>` | Delete a user from the database completely |

## 💳 Payment flow

**⭐ Telegram Stars:** the user pays via an invoice and Premium is activated automatically.

**💰 Card payment:**

1. The user gets the amount and pays.
2. The user sends a payment screenshot to the bot.
3. The screenshot is forwarded to the admin group (`PAYMENTS_GROUP_ID`).
4. The admin presses **✅ Confirm**, **❌ Cancel**, or **⚠️ Insufficient**.
5. If "Insufficient" is chosen, a new payment request is created for the remaining amount.

## 🗄 Database

| Table | Contents |
|---|---|
| `users` | User settings, state, Premium, referral and ban data |
| `payments` | Payments and their status (`pending`, `confirmed`, `cancelled`, `insufficient`) |
| `profit` | Total profit (cash and Stars) |
| `admin_message` | The admin message shown to free users |

Missing columns are added automatically on startup (a simple migration).

## ⚙️ How it works

- Every active user gets their own `asyncio` task (`send_scheduled_messages`).
- Messages are sent to groups one by one, with a short pause after each send to reduce spam-flag risk.
- If a group is private, banned, or write-restricted, it is automatically removed from the user's list and the user is notified.
- If the session is revoked, sending stops and the user is asked to reconnect the account.
- On bot restart, sending is automatically resumed for all active users.
- When Premium expires, image messages are converted to text messages.

## ⚠️ Important notes

- Automated bulk messaging may violate Telegram's Terms of Service and individual group rules. Sending too fast or too much can lead to account limits or bans. Use responsibly.
- The code reads `target_groups` with `eval()`. A safer approach is to use `json.loads()` / `json.dumps()`.
- Never commit sensitive data (tokens, API keys, card numbers) to a repository.

## 🤝 Contributing

Open an *Issue* for bugs and suggestions, or submit a *Pull Request*.

## 📄 License

This project is licensed under the **MIT License**. © 2026 Otabek Rustamov.

See the [LICENSE](LICENSE) file for the full text.
