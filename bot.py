import http.server
import socketserver
import threading
import os
import re
import asyncio
import json
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
# Configuration & Setup
# -------------------------
TH_TZ = ZoneInfo("Asia/Bangkok")
TOKEN = os.getenv("TOKEN")
EXCHANGE_RATE = 35.0
MASTER_WEEKLY_RESET = 200.0

# ---- DELETE MESSAGE TIME SETTINGS ----
DELETE_FAST = 10
DELETE_NORMAL = 10
DELETE_LONG = 10

SHEET_NAME = "CopyTradeTracker"
g_email = os.getenv("G_EMAIL")
g_private_key = os.getenv("G_PRIVATE_KEY")
g_project_id = os.getenv("G_PROJECT_ID")
SHEET_URL = "https://docs.google.com/spreadsheets/d/1dQXfk5wXwC1rnUPYB-SEAG3ySi3ZqNsTT6mRPb-BLfo/edit?usp=sharing"

scope = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive"
]

trade_sheet = None
config_sheet = None
balance_sheet = None
processed_ids = set()

thai_months = [
    "มกราคม","กุมภาพันธ์","มีนาคม","เมษายน","พฤษภาคม","มิถุนายน",
    "กรกฎาคม","สิงหาคม","กันยายน","ตุลาคม","พฤศจิกายน","ธันวาคม"
]

thai_days = [
    "วันจันทร์","วันอังคาร","วันพุธ","วันพฤหัสบดี","วันศุกร์","วันเสาร์","วันอาทิตย์"
]

# -------------------------
# Google Sheet Connection
# -------------------------
try:

    if not g_private_key:
        raise Exception("G_PRIVATE_KEY is missing")

    formatted_key = g_private_key.strip().replace('"','').replace("'","").replace("\\n","\n")

    if "-----BEGIN PRIVATE KEY-----" not in formatted_key:
        formatted_key = "-----BEGIN PRIVATE KEY-----\n" + formatted_key

    if "-----END PRIVATE KEY-----" not in formatted_key:
        formatted_key = formatted_key + "\n-----END PRIVATE KEY-----"

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

    print("✅ Successfully connected to Google Sheets")

except Exception as e:

    print(f"❌ Error during Google Sheets setup: {e}")

# -------------------------
# Menu Keyboards
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

def save_snapshot(col_index,value,type_name="Daily"):

    try:

        if config_sheet:
            cell = gspread.utils.rowcol_to_a1(1,col_index)
            config_sheet.update(range_name=cell,values=[[str(value)]])

        if balance_sheet:
            balance_sheet.append_row([
                datetime.now(TH_TZ).isoformat(),
                type_name,
                value,
                "Snapshot อัตโนมัติ"
            ])

    except Exception as e:
        print("Save snapshot error:",e)

def get_snapshot_values():

    try:

        if config_sheet:
            row = config_sheet.row_values(1)

            daily = float(row[1]) if len(row)>1 else MASTER_WEEKLY_RESET
            weekly = float(row[2]) if len(row)>2 else MASTER_WEEKLY_RESET
            monthly = float(row[3]) if len(row)>3 else MASTER_WEEKLY_RESET

            return daily,weekly,monthly

    except:
        pass

    return MASTER_WEEKLY_RESET,MASTER_WEEKLY_RESET,MASTER_WEEKLY_RESET


def get_current_balance():

    total,_ = read_week_trades()
    return MASTER_WEEKLY_RESET + total


def save_chat_id(cid):

    try:
        if config_sheet:
            config_sheet.update(range_name="A1",values=[[str(cid)]])
    except:
        pass


def get_chat_id():

    try:
        if config_sheet:
            val = config_sheet.acell("A1").value
            return int(val) if val else 0
    except:
        return 0


def thai_date_full():

    now = datetime.now(TH_TZ)

    return f"{thai_days[now.weekday()]}ที่ {now.day:02d} {thai_months[now.month-1]} {now.year+543}"


async def delete_message_safe(context,chat_id,message_id,delay=DELETE_NORMAL):

    await asyncio.sleep(delay)

    try:
        await context.bot.delete_message(chat_id=chat_id,message_id=message_id)
    except:
        pass

# -------------------------
# Core Trade Functions
# -------------------------

def read_trades(days):

    try:

        if not trade_sheet:
            return 0.0,0

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
        return 0.0,0


def read_week_trades():

    try:

        if not trade_sheet:
            return 0.0,0

        rows = trade_sheet.get_all_values()

        now = datetime.now(TH_TZ)

        sunday = (now - timedelta(days=(now.weekday()+1)%7)).replace(hour=0,minute=0,second=0,microsecond=0)

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
        return 0.0,0


def read_month_trades():

    try:

        if not trade_sheet:
            return 0.0,0

        rows = trade_sheet.get_all_values()

        now = datetime.now(TH_TZ)

        month_start = now.replace(day=1,hour=0,minute=0,second=0,microsecond=0)

        total = 0
        count = 0

        for row in rows[1:]:

            try:

                date = datetime.fromisoformat(row[0])

                if date >= month_start:

                    total += float(row[6])
                    count += 1

            except:
                continue

        return total,count

    except:
        return 0.0,0

# -------------------------
# Handlers
# -------------------------

async def start_command(update:Update,context:ContextTypes.DEFAULT_TYPE):

    chat_id = update.effective_chat.id

    save_chat_id(chat_id)

    await context.bot.send_message(
        chat_id=chat_id,
        text="📊 Copy Trade Tracker\nเลือกดูรายงานหรือใช้เครื่องมือคำนวณจากเมนูครับ",
        reply_markup=main_markup
    )


async def tobath_command(update:Update,context:ContextTypes.DEFAULT_TYPE):

    chat_id = update.effective_chat.id

    try:

        if not context.args:
            return

        usd = float(context.args[0].replace(",",""))
        thb = usd * EXCHANGE_RATE

        msg = await update.message.reply_text(
            f"💰 {usd:,.2f} USD ➡️ {thb:,.2f} บาท"
        )

        asyncio.create_task(
            delete_message_safe(context,chat_id,msg.message_id,DELETE_FAST)
        )

        try:
            await update.message.delete()
        except:
            pass

    except:
        pass


async def handle_message(update:Update,context:ContextTypes.DEFAULT_TYPE):

    try:

        if not update.message or not update.message.text:
            return

        text = update.message.text
        msg_id = update.message.message_id
        chat_id = update.effective_chat.id

        save_chat_id(chat_id)

        if text.replace('.', '', 1).isdigit():

            user_capital = float(text)

            total_today,_ = read_trades(1)
            d_s,_,_ = get_snapshot_values()

            pct = (total_today/d_s*100) if d_s else 0

            profit_usd = (user_capital*pct)/100
            profit_thb = profit_usd*EXCHANGE_RATE

            calc_report = (
                f"🧮 ผลการคำนวณตามทุนของคุณ\n"
                f"ทุน: {user_capital:,.2f} USD\n"
                f"กำไรพอร์ตวันนี้: {pct:+.2f}%\n"
                f"กำไรคุณ: {profit_usd:,.2f} USD\n"
                f"≈ {profit_thb:,.2f} บาท"
            )

            msg = await update.message.reply_text(calc_report)

            asyncio.create_task(
                delete_message_safe(context,chat_id,msg.message_id,DELETE_FAST)
            )

            try:
                await update.message.delete()
            except:
                pass

            return

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

        d_s,_,_ = get_snapshot_values()

        pct = (total/d_s*100) if d_s else 0

        await context.bot.send_message(
            chat_id=chat_id,
            text=f"📊 สรุปวันนี้\nไม้: {count}\nกำไร: {total:,.2f} USD ({pct:+.2f}%)"
        )

        save_snapshot(2,get_current_balance(),"Daily")


async def weekly_report_job(context):

    chat_id = get_chat_id()

    if chat_id:

        total,count = read_week_trades()

        _,w_s,_ = get_snapshot_values()

        pct = (total/w_s*100) if w_s else 0

        await context.bot.send_message(
            chat_id=chat_id,
            text=f"📅 กำไรสะสมสัปดาห์นี้\nไม้: {count}\nกำไรสะสม: {total:,.2f} USD ({pct:+.2f}%)"
        )

        save_snapshot(3,get_current_balance(),"Weekly")


async def monthly_report_job(context):

    chat_id = get_chat_id()

    if chat_id:

        total,count = read_month_trades()

        _,_,m_s = get_snapshot_values()

        pct = (total/m_s*100) if m_s else 0

        await context.bot.send_message(
            chat_id=chat_id,
            text=f"📆 กำไรสะสมรายเดือน\nไม้: {count}\nกำไรสะสม: {total:,.2f} USD ({pct:+.2f}%)"
        )

        save_snapshot(4,get_current_balance(),"Monthly")


async def sunday_reset_job(context):

    save_snapshot(3,MASTER_WEEKLY_RESET,"Weekly Reset")

    chat_id = get_chat_id()

    if chat_id:

        await context.bot.send_message(
            chat_id=chat_id,
            text=f"🔄 รีเซ็ตสัปดาห์ใหม่ ทุน {MASTER_WEEKLY_RESET} USD"
        )

# -------------------------
# Main
# -------------------------

def main():

    if not TOKEN:
        print("❌ TOKEN is missing!")
        return

    app = ApplicationBuilder().token(TOKEN).build()

    app.add_handler(CommandHandler("start",start_command))
    app.add_handler(CommandHandler("menu",start_command))
    app.add_handler(CommandHandler("tobath",tobath_command))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND,handle_message))

    job_queue = app.job_queue

    job_queue.run_daily(morning_date_job,time=time(0,1,tzinfo=TH_TZ))
    job_queue.run_daily(daily_report_job,time=time(23,59,tzinfo=TH_TZ))
    job_queue.run_daily(weekly_report_job,time=time(23,59,tzinfo=TH_TZ))
    job_queue.run_daily(monthly_report_job,time=time(23,59,tzinfo=TH_TZ))
    job_queue.run_daily(sunday_reset_job,time=time(0,0,tzinfo=TH_TZ))

    print("🚀 Copy Trade Tracker Started")

    app.run_polling()


if __name__ == "__main__":
    main()
