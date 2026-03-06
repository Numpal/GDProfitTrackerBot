import re
import csv
import os
from datetime import datetime, timedelta, time
from zoneinfo import ZoneInfo

from telegram import Update, ReplyKeyboardMarkup
from telegram.ext import ApplicationBuilder, ContextTypes, MessageHandler, CommandHandler, filters


TH_TZ = ZoneInfo("Asia/Bangkok")

TOKEN = os.getenv("TOKEN")

DATA_FILE = "trades.csv"
CHAT_ID_FILE = "chat_id.txt"
LAST_MSG_FILE = "last_message_id.txt"


keyboard = [
    ["📊 กำไรวันนี้"],
    ["📅 กำไรสัปดาห์นี้"],
    ["📈 กำไร 30 วัน"]
]

reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)


pattern = r'(กำไร|ขาดทุน):\s*([+-]?\d+\.?\d*)\s*USD'


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


def ensure_file(file, default):

    if not os.path.exists(file):
        with open(file, "w") as f:
            f.write(str(default))


def save_chat_id(chat_id):

    with open(CHAT_ID_FILE, "w") as f:
        f.write(str(chat_id))


def get_chat_id():

    ensure_file(CHAT_ID_FILE, 0)

    with open(CHAT_ID_FILE, "r") as f:
        return int(f.read().strip())


def get_last_msg_id():

    ensure_file(LAST_MSG_FILE, 0)

    with open(LAST_MSG_FILE, "r") as f:
        return int(f.read().strip())


def save_last_msg_id(msg_id):

    with open(LAST_MSG_FILE, "w") as f:
        f.write(str(msg_id))


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


def process_trade(text):

    match = re.search(pattern, text)

    if not match:
        return None

    trade_type = match.group(1)
    value = float(match.group(2))

    if trade_type == "ขาดทุน":
        value = -abs(value)
    else:
        value = abs(value)

    return value


# -----------------------
# Admin Menu
# -----------------------

async def menu(update: Update, context: ContextTypes.DEFAULT_TYPE):

    chat_id = update.effective_chat.id
    user_id = update.effective_user.id

    member = await context.bot.get_chat_member(chat_id, user_id)

    if member.status not in ["administrator", "creator"]:
        return

    save_chat_id(chat_id)

    await update.message.reply_text(
        "📊 Copy Trade Profit Tracker\n\nเลือกเมนูเพื่อดูรายงาน",
        reply_markup=reply_markup
    )


# -----------------------
# Handle Message
# -----------------------

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):

    if not update.message:
        return

    text = update.message.text
    msg_id = update.message.message_id

    last_id = get_last_msg_id()

    if msg_id <= last_id:
        return

    value = process_trade(text)

    if value is not None:

        save_trade(value)

        print("Trade saved:", value)

    save_last_msg_id(msg_id)


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


# -----------------------
# Auto Reports
# -----------------------

async def send_thai_date(context: ContextTypes.DEFAULT_TYPE):

    chat_id = get_chat_id()

    if chat_id == 0:
        return

    message = f"📅 วันนี้คือ\n{thai_date()}"

    await context.bot.send_message(chat_id=chat_id, text=message)


async def daily_report(context: ContextTypes.DEFAULT_TYPE):

    chat_id = get_chat_id()

    if chat_id == 0:
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

    if chat_id == 0:
        return

    total, count = read_week_trades()

    message = (
        "📅 สรุปกำไรสัปดาห์นี้\n\n"
        f"จำนวนไม้: {count}\n"
        f"กำไรสุทธิ: {round(total,2)} USC"
    )

    await context.bot.send_message(chat_id=chat_id, text=message)


# -----------------------
# Main
# -----------------------

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
        time=time(0,1, tzinfo=TH_TZ)
    )

    job_queue.run_daily(
        daily_report,
        time=time(23,59, tzinfo=TH_TZ)
    )

    job_queue.run_daily(
        weekly_report,
        time=time(23,59, tzinfo=TH_TZ)
    )


    print("Profit Tracker Bot Running...")

    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
