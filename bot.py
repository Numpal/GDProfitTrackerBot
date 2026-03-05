import re
import csv
import os
from datetime import datetime, timedelta

from telegram import Update, ReplyKeyboardMarkup
from telegram.ext import ApplicationBuilder, ContextTypes, MessageHandler, CommandHandler, filters


# ดึง TOKEN จาก Railway Variables
TOKEN = os.getenv("TOKEN")

# ไฟล์เก็บข้อมูล
DATA_FILE = "trades.csv"

# ปุ่มเมนู
keyboard = [
    ["📊 กำไรวันนี้"],
    ["📅 กำไร 7 วัน"],
    ["📈 กำไร 30 วัน"]
]

reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

# regex อ่านกำไร / ขาดทุน
pattern = r'(กำไร|ขาดทุน):\s*([+-]?\d+\.?\d*)'


# บันทึก trade
def save_trade(value):

    with open(DATA_FILE, "a", newline="", encoding="utf-8") as f:

        writer = csv.writer(f)

        writer.writerow([datetime.now().isoformat(), value])


# อ่าน trade ตามจำนวนวัน
def read_trades(days):

    total = 0
    count = 0

    try:

        with open(DATA_FILE, "r", encoding="utf-8") as f:

            reader = csv.reader(f)

            for row in reader:

                date = datetime.fromisoformat(row[0])
                value = float(row[1])

                if datetime.now() - date <= timedelta(days=days):

                    total += value
                    count += 1

    except FileNotFoundError:

        pass

    return total, count


# /start command
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):

    await update.message.reply_text(

        "📊 Copy Trade Profit Tracker\n\nเลือกเมนูเพื่อดูรายงาน",

        reply_markup=reply_markup

    )


# อ่านข้อความทั้งหมด
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):

    if not update.message:
        return

    text = update.message.text

    if not text:
        return


    # ตรวจจับกำไร / ขาดทุน
    match = re.search(pattern, text)

    if match:

        value = float(match.group(2))

        save_trade(value)

        print("Trade saved:", value)


    # รายงานวันนี้
    if text == "📊 กำไรวันนี้":

        total, count = read_trades(1)

        await update.message.reply_text(

            f"📊 รายงานวันนี้\n\nจำนวนไม้: {count}\nกำไรสุทธิ: {round(total,2)} USC"

        )


    # รายงาน 7 วัน
    elif text == "📅 กำไร 7 วัน":

        total, count = read_trades(7)

        await update.message.reply_text(

            f"📅 รายงาน 7 วัน\n\nจำนวนไม้: {count}\nกำไรสุทธิ: {round(total,2)} USC"

        )


    # รายงาน 30 วัน
    elif text == "📈 กำไร 30 วัน":

        total, count = read_trades(30)

        await update.message.reply_text(

            f"📈 รายงาน 30 วัน\n\nจำนวนไม้: {count}\nกำไรสุทธิ: {round(total,2)} USC"

        )


# เริ่ม bot
def main():

    if TOKEN is None:
        print("ERROR: TOKEN not found in environment variables")
        return


    app = ApplicationBuilder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", start))

    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))


    print("Profit Tracker Bot Running...")

    app.run_polling()


if __name__ == "__main__":
    main()
