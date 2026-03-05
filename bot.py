import re
import csv
import os
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from telegram import Update, ReplyKeyboardMarkup
from telegram.ext import ApplicationBuilder, ContextTypes, MessageHandler, CommandHandler, filters


TH_TZ = ZoneInfo("Asia/Bangkok")

TOKEN = os.getenv("TOKEN")

DATA_FILE = "trades.csv"
CHAT_ID_FILE = "chat_id.txt"


keyboard = [
    ["📊 กำไรวันนี้"],
    ["📅 กำไรสัปดาห์นี้"],
    ["📈 กำไร 30 วัน"]
]

reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

pattern = r'(กำไร|ขาดทุน):\s*([+-]?\d+\.?\d*)'


thai_months = [
    "มกราคม","กุมภาพันธ์","มีนาคม","เมษายน","พฤษภาคม","มิถุนายน",
    "กรกฎาคม","สิงหาคม","กันยายน","ตุลาคม","พฤศจิกายน","ธันวาคม"
]


def thai_date():

    now = datetime.now(TH_TZ)

    day = now.day
    month = thai_months[now.month - 1]
    year = now.year + 543

    return f"{day} {month} {year}"


def save_chat_id(chat_id):

    with open(CHAT_ID_FILE, "w") as f:
        f.write(str(chat_id))


def get_chat_id():

    try:
        with open(CHAT_ID_FILE, "r") as f:
            return int(f.read().strip())
    except:
        return None


def save_trade(value):

    with open(DATA_FILE, "a", newline="", encoding="utf-8") as f:

        writer = csv.writer(f)

        writer.writerow([datetime.now(TH_TZ).isoformat(), value])


def read_trades(days):

    total = 0
    count = 0

    try:

        with open(DATA_FILE, "r", encoding="utf-8") as f:

            reader = csv.reader(f)

            for row in reader:

                date = datetime.fromisoformat(row[0])
                value = float(row[1])

                if datetime.now(TH_TZ) - date <= timedelta(days=days):

                    total += value
                    count += 1

    except FileNotFoundError:
        pass

    return total, count


def read_week_trades():

    total = 0
    count = 0

    now = datetime.now(TH_TZ)

    days_since_sunday = (now.weekday() + 1) % 7
    sunday = now - timedelta(days=days_since_sunday)

    sunday_start = sunday.replace(hour=0, minute=0, second=0, microsecond=0)

    try:

        with open(DATA_FILE, "r", encoding="utf-8") as f:

            reader = csv.reader(f)

            for row in reader:

                date = datetime.fromisoformat(row[0])
                value = float(row[1])

                if date >= sunday_start:

                    total += value
                    count += 1

    except FileNotFoundError:
        pass

    return total, count


async def menu(update: Update, context: ContextTypes.DEFAULT_TYPE):

    chat_id = update.effective_chat.id
    save_chat_id(chat_id)

    await update.message.reply_text(
        "📊 Copy Trade Profit Tracker\n\nเลือกเมนูเพื่อดูรายงาน",
        reply_markup=reply_markup
    )


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):

    if not update.message:
        return

    text = update.message.text

    if not text:
        return

    match = re.search(pattern, text)

    if match:

        value = float(match.group(2))

        save_trade(value)

        print("Trade saved:", value)

    if text == "📊 กำไรวันนี้":

        total, count = read_trades(1)

        await update.message.reply_text(
            f"📊 รายงานวันนี้\n\nจำนวนไม้: {count}\nกำไรสุทธิ: {round(total,2)} USC"
        )

    elif text == "📅 กำไรสัปดาห์นี้":

        total, count = read_week_trades()

        await update.message.reply_text(
            f"📅 สรุปกำไรสัปดาห์นี้\n\nจำนวนไม้: {count}\nกำไรสุทธิ: {round(total,2)} USC"
        )

    elif text == "📈 กำไร 30 วัน":

        total, count = read_trades(30)

        await update.message.reply_text(
            f"📈 รายงาน 30 วัน\n\nจำนวนไม้: {count}\nกำไรสุทธิ: {round(total,2)} USC"
        )


async def daily_report(context: ContextTypes.DEFAULT_TYPE):

    chat_id = get_chat_id()

    if chat_id is None:
        return

    total, count = read_trades(1)

    message = (
        "📊 สรุปกำไรประจำวัน\n\n"
        f"จำนวนไม้: {count}\n"
        f"กำไรสุทธิ: {round(total,2)} USC"
    )

    await context.bot.send_message(chat_id=chat_id, text=message)


async def weekly_report(context: ContextTypes.DEFAULT_TYPE):

    chat_id = get_chat_id()

    if chat_id is None:
        return

    total, count = read_week_trades()

    message = (
        "📅 สรุปกำไรสัปดาห์นี้\n\n"
        f"จำนวนไม้: {count}\n"
        f"กำไรสุทธิ: {round(total,2)} USC"
    )

    await context.bot.send_message(chat_id=chat_id, text=message)


async def send_thai_date(context: ContextTypes.DEFAULT_TYPE):

    chat_id = get_chat_id()

    if chat_id is None:
        return

    message = f"📅 วันนี้คือ\n{thai_date()}"

    await context.bot.send_message(chat_id=chat_id, text=message)


def main():

    if TOKEN is None:
        print("TOKEN not found")
        return

    app = ApplicationBuilder().token(TOKEN).build()

    app.add_handler(CommandHandler("menu", menu))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    job_queue = app.job_queue

    job_queue.run_daily(
        send_thai_date,
        time=datetime.strptime("00:01", "%H:%M").time()
    )

    job_queue.run_daily(
        daily_report,
        time=datetime.strptime("23:59", "%H:%M").time()
    )

    job_queue.run_daily(
        weekly_report,
        time=datetime.strptime("23:59", "%H:%M").time()
    )

    print("Profit Tracker Bot Running...")

    app.run_polling()


if __name__ == "__main__":
    main()
