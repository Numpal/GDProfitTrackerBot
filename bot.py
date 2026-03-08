import http.server
import socketserver
import threading
import os
import asyncio
from datetime import datetime, timedelta, time
from zoneinfo import ZoneInfo

import gspread
from google.oauth2.service_account import Credentials
from telegram import Update, ReplyKeyboardMarkup, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, ContextTypes, MessageHandler, CommandHandler, filters

# -------------------------
# 1. Health Check Server
# -------------------------
def run_health_check_server():
    port = int(os.getenv("PORT", 8000))
    handler = http.server.SimpleHTTPRequestHandler
    with socketserver.TCPServer(("", port), handler) as httpd:
        print(f"✅ Health check server started on port {port}")
        httpd.serve_forever()

threading.Thread(target=run_health_check_server, daemon=True).start()

# -------------------------
# Configuration
# -------------------------
TH_TZ = ZoneInfo("Asia/Bangkok")
TOKEN = os.getenv("TOKEN")
EXCHANGE_RATE = 35.0
MASTER_WEEKLY_RESET = 200.0

DELETE_FAST = 10
DELETE_NORMAL = 10
DELETE_LONG = 10

SHEET_NAME = "CopyTradeTracker"
SHEET_URL = "https://docs.google.com/spreadsheets/d/1dQXfk5wXwC1rnUPYB-SEAG3ySi3ZqNsTT6mRPb-BLfo/edit?usp=sharing"

g_email = os.getenv("G_EMAIL")
g_private_key = os.getenv("G_PRIVATE_KEY")
g_project_id = os.getenv("G_PROJECT_ID")

scope = [
"https://www.googleapis.com/auth/spreadsheets",
"https://www.googleapis.com/auth/drive"
]

trade_sheet = None
config_sheet = None
balance_sheet = None

thai_months = [
"มกราคม","กุมภาพันธ์","มีนาคม","เมษายน","พฤษภาคม","มิถุนายน",
"กรกฎาคม","สิงหาคม","กันยายน","ตุลาคม","พฤศจิกายน","ธันวาคม"
]

thai_days = [
"วันจันทร์","วันอังคาร","วันพุธ","วันพฤหัสบดี","วันศุกร์","วันเสาร์","วันอาทิตย์"
]

# -------------------------
# Google Sheet
# -------------------------
try:

    formatted_key = g_private_key.replace("\\n","\n")

    creds_info = {
        "type":"service_account",
        "project_id":g_project_id,
        "private_key":formatted_key,
        "client_email":g_email,
        "token_uri":"https://oauth2.googleapis.com/token",
    }

    creds = Credentials.from_service_account_info(creds_info, scopes=scope)
    client = gspread.authorize(creds)
    spreadsheet = client.open(SHEET_NAME)

    trade_sheet = spreadsheet.worksheet("trades")
    config_sheet = spreadsheet.worksheet("config")

    try:
        balance_sheet = spreadsheet.worksheet("balance_history")
    except:
        balance_sheet = spreadsheet.add_worksheet(title="balance_history", rows="1000", cols="4")

    print("✅ Connected Google Sheets")

except Exception as e:

    print("❌ Google Sheet Error:",e)

# -------------------------
# Keyboards
# -------------------------
main_keyboard = [
["🧮 คำนวณตามทุน","📊 กำไรวันนี้"],
["📅 กำไรสัปดาห์นี้","📈 กำไร 30 วัน"],
["💵 แปลงค่าเงิน","🔗 ประวัติย้อนหลังทั้งหมด"]
]

main_markup = ReplyKeyboardMarkup(main_keyboard, resize_keyboard=True)

sheet_inline_keyboard = InlineKeyboardMarkup([
[InlineKeyboardButton(text="📂 เปิด Google Sheet", url=SHEET_URL)]
])

# -------------------------
# Utilities
# -------------------------

def save_chat_id(cid):
    try:
        config_sheet.update("A1",[[cid]])
    except:
        pass


def get_chat_id():
    try:
        return int(config_sheet.acell("A1").value)
    except:
        return 0


def thai_date_full():
    now = datetime.now(TH_TZ)
    return f"{thai_days[now.weekday()]}ที่ {now.day} {thai_months[now.month-1]} {now.year+543}"


async def delete_message_safe(context,chat_id,message_id,delay=DELETE_NORMAL):

    await asyncio.sleep(delay)

    try:
        await context.bot.delete_message(chat_id=chat_id,message_id=message_id)
    except:
        pass


# -------------------------
# Trade Functions
# -------------------------

def read_trades(days):

    try:

        rows = trade_sheet.get_all_values()

        total = 0
        count = 0
        now = datetime.now(TH_TZ)

        for row in rows[1:]:

            try:

                date = datetime.fromisoformat(row[0])

                if now-date <= timedelta(days=days):

                    total += float(row[6])
                    count += 1

            except:
                continue

        return total,count

    except:
        return 0,0


def read_week_trades():

    try:

        rows = trade_sheet.get_all_values()

        now = datetime.now(TH_TZ)

        sunday = (now - timedelta(days=(now.weekday()+1)%7)).replace(hour=0,minute=0,second=0)

        total = 0
        count = 0

        for row in rows[1:]:

            try:

                date = datetime.fromisoformat(row[0])

                if date >= sunday:

                    total += float(row[6])
                    count += 1

            except:
                continue

        return total,count

    except:
        return 0,0


def read_month_trades():

    try:

        rows = trade_sheet.get_all_values()

        now = datetime.now(TH_TZ)

        start = now.replace(day=1,hour=0,minute=0,second=0)

        total = 0
        count = 0

        for row in rows[1:]:

            try:

                date = datetime.fromisoformat(row[0])

                if date >= start:

                    total += float(row[6])
                    count += 1

            except:
                continue

        return total,count

    except:
        return 0,0


# -------------------------
# Commands
# -------------------------

async def start_command(update:Update,context:ContextTypes.DEFAULT_TYPE):

    chat_id = update.effective_chat.id
    save_chat_id(chat_id)

    await context.bot.send_message(
        chat_id=chat_id,
        text="📊 Copy Trade Tracker\nเลือกเมนูที่ต้องการ",
        reply_markup=main_markup
    )


async def tobath_command(update:Update,context:ContextTypes.DEFAULT_TYPE):

    chat_id = update.effective_chat.id

    try:

        usd = float(context.args[0])
        thb = usd * EXCHANGE_RATE

        msg = await update.message.reply_text(
            f"💰 {usd:,.2f} USD ➜ {thb:,.2f} บาท"
        )

        asyncio.create_task(delete_message_safe(context,chat_id,msg.message_id,DELETE_FAST))

        await update.message.delete()

    except:
        pass


async def calc_command(update:Update,context:ContextTypes.DEFAULT_TYPE):

    chat_id = update.effective_chat.id

    try:

        capital = float(context.args[0])

        total,_ = read_trades(1)

        pct = (total/MASTER_WEEKLY_RESET*100) if MASTER_WEEKLY_RESET else 0

        profit = capital*pct/100
        thb = profit*EXCHANGE_RATE

        msg = await update.message.reply_text(
            f"🧮 ทุน {capital:,.2f} USD\n"
            f"กำไร {profit:,.2f} USD\n"
            f"≈ {thb:,.2f} บาท"
        )

        asyncio.create_task(delete_message_safe(context,chat_id,msg.message_id,DELETE_FAST))

        await update.message.delete()

    except:
        pass


# -------------------------
# Message Handler
# -------------------------

async def handle_message(update:Update,context:ContextTypes.DEFAULT_TYPE):

    try:

        text = update.message.text
        chat_id = update.effective_chat.id

        save_chat_id(chat_id)

        if text == "📊 กำไรวันนี้":

            total,count = read_trades(1)
            report = f"📊 วันนี้\nไม้: {count}\nกำไร: {total:,.2f} USD"

        elif text == "📅 กำไรสัปดาห์นี้":

            total,count = read_week_trades()
            report = f"📅 สัปดาห์นี้\nไม้: {count}\nกำไรสะสม: {total:,.2f} USD"

        elif text == "📈 กำไร 30 วัน":

            total,count = read_trades(30)
            report = f"📈 30 วัน\nไม้: {count}\nกำไร: {total:,.2f} USD"

        elif text == "🧮 คำนวณตามทุน":

            await update.message.delete()

            msg = await context.bot.send_message(
                chat_id=chat_id,
                text="ใช้คำสั่ง /calc 500 เพื่อคำนวณทุน"
            )

            asyncio.create_task(delete_message_safe(context,chat_id,msg.message_id,DELETE_LONG))
            return

        elif text == "💵 แปลงค่าเงิน":

            await update.message.delete()

            msg = await context.bot.send_message(
                chat_id=chat_id,
                text="ใช้คำสั่ง /tobath 100 เพื่อแปลงเงิน"
            )

            asyncio.create_task(delete_message_safe(context,chat_id,msg.message_id,DELETE_NORMAL))
            return

        elif text == "🔗 ประวัติย้อนหลังทั้งหมด":

            await update.message.delete()

            msg = await context.bot.send_message(
                chat_id=chat_id,
                text="📂 เปิดประวัติ",
                reply_markup=sheet_inline_keyboard
            )

            asyncio.create_task(delete_message_safe(context,chat_id,msg.message_id,DELETE_NORMAL))
            return

        else:
            return

        msg = await context.bot.send_message(chat_id=chat_id,text=report)

        asyncio.create_task(delete_message_safe(context,chat_id,msg.message_id,DELETE_NORMAL))

        await update.message.delete()

    except:
        pass


# -------------------------
# Jobs
# -------------------------

async def morning_date_job(context):

    chat_id = get_chat_id()

    if chat_id:
        await context.bot.send_message(chat_id=chat_id,text=f"📅 {thai_date_full()}")


async def daily_report_job(context):

    chat_id = get_chat_id()

    if chat_id:

        total,count = read_trades(1)

        await context.bot.send_message(
            chat_id=chat_id,
            text=f"📊 สรุปวันนี้\nไม้ {count}\nกำไร {total:,.2f} USD"
        )


async def weekly_report_job(context):

    chat_id = get_chat_id()

    if chat_id:

        total,count = read_week_trades()

        await context.bot.send_message(
            chat_id=chat_id,
            text=f"📅 สัปดาห์นี้\nไม้ {count}\nกำไรสะสม {total:,.2f} USD"
        )


async def monthly_report_job(context):

    chat_id = get_chat_id()

    if chat_id:

        total,count = read_month_trades()

        await context.bot.send_message(
            chat_id=chat_id,
            text=f"📆 เดือนนี้\nไม้ {count}\nกำไรสะสม {total:,.2f} USD"
        )


# -------------------------
# Main
# -------------------------

def main():

    app = ApplicationBuilder().token(TOKEN).build()

    app.add_handler(CommandHandler("start",start_command))
    app.add_handler(CommandHandler("menu",start_command))
    app.add_handler(CommandHandler("tobath",tobath_command))
    app.add_handler(CommandHandler("calc",calc_command))

    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND,handle_message))

    job_queue = app.job_queue

    job_queue.run_daily(morning_date_job,time=time(0,1,tzinfo=TH_TZ))
    job_queue.run_daily(daily_report_job,time=time(23,59,tzinfo=TH_TZ))
    job_queue.run_daily(weekly_report_job,time=time(23,59,tzinfo=TH_TZ))
    job_queue.run_daily(monthly_report_job,time=time(23,59,tzinfo=TH_TZ))

    print("🚀 Bot Started")

    app.run_polling()


if __name__ == "__main__":
    main()
